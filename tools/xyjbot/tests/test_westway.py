"""Tests for reaching the whole of 长安城西.

袁天罡 names an area, MISC_D->find_place derives it from the spawn room's
DIRECTORY (find.map:56 -- d/westway 长安城西), and the bot then sweeps it.
Three things stopped that sweep covering the western half:

  * 饮马峪's 马盗 (yinma.lpc:31-45) refuses `northwest` until you pay,
    and that exit is the only road to 马道, 酒泉郊外, 石栈道, 嘉峪关,
    烽火台 and 云梯冈. Read as an ordinary shut exit, it cost every job
    whose target spawned out there.
  * the road doesn't stop at the directory boundary: 云梯冈 runs north
    into 五庄观's 山路 and 林荫小道, and a wandering 妖怪 goes with it.
  * 石栈道 is a trapdoor (shizhan.lpc:27) -- standing in it for 25
    seconds drops you into an exitless 铁笼.

Run with: python3 test_westway.py
"""
import importlib.util, json, re, sys
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


MAP = json.loads((HERE / "rooms.json").read_text(encoding="utf-8"))
ROOMS = MAP["rooms"]
WEST = MAP["areas"]["长安城西"]


print("the whole of 长安城西 is reachable from the 长安 end")
inside = bot.area_paths(ROOMS, WEST, "长安城西")
start = "d/westway/west1"          # 大官道, in through 西门
reach = {start}
frontier = [start]
while frontier:
    cur = frontier.pop()
    for d, nxt in ROOMS[cur]["exits"].items():
        if nxt in inside and nxt not in reach:
            reach.add(nxt)
            frontier.append(nxt)

for room in ("d/westway/madao", "d/westway/jiuquan", "d/westway/shizhan",
             "d/westway/jiayu", "d/westway/fenghuo", "d/westway/yunti"):
    check(f"{ROOMS[room]['short']} ({room.split('/')[-1]})", room in reach, True)

print("\n...including the stretch that runs on into 五庄观")
for room in ("d/qujing/wuzhuang/shanlu1", "d/qujing/wuzhuang/shanlu2",
             "d/qujing/wuzhuang/linyin1", "d/qujing/wuzhuang/linyin2"):
    check(f"{ROOMS[room]['short']} ({room.split('/')[-1]})", room in reach, True)

print("\nand bfs() routes the whole stretch, 石栈道 through to 林荫小道")
# They are not on one line -- 石栈道 is west of 酒泉郊外, 林荫小道 north of
# 云梯冈 -- so this is the sweep proving it can cross from one end of the
# western road to the other without leaving the area.
path = bot.bfs(ROOMS, inside, "d/westway/shizhan", {"d/qujing/wuzhuang/linyin2"})
check("route exists", path is not None, True)
check("ends at 林荫小道", ROOMS[path[-1][1]]["short"] if path else None, "林荫小道")
check("stays inside the search area",
      all(p in inside for _, p in (path or [])), True)
check("via 酒泉郊外 and 云梯冈",
      [ROOMS[p]["short"] for _, p in (path or [])][:3],
      ["酒泉郊外", "云梯冈", "山路"])

print("\nthe extension is per-area, not global")
city = bot.area_paths(ROOMS, MAP["areas"]["长安城"], "长安城")
check("五庄观 rooms stay out of 长安城",
      any(p.startswith("d/qujing/wuzhuang") for p in city), False)
check("and 长安城 is unchanged in size",
      len(city), sum(1 for p, r in ROOMS.items() if r["area"] in MAP["areas"]["长安城"]))

print("\n马盗's shakedown is a toll, not a wall")
check("his refusal is recognised",
      bool(re.search(bot.TOLL_RE, "马盗喊叫着：不给钱我要杀人啦！")), True)
check("so is the grab",
      bool(re.search(bot.TOLL_RE, "马盗恶狠狠地劈胸一把揪住你：往哪儿跑！给钱！")), True)
check("and his stand-aside",
      bool(re.search(bot.TOLL_OK, "马盗嘿嘿嘿几声怪笑，闪身让道。")), True)
check("200 文 is what he wants (madao.lpc:49)", bot.TOLL_SILVER * 100 >= 200, True)


class TollAPI:
    """Refuses the move until the toll is paid, then lets it through."""
    def __init__(self):
        self.paid = False
        self.pending, self.logs, self.sent = [], [], []

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

    def send(self, cmd, quiet=False):
        self.sent.append(cmd)
        if cmd.startswith("give"):
            self.paid = True
            self.pending = ["马盗嘿嘿嘿几声怪笑，闪身让道。"]
        elif cmd == "northwest":
            self.pending = (["马道 - d/westway/madao", "这里明显的出口是 west。"]
                            if self.paid else
                            ["马盗喊叫着：不给钱我要杀人啦！"])
        else:
            self.pending = []


api = TollAPI()
title, _, _ = bot.step_full(api, "northwest")
check("got through", title, "马道")
check("paid, then walked", api.sent,
      ["northwest", f"give {bot.TOLL_SILVER} silver to {bot.TOLL_TARGET}",
       "northwest"])

print("\n石栈道 is walked through, never stood in")
check("listed as a trap", "石栈道" in bot.TRAP_ROOMS, True)
check("watched for less time than the 25s fuse", bot.TRAP_WAIT < 25, True)
check("the cage it drops you in has no exits on the map",
      ROOMS["d/westway/tielong"]["exits"], {})
check("but 山洞内 leads back out to it",
      ROOMS["d/westway/lu1"]["exits"]["south"], "d/westway/shizhan")

print("\n海底莽林 is entered only by a character who can survive its residents")
# Two 海兽 there have attitude "aggressive" (feature/attack.lpc:244 ->
# auto_fight on entry) at 170k and 370k combat_exp. 袁天罡 caps his quests at
# (daoxing+combat_exp)/2 = 50,000, so his questers are never strong enough.
# The table is generated into danger.json; these are real entries from it.
MAZE = {"d/sea/maze2": {"short": "海底莽林", "area": "d/sea", "flags": {},
                        "exits": {}},
        "d/sea/under1": {"short": "海底", "area": "d/sea", "flags": {},
                         "exits": {}}}


class Char:
    def __init__(self, wuxue): self.wuxue = wuxue; self.logs = []
    def log(self, m): self.logs.append(m)
    def status(self): return {"wuxue": self.wuxue}


check("danger.json was generated", bot.DANGER_FILE.exists(), True)

bot.DANGER.clear()
weak = Char(40_000)                       # a 袁天罡 quester
shut = bot.assess_danger(weak)
check("it lists the maze room", "d/sea/maze2" in bot.DANGER, True)
check("and 高老庄's 夏鹏展 room", any(p.startswith("d/gao/") for p in bot.DANGER), True)
check("a 袁天罡 quester stays out", bot.avoided(MAZE, "d/sea/maze2"), True)
check("but ordinary rooms are fine", bot.avoided(MAZE, "d/sea/under1"), False)
check("and it says how many are shut", shut > 0, True)

strong = Char(900_000)                    # a 李靖 quester
bot.assess_danger(strong)
check("a strong character goes in", bot.avoided(MAZE, "d/sea/maze2"), False)

bot.assess_danger(weak)
check("the clearance is not permanent", bot.avoided(MAZE, "d/sea/maze2"), True)

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
