"""Tests for following the quest target instead of chasing it by text.

The bug this replaces: a monster that moves TWICE inside one round trip.
The bot read 「白兔怪往东落荒而逃了」, sent east, and arrived where the
monster no longer was -- then tried to kill something that wasn't there.

`follow <id>` moves us with it, on the mud's side, with no window to race:
npc.lpc:151 wanders via command("go " + dir) and go.lpc do_flee flees via
main(me, dir, 0), and both call all_inventory(env)->follow_me(me, arg)
(team.lpc:29). No direction parsing, so 北边's northup/northdown ambiguity
stops mattering.

The danger is that following moves us WITHOUT ASKING, past every guard the
bot has. Layer 1 is the answer: a monster can only move to a neighbour, so
staying in follow state is safe exactly while no exit of the CURRENT room
leads somewhere avoided. That is a pure map property -- no server, no
timing -- and it is what these tests pin.

Run with: python3 test_follow.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mudsim import MudSim, ROOMS, bot

DANGER = json.loads((Path(__file__).resolve().parent.parent / "danger.json")
                    .read_text(encoding="utf-8"))


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    return ok


fails = 0
bot.DANGER.clear()
bot.DANGER.update(DANGER)
bot._MY_EXP[0] = 767          # the test character's 武学

print("A. follow is armed only while every neighbour is safe")
# 高老庄 is the one quest area with danger-adjacent rooms. d/gao/lu1 has an
# exit into d/gao/room (60,000 exp resident) -- following from there could
# be dragged straight in.
risky = [k for k, v in ROOMS.items() if v["area"] == "d/gao"
         and any(bot.avoided(ROOMS, t) for t in v["exits"].values())]
fails += not check("高老庄 has rooms we must not follow from", bool(risky), True)
for r in risky:
    fails += not check(f"  disarmed at {ROOMS[r]['short']}",
                       bot.follow_safe(ROOMS, r), False)

print("\nB. ...and armed everywhere that is genuinely safe")
safe = "d/city/tianjiantai"
fails += not check("天监台 is safe to follow from", bot.follow_safe(ROOMS, safe), True)

print("\nC. the trapdoor counts as dangerous, mazes and peace rooms do not")
# Being pulled onto 石栈道 costs a cage escape (CAGE_BREAKS/CAGE_MIN_KEE).
trapdoor_neighbours = [k for k, v in ROOMS.items()
                       if any(ROOMS.get(t, {}).get("short") in bot.TRAP_ROOMS
                              for t in v["exits"].values())]
fails += not check("some room borders 石栈道", bool(trapdoor_neighbours), True)
fails += not check("  and follow is disarmed there",
                   bot.follow_safe(ROOMS, trapdoor_neighbours[0]), False)

print("\nD. fail closed: an unknown position is never safe to follow from")
fails += not check("unknown room", bot.follow_safe(ROOMS, None), False)
fails += not check("room not in the map", bot.follow_safe(ROOMS, "d/nowhere"), False)

print("\nG. arming and disarming, and no redundant commands")
RISKY = risky[0]           # a 高老庄 room bordering a lethal one
SAFE = "d/city/tianjiantai"
OK = {"follow shanji jing": ["你决定开始跟随山鸡精一起行动。"]}

sim = MudSim(SAFE); sim.on_send = OK
bot.FOLLOW["on"] = False
bot.follow_state(sim, ROOMS, SAFE, "shanji jing")
fails += not check("arms where safe", (bot.FOLLOW["on"], sim.sent_follow()),
                   (True, ["follow shanji jing"]))

sim = MudSim(SAFE); sim.on_send = OK
bot.FOLLOW["on"] = True
bot.follow_state(sim, ROOMS, SAFE, "shanji jing")
fails += not check("already following -> says nothing",
                   (bot.FOLLOW["on"], sim.sent_follow()), (True, []))

sim = MudSim(RISKY)
bot.FOLLOW["on"] = True
bot.follow_state(sim, ROOMS, RISKY, "shanji jing")
fails += not check("disarms before it can drag us",
                   (bot.FOLLOW["on"], sim.sent_follow()), (False, ["follow none"]))

sim = MudSim(RISKY)
bot.FOLLOW["on"] = False
bot.follow_state(sim, ROOMS, RISKY, "shanji jing")
fails += not check("never arms somewhere unsafe",
                   (bot.FOLLOW["on"], sim.sent_follow()), (False, []))

print("\nH. the sequence: sighted -> armed -> dragged -> disarmed")
sim = MudSim(SAFE); sim.on_send = OK
bot.FOLLOW["on"] = False
bot.follow_state(sim, ROOMS, SAFE, "shanji jing")
fails += not check("armed on sighting", bot.FOLLOW["on"], True)
bot.follow_state(sim, ROOMS, RISKY, "shanji jing")
fails += not check("dropped on arriving next to danger", bot.FOLLOW["on"], False)
fails += not check("and said both things in order", sim.sent_follow(),
                   ["follow shanji jing", "follow none"])

print("\nJ. `follow` is only believed when the mud accepts it")
# follow.lpc:22 refuses with 这里没有 X。 if the target is not present -- it
# bolted between our sighting and our command. Setting the flag on the SEND
# rather than the ANSWER made the bot believe it was following, log 我跟着它,
# and skip widening the search for a monster it had already lost.
sim = MudSim(SAFE)
sim.on_send = {"follow shanji jing": ["这里没有 shanji jing。"]}
bot.FOLLOW["on"] = False
bot.follow_state(sim, ROOMS, SAFE, "shanji jing")
fails += not check("refused -> not following", bot.FOLLOW["on"], False)

sim = MudSim(SAFE); sim.on_send = OK
bot.FOLLOW["on"] = False
bot.follow_state(sim, ROOMS, SAFE, "shanji jing")
fails += not check("accepted -> following", bot.FOLLOW["on"], True)

print("\nK. no exit from hunt() leaves the character following")
# The wimpy branch rests while still following (the target drags us out of
# the rest), and its `raise Exhausted` skipped the cleanup at the end of
# hunt(). A leaked leader puppets the bot through the walk home and the
# next job.
real_rest, real_fight = bot.rest_until_healed, bot.fight_target
try:
    bot.fight_target = lambda api, mid, name: "hurt"
    bot.rest_until_healed = lambda *a, **k: (False, None)
    sim = MudSim("d/city/tianjiantai")
    sim.on_send = OK
    bot.FOLLOW["on"] = True      # pretend a previous sighting armed it
    sim.pending = ["山鸡精"]
    j = bot.Job("山鸡精", "shanji jing", "长安城", ["d/city"],
                bot.area_paths(ROOMS, ["d/city"], "长安城"), None)
    try:
        bot.hunt(sim, ROOMS, j, time.time() + 30, set())
    except bot.Exhausted:
        pass
    fails += not check("Exhausted leaves nobody followed", bot.FOLLOW["on"], False)
finally:
    bot.rest_until_healed, bot.fight_target = real_rest, real_fight

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILURE(S)"))
sys.exit(1 if fails else 0)
