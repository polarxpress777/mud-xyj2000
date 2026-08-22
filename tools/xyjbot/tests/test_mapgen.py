"""Regression tests for exits the map generator silently drops.

The live failure: the bot stood in 嘉峪关 and logged
「8 次认不出位置，走不到天监台」, then asked to be walked home by hand.

嘉峪关 IS in the map. The problem is its exits. The game shows
west、east、southup; rooms.json declared only east and southup, because
jiayu.lpc:25-29 builds the west target from a VARIABLE:

    dir = "/d/qujing/";
    set("exits", ([
      "east": __DIR__ "shizhan",
      "west": dir + "baoxiang/yelu8",     <- EXIT_ENTRY_RE cannot see this
      "southup": __DIR__ "fenghuo",
    ]));

candidates() (mudmap.py:177) refuses a room whose declared exits don't
contain everything it can see, so the real 嘉峪关 never matched itself and
localisation was impossible from that room. The reverse edge existed
(野路 east -> 嘉峪关 is a literal), which is why the gap was invisible from
the other side.

Run with: python3 test_mapgen.py
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bm", HERE / "build_map.py")
bm = importlib.util.module_from_spec(spec); spec.loader.exec_module(bm)
ROOMS = json.loads((HERE / "rooms.json").read_text(encoding="utf-8"))["rooms"]


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    return ok


fails = 0

print("A. an exit built from a file-level constant is parsed")
SRC = '''
inherit ROOM;
void create() {
  string dir;
  dir = "/d/qujing/";
  set("short", "嘉峪关");
  set("exits", ([
    "east": __DIR__ "shizhan",
    "west": dir + "baoxiang/yelu8",
    "southup": __DIR__ "fenghuo",
  ]));
}
'''
got = bm.parse_exits(SRC, "d/westway/jiayu")
fails += not check("all three exits", sorted(got), ["east", "southup", "west"])
fails += not check("west resolves", got.get("west"), "d/qujing/baoxiang/yelu8")
fails += not check("__DIR__ still works", got.get("east"), "d/westway/shizhan")

print("\nB. the shipped map has the edges the bot needs")
# Both real, both statically resolvable, both previously missing.
fails += not check("嘉峪关 west",
                   ROOMS.get("d/westway/jiayu", {}).get("exits", {}).get("west"),
                   "d/qujing/baoxiang/yelu8")
fails += not check("女儿国 southeast",
                   ROOMS.get("d/qujing/nuerguo/start", {}).get("exits", {}).get("southeast"),
                   "d/qujing/jindou/shanlu6")

print("\nC. 嘉峪关 can localise itself from what a player sees")
# The user-visible bug: seen exits must be a subset of declared ones.
seen = {"west", "east", "southup"}
declared = set(ROOMS.get("d/westway/jiayu", {}).get("exits", {}))
fails += not check("seen exits are all declared", seen - declared, set())

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILURE(S)"))
sys.exit(1 if fails else 0)
