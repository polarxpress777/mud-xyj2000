"""Tests for breaking off a fight and chasing a monster that runs.

Two things the mud tells us for free that the bot used to throw away:

  * go.lpc:85 announces a fleeing fighter to the room it leaves, naming
    the exit it took -- 白马精往上落荒而逃了。 One in ten 妖怪 gets
    env/wimpy 40 (yaoguai.lpc:483) and bolts at 40% 气血 every round, so
    those fights are a running battle rather than one exchange.
  * our own retreat is a `go`, so we know exactly which room we ran to
    and never need to re-localise. (There is no `flee` command in this
    mudlib at all -- cmds/std has no flee.lpc.)

Run with: python3 test_chase.py
"""
import importlib.util, re, sys
from pathlib import Path

# tools/xyjbot -- every path below is relative to it, so this
# stayed correct when the tests moved down into tests/.
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("bot", HERE / "bots/changan-mieyao.py")
bot = importlib.util.module_from_spec(spec); spec.loader.exec_module(bot)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


# A three-room strip plus a room above the middle one, all in 长安城.
#   west <-> mid <-> east,  mid up -> loft
ROOMS = {
    "d/city/west": {"short": "西头", "area": "d/city", "flags": {},
                    "exits": {"east": "d/city/mid"}},
    "d/city/mid": {"short": "路口", "area": "d/city", "flags": {},
                   "exits": {"west": "d/city/west", "east": "d/city/east",
                             "up": "d/city/loft"}},
    "d/city/east": {"short": "东头", "area": "d/city", "flags": {},
                    "exits": {"west": "d/city/mid"}},
    "d/city/loft": {"short": "阁楼", "area": "d/city", "flags": {},
                    "exits": {"down": "d/city/mid"}},
    "d/city/cell": {"short": "地牢", "area": "d/city", "flags": {},
                    "exits": {}},
}


class FakeAPI:
    """Walks the map above. `here` is the truth; the bot has to work it
    out from the room descriptions."""

    def __init__(self, here, monster_at=None, name="白马精", busy=0,
                 fight=()):
        self.here, self.monster_at, self.name = here, monster_at, name
        self.busy = busy          # moves refused with 动作还没有完成 first
        self.fight = list(fight)  # what `kill` produces, in order
        self.pending, self.logs, self.sent = [], [], []
        self.kee = 30

    # -- harness ---------------------------------------------------------
    def stopped(self): return False
    def drain(self): self.pending = []
    def log(self, m): self.logs.append(m)
    def sleep(self, n): pass

    def status(self):
        self.kee = min(100, self.kee + 40)      # heals between polls
        return {"kee": self.kee, "max_kee": 100,
                "water": 90, "max_water": 100, "food": 90, "max_food": 100}

    def wait_line(self, pattern, timeout=10.0):
        rx = re.compile(pattern)
        while self.pending:
            m = rx.search(self.pending.pop(0))
            if m:
                return m
        return None

    # -- the mud ---------------------------------------------------------
    def room_lines(self, path):
        r = ROOMS[path]
        out = [f"{r['short']} - {path}", "四下里看不出什么名堂。",
               "这里明显的出口是 " + "、".join(r["exits"]) + "。"]
        if self.monster_at == path:
            out.append(f"    {self.name}(Baima jing)")
        return out

    def send(self, cmd, quiet=False):
        self.sent.append(cmd)
        if cmd == "look":
            self.pending = self.room_lines(self.here)
            return
        if cmd.startswith("kill "):
            self.pending = self.fight
            return
        dest = ROOMS[self.here]["exits"].get(cmd)
        if dest is None:
            self.pending = ["这个方向没有出路。"]
            return
        if self.busy > 0:
            self.busy -= 1
            self.pending = ["你的动作还没有完成，不能移动。"]
            return
        self.here = dest
        self.pending = self.room_lines(dest)

    def moves(self):
        return [c for c in self.sent if c not in ("look",)]


print("往<方向>落荒而逃了 resolves to an exit")
check("北 -> north", bot.flee_dirs("北", {"north": 1, "south": 1}), ["north"])
check("上 -> up", bot.flee_dirs("上", {"up": 1}), ["up"])
check("北边 picks the exit this room actually has",
      bot.flee_dirs("北边", {"northdown": 1, "east": 1}), ["northdown"])
check("北边 with both stays ambiguous, both tried",
      bot.flee_dirs("北边", {"northup": 1, "northdown": 1}),
      ["northup", "northdown"])
