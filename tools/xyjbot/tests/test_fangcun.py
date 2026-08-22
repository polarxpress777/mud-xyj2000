"""Tests for the 方寸山 skill bot.

Three things the mudlib forces, and one thing the user asked for:

  * learn.lpc:31 refuses anyone who is not the teacher's apprentice, so the
    bot checks 门派 first and never joins a sect on your behalf.
  * learning is bounded by 潜能 - learned_points (learn.lpc:74), and sleeping
    restores 精神 but NOT 潜能 -- so 潜能 exhaustion is terminal.
  * a teacher who lacks a skill says 这项技能你恐怕必须找别人学了, once.
  * skills are trained EVENLY: always the lowest one under the cap.

Run with: python3 tests/test_fangcun.py
"""
import importlib.util, json, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent      # tools/xyjbot
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("fs", HERE / "bots/fangcun-skill.py")
fs = importlib.util.module_from_spec(spec); spec.loader.exec_module(fs)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


class FakeAPI:
    def __init__(self, replies=None):
        self.replies = dict(replies or {})
        self.pending, self.logs, self.sent = [], [], []

    def stopped(self): return False
    def drain(self): self.pending = []
    def log(self, m): self.logs.append(m)
    def sleep(self, n): pass

    def wait_line(self, pattern, timeout=10.0):
        import re
        rx = re.compile(pattern)
        while self.pending:
            m = rx.search(self.pending.pop(0))
            if m:
                return m
        return None

    def send(self, cmd, quiet=False):
        self.sent.append(cmd)
        for key, lines in self.replies.items():
            if cmd.startswith(key):
                self.pending = list(lines)
                return
        self.pending = []

    def said(self, needle):
        return any(needle in m for m in self.logs)


print("skills are trained evenly -- always the laggard")
skills = {"unarmed": 12, "dodge": 5, "parry": 5, "force": 30}
check("lowest first", fs.next_skill(skills, 30), "dodge")
check("ties break by name (stable rotation)",
      fs.next_skill({"parry": 5, "dodge": 5}, 30), "dodge")
check("a skill at the cap is skipped", fs.next_skill({"force": 30}, 30), None)
check("so is one the teacher cannot teach",
      fs.next_skill(skills, 30, unteachable={"dodge", "parry"}), "unarmed")
check("None when everything is capped",
      fs.next_skill({"a": 30, "b": 31}, 30), None)

print("\nthe rotation actually levels the set")
sim = {"unarmed": 1, "dodge": 1, "parry": 8}
for _ in range(30):
    s = fs.next_skill(sim, 20)
    sim[s] += 1
check("all three end within one level of each other",
      max(sim.values()) - min(sim.values()) <= 1, True)

print("\nlearn replies are classified, not guessed at")
cases = [("这项技能你恐怕必须找别人学了。", "cant"),
         ("你的潜能已经发挥到极限了，没有办法再成长了。", "spent"),
         ("菩提祖师说道：您太客气了，这怎么敢当？", "blocked"),
         ("依你目前的能力，没有办法学习这种技能。", "blocked"),
         ("你向菩提祖师学习了一会儿基本拳脚。", "ok")]
for reply, want in cases:
    api = FakeAPI({"learn": [reply]})
    check(f"{reply[:12]}…", fs.learn_once(api, "unarmed", "puti"), want)

print("\na teacher from another sect is refused, not joined")
table = {"puti": {"name": "菩提祖师", "family": "方寸山三星洞", "skills": {}},
         "guanyin": {"name": "观音菩萨", "family": "南海普陀山", "skills": {}}}
tmp = Path(tempfile.mkdtemp()) / "teachers.json"
tmp.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
fs.TEACHERS = tmp

api = FakeAPI({"title": ["你目前的头衔及门派：", "【小道士】 方寸山三星洞第四代弟子 鲁智深(Polar)"]})
check("same sect starts", fs.sect_ok(api, "puti"), True)

api = FakeAPI({"title": ["你目前的头衔及门派：", "【小道士】 方寸山三星洞第四代弟子 鲁智深(Polar)"]})
check("other sect refuses", fs.sect_ok(api, "guanyin"), False)
check("and never sends bai/apprentice",
      [c for c in api.sent if "bai" in c or "apprentice" in c], [])
check("and says why", api.said("不同门派学不了"), True)

api = FakeAPI({"title": ["【小道士】 方寸山三星洞第四代弟子"]})
check("an unknown name is refused too", fs.sect_ok(api, "nobody"), False)

print("\nthe map mudmap.load() hands back is one the walker can use")
# The live crash: 出错停止: 'short'. fangcun-skill did `rooms = mudmap.load()`
# and got the whole document -- {"areas": ..., "rooms": ...} -- so candidates()
# iterated the two TOP-LEVEL keys and hit r["short"] on the areas dict. The bot
# died on its first map lookup, every run. study.py:127 wrote
# `mudmap.load()["rooms"]` and worked, which is the tell: a function named
# load() in a module named mudmap must return the map, not the file.
sys.path.insert(0, str(HERE))
import mudmap
loaded = mudmap.load()
check("every entry is a room", all("short" in r for r in loaded.values()), True)
# Three rooms are 厢房 with an east exit; the two whose exits are EXACTLY
# {east} rank ahead of 车迟's, which merely contains it (west+east).
check("localisable without raising",
      mudmap.candidates(loaded, "厢房", {"east"}),
      ["d/lingtai/inside3", "d/lingtai/inside5", "d/qujing/chechi/xiang2"])

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
