"""Regression tests for the bot sealing itself into a one-exit room.

The incident: the bot stood in 林中木屋 (d/lingtai/houlang5) and printed
「暂时找不到去天监台的路」eight times without taking a single step, then
gave up and asked to be walked home by hand. The map was fine -- BFS finds
a 41-step route -- and houlang5.lpc has no door and no valid_leave. The
bot had crossed off `southwest` itself, and that is the room's only way
out that isn't a dead end.

Why it crossed it off: cmds/std/valid_move.h refuses EVERY move in this
mudlib for three reasons that are about the character rather than the
exit --

    你的负荷过重，动弹不得。        over-encumbered
    你的动作还没有完成，不能移动。  mid-action
    你现在不能移动！                held (定身)

-- and go.lpc:79 adds 你的座骑走动不了 for the mount. note_step_failure()
read any non-arrival as "this exit is shut".

Run with: python3 test_stranded.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mudsim import MudSim, ROOMS, bot

bot.STEP_PAUSE = 0

CABIN = "d/lingtai/houlang5"      # 林中木屋, exits: southwest, enter
YUAN = "d/city/tianjiantai"       # 天监台

# The exact refusal lines, from the mudlib rather than from memory.
TOO_HEAVY = "你的负荷过重，动弹不得。"
STILL_BUSY = "你的动作还没有完成，不能移动。"
HELD = "你现在不能移动！"


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    return ok


fails = 0
print("A. a refusal about the CHARACTER never crosses the exit off")
for label, text in [("负荷过重", TOO_HEAVY), ("动作还没完成", STILL_BUSY),
                    ("被定住", HELD)]:
    sim, blocked = MudSim(CABIN), set()
    bot.note_step_failure(sim, blocked, CABIN, "southwest", text)
    fails += not check(f"{label} leaves the map alone", blocked, set())

print("\nB. a refusal about the EXIT still crosses it off")
sim, blocked = MudSim("d/city/kezhan"), set()
bot.note_step_failure(sim, blocked, "d/city/kezhan", "east",
                      "店小二拦住你说：客官，先付店钱吧。")
fails += not check("unpaid bill still blocks", blocked,
                   {("d/city/kezhan", "east")})

print("\nC. carrying too much is said out loud, once per job")
# Waiting doesn't fix this one -- the weight doesn't go away on its own --
# and while it lasts the bot can't move ANYWHERE, so it will burn the rest
# of the quest walking into refusals. Only the player can clear it, so the
# one thing the bot must do is say so. Silence is what let this hide.
sim, blocked = MudSim(CABIN), set()
bot.forget_job_warnings()
bot.note_step_failure(sim, blocked, CABIN, "southwest", TOO_HEAVY)
fails += not check("says it", sim.said("负荷"), True)
before = len(sim.logs)
bot.note_step_failure(sim, blocked, CABIN, "southwest", TOO_HEAVY)
fails += not check("doesn't repeat itself", len(sim.logs), before)
bot.forget_job_warnings()
bot.note_step_failure(sim, blocked, CABIN, "southwest", TOO_HEAVY)
fails += not check("but says it again next job", len(sim.logs) > before, True)

print("\nD. being busy or held is NOT worth a log line")
# These clear on their own in seconds; the walk retries and carries on.
sim, blocked = MudSim(CABIN), set()
bot.forget_job_warnings()
for text in (STILL_BUSY, HELD):
    bot.note_step_failure(sim, blocked, CABIN, "southwest", text)
fails += not check("stays quiet", sim.logs, [])

print("\nE. a move refused because we're mid-action is retried")
# valid_move.h refuses while is_busy(), which clears in a second or two --
# the break-off code already knows this (BREAK_OFF_TRIES/BREAK_OFF_WAIT).
# Walking never learned it, so a perfectly good exit read as shut.
sim = MudSim(CABIN, refusals={(CABIN, "southwest"): (STILL_BUSY, 2)})
arrived, _ = bot.step(sim, "southwest")
fails += not check("gets through anyway", arrived,
                   ROOMS["d/lingtai/houlang4"]["short"])
fails += not check("took more than one try", sim.tries[(CABIN, "southwest")] > 1,
                   True)

print("\nF. a move refused because we're held is NOT waited out")
# 定身 lasts up to a minute (freez.lpc:75 caps it at 60). Standing still retrying for a
# minute while something hits us is the worst option available -- the step
# is lost, the walk re-localises and comes straight back round.
sim = MudSim(CABIN, refusals={(CABIN, "southwest"): (HELD, None)})
arrived, _ = bot.step(sim, "southwest")
fails += not check("doesn't move", arrived, "")
fails += not check("and doesn't stand there retrying",
                   sim.tries[(CABIN, "southwest")], 1)

print("\nG. THE INCIDENT: sealed into 林中木屋, still gets home")
# southwest is already crossed off when the walk home starts -- exactly the
# state the bot was in at 18:47. The exit is fine; the map has a 41-step
# route to 天监台. Anything that ends with the bot standing in the cabin
# asking to be walked home by hand is the bug.
bot.forget_job_warnings()
sim, blocked = MudSim(CABIN), {(CABIN, "southwest")}
got = bot.walk_to(sim, ROOMS, blocked, YUAN, "天监台")
fails += not check("walks home", (got, sim.at), (True, YUAN))

print("\nH. a genuinely shut exit gets ONE second chance, then stands")
# The forgiveness must not become a loop: forgive, try, refused, forgive...
# Refused again after its second chance, the exit stays crossed off and the
# walk fails the way it does today -- bounded, not spinning.
DOOR = "木门紧闭，你推不开。"
bot.forget_job_warnings()
sim = MudSim(CABIN, refusals={(CABIN, "southwest"): (DOOR, None)})
blocked = {(CABIN, "southwest")}
got = bot.walk_to(sim, ROOMS, blocked, YUAN, "天监台")
fails += not check("gives up", got, False)
fails += not check("tried it exactly once more, then stopped",
                   sim.tries[(CABIN, "southwest")], 1)
fails += not check("and left it crossed off", (CABIN, "southwest") in blocked,
                   True)

print("\nH2. the second chance is once per JOB, not once per walk")
# A job makes a dozen walks (the horse, the bank, the inn, 天监台). A
# walk-local memory would hand a locked door a fresh chance on every one
# of them, which is a slow spin rather than a bounded failure.
bot.forget_job_warnings()
blocked = {(CABIN, "southwest")}
sim = MudSim(CABIN, refusals={(CABIN, "southwest"): (DOOR, None)})
bot.walk_to(sim, ROOMS, blocked, YUAN, "天监台")
first = sim.tries[(CABIN, "southwest")]
sim2 = MudSim(CABIN, refusals={(CABIN, "southwest"): (DOOR, None)})
bot.walk_to(sim2, ROOMS, blocked, YUAN, "天监台")
fails += not check("spent on the first walk", first, 1)
fails += not check("second walk doesn't try again",
                   sim2.tries.get((CABIN, "southwest"), 0), 0)

print("\nK. only the exits the new route NEEDS are forgiven")
# Forgiving the whole set would spend the one chance of a wrongly-marked
# exit on the far side of the map without ever retrying it.
bot.forget_job_warnings()
far = ("d/city/kezhan", "east")
blocked = {(CABIN, "southwest"), far}
sim = MudSim(CABIN)
bot.walk_to(sim, ROOMS, blocked, YUAN, "天监台")
fails += not check("the one in the way was used", (CABIN, "southwest") in bot.FORGIVEN,
                   True)
fails += not check("the far one keeps its chance", far in bot.FORGIVEN, False)
fails += not check("and stays crossed off", far in blocked, True)

print("\nI. when it can't find a route, it names what IT crossed off")
# The live log blamed the map and pointed at build_map.py's SPECIAL_EXITS.
# The map was fine. That message cost a whole session re-deriving the route
# graph by hand to find out the bot had done it to itself.
bot.forget_job_warnings()
sim = MudSim(CABIN, refusals={(CABIN, "southwest"): (DOOR, None)})
bot.walk_to(sim, ROOMS, {(CABIN, "southwest")}, YUAN, "天监台")
fails += not check("names the exit", sim.said("林中木屋 的 southwest"), True)
fails += not check("doesn't blame the map", sim.said("地图缺边"), False)

print("\nJ. with nothing crossed off, a real map gap still reads as one")
# 大松树顶 is behind 吴刚's 桂树, which the static map has no edge for, so
# there genuinely is no route -- and then the map IS the right thing to
# blame. The fix must not swallow that.
sim = MudSim(CABIN)
bot.walk_to(sim, ROOMS, set(), "d/lingtai/uptree", "大松树顶")
fails += not check("blames the map", sim.said("地图缺边"), True)

print("\nL. a real map gap still reads as one even after a broken exit")
# `blocked` is seeded from BROKEN_EXITS, which persists for the whole
# session. Gating the "blame my own marks" message on `blocked` would make
# every genuine map gap read as bookkeeping from the first compile-error
# exit onwards -- and those are exactly the sessions where you most need
# the map message to be honest.
bot.forget_job_warnings()
bot.BROKEN_EXITS.add(("d/moon/rain", "up"))
try:
    sim = MudSim(CABIN)
    bot.walk_to(sim, ROOMS, set(bot.BROKEN_EXITS), "d/lingtai/uptree", "大松树顶")
    fails += not check("still blames the map", sim.said("地图缺边"), True)
    fails += not check("doesn't blame our marks", sim.said("先怀疑这些"), False)
finally:
    bot.BROKEN_EXITS.clear()

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILURE(S)"))
sys.exit(1 if fails else 0)
