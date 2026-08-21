"""Tests for the post-kill skill wipe.

The wipe exists to keep monster difficulty at the floor (yaoguai.lpc:321
scales the monster off your highest skill), but it must not eat training
that was put there on purpose -- so it only runs while every skill is
still at or below WIPE_MAX_LEVEL.

Run with: python3 test_abandon.py
"""
import importlib.util, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("bot", HERE / "bots/changan-mieyao-bot.py")
bot = importlib.util.module_from_spec(spec); spec.loader.exec_module(bot)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def skills_page(*pairs):
    """cmds/usr/skills.lpc:52-59 output for the given (id, level) pairs."""
    out = ["你目前所掌握的技能：", ""]
    for sid, lvl in pairs:
        out.append(f"  基本功夫 ({sid})                              "
                   f"- 初学乍练   {lvl:4d}/{lvl * lvl:5d}")
    out.append("")
    return out


class FakeAPI:
    def __init__(self, page):
        self.page, self.pending, self.logs, self.sent = page, [], [], []

    def stopped(self): return False
    def drain(self): self.pending = []
    def log(self, m): self.logs.append(m)

    def wait_line(self, pattern, timeout=10.0):
        rx = re.compile(pattern)
        while self.pending:
            m = rx.search(self.pending.pop(0))
            if m:
                return m
        return None

    def send(self, cmd, quiet=False):
        self.sent.append(cmd)
        if cmd == "skills":
            self.pending = list(self.page)
        elif cmd.startswith("abandon "):
            self.pending = ["你决定放弃继续学习这项技能。"]
        else:
            self.pending = []

    def abandoned(self):
        return [c.split(" ", 1)[1] for c in self.sent if c.startswith("abandon ")]


print("junk skills picked up in combat get wiped")
api = FakeAPI(skills_page(("stick", 1), ("dodge", 2), ("unarmed", 1)))
n = bot.abandon_all_skills(api)
check("all three abandoned", sorted(api.abandoned()), ["dodge", "stick", "unarmed"])
check("count returned", n, 3)

print("\nanything above WIPE_MAX_LEVEL leaves the whole set alone")
api = FakeAPI(skills_page(("stick", 1), ("dodge", 40)))
check("nothing abandoned", bot.abandon_all_skills(api), 0)
check("no abandon sent", api.abandoned(), [])
check("and it says why", any("40" in m and "不动它们" in m for m in api.logs), True)

print("\nexactly at the threshold still counts as blank")
api = FakeAPI(skills_page(("stick", 2), ("dodge", 2)))
check("2 is fine", sorted(api.abandoned()) if bot.abandon_all_skills(api) else [],
      ["dodge", "stick"])
api = FakeAPI(skills_page(("stick", 3)))
check("3 is not", bot.abandon_all_skills(api), 0)

print("\nno skills at all is a no-op, not a crash")
api = FakeAPI(["你目前并没有学会任何技能。"])
check("nothing to do", bot.abandon_all_skills(api), 0)
check("no abandon sent", api.abandoned(), [])

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
