#!/usr/bin/env python3
"""mudmap -- shared room-graph navigation for bots.

Loads rooms.json (built by build_map.py) and provides the pieces every
walking bot needs: read a room from the mud's output, work out where you
are, and path to somewhere else.

Extracted so a second bot doesn't have to re-derive the parsing quirks
that live testing turned up:
  - the room title arrives glued to the prompt ("> 天监台 - /d/city/...")
  - single-exit rooms say 这里唯一的出口是, not 这里明显的出口是
  - `look` output can be a strict subset of the declared exits, because
    rooms hide exits behind valid_leave/doors/sect checks
  - a blocked move prints no room title at all, which is how you detect
    that you didn't actually go anywhere
"""
from __future__ import annotations

import json
import re
import time
from collections import deque
from pathlib import Path

MAP_FILE = Path(__file__).with_name("rooms.json")

EXITS_RE = r"这里[^出\n]{0,6}出口是\s*(.+?)。"


def load():
    return json.loads(MAP_FILE.read_text(encoding="utf-8"))


def parse_exits(text):
    m = re.search(EXITS_RE, text)
    if not m:
        return set()
    body = re.sub(r"[、和，,]", " ", m.group(1))
    return {w for w in body.split() if re.fullmatch(r"[a-z]+", w)}


def read_room(api, timeout=4):
    """Collect one room description -> (title, exits, full_text).

    Returns the full text too: this drains the queue, so anything the
    caller cares about (an NPC in the room, a skill-up message) has to be
    scanned from what's returned here.
    """
    lines, deadline = [], time.time() + timeout
    while time.time() < deadline:
        m = api.wait_line(r".+", timeout=1.0)
        if not m:
            if lines:
                break
            continue
        lines.append(m.string)
        if "出口是" in m.string:
            # Room CONTENTS are printed after the exits line, so stopping
            # here loses exactly what we care about (the target monster,
            # or an intruder we're waiting out). Keep reading briefly.
            grace = time.time() + 1.2
            while time.time() < grace:
                extra = api.wait_line(r".+", timeout=0.4)
                if not extra:
                    break
                lines.append(extra.string)
            break
    text = "\n".join(lines)
    title = ""
    for line in lines:
        if " - " in line:
            title = line.split(" - ")[0].lstrip("> ").strip()
            break
    return title, parse_exits(text), text


def look(api, timeout=6):
    api.drain()
    api.send("look", quiet=True)
    return read_room(api, timeout)


def step(api, direction):
    """Move one room. Returns (title, text); title is '' if we didn't
    move (blocked exit, door, sect check, encumbrance).

    Closed doors are opened and the move retried: std/room.lpc:199-216
    refuses with 你必须先把<门名>打开！, and cmds/std/open.lpc:18 accepts
    the direction itself as the target. Without this the walker marks
    the exit permanently impassable and routes the long way round -- or
    gives up, since the only ways into 方寸山 (d/lingtai/gate.lpc) and
    普陀山 (d/nanhai/gate.lpc) are behind closed 石门.
    """
    api.drain()
    api.send(direction, quiet=True)
    title, _, text = read_room(api)

    if not title and "必须先把" in text and "打开" in text:
        api.log(f"{direction} 有扇门关着，先开门。")
        api.drain()
        api.send(f"open {direction}", quiet=True)
        api.wait_line(r"打开|你要打开什么", timeout=4)
        api.drain()
        api.send(direction, quiet=True)
        title, _, text = read_room(api)

    return title, text


# --- maze escape ----------------------------------------------------------
# 紫竹林 (d/nanhai/zhulin*.lpc) can't be pathed with the static map: every
# looping exit is `"zhulin" + sprintf("%d", random(6))`, evaluated at
# create() time, so build_map records a nonexistent "d/nanhai/zhulin".
# The structure is knowable though:
#   zhulin0  south -> road4     (the way out)
#   zhulin15 north -> pool
#   zhulin16/17 enter -> 罗汉堂
#   zhulin1-14  loop back inside, always to zhulin0-5
# Since every random exit lands in zhulin0-5, and zhulin0 is one of them,
# wandering reaches the exit room in a handful of moves. So: try the known
# ways out, otherwise shuffle and try again.
MAZE_EXITS = ("south", "north", "enter")
STEP_PAUSE = 0.4


