"""Regression tests for the walker getting stuck in identical rooms.

The bot looped forever east of 长安: 长安城东门 -> 大官道 -> 长安城东门 ...
Two separate defects combined to cause it, and both are covered here.
Run with: python3 test_localise.py
"""
import importlib.util, json, random, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("bot", HERE / "bots/changan-mieyao-bot.py")
bot = importlib.util.module_from_spec(spec); spec.loader.exec_module(bot)
DATA = json.loads((HERE / "rooms.json").read_text(encoding="utf-8"))
ROOMS = DATA["rooms"]


class MudSim:
    """Answers `look` and movement from the real map, so the bot has to
    localise from exactly the information the game gives a player.

    `shove` simulates a wandering monster displacing you after a move --
    the thing that makes a long walk drift -- and `gates` simulates exits
    that refuse to open (doors, valid_leave, sect checks).
    """
    def __init__(self, at, shove=0.0, gates=(), rng=None):
        self.at = at
        self.pending, self.logs, self.moves = [], [], 0
        self.shove, self.gates = shove, set(gates)
        self.rng = rng or random.Random(0)

    def stopped(self): return False
    def sleep(self, s): pass
    def drain(self): self.pending = []
    def log(self, m): self.logs.append(m)

    def _render(self):
        r = ROOMS[self.at]
        ex = list(r["exits"])
        return [f"{r['short']} - {self.at}",
                "这里是一段描述文字。",
                f"    这里明显的出口是 {' 和 '.join(ex)}。" if ex else "    这里没有明显的出口。"]

    def send(self, cmd, quiet=False):
        if cmd == "look":
            self.pending = self._render(); return
        if (self.at, cmd) in self.gates:
            self.pending = ["有什么东西挡住了去路。"]; return
        dest = ROOMS[self.at]["exits"].get(cmd)
        if dest and dest in ROOMS:
            self.at = dest; self.moves += 1
            if self.rng.random() < self.shove:
                nb = [t for t in ROOMS[self.at]["exits"].values() if t in ROOMS]
                if nb:
                    self.at = self.rng.choice(nb)
            self.pending = self._render()
        else:
            self.pending = ["你不能往那个方向走。"]

    def wait_line(self, pattern, timeout=10.0):
        rx = re.compile(pattern)
        while self.pending:
            m = rx.search(self.pending.pop(0))
            if m: return m
        return None


def trial(start, dirs=None):
    sim = MudSim(start)
    got = bot.relocalise(sim, ROOMS, dirs=dirs)
    ok = got == sim.at and got is not None
    print(f"  {'PASS' if ok else 'FAIL'}  start {start:22} -> resolved {str(got):22} "
          f"actually {sim.at:22} ({sim.moves} probe move(s))")
    return ok

def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    return ok


fails = 0
print("A. the 大官道 corridor east of 长安 (5 identical rooms, all west/east)")
for r in ["d/kaifeng/east1", "d/kaifeng/east2", "d/kaifeng/east3",
          "d/kaifeng/east4", "d/kaifeng/east5"]:
    fails += not trial(r)

print("\nB. the 大官道 rooms west of 长安 (d/westway) -- same title, different area")
for r in ["d/westway/west1", "d/westway/west2", "d/westway/west3"]:
    fails += not trial(r)

print("\nC. unambiguous rooms still resolve with zero probe moves")
for r in ["d/city/dongmen", "d/city/tianjiantai", "d/city/kezhan", "d/city/bank"]:
    sim = MudSim(r)
    got = bot.relocalise(sim, ROOMS)
    ok = got == r and sim.moves == 0
    print(f"  {'PASS' if ok else 'FAIL'}  {r:22} -> {got} ({sim.moves} moves)")
    fails += not ok

