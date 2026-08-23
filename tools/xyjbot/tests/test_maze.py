"""How thoroughly does the bot actually search 紫竹林?

紫竹林 (d/nanhai/zhulin*.lpc) is 18 identical-looking rooms whose exits are
randomised at create() time, so the static map is useless inside and the
bot sweeps by wandering. The grove has three ways out, and the old sweep
tried them FIRST -- it usually walked out of the maze within a move or two
and reported "clear" having seen almost nothing.

This rebuilds the grove exactly as the room files do, hides the quest
target in one of the 18 rooms, and measures how often a sweep finds it.
Run with: python3 test_maze.py
"""
import importlib.util, random, re, sys
from pathlib import Path

# tools/xyjbot -- every path below is relative to it, so this
# stayed correct when the tests moved down into tests/.
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("bot", HERE / "bots/changan-mieyao.py")
bot = importlib.util.module_from_spec(spec); spec.loader.exec_module(bot)
bot.STEP_PAUSE = 0

fails = []


def check(label, got, want, cmp=lambda a, b: a == b):
    ok = cmp(got, want)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def build_grove(rng):
    """The exits from d/nanhai/zhulin0-17.lpc, random parts re-rolled."""
    def z6():  return f"zhulin{rng.randrange(6)}"
    def z9():  return f"zhulin{6 + rng.randrange(9)}"

    g = {
        "zhulin0": {"northeast": z6(), "northwest": z6(), "south": "小路"},
        "zhulin3": {"southwest": z6(), "northwest": z6(),
                    "northeast": "zhulin5", "southeast": z6()},
        "zhulin4": {"southwest": z6(), "northwest": "zhulin5",
                    "northeast": z6(), "southeast": z6()},
        "zhulin5": {"southwest": z6(), "northwest": z9(),
                    "northeast": z9(), "southeast": z6()},
        "zhulin7": {"south": z6(), "west": z9(), "north": "zhulin10", "east": z9()},
        "zhulin9": {"south": z9(), "west": z9(), "north": z9(), "east": "zhulin10"},
        "zhulin10": {"south": "zhulin7", "west": "zhulin9",
                     "north": "zhulin15", "east": "zhulin11"},
        "zhulin11": {"south": z9(), "west": "zhulin10", "north": z9(), "east": z9()},
        "zhulin12": {"south": "zhulin6", "west": z9(), "north": z9(), "east": z9()},
        "zhulin13": {"south": "zhulin10", "west": z9(), "north": z9(), "east": z9()},
        "zhulin15": {"north": "池塘边", "west": "zhulin16",
                     "south": z9(), "east": "zhulin17"},
        "zhulin16": {"east": "zhulin15", "enter": "罗汉塔"},
        "zhulin17": {"west": "zhulin15", "enter": "罗汉塔"},
    }
    for i in (1, 2):
        g[f"zhulin{i}"] = {"southwest": z6(), "northwest": z6(),
                           "northeast": z6(), "southeast": z6()}
    for i in (6, 8, 14):
        g[f"zhulin{i}"] = {"south": z6() if i != 14 else "zhulin8",
                           "west": z9(), "north": z9(), "east": z9()}
    # The rooms just outside, and the way back in.
    g["小路"] = {"north": "zhulin0", "southeast": "road3", "southwest": "road33"}
    g["池塘边"] = {"south": "zhulin15"}
    g["罗汉塔"] = {"out": "zhulin16", "southup": "luohanw2"}
    g["road3"] = {"northwest": "小路"}
    g["road33"] = {"northeast": "小路"}
    g["luohanw2"] = {"northdown": "罗汉塔"}
    return g


class GroveSim:
    """Answers look/movement from a freshly rolled grove, with the target
    hidden in one room. `wander` moves it like yaoguai.lpc's random_move."""

    def __init__(self, seed, target="马鹿精", wander=0.0, start="zhulin0"):
        self.rng = random.Random(seed)
        self.g = build_grove(self.rng)
        self.at = start
        self.target = target
        self.mob = f"zhulin{self.rng.randrange(18)}"
        self.wander = wander
        self.pending, self.logs, self.moves = [], [], 0

    def stopped(self): return False
    def sleep(self, s): pass
    def drain(self): self.pending = []
    def log(self, m): self.logs.append(m)

    def _title(self, room):
        return "紫竹林" if room.startswith("zhulin") else room

    def _render(self):
        ex = list(self.g[self.at])
        out = [f"{self._title(self.at)} - /d/nanhai/{self.at}",
               "紫竹细疏，清风微拂。",
               f"    这里明显的出口是 {'、'.join(ex[:-1])} 和 {ex[-1]}。"]
        if self.at == self.mob:
            out.append(f"  {self.target}(Malu jing)")
        return out

    def _drift(self):
        if self.wander and self.rng.random() < self.wander:
            nxt = [d for d in self.g[self.mob].values() if d.startswith("zhulin")]
            if nxt:
                self.mob = self.rng.choice(nxt)

    def send(self, cmd, quiet=False):
        if cmd == "look":
            self.pending = self._render()
            return
        dest = self.g[self.at].get(cmd)
        if dest:
            self.at = dest
            self.moves += 1
            self._drift()
            self.pending = self._render()
        else:
            self.pending = ["你不能往那个方向走。"]

    def wait_line(self, pattern, timeout=10.0):
        rx = re.compile(pattern)
        while self.pending:
            m = rx.search(self.pending.pop(0))
            if m:
                return m
        return None


