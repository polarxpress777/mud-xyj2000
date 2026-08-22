"""Regression tests for edits to a helper module not reaching a running bot.

The incident: mudmap.load() was fixed on disk and proven by tests, but
/run fangcun-skill kept dying with the OLD code's KeyError('short').
botmanager._load() re-executes the BOT file on every /run, and botapi is
explicitly reloaded -- but a bot's `import mudmap` is served from
sys.modules, so re-executing the bot just rebinds the same stale module.
Every shared helper was frozen at whatever it was when botproxy started.

The failure is expensive because it makes you doubt the fix instead of
the loader: the tests pass, the game disagrees, and nothing says why.

Run with: python3 test_reload.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import botmanager


class FakeSession:
    def __init__(self):
        self.notes = []

    def note(self, m):
        self.notes.append(m)

    def said(self, needle):
        return any(needle in m for m in self.notes)


def edit(path, text):
    """Rewrite a module the way a person would -- at a later timestamp.

    Written back-to-back in one process, two same-length versions can land
    in the same instant, and the import system then reads the file as
    unchanged. That is an artifact of tests editing files in microseconds,
    not something a human editor can produce, so the clock is advanced
    rather than the assertion weakened.
    """
    path.write_text(text, encoding="utf-8")
    later = time.time() + 2
    os.utime(path, (later, later))


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    return ok


fails = 0
tmp = Path(tempfile.mkdtemp())
(tmp / "bots").mkdir()
botmanager.BOTS_DIR = tmp / "bots"
botmanager.LOCAL_DIR = tmp
sys.path.insert(0, str(tmp))

HELPER = tmp / "tmphelper.py"
BOT = tmp / "bots" / "probe.py"
BOT.write_text("import tmphelper\n\n\ndef run(api):\n    return tmphelper.VALUE\n",
               encoding="utf-8")

print("A. a bot picks up an edit to the helper it imports")
HELPER.write_text('VALUE = "v1"\n', encoding="utf-8")
mgr = botmanager.BotManager(FakeSession())
mod = mgr._load("probe")
fails += not check("first load sees v1", mod.run(None), "v1")

edit(HELPER, 'VALUE = "v2"\n')
mod = mgr._load("probe")
fails += not check("second load sees the edit", mod.run(None), "v2")

print("\nB. a broken helper is named, and the bot does not start on stale code")
# Same failure mode we're fixing: running code that isn't what's on disk.
# botmanager already sets this precedent for botapi (:77-80).
edit(HELPER, 'VALUE = "v3"\nthis is not python\n')
sess = FakeSession()
mgr = botmanager.BotManager(sess)
mgr.start("probe")
fails += not check("names the module", sess.said("tmphelper"), True)
# NOT `"probe" in mgr.running` -- the thread pops itself the moment run()
# returns, so that assertion passes even when the bot did start.
fails += not check("didn't start", sess.said("启动"), False)

print("\nC. the proxy's own modules are left alone")
# ansi/triggers/botmanager are load-bearing for the CONNECTION; reloading
# them mid-session risks dropping the very session this preserves.
fails += not check("botmanager is not a reload target",
                   botmanager.is_helper("botmanager", botmanager), False)
fails += not check("botapi is not either (start() reloads it separately)",
                   botmanager.is_helper("botapi", sys.modules["botapi"]), False)

print("\nD. the script the proxy was STARTED as is not a reload target")
# The regression: botproxy.py run as a script is registered in sys.modules
# under the name "__main__", not "botproxy", so a name-based exclusion list
# misses it -- and reload() refuses a module with no spec:
#     __main__.py 有错误，无法载入: spec not found for the module '__main__'
# which broke every /run. A module with no __spec__ cannot be reloaded at
# all, so that, not the name, is the honest test.
import types
script = types.ModuleType("__main__")
script.__file__ = str(Path(botmanager.LOCAL_DIR) / "botproxy.py")
script.__spec__ = None
fails += not check("__main__ is skipped", botmanager.is_helper("__main__", script),
                   False)

specless = types.ModuleType("whatever")
specless.__file__ = str(Path(botmanager.LOCAL_DIR) / "whatever.py")
specless.__spec__ = None
fails += not check("so is anything else without a spec",
                   botmanager.is_helper("whatever", specless), False)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILURE(S)"))
sys.exit(1 if fails else 0)
