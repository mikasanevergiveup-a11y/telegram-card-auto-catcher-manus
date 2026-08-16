import asyncio
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Set

from flask import Flask, jsonify
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError
from telethon.sessions import StringSession

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("card-autocatcher")


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


API_ID = env_int("API_ID", 0)
if API_ID <= 0:
    raise RuntimeError("API_ID must be a positive integer")
API_HASH = required_env("API_HASH")
SESSION_STRING = required_env("SESSION_STRING")
GROUP_ID = env_int("GROUP_ID", -1004378413999)
CATCH_BOT_ID = env_int("CATCH_BOT_ID", 8506436817)
TASK_TEXT = os.getenv("TASK_TEXT", "task လုပ်ပါ")
TASK_INTERVAL_SECONDS = max(4, env_int("TASK_INTERVAL_SECONDS", 4))
SPAWN_MARKER = os.getenv("SPAWN_MARKER", "New Waifu Is Here").casefold()
BOT_REPLY_TIMEOUT_SECONDS = max(10, env_int("BOT_REPLY_TIMEOUT_SECONDS", 25))

# Commands are deliberately extracted line-by-line so unrelated bot text is not
# copied into the group.
COMMAND_RE = re.compile(
    r"^\s*(/(?:guess|sudo)(?:@[A-Za-z0-9_]+)?\s+[^\r\n`]+?)\s*$",
    re.IGNORECASE,
)


@dataclass
class PendingSpawn:
    source_message_id: int
    created_at: float = field(default_factory=time.monotonic)
    sent_commands: Set[str] = field(default_factory=set)


pending_spawns: Deque[PendingSpawn] = deque()
seen_spawn_ids: Deque[int] = deque(maxlen=500)
state_lock = asyncio.Lock()


# Render requires a bound HTTP port for a Web Service. This endpoint does not
# control Telegram; it only reports process health.
health_app = Flask(__name__)


@health_app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "telegram-card-autocatcher",
        "group_id": GROUP_ID,
        "task_interval_seconds": TASK_INTERVAL_SECONDS,
        "pending_spawns": len(pending_spawns),
    })


def run_health_server() -> None:
    port = env_int("PORT", 8080)
    health_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def extract_commands(text: str) -> list[str]:
    commands: list[str] = []
    for line in text.splitlines():
        match = COMMAND_RE.match(line)
        if not match:
            continue
        command = " ".join(match.group(1).split())
        if command.lower().startswith("/guess") or command.lower().startswith("/sudo"):
            if command not in commands:
                commands.append(command)
    return commands


async def prune_pending() -> None:
    now = time.monotonic()
    async with state_lock:
        while pending_spawns and now - pending_spawns[0].created_at > BOT_REPLY_TIMEOUT_SECONDS:
            expired = pending_spawns.popleft()
            logger.warning("Bot reply timeout for spawn message %s", expired.source_message_id)


async def task_sender(client: TelegramClient) -> None:
    while client.is_connected():
        try:
            await client.send_message(GROUP_ID, TASK_TEXT)
            logger.info("Sent task message to %s", GROUP_ID)
            await asyncio.sleep(TASK_INTERVAL_SECONDS)
        except FloodWaitError as exc:
            wait_seconds = max(1, int(exc.seconds))
            logger.warning("Flood wait received; sleeping %s seconds", wait_seconds)
            await asyncio.sleep(wait_seconds)
        except RPCError:
            logger.exception("Telegram RPC error while sending task; retrying in 15 seconds")
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected task sender error; retrying in 15 seconds")
            await asyncio.sleep(15)


async def handle_spawn(client: TelegramClient, message) -> None:
    text = message.raw_text or ""
    if SPAWN_MARKER not in text.casefold() or not message.media:
        return

    async with state_lock:
        if message.id in seen_spawn_ids:
            return
        seen_spawn_ids.append(message.id)
        pending_spawns.append(PendingSpawn(source_message_id=message.id))

    try:
        await client.forward_messages(CATCH_BOT_ID, message)
        logger.info("Forwarded spawn message %s to bot %s", message.id, CATCH_BOT_ID)
    except FloodWaitError as exc:
        logger.warning("Flood wait while forwarding spawn %s: %s seconds", message.id, exc.seconds)
    except RPCError:
        logger.exception("Telegram RPC error while forwarding spawn %s", message.id)
    except Exception:
        logger.exception("Unexpected error while forwarding spawn %s", message.id)


async def handle_bot_reply(client: TelegramClient, message) -> None:
    commands = extract_commands(message.raw_text or "")
    if not commands:
        return

    await prune_pending()
    async with state_lock:
        if not pending_spawns:
            logger.info("Ignoring bot commands because no spawn is pending")
            return
        pending = pending_spawns[0]
        new_commands = [command for command in commands if command.casefold() not in {
            item.casefold() for item in pending.sent_commands
        }]
        pending.sent_commands.update(new_commands)
        # Most catcher replies contain both commands. Keep a partial response
        # pending briefly in case /guess and /sudo arrive as separate messages.
        if {"/guess", "/sudo"}.issubset({item.split()[0].split("@")[0].casefold() for item in pending.sent_commands}):
            pending_spawns.popleft()

    for command in new_commands:
        try:
            await client.send_message(GROUP_ID, command)
            logger.info("Relayed bot command to group %s: %s", GROUP_ID, command)
        except FloodWaitError as exc:
            logger.warning("Flood wait while relaying command: %s seconds", exc.seconds)
        except RPCError:
            logger.exception("Telegram RPC error while relaying command")
        except Exception:
            logger.exception("Unexpected error while relaying command")


async def run() -> None:
    client = TelegramClient(
        StringSession(SESSION_STRING),
        API_ID,
        API_HASH,
        device_model="Render Card Auto Catcher",
        app_version="1.0.0",
        sequential_updates=True,
        flood_sleep_threshold=60,
    )

    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(
            "SESSION_STRING is not authorized. Generate a new session locally with scripts/generate_session.py."
        )

    me = await client.get_me()
    logger.info("Logged in as %s (id=%s)", getattr(me, "username", None), me.id)

    client.add_event_handler(
        lambda event: handle_spawn(client, event.message),
        events.NewMessage(chats=GROUP_ID),
    )
    client.add_event_handler(
        lambda event: handle_bot_reply(client, event.message),
        events.NewMessage(from_users=CATCH_BOT_ID),
    )

    sender_task = asyncio.create_task(task_sender(client))
    try:
        logger.info("Card auto catcher is running")
        await client.run_until_disconnected()
    finally:
        sender_task.cancel()
        await asyncio.gather(sender_task, return_exceptions=True)
        await client.disconnect()


def main() -> None:
    threading.Thread(target=run_health_server, daemon=True, name="health-server").start()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped")


if __name__ == "__main__":
    main()
