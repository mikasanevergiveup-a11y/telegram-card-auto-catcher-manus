import os

os.environ.setdefault("API_ID", "123456")
os.environ.setdefault("API_HASH", "hash")
os.environ.setdefault("SESSION_STRING", "session")

from main import CONTROL_RE, extract_commands, normalize_session_string, parse_id_list, SPAWN_MARKER

assert extract_commands("/guess Sakura\n/sudo Sakura") == ["/guess Sakura", "/sudo Sakura"]
assert extract_commands("hello\nnot a command") == []
assert extract_commands("Answer: /guess Sakura") == ["/guess Sakura"]
assert extract_commands("🎯 **/guess Sakura**\n`/sudo Sakura`") == ["/guess Sakura", "/sudo Sakura"]
assert extract_commands("/guess Sakura\n/sudo Sakura") == ["/guess Sakura", "/sudo Sakura"]
assert SPAWN_MARKER == "new waifu is here"
assert parse_id_list("-1001,-1002,-1001", "-1009") == (-1001, -1002)
assert parse_id_list("", "-1009") == (-1009,)
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
