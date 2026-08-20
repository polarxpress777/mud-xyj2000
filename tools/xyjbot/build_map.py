#!/usr/bin/env python3
"""build_map.py -- extract a room graph from the mudlib for auto-walking.

    python3 build_map.py            # writes rooms.json

Parses every room .lpc under the 灭妖 spawn areas, pulling:
  - the room's `short` name (what you see when you walk in)
  - its `exits` mapping (direction -> target file)

and the area labels from adm/daemons/find.map, so a bot told
"在长安城" can look up which directory to search.

Room identity is the file path; the `short` name is how a bot recognises
where it currently is from the mud's output. Short names are NOT unique
(dozens of rooms are called 小路), which is why the walker verifies its
position by expected-exit-set as well -- see mieyao-bot.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MUDLIB = Path("/Users/polar/Dev/Local Projects/claude code project/"
              "mud-xyj2000/libs/xyj2000f/work")
OUT = Path(__file__).with_name("rooms.json")

# d/dntg/yunlou/npc/yaoguai.lpc dirs1 -- where 灭妖 monsters spawn.
SPAWN_DIRS = [
    "d/city", "d/westway", "d/kaifeng", "d/lingtai", "d/moon",
    "d/gao", "d/sea", "d/nanhai", "d/eastway", "d/ourhome/honglou",
]

# Scan the whole of d/, not just the spawn areas: the connecting rooms
# often live elsewhere. 龙宫 (d/sea) is only reachable by diving from
# 东海之滨, which is in d/changan -- with only the spawn dirs mapped there
# was no path at all, and the walker just reported 走不到.
SCAN_ROOT = "d"

# Transitions the room files don't declare as exits: a command typed in
# one room that relocates you somewhere else. The walker sends the key
# verbatim like any direction, so these slot straight into the graph.
# `note` records the prerequisite so a failure is explicable rather than
# mysterious -- a blocked one just gets marked impassable at runtime.
SPECIAL_EXITS = {
    # d/changan/eastseashore.lpc:119-144 do_dive() -- needs a 避水咒
    # (bishui zhou, unit 张) or 龙宫/东海龙宫 membership.
    "d/changan/eastseashore": {
        "dive": ("d/sea/under1", "需要避水咒或龙宫弟子身份"),
    },
    # d/changan/southseashore.lpc:29-45 do_swim() -- no prerequisite,
    # just costs 20 kee and 20 sen.
    "d/changan/southseashore": {
        "swim": ("d/nanhai/island", "消耗 20 气血、20 精神"),
    },
    # cmds/std/sleep.lpc:186-192 -- sleeping while carrying a 黄粱枕
    # (from 卢生) drops you into the dream realm. Any sleep_room works;
    # 南城客栈客房 is the closest one to 长安, but reaching it needs
    # rent_paid (give >=300 to 店小二, d/city/npc/xiaoer.lpc:139-145).
    "d/city/sleep": {
        "sleep": ("d/ourhome/honglou/kat", "需带黄粱枕，且已付店钱"),
    },
    # d/ourhome/honglou/npc/fairygirl.lpc:40-47 send_back() -- the way
    # out of the dream. Returns you to dream_place, or 泾水亭 if unset.
    "d/ourhome/honglou/fairyplace": {
        "ask girl about 回去": ("d/changan/pinqiting",
                                "警幻仙姑送你出梦境（回到入梦处）"),
    },
}

SHORT_RE = re.compile(r'set\(\s*"short"\s*,\s*"([^"]+)"')

# Rooms don't all `inherit ROOM`: globals.h defines several macros that
# resolve under /std/room -- BANK ("/std/room/bank"), HOCKSHOP, and
# CLASS_GUILD. Matching only "inherit ROOM" silently dropped 11 rooms,
# among them d/city/bank (相记钱庄), which left the walker unable to
# route to the bank even though d/city/baihu-w1 exits south into it.
ROOM_INHERIT_RE = re.compile(r"\binherit\s+(?:ROOM|BANK|HOCKSHOP|CLASS_GUILD)\s*;")
EXITS_RE = re.compile(r'set\(\s*"exits"\s*,\s*\(\[(.*?)\]\)\s*\)', re.S)
EXIT_ENTRY_RE = re.compile(r'"(\w+)"\s*:\s*(__DIR__\s*)?"([^"]+)"')
# Commented-out exits are common (kezhan.lpc has //"north" : "bobing")
# and would otherwise land in the map as real exits the game won't honour.
FLAG_RE = re.compile(r'set\(\s*"(sleep_room|no_fight|no_magic|no_mieyao)"\s*,\s*(\d+)')
LINE_COMMENT_RE = re.compile(r"//[^\n]*")
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def strip_comments(text: str) -> str:
    return LINE_COMMENT_RE.sub("", BLOCK_COMMENT_RE.sub("", text))


def load_area_names():
    """find.map: '<dir> <chinese name>' per line.

    Returns name -> [dirs]. Names are NOT unique -- both d/city and
    d/eastway are 长安城 -- so a bot told "在长安城" has to search every
    directory carrying that label, not just the first one.
    """
    out = {}
    f = MUDLIB / "adm/daemons/find.map"
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            d, name = parts[0].strip(), parts[1].replace(" ", "").strip()
            # LPC's strlen() counts BYTES; Python's len() counts characters.
            # Copying `strlen(name) > 2` literally drops two-character
            # names like 月宫 and 龙宫, which are 6 bytes and perfectly valid.
            if len(d) > 2 and len(name.encode("utf-8")) > 2:
                out.setdefault(name, [])
                if d not in out[name]:
                    out[name].append(d)
    return out


# Mudlib top-level directories. A target starting with one of these is
# root-relative even without a leading slash -- d/changan/wroad3.lpc has
# `"west": "d/gao/lu1"`, and treating that as relative to the source
# directory produced the bogus room "d/changan/d/gao/lu1", silently
# cutting 高老庄 (and others) out of the graph entirely.
ROOT_DIRS = ("d/", "u/", "adm/", "obj/", "std/", "cmds/", "daemon/")


def resolve(target: str, src_rel: str, used_dir_macro: bool) -> str:
    """Resolve an exit target to a repo-relative room path without .lpc."""
    import posixpath

    if target.endswith(".lpc"):
        target = target[:-4]

    if used_dir_macro:
        # __DIR__ "foo" -- always relative to the source file's directory.
        joined = posixpath.join(str(Path(src_rel).parent), target)
    elif target.startswith("/"):
        joined = target.lstrip("/")
    elif target.startswith(ROOT_DIRS):
        joined = target                      # root-relative, slash omitted
    else:
        joined = posixpath.join(str(Path(src_rel).parent), target)

    # Collapse any ../ and duplicate separators.
    return posixpath.normpath(joined).lstrip("/")


def main():
    area_names = load_area_names()
    rooms = {}

    for f in (MUDLIB / SCAN_ROOT).rglob("*.lpc"):
        if True:
            txt = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
            if not ROOM_INHERIT_RE.search(txt):
                continue
            rel = str(f.relative_to(MUDLIB))[:-4]        # strip .lpc
            short = SHORT_RE.search(txt)
            exits = {}
            m = EXITS_RE.search(txt)
            if m:
                for dirn, dirmacro, target in EXIT_ENTRY_RE.findall(m.group(1)):
                    exits[dirn] = resolve(target, rel, bool(dirmacro))
            # Area = the spawn dir this room belongs to (longest match),
            # else its own directory, so find.map lookups still work.
            area = str(Path(rel).parent)
            for sd in SPAWN_DIRS:
                if rel.startswith(sd + "/"):
                    area = sd
                    break
            # Room flags the bots need: sleep_room gates `sleep`
            # (cmds/std/sleep.lpc:16), and no_fight/no_magic block both
            # study (cmds/std/study.lpc:15-17) and dazuo/meditate.
            flags = {k: int(v) for k, v in FLAG_RE.findall(txt) if int(v)}
            rooms[rel] = {
                "short": short.group(1) if short else "",
                "exits": exits,
                "area": area,
                "flags": flags,
            }

    # Splice in command-based transitions (dive etc.).
    specials = 0
    for src, moves in SPECIAL_EXITS.items():
        if src not in rooms:
            print(f"  ! special exit source missing from map: {src}")
            continue
        for cmd, (dest, note) in moves.items():
            if dest not in rooms:
                print(f"  ! special exit target missing: {dest}")
                continue
            rooms[src]["exits"][cmd] = dest
            rooms[src].setdefault("special", {})[cmd] = note
            specials += 1
    print(f"spliced {specials} special exit(s)")

    data = {"areas": area_names, "rooms": rooms}
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # Report reachability per area so a bad parse is visible immediately.
    print(f"{len(rooms)} rooms across {len(SPAWN_DIRS)} spawn areas -> {OUT.name}")
    for d in SPAWN_DIRS:
        sub = {k: v for k, v in rooms.items() if v["area"] == d}
        dangling = sum(1 for v in sub.values()
                       for t in v["exits"].values() if t not in rooms)
        label = [n for n, dds in area_names.items() if d in dds]
        print(f"  {d:22} {len(sub):4} rooms  "
              f"{dangling:4} exits leaving the map  "
              f"{'/'.join(label)}")


if __name__ == "__main__":
    main()
