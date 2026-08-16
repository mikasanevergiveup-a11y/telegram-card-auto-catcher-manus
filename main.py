import asyncio
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Set

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError
from telethon.sessions import StringSession

from keep_alive import start_keep_alive

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


def normalize_session_string(value: str) -> str:
    """Normalize common dashboard copy/paste wrappers without revealing the secret."""
    value = value.strip()
    if value.startswith("SESSION_STRING="):
        value = value.split("=", 1)[1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    value = "".join(value.split())
    if not value or value.lower() in {"replace-me", "your-session-string", "changeme"}:
        raise RuntimeError(
            "SESSION_STRING is empty or still a placeholder. Generate it with scripts/generate_session.py."
        )
    return value


def parse_id_set(value: str) -> set[int]:
    result: set[int] = set()
    for raw in value.split(","):
        raw = raw.strip()
        if raw:
            try:
                result.add(int(raw))
            except ValueError as exc:
                raise RuntimeError("CONTROL_USER_IDS must be comma-separated numeric Telegram IDs") from exc
    return result


API_ID = env_int("API_ID", 0)
if API_ID <= 0:
    raise RuntimeError("API_ID must be a positive integer")
API_HASH = required_env("API_HASH")
SESSION_STRING = normalize_session_string(required_env("SESSION_STRING"))
GROUP_ID = env_int("GROUP_ID", -1004378413999)
CATCH_BOT_ID = env_int("CATCH_BOT_ID", 8506436817)
TASK_TEXT = os.getenv("TASK_TEXT", "task လုပ်ပါ")
TASK_INTERVAL_SECONDS = max(4, env_int("TASK_INTERVAL_SECONDS", 4))
SPAWN_MARKER = os.getenv("SPAWN_MARKER", "New Waifu Is Here").casefold()
BOT_REPLY_TIMEOUT_SECONDS = max(10, env_int("BOT_REPLY_TIMEOUT_SECONDS", 25))
CONTROL_USER_IDS = parse_id_set(os.getenv("CONTROL_USER_IDS", ""))

# Match commands anywhere in a bot reply, including after labels such as
# "Answer:", emoji, bullets, or Markdown formatting.
COMMAND_RE = re.compile(
    r"(?<![A-Za-z0-9_])(/(?:guess|sudo)(?:@[A-Za-z0-9_]+)?[ \t]+[^\r\n`]+)",
    re.IGNORECASE,
)
CONTROL_RE = re.compile(r"^\s*/(start|stop)(?:@[A-Za-z0-9_]+)?\s*$", re.IGNORECASE)


@dataclass
class PendingSpawn:
    source_message_id: int
    created_at: float = field(default_factory=time.monotonic)
    sent_commands: Set[str] = field(default_factory=set)


pending_spawns: Deque[PendingSpawn] = deque()
seen_spawn_ids: Deque[int] = deque(maxlen=500)
state_lock: asyncio.Lock | None = None
task_enabled: asyncio.Event | None = None
authorized_control_ids: set[int] = set(CONTROL_USER_IDS)


def extract_commands(text: str) -> list[str]:
    commands: list[str] = []
    # Telegram replies can contain zero-width spaces and Markdown markers.
    cleaned = text.replace("\u200b", " ").replace("\u2060", " ")
    for match in COMMAND_RE.finditer(cleaned):
        command = " ".join(match.group(1).strip().split())
        command = command.strip("`*_ ")
        if command and command.casefold() not in {item.casefold() for item in commands}:
            commands.append(command)
    return commands


async def prune_pending() -> None:
    assert state_lock is not None
    now = time.monotonic()
    async with state_lock:
        while pending_spawns and now - pending_spawns[0].created_at > BOT_REPLY_TIMEOUT_SECONDS:
            expired = pending_spawns.popleft()
            logger.warning("Bot reply timeout for spawn message %s", expired.source_message_id)


async def task_sender(client: TelegramClient) -> None:
    assert task_enabled is not None
    while client.is_connected():
        await task_enabled.wait()
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
    assert state_lock is not None

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
    raw_text = message.raw_text or ""
    commands = extract_commands(raw_text)
    logger.info(
        "Bot reply received from %s; commands_detected=%s",
        message.sender_id,
        len(commands),
    )
    if not commands:
        return
    assert state_lock is not None

    await prune_pending()
    async with state_lock:
        if not pending_spawns:
            logger.info("Ignoring bot commands because no spawn is pending")
            return
        pending = pending_spawns[0]
        sent_lower = {item.casefold() for item in pending.sent_commands}
        new_commands = [command for command in commands if command.casefold() not in sent_lower]
        pending.sent_commands.update(new_commands)
        # Keep a partial response pending when /guess and /sudo arrive separately.
        command_names = {item.split()[0].split("@")[0].casefold() for item in pending.sent_commands}
        if {"/guess", "/sudo"}.issubset(command_names):
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


async def handle_control_command(client: TelegramClient, message) -> bool:
    global task_enabled
    match = CONTROL_RE.match(message.raw_text or "")
    if not match or message.sender_id not in authorized_control_ids:
        return False
    assert task_enabled is not None

    command = match.group(1).casefold()
    if command == "start":
        task_enabled.set()
        reply = "Task loop started."
        logger.info("Task loop started by user %s", message.sender_id)
    else:
        task_enabled.clear()
        reply = "Task loop stopped."
        logger.info("Task loop stopped by user %s", message.sender_id)
    try:
        await client.send_message(GROUP_ID, reply)
    except FloodWaitError as exc:
        logger.warning("Flood wait while sending control acknowledgement: %s seconds", exc.seconds)
    return True


async def handle_group_message(client: TelegramClient, event) -> None:
    if await handle_control_command(client, event.message):
        return
    await handle_spawn(client, event.message)


async def run() -> None:
    global state_lock, task_enabled, authorized_control_ids
    state_lock = asyncio.Lock()
    task_enabled = asyncio.Event()
    task_enabled.set()  # Preserve the previous auto-start behavior after deployment.

    try:
        session = StringSession(SESSION_STRING)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "SESSION_STRING is not a valid Telethon StringSession. "
            "Run scripts/generate_session.py locally and paste only the printed value into Render."
        ) from exc

    client = TelegramClient(
        session,
        API_ID,
        API_HASH,
        device_model="Render Card Auto Catcher",
        app_version="1.1.0",
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
    if not authorized_control_ids:
        authorized_control_ids = {me.id}
    logger.info("Logged in as %s (id=%s)", getattr(me, "username", None), me.id)
    logger.info("Authorized control user IDs: %s", sorted(authorized_control_ids))

    client.add_event_handler(
        lambda event: handle_group_message(client, event),
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
    start_keep_alive()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped")


if __name__ == "__main__":
    main()
