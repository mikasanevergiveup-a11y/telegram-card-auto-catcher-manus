import os

os.environ.setdefault("GROUP_ID", "-1004378413999")
os.environ.setdefault("API_ID", "123456")
os.environ.setdefault("API_HASH", "hash")
os.environ.setdefault("SESSION_STRING", "session")

from main import CONTROL_RE, GROUP_ID, NEW_WAIFU_TEXT_RE, SPAWN_TEXT_RE, extract_commands, normalize_session_string, SPAWN_MARKER

assert extract_commands("/guess Sakura\n/sudo Sakura") == ["/guess Sakura", "/sudo Sakura"]
assert extract_commands("hello\nnot a command") == []
assert extract_commands("Answer: /catch Sakura") == ["/catch Sakura"]
assert extract_commands("Answer: /guess Sakura") == ["/guess Sakura"]
assert extract_commands("👒 New Waifu Is Here, Hurry-Up!\nType /guess Sakura To Add Her Into Your Harem") == ["/guess Sakura To Add Her Into Your Harem"]
assert extract_commands("🎯 **/guess Sakura**\n`/sudo Sakura`") == ["/guess Sakura", "/sudo Sakura"]
assert extract_commands("/guess Sakura\n/sudo Sakura") == ["/guess Sakura", "/sudo Sakura"]
assert SPAWN_MARKER == "new waifu is here"
assert NEW_WAIFU_TEXT_RE.search("👒 New Waifu Is Here, Hurry-Up!\nType /guess <name> To Add Her Into Your Harem")
assert SPAWN_TEXT_RE.search("A new card was spawned")
assert SPAWN_TEXT_RE.search("SPAWN detected")
assert not SPAWN_TEXT_RE.search("respawning")
assert GROUP_ID == -1004378413999
assert normalize_session_string("  'abc123'  ") == "abc123"
assert normalize_session_string("SESSION_STRING=abc123") == "abc123"
try:
    normalize_session_string("replace-me")
except RuntimeError:
    pass
else:
    raise AssertionError("placeholder session string must be rejected")
assert CONTROL_RE.match("/start")
assert CONTROL_RE.match("/stop@my_bot")
assert not CONTROL_RE.match("/start now")
print("smoke tests passed")
