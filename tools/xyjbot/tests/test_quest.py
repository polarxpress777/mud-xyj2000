"""Regression tests for the mieyao bot abandoning a live quest, then parking.

The incident: the hunt for 山鸡精 ran out, the bot walked home, and 袁天罡
answered 在下不是请您去收服山鸡精吗？ -- the job was STILL LIVE. The bot
parked at 天监台 and watched, throwing away the area it had been searching.
The player found the monster by hand in 兵器铺, and even then the bot could
not act:

    [bot] 山鸡精 出现了，动手！
    [bot] -> kill 山鸡精
    > 这里没有这个人。

yaoguai.lpc:219-225 does set_name(name, id) with name 山鸡精 and ids
({"shanji jing", "jing"}). present() matches ids, so the Chinese name can
never address the monster. The room prints the id it needs -- 山鸡精(Shanji
jing) -- and the bot never read it.

Run with: python3 test_quest.py
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mudsim import MudSim, ROOMS, bot

bot.STEP_PAUSE = 0


class FakeAPI:
    def __init__(self, lines=()):
        self.pending, self.logs, self.sent = list(lines), [], []
        self.on_send = {}

    def stopped(self): return False
    def sleep(self, s): pass
    def drain(self): self.pending = []
    def log(self, m): self.logs.append(m)

    def said(self, needle):
        return any(needle in m for m in self.logs)

    def send(self, cmd, quiet=False):
        self.sent.append(cmd)
        self.pending = list(self.on_send.get(cmd, []))

    def wait_line(self, pattern, timeout=10.0):
        rx = re.compile(pattern)
        while self.pending:
            m = rx.search(self.pending.pop(0))
            if m:
                return m
        return None


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    return ok


fails = 0

print("A. the id is read off the room, never guessed from the Chinese name")
ROOM_LINE = "  小小  山鸡精(Shanji jing)"
fails += not check("id parsed from a room listing",
                   bot.monster_id(ROOM_LINE, "山鸡精"), "shanji jing")
fails += not check("a bare arrival line yields nothing",
                   bot.monster_id("山鸡精走了过来。", "山鸡精"), None)
fails += not check("someone else's id is not mistaken for ours",
                   bot.monster_id("  游侠儿(Youxia er)", "山鸡精"), None)

print("\nB. a sighting without an id triggers `look` before attacking")
# 兵器铺 is where the player found it. An arrival line may be the ONLY
# mention before it wanders off, so the id has to be fetched, not skipped.
api = FakeAPI()
api.on_send["look"] = ["兵器铺 - ", "    这里唯一的出口是 north。", ROOM_LINE]
got = bot.identify_target(api, "山鸡精")
fails += not check("looked", "look" in api.sent, True)
fails += not check("and got the id", got, "shanji jing")

print("\nC. with no id anywhere, it does not fall back to the Chinese name")
# `kill 山鸡精` is the line that produced 这里没有这个人. Sending it is
# always wrong; sending the bare `jing` id would attack an unrelated 精.
api = FakeAPI()
api.on_send["look"] = ["兵器铺 - ", "    这里唯一的出口是 north。"]
got = bot.identify_target(api, "山鸡精")
fails += not check("no id found", got, None)
fails += not check("never sent kill", [c for c in api.sent if "kill" in c], [])

print("\nD. pouncing on a wanderer attacks by id, or not at all")
api = FakeAPI()
api.on_send["look"] = ["兵器铺 - ", "    这里唯一的出口是 north。", ROOM_LINE]
api.on_send["kill shanji jing"] = ["山鸡精和你仇人相见份外眼红，立刻打了起来！",
                                   "山鸡精惨叫一声，死了。",
                                   "你得到了 300 点武学经验和 30 点潜能"]
bot.pounce(api, "山鸡精")
fails += not check("attacked by id", "kill shanji jing" in api.sent, True)
fails += not check("never by name",
                   [c for c in api.sent if "kill 山鸡精" in c], [])

api = FakeAPI()
api.on_send["look"] = ["兵器铺 - ", "    这里唯一的出口是 north。"]
bot.pounce(api, "山鸡精")
fails += not check("unidentifiable -> no attack at all",
                   [c for c in api.sent if c.startswith("kill")], [])
fails += not check("and says why", api.said("认不出"), True)

print("\nE. the hunt uses the WHOLE budget, not a reserve short of it")
# The old loop stopped QUEST_SECS - 120 in, to be standing at 天监台 when the
# job lapsed. Nothing lapses on a clock you must catch (yuantiangang.lpc:145-168
# issues the next job on whatever ask comes after t+600), so that 120s was a
# fifth of every quest given away -- and it produced the still-outstanding
# reply the bot then handled by parking.
job = bot.Job("山鸡精", "shanji jing", "长安城",
              ["d/city"], bot.area_paths(ROOMS, ["d/city"], "长安城"), None)
sim = MudSim("d/city/tianjiantai")
began = time.time()
killed = bot.hunt(sim, ROOMS, job, began + 1.5, set())
spent = time.time() - began
fails += not check("nothing killed", killed, False)
fails += not check("hunted until the deadline", spent >= 1.4, True)
fails += not check("and actually searched", sim.moves > 0, True)

print("\nF. no HOMEWARD_RESERVE remains to give the budget away")
fails += not check("constant is gone", hasattr(bot, "HOMEWARD_RESERVE"), False)

print("\nG. a job 袁天罡 still considers open is RESUMED, not parked on")
# The incident: the bot walked home, was told 在下不是请您去收服山鸡精吗？,
# and parked at 天监台 -- discarding the area it had been searching sixty
# seconds earlier. The monster was wandering 长安城; the player found it in
# 兵器铺 by hand.
now = 1000.0
fails += not check("same target with time left -> resume",
                   bot.should_resume("山鸡精", job, now + 60, now), True)
fails += not check("window already lapsed -> don't",
                   bot.should_resume("山鸡精", job, now - 1, now), False)
fails += not check("a different target -> don't",
                   bot.should_resume("马鹿精", job, now + 60, now), False)
fails += not check("nothing remembered (restarted bot) -> don't",
                   bot.should_resume("山鸡精", None, now + 60, now), False)

print("\nH. the id must be the RIGHT npc's, not merely a suffix match")
# 小小 山鸡精(Shanji jing) and a hypothetical 大山鸡精 both end with 山鸡精.
# Killing whichever the regex reaches first is worse than not attacking.
TWO = "  大山鸡精(Dashanji jing)\n  小小  山鸡精(Shanji jing)"
fails += not check("exact name wins over a suffix match",
                   bot.monster_id(TWO, "山鸡精"), "shanji jing")
fails += not check("suffix still works when it's the only candidate",
                   bot.monster_id("  大山鸡精(Dashanji jing)", "山鸡精"),
                   "dashanji jing")

print("\nI. a character that cannot heal stops the bot, it doesn't take more work")
# rest_until_healed returning False means 饮水 is 0 and 气血 will never come
# back -- the state the live log reached ("气血卡在 0/0 不动了"). Before the
# hunt was extracted, `if not rested: return` returned from run() and STOPPED
# the bot. A plain bool return silently downgraded that to "didn't kill it",
# so run() would walk home, eat and take another job it cannot survive.
real_rest, real_fight = bot.rest_until_healed, bot.fight_target
try:
    bot.fight_target = lambda api, mid, name: "hurt"
    bot.rest_until_healed = lambda *a, **k: (False, None)
    sim = MudSim("d/city/tianjiantai")
    sim.pending = ["山鸡精"]          # spotted, so the fight path is taken
    j = bot.Job("山鸡精", "shanji jing", "长安城", ["d/city"],
                bot.area_paths(ROOMS, ["d/city"], "长安城"), None)
    try:
        bot.hunt(sim, ROOMS, j, time.time() + 30, set())
        got = "returned normally"
    except bot.Exhausted:
        got = "Exhausted"
    fails += not check("unhealable aborts the whole job", got, "Exhausted")
finally:
    bot.rest_until_healed, bot.fight_target = real_rest, real_fight

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILURE(S)"))
sys.exit(1 if fails else 0)
