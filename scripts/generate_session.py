"""Generate a Telethon StringSession locally.

Run this file on your own computer. Never commit the printed value to GitHub.
"""

import os

from telethon import TelegramClient
from telethon.sessions import StringSession


def main() -> None:
    api_id = os.getenv("API_ID") or input("Telegram API ID: ").strip()
    api_hash = os.getenv("API_HASH") or input("Telegram API hash: ").strip()
    if not api_id.isdigit() or not api_hash:
        raise SystemExit("API_ID must be numeric and API_HASH must not be empty.")

    client = TelegramClient(StringSession(), int(api_id), api_hash)
    with client:
        client.start()
        print("\nSESSION_STRING (copy to Render Environment Variables only):\n")
        print(client.session.save())
        print("\nDo not paste this value into GitHub, issues, screenshots, or chat messages.")


if __name__ == "__main__":
    main()