def escape_maze(api, maze_name="紫竹林", max_moves=80):
    """Get out of a randomised maze by probing rather than pathing.

    Returns the room title we ended up in, or "" if we never got out.
    """
    api.log(f"发现自己在{maze_name}里，开始找出口。")
    for move in range(max_moves):
        if api.stopped():
            return ""
        title, exits, _ = look(api)
        if title and title != maze_name:
            api.log(f"已走出{maze_name}，现在在「{title}」。")
            return title

        # Known ways out first.
        tried = False
        for d in MAZE_EXITS:
            if d not in exits:
                continue
            tried = True
            got, _ = step(api, d)
            api.sleep(STEP_PAUSE)
            if got and got != maze_name:
                api.log(f"从 {d} 走出{maze_name}，现在在「{got}」。")
                return got
            if got:
                break        # moved, still inside -- re-read and retry

        # No known exit here: shuffle deeper. Every looping exit lands in
        # zhulin0-5, and zhulin0 is the one with the way out.
        if not tried:
            for d in exits:
                got, _ = step(api, d)
                api.sleep(STEP_PAUSE)
                if got:
                    break

    api.log(f"走了 {max_moves} 步还没出{maze_name}，放弃，请手动走出来。")
    return ""


def candidates(rooms, title, exits, dirs=None):
    """Rooms matching what we can see. Never guesses without a title."""
    if not title:
        return []
    exact, loose = [], []
    for path, r in rooms.items():
        if dirs is not None and r["area"] not in dirs:
            continue
        if r["short"] != title:
            continue
        declared = set(r["exits"])
        if exits and not exits <= declared:
            continue
        (exact if exits == declared else loose).append(path)
    return exact + loose


def route(rooms, start, goals, blocked=frozenset(), avoid=frozenset()):
    """Shortest path start -> nearest goal as [(direction, room), ...]."""
    if start in goals:
        return []
    seen, q = {start}, deque([(start, [])])
    while q:
        cur, path = q.popleft()
        for d, nxt in rooms.get(cur, {}).get("exits", {}).items():
            if (cur, d) in blocked or nxt in seen or nxt not in rooms:
                continue
            if rooms[nxt].get("short") in avoid:
                continue
            seen.add(nxt)
            leg = path + [(d, nxt)]
            if nxt in goals:
                return leg
            q.append((nxt, leg))
    return None


def locate(api, rooms, retries=3):
    """Work out the current room, retrying if output arrives late."""
    for _ in range(retries):
        title, exits, _ = look(api)
        hits = candidates(rooms, title, exits)
        if hits:
            return hits[0]
        api.sleep(1)
    return None


def walk(api, rooms, pos, leg, blocked, on_text=None):
    """Walk a route, verifying each arrival. Returns the new position, or
    None if we lost track (caller should re-localise).

    on_text(text) is called with each room's output so the caller can
    react to what it sees along the way without a second read.
    """
    for d, dest in leg:
        if api.stopped():
            return pos
        arrived, text = step(api, d)
        api.sleep(0.4)
        if on_text:
            on_text(text)
        if arrived == rooms[dest]["short"]:
            pos = dest
        elif not arrived:
            blocked.add((pos, d))       # gated exit; route around it
            return None
        else:
            return None                 # somewhere unexpected
    return pos


def rooms_with_flag(rooms, flag):
    return {p for p, r in rooms.items() if r.get("flags", {}).get(flag)}


def studyable(rooms):
    """Rooms where `study` is allowed -- study.lpc:15-17 refuses in any
    no_fight or no_magic room."""
    return {p for p, r in rooms.items()
            if not r.get("flags", {}).get("no_fight")
            and not r.get("flags", {}).get("no_magic")}
