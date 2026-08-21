"""Tests for 袁天罡 naming an AREA rather than a single room.

MISC_D->find_place() (adm/daemons/miscd.lpc) used to look up the room's
EXACT directory in find.map and, on a miss, fall back to the room's own
short name. That is how the 灭妖 assignment could come out as 近有X在
休息室出没 -- and there are four 休息室 in the game (月宫, 普陀山, 龙宫,
大雪山), fifteen directories' worth of 山路 and three of 大官道, so the
player is told nothing about where to go.

miscd.lpc now has find_area(), which normalises the path and walks UP the
directory tree to the nearest name in find.map; the two yaoguai files use
it and keep find_place() only as a fallback. This mirrors that algorithm
in Python and checks it against the real find.map and the real map, so a
find.map edit that breaks the promise fails here.

Run with: python3 test_findarea.py
"""
import json
import re
import sys
from pathlib import Path

# tools/xyjbot -- every path below is relative to it, so this
# stayed correct when the tests moved down into tests/.
HERE = Path(__file__).resolve().parent.parent
MUDLIB = HERE.parent.parent / "libs/xyj2000f/work"

# The threshold in miscd.lpc's loader. It exists to skip nameless lines
# (find.map has a few, e.g. "d/wiz "), so anything above 0 throws away
# valid data on a driver whose strlen() counts characters.
MIN_NAME_CHARS = 0
ROOMS = json.loads((HERE / "rooms.json").read_text(encoding="utf-8"))["rooms"]

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def load_maps():
    """miscd.lpc create(): '<dir> <name>' per line, spaces stripped."""
    out = {}
    for line in (MUDLIB / "adm/daemons/find.map").read_text(
            encoding="utf-8", errors="replace").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            d, name = parts[0], parts[1].replace(" ", "").replace("\r", "")
            # miscd.lpc's guard, mirrored EXACTLY. This driver's strlen()
            # counts CHARACTERS, not bytes -- verified at boot: with
            # `> 2` the daemon reported map_count() = 50 against 55
            # parsable lines, the 5 missing being every two-character
            # region name (月宫 龙宫 天宫 灵山 梅山). An earlier version of
            # this mirror counted bytes, passed, and hid the bug.
            if len(d) > 2 and len(name) > MIN_NAME_CHARS:
                out[d] = name
    return out


MAPS = load_maps()


def find_area(path):
    """miscd.lpc find_area(): walk up until a directory is named."""
    filename = path if path.startswith("/") else "/" + path
    parts = filename.strip("/").split("/")
    for cut in range(len(parts) - 1, 0, -1):
        label = MAPS.get("/".join(parts[:cut]))
        if label:
            return label
    return None


def old_find_place(path):
    """What miscd.lpc did before: exact directory, else the room name."""
    d = path.rsplit("/", 1)[0]
    return MAPS.get(d) or ROOMS.get(path, {}).get("short", "")


def spawn_dirs():
    """dirs1 + dirs2 + dirs3 straight out of the mudlib, so this test
    can't drift from the quest it is about."""
    src = (MUDLIB / "d/dntg/yunlou/npc/yaoguai.lpc").read_text(encoding="utf-8")
    out = []
    for name in ("dirs1", "dirs2", "dirs3"):
        block = re.search(rf'string \*{name} = \(\{{(.*?)\}}\);', src, re.S)
        for line in block.group(1).splitlines():
            line = line.split("//")[0]
            out += re.findall(r'"/?(d/[^"]+)"', line)
    return out


DIRS = spawn_dirs()
print(f"灭妖 spawn directories, read from yaoguai.lpc: {len(DIRS)}")

print("\nevery room a 妖怪 can spawn in resolves to an area name")
spawnable = [p for p in ROOMS if p.rsplit("/", 1)[0] in DIRS]
missing = sorted({p.rsplit("/", 1)[0] for p in spawnable if not find_area(p)})
check("rooms checked", len(spawnable) > 1000, True)
check("directories with no area name", missing, [])

print("\n袁天罡 can no longer say 休息室 -- each one names its own area")
for path, want in (("d/moon/wroom", "月宫"),
                   ("d/nanhai/restroom", "普陀山"),
                   ("d/sea/wolongrest", "龙宫"),
                   ("d/xueshan/restroom", "大雪山")):
    check(f"{path} ({ROOMS[path]['short']})", find_area(path), want)

print("\nrooms in a SUBdirectory of a named area used to fall through")
for path in ("d/moon/quest/boat", "d/city/misc/kantai",
             "d/changan/playerhomes/h_nonn"):
    if path not in ROOMS:
        continue
    old, new = old_find_place(path), find_area(path)
    check(f"{path}: was the room's own name", old, ROOMS[path]["short"])
    check(f"{path}: now an area", bool(new) and new != ROOMS[path]["short"], True)

print("\nthe leading slash is normalised either way file_name() reports it")
check("with slash", find_area("/d/moon/wroom"), "月宫")
check("without slash", find_area("d/moon/wroom"), "月宫")

print("\nand a path with nothing named on it still refuses to guess")
check("unnamed tree", find_area("d/nowhere/at/all"), None)

print("\nmiscd's own logging cannot throw during preload")
# A guard, not a behaviour spec: there is no driver here to run LPC
# against. adm/etc/preload:19 preloads /adm/daemons/miscd, so anything
# create() throws happens at boot; adm/simul_efun/file.lpc:8 is a bare
# write_file(LOG_DIR + file, text) with no assure_file(), and LOG_DIR
# exists only because docker/entrypoint.sh creates it. The mud's own
# crash handler has already tripped this exact shape:
#   *Wrong permissions for opening file /log/nosave/CRASHES for append.
# AGENTS.md 7.11: mkdir the directory AND catch() at the call site.
for lib in ("xyj2000", "xyj2000f"):
    src = (HERE.parent.parent / "libs" / lib
           / "work/adm/daemons/miscd.lpc").read_text(encoding="utf-8")
    # Strip // comments first, or the rule trips over its own explanation.
    code = "\n".join(re.sub(r"//.*", "", line) for line in src.splitlines())
    calls = code.count("log_file(")
    caught = code.count("catch(log_file(")
    check(f"{lib}: every log_file() is inside catch()", (caught, calls),
          (calls, calls))
    check(f"{lib}: and there is logging to guard", calls > 0, True)

print("\nthe mudlib really calls find_area from both yaoguai files")
for rel in ("d/dntg/yunlou/npc/yaoguai.lpc", "d/city/npc/yg/yaoguai.lpc"):
    for lib in ("xyj2000", "xyj2000f"):
        src = (HERE.parent.parent / "libs" / lib / "work" / rel).read_text(encoding="utf-8")
        check(f"{lib}/{rel}", "MISC_D->find_area(env)" in src, True)

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
