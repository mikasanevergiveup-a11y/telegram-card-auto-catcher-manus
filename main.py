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


def parse_id_list(value: str, fallback: str) -> tuple[int, ...]:
    raw_value = value.strip() or fallback.strip()
    result: list[int] = []
    for raw in raw_value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            group_id = int(raw)
        except ValueError as exc:
            raise RuntimeError("GROUP_IDS must be comma-separated numeric Telegram IDs") from exc
        if group_id not in result:
            result.append(group_id)
    if not result:
        raise RuntimeError("At least one Telegram group ID is required in GROUP_IDS")
    return tuple(result)


def load_group_ids() -> tuple[int, ...]:
    """Load comma-separated GROUP_IDS and optional GROUP_ID_1..GROUP_ID_20 values.

    This supports both a single Render variable and separate variables, which
    makes it easier to see and edit five or more groups in the dashboard.
    """
    values: list[str] = []
    combined = os.getenv("GROUP_IDS", "").strip()
    if combined:
        values.append(combined)
    for index in range(1, 21):
        value = os.getenv(f"GROUP_ID_{index}", "").strip()
        if value:
            values.append(value)
    return parse_id_list(",".join(values), os.getenv("GROUP_ID", "-1004378413999"))


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
GROUP_IDS = load_group_ids()
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
    group_id: int
    source_message_id: int
    forwarded_message_id: int | None = None
    created_at: float = field(default_factory=time.monotonic)
    sent_commands: Set[str] = field(default_factory=set)


pending_spawns: Deque[PendingSpawn] = deque()
seen_spawn_ids: Deque[tuple[int, int]] = deque(maxlen=1000)
state_lock: asyncio.Lock | None = None
task_enabled: asyncio.Event | None = None
authorized_control_ids: set[int] = set(CONTROL_USER_IDS)


def extract_commands(text: str) -> list[str]:
    commands: list[str] = []
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
            logger.warning(
                "Bot reply timeout for group %s spawn %s",
                expired.group_id,
                expired.source_message_id,
            )


async def send_task_for_group(client: TelegramClient, group_id: int) -> None:
    assert task_enabled is not None
    while client.is_connected():
        await task_enabled.wait()
        try:
            await client.send_message(group_id, TASK_TEXT)
            logger.info("Sent task message to group %s", group_id)
            await asyncio.sleep(TASK_INTERVAL_SECONDS)
        except FloodWaitError as exc:
            wait_seconds = max(1, int(exc.seconds))
            logger.warning("Flood wait for group %s; sleeping %s seconds", group_id, wait_seconds)
            await asyncio.sleep(wait_seconds)
        except RPCError:
            logger.exception("Telegram RPC error for group %s; retrying in 15 seconds", group_id)
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected task sender error for group %s", group_id)
            await asyncio.sleep(15)


async def task_sender(client: TelegramClient) -> None:
    tasks = [asyncio.create_task(send_task_for_group(client, group_id)) for group_id in GROUP_IDS]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def handle_spawn(client: TelegramClient, message, group_id: int) -> None:
    text = message.raw_text or ""
    if SPAWN_MARKER not in text.casefold():
        return
    assert state_lock is not None

    pending = PendingSpawn(group_id=group_id, source_message_id=message.id)
    spawn_key = (group_id, message.id)
    async with state_lock:
        if spawn_key in seen_spawn_ids:
            return
        seen_spawn_ids.append(spawn_key)
        pending_spawns.append(pending)

    try:
        # Forward immediately; no artificial delay is added here.
        forwarded = await client.forward_messages(CATCH_BOT_ID, message)
        if isinstance(forwarded, list):
            forwarded = forwarded[0] if forwarded else None
        pending.forwarded_message_id = getattr(forwarded, "id", None)
        logger.info(
            "Forwarded spawn group=%s source=%s bot_message=%s",
            group_id,
            message.id,
            pending.forwarded_message_id,
        )
    except FloodWaitError as exc:
        logger.warning("Flood wait while forwarding group %s spawn %s: %s seconds", group_id, message.id, exc.seconds)
        async with state_lock:
            if pending in pending_spawns:
                pending_spawns.remove(pending)
    except RPCError:
        logger.exception("Telegram RPC error while forwarding group %s spawn %s", group_id, message.id)
        async with state_lock:
            if pending in pending_spawns:
                pending_spawns.remove(pending)
    except Exception:
        logger.exception("Unexpected error while forwarding group %s spawn %s", group_id, message.id)
        async with state_lock:
            if pending in pending_spawns:
                pending_spawns.remove(pending)


async def relay_command(client: TelegramClient, group_id: int, command: str) -> None:
    try:
        await client.send_message(group_id, command)
        logger.info("Relayed bot command to group %s: %s", group_id, command)
    except FloodWaitError as exc:
        logger.warning("Flood wait while relaying to group %s: %s seconds", group_id, exc.seconds)
    except RPCError:
        logger.exception("Telegram RPC error while relaying to group %s", group_id)
    except Exception:
        logger.exception("Unexpected error while relaying to group %s", group_id)


