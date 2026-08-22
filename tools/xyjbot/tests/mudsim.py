"""A stand-in for the mud server, driven by the real map.

Shared by the walking suites. It answers the same calls the bot makes
against a live connection -- send/wait_line/log/drain/sleep -- out of
rooms.json, so the bot has to work out where it is from nothing but the
text a player would see.

It lives in its own module rather than inside one suite because the bot's
walking bugs keep needing new knobs on it (`shove` came from the drifting
walk, `gates` from 南城客栈's unpaid bill, `refusals` from the 林中木屋
strand), and two copies of it would drift apart.

Only the walking suites import it; the others still load the bot themselves,
which is fine -- run_all.py runs every suite in its own process precisely so
module-level state (BROKEN_EXITS, RIDE, FORGIVEN) cannot leak between them.
Inside ONE process that state IS shared, so a suite with several cases has to
reset it between them the way the start of a job would.
"""
import importlib.util
import json
import random
import re
import sys
from pathlib import Path

# tools/xyjbot -- this module sits in tests/ underneath it.
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location("bot", HERE / "bots/changan-mieyao.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

DATA = json.loads((HERE / "rooms.json").read_text(encoding="utf-8"))
ROOMS = DATA["rooms"]


class MudSim:
    """Answers `look` and movement from the real map, so the bot has to
    localise from exactly the information the game gives a player.

    `shove` simulates a wandering monster displacing you after a move --
    the thing that makes a long walk drift -- and `gates` simulates exits
    that refuse to open (doors, valid_leave, sect checks).

    `refusals` is the same idea one level down: {(room, dir): (text, times)}
    refuses that move `times` times with that exact message and then lets it
    through, or forever if `times` is None. It exists because the bot has to
    tell refusals apart by what they SAY -- valid_move.h's 负荷过重 /
    动作还没有完成 / 你现在不能移动 are about the character and must not be
    mistaken for a shut exit.
    """
    def __init__(self, at, shove=0.0, gates=(), rng=None, refusals=None):
        self.at = at
        self.pending, self.logs, self.moves = [], [], 0
        self.shove, self.gates = shove, set(gates)
        self.refusals = dict(refusals or {})
        self.tries = {}
        self.rng = rng or random.Random(0)

    def stopped(self): return False
    def sleep(self, s): pass
    def drain(self): self.pending = []
    def log(self, m): self.logs.append(m)

    def said(self, needle):
        return any(needle in m for m in self.logs)

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
        if (self.at, cmd) in self.refusals:
            text, times = self.refusals[(self.at, cmd)]
            n = self.tries[(self.at, cmd)] = self.tries.get((self.at, cmd), 0) + 1
            if times is None or n <= times:
                self.pending = [text]; return
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
