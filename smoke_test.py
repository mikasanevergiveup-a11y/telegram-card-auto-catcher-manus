import os

os.environ.setdefault("API_ID", "123456")
os.environ.setdefault("API_HASH", "hash")
os.environ.setdefault("SESSION_STRING", "session")

from main import extract_commands, SPAWN_MARKER

assert extract_commands("/guess Sakura\n/sudo Sakura") == ["/guess Sakura", "/sudo Sakura"]
assert extract_commands("hello\nnot a command") == []
assert SPAWN_MARKER == "new waifu is here"
print("smoke tests passed")