def reply_to_message_id(message) -> int | None:
    direct_id = getattr(message, "reply_to_msg_id", None)
    if direct_id is not None:
        return direct_id
    reply = getattr(message, "reply_to", None)
    return getattr(reply, "reply_to_msg_id", None) if reply is not None else None


async def handle_bot_reply(client: TelegramClient, message) -> None:
    raw_text = message.raw_text or ""
    commands = extract_commands(raw_text)
    logger.info("Bot reply received from %s; commands_detected=%s", message.sender_id, len(commands))
    if not commands:
        return
    assert state_lock is not None

    await prune_pending()
    new_commands: list[str] = []
    async with state_lock:
        pending: PendingSpawn | None = None
        reply_to_id = reply_to_message_id(message)
        if reply_to_id is not None:
            pending = next(
                (item for item in pending_spawns if item.forwarded_message_id == reply_to_id),
                None,
            )
        if pending is None and pending_spawns:
            # Some catcher bots do not set reply_to_msg_id. Use the newest
            # pending spawn, which is the most likely source of the reply.
            pending = max(pending_spawns, key=lambda item: item.created_at)
        if pending is None:
            logger.info("Ignoring bot commands because no spawn is pending")
            return

        sent_lower = {item.casefold() for item in pending.sent_commands}
        new_commands = [command for command in commands if command.casefold() not in sent_lower]
        pending.sent_commands.update(new_commands)
        command_names = {item.split()[0].split("@")[0].casefold() for item in pending.sent_commands}
        # The /guess result completes this spawn for the requested workflow.
        # If /sudo is included in the same reply, it is broadcast as well.
        if "/guess" in command_names or {"/guess", "/sudo"}.issubset(command_names):
            pending_spawns.remove(pending)

    if new_commands:
        # Broadcast every bot command to every configured card group in
        # parallel. There is no artificial sleep between groups.
        deliveries = [
            relay_command(client, group_id, command)
            for group_id in GROUP_IDS
            for command in new_commands
        ]
        await asyncio.gather(*deliveries)
        logger.info(
            "Broadcast commands=%s to group_count=%s groups=%s",
            len(new_commands),
            len(GROUP_IDS),
            GROUP_IDS,
        )


async def handle_control_command(client: TelegramClient, message) -> bool:
    global task_enabled
    match = CONTROL_RE.match(message.raw_text or "")
    if not match or message.sender_id not in authorized_control_ids:
        return False
    assert task_enabled is not None

    command = match.group(1).casefold()
    if command == "start":
        task_enabled.set()
        reply = "Task loops started for all configured groups."
        logger.info("Task loops started by user %s", message.sender_id)
    else:
        task_enabled.clear()
        reply = "Task loops stopped for all configured groups."
        logger.info("Task loops stopped by user %s", message.sender_id)
    try:
        await client.send_message(message.chat_id, reply)
    except FloodWaitError as exc:
        logger.warning("Flood wait while sending control acknowledgement: %s seconds", exc.seconds)
    return True


async def handle_group_message(client: TelegramClient, event) -> None:
    group_id = event.chat_id
    if group_id not in GROUP_IDS:
        return
    if await handle_control_command(client, event.message):
        return
    await handle_spawn(client, event.message, group_id)


async def run() -> None:
    global state_lock, task_enabled, authorized_control_ids
    state_lock = asyncio.Lock()
    task_enabled = asyncio.Event()
    task_enabled.set()

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
        app_version="1.2.0",
        # Concurrent update handling keeps spawn forwarding responsive across groups.
        sequential_updates=False,
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
    logger.info("Configured group count=%s groups=%s", len(GROUP_IDS), GROUP_IDS)
    if len(GROUP_IDS) < 5:
        logger.warning(
            "Only %s group IDs configured; add GROUP_IDS or GROUP_ID_1..GROUP_ID_5 for five groups",
            len(GROUP_IDS),
        )

    async def resolve_group(group_id: int) -> tuple[int, bool, str]:
        try:
            entity = await client.get_entity(group_id)
            title = getattr(entity, "title", "resolved")
            return group_id, True, str(title)
        except Exception as exc:
            return group_id, False, type(exc).__name__

    resolved_groups = await asyncio.gather(*(resolve_group(group_id) for group_id in GROUP_IDS))
    unavailable = [item for item in resolved_groups if not item[1]]
    for group_id, ok, detail in resolved_groups:
        if ok:
            logger.info("Group ready id=%s title=%s", group_id, detail)
        else:
            logger.error("Group unavailable id=%s error=%s", group_id, detail)
    if unavailable:
        logger.warning("%s configured group(s) could not be resolved; check membership and IDs", len(unavailable))

    logger.info("Authorized control user IDs: %s", sorted(authorized_control_ids))

    async def group_event_handler(event) -> None:
        await handle_group_message(client, event)

    async def bot_event_handler(event) -> None:
        await handle_bot_reply(client, event.message)

    client.add_event_handler(group_event_handler, events.NewMessage(chats=list(GROUP_IDS)))
    client.add_event_handler(bot_event_handler, events.NewMessage(from_users=CATCH_BOT_ID))

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