def run_trials(n=400, wander=0.0, moves=None):
    """(hit rate %, average moves, average moves when it MISSES).

    The miss figure is the interesting one: a sweep that gives up early
    misses cheaply, which is exactly the shallowness this guards against.
    """
    found, walked, missed = 0, 0, []
    for seed in range(n):
        sim = GroveSim(seed, wander=wander)
        kw = {"max_moves": moves} if moves else {}
        if bot.sweep_maze(sim, "紫竹林", "马鹿精", "malu jing", **kw) == "found":
            found += 1
        else:
            missed.append(sim.moves)
        walked += sim.moves
    avg_miss = sum(missed) // len(missed) if missed else 0
    return found * 100 // n, walked // n, avg_miss


# --- walking home ---------------------------------------------------------
# relocalise() knew about the cage and about AVOID_ROOMS but never about
# MAZE_ROOMS, so walking home from the grove localised 紫竹林, found ten
# identical candidates, probed `east`, and looped until the walker gave up:
#   「紫竹林」有 10 间同名房间，往 east 走一步确认是哪一间。
HOME_ROOMS = {
    "d/nanhai/road4": {"short": "小路", "area": "d/nanhai", "flags": {},
                       "exits": {"north": "d/nanhai/zhulin0",
                                 "south": "d/nanhai/road3"}},
    "d/nanhai/road3": {"short": "山道", "area": "d/nanhai", "flags": {},
                       "exits": {"north": "d/nanhai/road4"}},
}


class HomeSim:
    """Stuck in 紫竹林 until something steps south into 小路."""

    def __init__(self):
        self.out = False
        self.pending, self.sent, self.logs = [], [], []

    def stopped(self): return False
    def drain(self): self.pending = []
    def log(self, m): self.logs.append(m)
    def sleep(self, n): pass

    def wait_line(self, pattern, timeout=10.0):
        rx = re.compile(pattern)
        while self.pending:
            m = rx.search(self.pending.pop(0))
            if m:
                return m
        return None

    def room(self):
        if self.out:
            return ["小路 - d/nanhai/road4", "这里明显的出口是 north、south。"]
        return ["紫竹林 - ", "这里明显的出口是 west、east、north 和 south。"]

    def send(self, cmd, quiet=False):
        self.sent.append(cmd)
        if cmd == "south" and not self.out:
            self.out = True          # zhulin0 south -> road4, the only door
        self.pending = self.room()


print("\nthe way out is chosen by looking, then picking -- and picking randomly")
# The grove's looping exits are "zhulin" + random(6) evaluated in create(),
# so each room's southwest is FIXED at load. A walk that always prefers the
# same direction is therefore deterministic, and a deterministic walk in a
# fixed graph falls into a cycle: observed live as nine identical rooms in a
# row while the bot looked, stepped southwest, and looked again forever.
check("zhulin0's door is taken, not gambled",
      bot.maze_escape_choice({"northeast", "northwest", "south"}), "south")
# `enter` is NOT a way out and must never be chosen when ESCAPING.
# zhulin16/17's enter leads to 罗汉塔 -- 20 rooms that all share that name,
# whose only non-罗汉塔 exit is `out`, straight back into the grove.
# luohanw1 and luohane1 even have identical exit sets {southup, out}, so
# candidates() can never tell them apart. Taking `enter` swapped one maze for
# a worse one: live, the bot escaped to 罗汉塔, relocalise probed `out` to
# disambiguate, landed back in 紫竹林, and ping-ponged until it gave up.
check("enter is refused -- it goes deeper, not out",
      bot.maze_escape_choice({"east", "enter"}), "east")
check("and is never the random pick either",
      {bot.maze_escape_choice({"east", "west", "enter"}) for _ in range(60)},
      {"east", "west"})

# Uniform, NOT southward-only. Restricting to southwest/southeast means
# northwest and northeast can never be taken, so the walk explores a
# subgraph -- measured at 42/360 stuck versus 3/360 for uniform.
diag = {"southeast", "southwest", "northeast", "northwest"}
picks = {bot.maze_escape_choice(diag) for _ in range(80)}
check("every exit is reachable by the chooser", picks, diag)

print("\nso escaping terminates from EVERY room, not just from the door")
# GroveSim starts at zhulin0 by default -- which is the room with the door,
# so an escape test from there proves nothing. Start from all 18.
STARTS = [f"zhulin{i}" for i in range(18)]
failures, worst = 0, 0
for seed in range(40):
    for start in STARTS:
        sim = GroveSim(seed, start=start)
        if not bot.escape_maze(sim, "紫竹林"):
            failures += 1
        worst = max(worst, sim.moves)
