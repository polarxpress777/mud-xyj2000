"""Regression tests for eating and drinking.

饮水 at 0 does not slow 气血 regen, it stops it (feature/damage.lpc:465),
which wedged the bot in an endless "休息中…" at 50% 气血. These drive the
sustenance code with the mudlib's own reply strings.
Run with: python3 test_sustenance.py
"""
import importlib.util, re, sys, types
from pathlib import Path

# tools/xyjbot -- every path below is relative to it, so this
# stayed correct when the tests moved down into tests/.
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("bot", HERE / "bots/changan-mieyao-bot.py")
bot = importlib.util.module_from_spec(spec); spec.loader.exec_module(bot)


class FakeAPI:
    """Simulates the mud's replies to drink/eat/buy/withdraw."""
    def __init__(self, water=0, food=0, jiudai=0, gourou=0, money=0, balance=15529):
        self.w, self.f = water, food
        self.maxw = self.maxf = 100
        self.kee, self.maxkee = 136, 272
        self.jiudai, self.gourou, self.money, self.balance = jiudai, gourou, money, balance
        self.pending, self.logs, self.sent = [], [], []

    def stopped(self): return False
    def sleep(self, s): pass
    def drain(self): self.pending = []
    def log(self, m): self.logs.append(m)

    def status(self):
        return {"kee": self.kee, "max_kee": self.maxkee, "food": self.f,
                "max_food": self.maxf, "water": self.w, "max_water": self.maxw,
                "sen": 0, "max_sen": 0, "force": 0, "max_force": 0,
                "mana": 0, "max_mana": 0, "wuxue": 0, "potential": 0,
                "bellicosity": 0}

    def wait_line(self, pattern, timeout=10.0):
        rx = re.compile(pattern)
        while self.pending:
            line = self.pending.pop(0)
            m = rx.search(line)
            if m: return m
        return None

    def send(self, cmd, quiet=False):
        self.sent.append(cmd)
        self.pending = self._reply(cmd)

    def _reply(self, cmd):
        # -- drink jiudai : feature/liquid.lpc:29-66
        if cmd == "drink jiudai":
            if not self.jiudai:
                return ["什么？"]                        # verb unbound
            if self.jiudai_remaining <= 0:
                return ["桂花酒袋已经被喝得一滴也不剩了。"]
            if self.w >= self.maxw:
                return ["你已经喝太多了，再也灌不下一滴水了。"]
            self.jiudai_remaining -= 1
            self.w = min(self.maxw, self.w + 30)
            out = ["你拿起桂花酒袋咕噜噜地喝了几口桂花酒。"]
            if self.jiudai_remaining == 0:
                out.append("你已经将桂花酒袋里的桂花酒喝得一滴也不剩了。")
            return out
        # -- eat gou rou : feature/food.lpc:10-50
        if cmd == "eat gou rou":
            if not self.gourou:
                return ["什么？"]
            if self.gourou_remaining <= 0:
                return ["红烧狗肉已经没什么好吃的了。"]
            if self.f >= self.maxf:
                return ["你已经吃太饱了，再也塞不下任何东西了。"]
            self.gourou_remaining -= 1
            self.f = min(self.maxf, self.f + 100)
            if self.gourou_remaining == 0:
                return ["你将剩下的红烧狗肉吃得干干净净。"]
            return ["你拿起红烧狗肉吃了几口。"]
        # -- buy : cmds/std/buy.lpc + feature/vendor.lpc:15
        if cmd.startswith("buy "):
            key = cmd.split()[1]
            if self.money < 100:
                return ["你的钱不够。"]
            self.money -= 100
            if key == "jiudai":
                self.jiudai, self.jiudai_remaining = 1, 15
                return ["你向店小二买下一个桂花酒袋。"]
            self.gourou, self.gourou_remaining = 1, 2
            return ["你向店小二买下一份红烧狗肉。"]
        # -- withdraw : std/room/bank.lpc:127
        if cmd.startswith("withdraw "):
            amt = int(cmd.split()[1]) * 100
            if amt > self.balance:
                return ["你存的钱不够取。"]
            self.balance -= amt; self.money += amt
            return ["你从银号里取出十两银子。"]
        if cmd == "look":
            # A dead end, so break_off() has nowhere to run and the test
            # stays about resting rather than about retreating.
            return ["石室 - d/x/cell", "四壁都是石头。", "这里明显的出口是 无。"]
        if cmd == "drop jiudai":
            self.jiudai = 0
            return ["Ok."]
        return []

    jiudai_remaining = 0
    gourou_remaining = 0


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    return ok

fails = 0
print("1. thirsty+hungry, carrying a full 酒袋 and 狗肉 -> tops up from inventory")
a = FakeAPI(water=0, food=0, jiudai=1, gourou=1); a.jiudai_remaining, a.gourou_remaining = 15, 2
w, r = bot.drink_up(a); fails += not check("water", (w, r), (90, "ok"))
f, r = bot.eat_up(a);   fails += not check("food",  (f, r), (100, "ok"))

print("2. carrying nothing at all -> reports 'none', doesn't loop")
a = FakeAPI(water=0, food=0)
fails += not check("drink", bot.drink_up(a), (0, "none"))
fails += not check("eat",   bot.eat_up(a),   (0, "none"))

print("3. 酒袋 present but drained -> 'empty' (must NOT be read as success)")
a = FakeAPI(water=10, jiudai=1); a.jiudai_remaining = 0
fails += not check("drink", bot.drink_up(a), (10, "empty"))

print("4. last sip empties it -> still 'ok', not 'empty' (both lines arrive)")
a = FakeAPI(water=60, jiudai=1); a.jiudai_remaining = 1
fails += not check("drink", bot.drink_up(a), (90, "ok"))

print("5. already full -> stops immediately")
a = FakeAPI(water=100, food=100, jiudai=1, gourou=1); a.jiudai_remaining, a.gourou_remaining = 15, 2
fails += not check("drink", bot.drink_up(a), (100, "ok"))
fails += not check("sips sent", a.sent.count("drink jiudai"), 1)

print("6. buy with no cash -> 'broke'; after withdraw -> 'ok'")
a = FakeAPI(money=0)
fails += not check("buy", bot.buy_from_xiaoer(a, "gourou", "红烧狗肉"), "broke")
a.send("withdraw 10 silver")
fails += not check("buy after withdraw", bot.buy_from_xiaoer(a, "gourou", "红烧狗肉"), "ok")

print("7. drunk budget: MAX_SIPS caps the +5-per-sip drunk stacking")
limit = 20 * 6 + 210 // 50
fails += not check("max drunk from one top-up", bot.MAX_SIPS * 5 < limit, True)

print("8. rest_until_healed bails instead of spinning when 气血 is frozen")
a = FakeAPI(water=0, food=0); a.kee = 136
CELL = {"d/x/cell": {"short": "石室", "area": "d/x", "flags": {}, "exits": {}}}
st, where = bot.rest_until_healed(a, CELL, "d/x/cell", set())
fails += not check("gives up", st, "")
fails += not check("keeps the position", where, "d/x/cell")
fails += not check("polls bounded", len([l for l in a.logs if "休息中" in l]) <= bot.REST_STALL_LIMIT, True)
print("     last log:", a.logs[-1])

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILURE(S)"))
sys.exit(1 if fails else 0)