print("\nD. every ambiguous room in 开封城 / 长安城 / eastway / westway")
areas = ["d/kaifeng", "d/city", "d/eastway", "d/westway", "d/changan"]
# Titleless entries (d/city/misc/scoresheet and friends) are objects
# that happen to inherit ROOM, not places -- candidates() refuses to
# match an empty title on purpose, so they are not walker territory.
amb = [p for p, r in ROOMS.items() if r["area"] in areas and r["short"]
       and sum(1 for q, s in ROOMS.items()
               if s["short"] == r["short"] and set(s["exits"]) == set(r["exits"])) > 1]
bad = []
for r in amb:
    sim = MudSim(r)
    got = bot.relocalise(sim, ROOMS)
    if got != sim.at or got is None:
        bad.append((r, got, sim.at))
print(f"  {len(amb)} ambiguous rooms tested, {len(bad)} unresolved")
for r, got, real in bad[:15]:
    print(f"     UNRESOLVED {r:26} guessed {str(got):26} really {real}")
fails += len(bad) > 0

print("\nE. bfs() distinguishes 'already at a goal' from 'no route'")
# The original hang: arriving in the target area put the walker in a
# room that was itself unsearched, bfs returned [], `if not path` read
# that as unreachable, and the walker reset and wandered back out.
goals = {p for p, r in ROOMS.items() if r["area"] == "d/kaifeng"}
here = bot.bfs(ROOMS, bot.area_paths(ROOMS, ["d/kaifeng"]), "d/kaifeng/east1", goals, set())
fails += not check("standing in a goal -> []", here, [])
away = bot.bfs(ROOMS, bot.area_paths(ROOMS, ["d/kaifeng"]), "d/kaifeng/east1",
               {"d/kaifeng/east3"}, set())
fails += not check("goal elsewhere -> a path", bool(away) and away[-1][1],
                   "d/kaifeng/east3")
none = bot.bfs(ROOMS, bot.area_paths(ROOMS, ["d/kaifeng"]), "d/kaifeng/east1", {"d/city/kezhan"}, set())
fails += not check("goal outside the area -> None", none, None)
fails += not check("[] and None are distinguishable", (here is None, none is None),
                   (False, True))

print("\nF. walk_to() survives being shoved around on a long walk")
# The live failure: the bot ended up in 高老庄 and logged 自己走不回天监台
# even though 天监台 was 27 steps away. Three separate causes -- travel()
# returning None was treated as fatal instead of "re-localise", a shove
# burned one of only three retries, and a blocked exit was recorded
# against a possibly-drifted position, poisoning the route graph.
YUAN = "d/city/tianjiantai"
STARTS = [r for r in ["d/gao/tulu", "d/gao/lu1", "d/changan/wroad1",
                      "d/kaifeng/east3", "d/westway/west2", "d/moon/moon1"]
          if r in ROOMS]
# Gates chosen inside 长安城's grid, where a detour exists -- a gate on a
# linear corridor genuinely severs the route, and failing there is right.
GATES = [("d/city/qinglong-e3", "west"), ("d/city/center", "south")]

for label, shove, gates in [("no interference", 0.0, ()),
                            ("25% shove", 0.25, ()),
                            ("40% shove", 0.40, ()),
                            ("25% shove + passable gates", 0.25, GATES)]:
    ok = tot = 0
    for seed in range(15):
        for st in STARTS:
            sim = MudSim(st, shove, gates, random.Random(seed))
            if bot.walk_to(sim, ROOMS, set(), YUAN, "天监台") and sim.at == YUAN:
                ok += 1
            tot += 1
    fails += not check(f"{label}: reaches 天监台", (ok, tot), (tot, tot))

# A genuinely unreachable goal must fail cleanly and bounded, not spin.
SEVERED = [("d/gao/road3", "east"), ("d/gao/lu1", "east"), ("d/gao/road4", "east")]
sim = MudSim("d/gao/tulu", 0.0, SEVERED, random.Random(1))
got = bot.walk_to(sim, ROOMS, set(), YUAN, "天监台")
fails += not check("severed route gives up", got, False)
fails += not check("and stays bounded", sim.moves <= bot.WALK_MAX_STEPS, True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILURE GROUP(S)"))
sys.exit(1 if fails else 0)