# NOT `== 0`: escaping is a random walk with an unbounded tail, so a strict
# zero is a coin flip that will eventually fail for no reason -- it did,
# which is how the budget came to be measured properly (2160 runs: 2 stuck
# at 150, 0 at 300, max 220 moves). Guard the RATE.
check("essentially always gets out", failures <= 1, True)
check("inside the budget", worst <= 300, True)
print(f"     {40 * len(STARTS)} runs, worst took {worst} moves")

print("\n...and a FIXED preference would not, which is the bug this guards")
# Replace the chooser with the old fixed-order one and the walk becomes
# deterministic: same room, same exit, every time. In a graph whose exits
# were fixed at create() time that is a cycle, and the bot never leaves.
real = bot.maze_escape_choice
bot.maze_escape_choice = lambda ex, rng=None: (
    "south" if set(ex) == bot.MAZE_DOOR_SIG else
    "enter" if "enter" in ex else
    next((d for d in ("southwest", "southeast") if d in ex), sorted(ex)[0]))
stuck = 0
for seed in range(20):
    for start in STARTS:
        sim = GroveSim(seed, start=start)
        if not bot.escape_maze(sim, "紫竹林"):
            stuck += 1
bot.maze_escape_choice = real
check("the deterministic version does get stuck", stuck > 0, True)
print(f"     {stuck} of {20 * len(STARTS)} runs never escaped")

print("\nwalking home from the grove escapes it instead of probing forever")
# maze_escape_choice() picks UNIFORMLY at random on purpose -- a fixed
# preference order walks a cycle in the grove's fixed graph, which is the bug
# the section above guards. In HomeSim every direction except south leaves you
# where you were, so each probe is an independent 1-in-4 and the number of
# probes is pure luck: measured over 300 seeds it runs 4 / 8 / 24 / 48
# (min / median / p95 / max). The old assertion `api.sent.count("east") < 3`
# was asserting luck, and failed about 1 run in 5 with nothing wrong.
#
# What is NOT luck, and is what the test actually means: the walk stops the
# moment the door works. Assert that instead -- it holds for every seed.
api = HomeSim()
pos = bot.relocalise(api, HOME_ROOMS)
moves = [c for c in api.sent if c != "look"]
check("localised outside the grove", pos, "d/nanhai/road4")
check("by taking the door south", "south" in moves, True)
check("tried the door once, not repeatedly", moves.count("south"), 1)
check("and stopped as soon as it worked", moves[-1], "south")

print(f"budget is MAZE_SWEEP_MOVES = {bot.MAZE_SWEEP_MOVES}, "
      f"re-entries {bot.MAZE_REENTRIES}")

print("\na still target hidden in one of the 18 rooms")
rate, moves, miss_moves = run_trials()
print(f"       found {rate}% of the time, {moves} moves per sweep on average")
print(f"       when it misses it has spent {miss_moves} moves first")
check("finds it nearly always", rate, 85, lambda a, b: a >= b)
# The remaining misses are rooms nothing points to on that boot (zhulin16
# and 17 hang off zhulin15, which only zhulin10's north reaches), not the
# sweep bailing out: those runs spend the whole budget looking.
check("a miss is a full search, not a bail-out", miss_moves,
      bot.MAZE_SWEEP_MOVES * 8 // 10, lambda a, b: a >= b)

print("\nand one that wanders while we search (yaoguai.lpc random_move)")
rate_w, moves_w, _ = run_trials(wander=0.3)
print(f"       found {rate_w}% of the time, {moves_w} moves per sweep")
check("still finds it", rate_w, 90, lambda a, b: a >= b)

print("\nthe old shallow budget is measurably worse (regression guard)")
# Ways out first, tiny budget -- what the sweep used to do. Emulated by
# giving it barely any budget, since the exit-first ordering is gone.
rate_old, moves_old, _ = run_trials(moves=5)
print(f"       5-move sweep finds {rate_old}%, {moves_old} moves")
check("depth matters", rate, rate_old, lambda a, b: a > b + 20)

print("\nways out are taken last, so a sweep doesn't leak out of the grove")
sim = GroveSim(7)
check("zhulin0's south is last", bot.maze_choices(
    ["northeast", "northwest", "south"])[-1], "south")
check("enter is last", bot.maze_choices(["east", "enter"])[-1], "enter")
# ...but a plain south inside the grove is an ordinary move, not an exit.
# maze_choices() SHUFFLES the inner group, so asking whether south lands in
# the first three is a 3-in-4 coin toss -- this assertion used to pass by
# luck and failed the moment an unrelated change shifted the RNG state.
# What it actually means to say is that south is not pinned last, i.e. it is
# in the inner group: over many shuffles it must sometimes come out first.
inner_first = any(
    bot.maze_choices(["south", "west", "north", "east"])[0] == "south"
    for _ in range(50))
check("inner south is not deferred", inner_first, True)
check("and zhulin0's south still is", all(
    bot.maze_choices(["northeast", "northwest", "south"])[-1] == "south"
    for _ in range(20)), True)

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