check("a direction this room hasn't got is dropped",
      bot.flee_dirs("北", {"east": 1, "west": 1}), [])
check("an exit go.lpc had no Chinese name for is used verbatim",
      bot.flee_dirs("xiaolu", {"xiaolu": 1}), ["xiaolu"])
check("nonsense is not a direction", bot.flee_dirs("一阵青烟", {"north": 1}), [])

print("\nthe fight loop reports a runner instead of waiting out FIGHT_TIMEOUT")
api = FakeAPI("d/city/mid", fight=["白马精往上落荒而逃了。"])
check("direction carried out", bot.fight_target(api, "baima jing", "白马精"),
      "fled:上")

print("\n...but only for OUR monster, and not for our own wounds")
api = FakeAPI("d/city/mid", fight=["城管往北落荒而逃了。",
                                   "你得到了一千点武学经验和三百点潜能！"])
check("someone else running is ignored",
      bot.fight_target(api, "baima jing", "白马精"), "killed")
# combatd.lpc:218 puts the status on a line of its own: "( $N" + msg.
api = FakeAPI("d/city/mid",
              fight=["白马精一掌打在你胸口，你痛哼了一声。",
                     "( 你似乎十分疲惫，看来需要好好休息了。 )"])
check("our own wound still retreats",
      bot.fight_target(api, "baima jing", "白马精"), "hurt")

print("\nour own env/wimpy walking us out of the fight is reported too")
# std/char.lpc:96-102 -> go.lpc:132; the direction it picks is announced
# to the room we LEAVE, so all we get is the new room around us.
api = FakeAPI("d/city/mid", fight=["看来该找机会逃跑了．．．",
                                   "西头 - d/city/west",
                                   "这里明显的出口是 east。"])
check("reported as wimpy", bot.fight_target(api, "baima jing", "白马精"),
      "wimpy")

print("\n...but a failed flee is not a flee")
api = FakeAPI("d/city/mid", fight=["看来该找机会逃跑了．．．",
                                   "你逃跑失败。",
                                   "你得到了一千点武学经验和三百点潜能！"])
check("still fighting", bot.fight_target(api, "baima jing", "白马精"), "killed")
api = FakeAPI("d/city/mid", fight=["看来该找机会逃跑了．．．",
                                   "可你被定住了，逃不掉！",
                                   "你得到了一千点武学经验和三百点潜能！"])
check("held in place is not a flee",
      bot.fight_target(api, "baima jing", "白马精"), "killed")

print("\nresting after a wimpy flee doesn't try to retreat again")
api = FakeAPI("d/city/mid")
st, pos = bot.rest_until_healed(api, ROOMS, None, set(), retreat=False)
check("healed", st, "ok")
check("no move commands", api.moves(), [])

print("\na monster standing in a peace room is reported, not waited out")
api = FakeAPI("d/city/mid", fight=["这里不准战斗。"])
check("kill.lpc:19 refusal", bot.fight_target(api, "yema guai", "野马怪"),
      "nofight")
api = FakeAPI("d/city/mid", fight=["这里禁止战斗。"])
check("fight.lpc:10 refusal", bot.fight_target(api, "yema guai", "野马怪"),
      "nofight")

print("\n...and we watch which way it strolls off")
api = FakeAPI("d/city/mid")
api.pending = ["伺官(Si guan)", "野马怪往西离开。"]
check("direction read", bot.wait_for_exit(api, "野马怪", 1), "西")
check("which is an exit we can take", bot.flee_dirs("西", {"west": 1, "up": 1}),
      ["west"])

api = FakeAPI("d/city/mid")
api.pending = ["伺官往东离开。"]
check("someone else leaving is not our monster",
      bot.wait_for_exit(api, "野马怪", 1), None)

print("\nchase follows it one room and finds it there")
api = FakeAPI("d/city/mid", monster_at="d/city/loft")
pos, found = bot.chase(api, ROOMS, "d/city/mid", set(), "白马精", "baima jing", "上")
check("walked up", api.moves(), ["up"])
check("position tracked", pos, "d/city/loft")
check("spotted it", found, True)

print("\ngone by the time we get there: we still know where we are")
api = FakeAPI("d/city/mid", monster_at="d/city/east")
pos, found = bot.chase(api, ROOMS, "d/city/mid", set(), "白马精", "baima jing", "上")
check("position tracked", pos, "d/city/loft")
check("not found", found, False)

