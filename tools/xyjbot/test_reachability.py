"""Tests for the mieyao walker's pre-flight reachability check.

The bot used to accept any job 袁天罡 handed out and only discover on
site that the room was unreachable -- at 湖边 (d/moon/lotuspond, behind
`climb tree` at 玉女峰顶) it spent the full 30 minutes looping
"从这里走不到未搜索的房间，重新定位" in 崎岖小路. These cover the check
that now runs from 天监台 before the bot sets off.

Run with: python3 test_reachability.py
"""
import importlib.util, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("bot", HERE / "bots/changan-mieyao-bot.py")
bot = importlib.util.module_from_spec(spec); spec.loader.exec_module(bot)
ROOMS = json.loads((HERE / "rooms.json").read_text(encoding="utf-8"))["rooms"]

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def named(short):
    return {p for p, r in ROOMS.items() if r["short"] == short}


def area(d):
    return {p for p, r in ROOMS.items()
            if r["area"] == d and not r["flags"].get("no_mieyao")}


walk = bot.reachable_from(ROOMS, bot.YUAN_ROOM)

print("gated rooms are excluded, ordinary ones are not")
# 湖边 and the rest of the inner 月宫 hang off the 桂树 (d/moon/ontop2.lpc
# :53-79); 吴刚 refuses anyone outside 月宫, so the job is a write-off.
check("湖边 unreachable", bool(named("湖边") & walk), False)
check("听雨楼 unreachable", bool(named("听雨楼") & walk), False)
# 玉女峰 and 崎岖小路 are on the way there, before the tree -- fine.
check("玉女峰 reachable", named("玉女峰") <= walk, True)
check("崎岖小路 reachable", named("崎岖小路") <= walk, True)
check("天监台 itself", bot.YUAN_ROOM in walk, True)

print("\nspawn areas: gated ones are written off, the rest are not")
# 龙宫 needs a 避水咒 to dive into and 红楼一梦 a 黄粱枕 to sleep into, so
# both are hopeless for a plain character. 普陀山 only costs 20 气血 to
# swim to, which is not a gate -- writing it off would be a regression.
check("d/sea has nothing walkable", bool(area("d/sea") & walk), False)
check("d/ourhome/honglou likewise", bool(area("d/ourhome/honglou") & walk), False)
check("d/nanhai stays searchable", bool(area("d/nanhai") & walk), True)
for d in ("d/city", "d/eastway", "d/westway", "d/kaifeng",
          "d/lingtai", "d/moon", "d/gao"):
    check(f"{d} stays searchable", bool(area(d) & walk), True)

print("\nthe reason given names the gate that blocks the route")
check("湖边 gate", bot.route_gates(ROOMS, bot.YUAN_ROOM, named("湖边"))[0].split("（")[0],
      "climb tree")
check("龙宫 gate", bot.route_gates(ROOMS, bot.YUAN_ROOM, area("d/sea"))[0].split("（")[0],
      "dive")
check("an ordinary target reports no gates",
      bot.route_gates(ROOMS, bot.YUAN_ROOM, named("玉女峰")), [])
check("an off-map target reports no route",
      bot.route_gates(ROOMS, bot.YUAN_ROOM, {"d/nowhere/nothing"}), None)

print("\nUSABLE_GATES re-opens an area once you can pass its gate")
try:
    bot.USABLE_GATES = {"dive"}
    with_dive = bot.reachable_from(ROOMS, bot.YUAN_ROOM)
    check("d/sea searchable with 避水咒", bool(area("d/sea") & with_dive), True)
    check("湖边 still not (different gate)", bool(named("湖边") & with_dive), False)
    check("dive no longer reported as a blocker",
          bot.route_gates(ROOMS, bot.YUAN_ROOM, area("d/sea")), [])
finally:
    bot.USABLE_GATES = set()

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