print("\nan unmappable direction leaves us where we were, no blind walking")
api = FakeAPI("d/city/mid")
pos, found = bot.chase(api, ROOMS, "d/city/mid", set(), "白马精", "baima jing", "西南")
check("no move sent", api.moves(), [])
check("position kept", pos, "d/city/mid")

print("\nbreaking off is a real move, and retries while mid-swing")
api = FakeAPI("d/city/mid", busy=2)
pos = bot.break_off(api, ROOMS, "d/city/mid", set())
check("kept asking until the swing finished", api.moves(), ["west", "west", "west"])
check("ended up next door", pos, "d/city/west")
check("no phantom flee command", [c for c in api.sent if c == "flee"], [])

print("\nblocked exits are skipped, not battered")
api = FakeAPI("d/city/mid")
pos = bot.break_off(api, ROOMS, "d/city/mid", {("d/city/mid", "west")})
check("took the next exit instead", api.moves(), ["east"])
check("position tracked", pos, "d/city/east")

print("\ncornered, and the only exit is one that refused us before: try it anyway")
api = FakeAPI("d/city/west")
pos = bot.break_off(api, ROOMS, "d/city/west", {("d/city/west", "east")})
check("last resort taken", api.moves(), ["east"])
check("position tracked", pos, "d/city/mid")

print("\nnowhere to go at all: say so and stay put rather than lose the position")
api = FakeAPI("d/city/cell")
pos = bot.break_off(api, ROOMS, "d/city/cell", set())
check("no move", api.moves(), [])
check("still there", pos, "d/city/cell")
check("and it says why", any("逃不掉" in m for m in api.logs), True)

print("\nresting keeps the position it retreated to")
api = FakeAPI("d/city/mid")
st, pos = bot.rest_until_healed(api, ROOMS, "d/city/mid", set())
check("healed", st, "ok")
check("knows the room", pos, "d/city/west")
check("no flee command", [c for c in api.sent if c == "flee"], [])

print("\na monster that follows us into the rest spot: give ground, keep resting")
api = FakeAPI("d/city/mid")
api.kee = 30
api.pending = ["白马精跌跌撞撞地跑了过来，模样有些狼狈。"]
st, pos = bot.rest_until_healed(api, ROOMS, "d/city/mid", set(),
                                retreat=False, name="白马精")
check("healed in the end", st, "ok")
check("backed off a room", api.moves(), ["west"])
check("said so", any("追过来" in m for m in api.logs), True)

print("\n...and if it dies there, the job is done -- stop hunting the corpse")
# yg/yaoguai.lpc:134 reports the reward to the owner wherever they are,
# so this arrives even though the bot never sent another `kill`.
api = FakeAPI("d/city/mid")
api.pending = ["你得到了一千点武学经验和三百点潜能！"]
st, pos = bot.rest_until_healed(api, ROOMS, "d/city/mid", set(),
                                retreat=False, name="白马精")
check("reported as killed", st, "killed")
check("didn't wander off", api.moves(), [])

print("\nthe death line arrives BEFORE the reward line -- both must count")
# Observed live: the monster followed us out, the fight restarted by itself
# and it died. The mud prints, in this order:
#     黑狮怪惨叫一声，死了。
#     你得到了三百二十五点武学经验和一百二十四点潜能！
# The first line contains the monster's NAME, so a watcher that acts on the
# first match concludes "it followed us" and retreats -- discarding the
# reward line behind it. The bot then hunted a corpse for the rest of the
# quest instead of going home.
api = FakeAPI("d/city/mid")
api.pending = ["黑狮怪惨叫一声，死了。",
               "你得到了三百二十五点武学经验和一百二十四点潜能！"]
st, pos = bot.rest_until_healed(api, ROOMS, "d/city/mid", set(),
                                retreat=False, name="黑狮怪")
check("job is done", st, "killed")
check("didn't back away from a corpse", api.moves(), [])

print("\n...and a live monster in the room still means give ground")
api = FakeAPI("d/city/mid")
api.kee = 30
api.pending = ["黑狮怪跌跌撞撞地跑了过来，模样有些狼狈。"]
st, pos = bot.rest_until_healed(api, ROOMS, "d/city/mid", set(),
                                retreat=False, name="黑狮怪")
check("healed in the end", st, "ok")
check("gave ground", api.moves(), ["west"])

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
