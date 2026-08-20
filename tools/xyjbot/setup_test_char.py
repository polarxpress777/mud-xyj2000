#!/usr/bin/env python3
"""setup_test_char.py -- put the `test` character into its standard
testing loadout, then leave it wherever you asked for.

    python3 setup_test_char.py            # equip, mount, go to 天监台
    python3 setup_test_char.py --stay     # equip + mount, don't travel

Equipment in this mudlib does NOT survive logout -- std/equip.lpc's
query_autoload() returns 0, so only money autoloads. That means this
setup has to be re-run at the start of every test session; it can't be
done once and left.

It needs the wizard account to hand over the gear (a fresh character
can't clone), so it opens two connections: `test` and `fluffos`.
"""
from __future__ import annotations

import json
import socket
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ansi import strip_ansi

MUD = ("127.0.0.1", 40012)
TEST = ("test", "test1")
WIZ = ("fluffos", "Mud@2026")
MAP = json.loads((Path(__file__).with_name("rooms.json")).read_text(encoding="utf-8"))

GEAR = [
    ("/d/obj/armor/niupi", "shield", "wear"),          # 牛皮盾
    ("/d/obj/weapon/stick/bintiegun", "bintiegun", "wield"),  # 镔铁棍
    # 避水咒 -- required to `dive` into 龙宫 at 东海之滨
    # (d/changan/eastseashore.lpc:127-133 checks present("bishui zhou")
    # with unit 张). Carried, not worn/wielded.
    ("/d/obj/magic/bishuizhou", "bishui zhou", None),
]
MACHANG = "d/kaifeng/machang"     # 开封马场
TIANJIAN = "d/city/tianjiantai"   # 天监台 -- 袁天罡, the 灭妖 quest giver


def connect(user, pw):
    s = socket.create_connection(MUD, timeout=10)

    def recv(t=2.0):
        s.settimeout(t)
        buf = b""
        try:
            while True:
                c = s.recv(4096)
                if not c:
                    break
                buf += c
        except socket.timeout:
            pass
        return strip_ansi(buf.decode("utf-8", "replace"))

    def send(line):
        s.sendall(line.encode() + b"\n")
        time.sleep(0.45)

    recv(2)
    send("gb"); recv(2)
    send("no"); recv(2)
    send(user); recv(2)
    send(pw)
    out = recv(2.5)
    if "取而代之" in out:          # a stale session is still connected
        send("y")
        out = recv(2.5)
    return s, recv, send, out


def title_of(text):
    for line in text.splitlines():
        if " - " in line:
            return line.split(" - ")[0].strip()
    return ""


def route(start, goal):
    rooms = MAP["rooms"]
    seen, q = {start}, deque([(start, [])])
    while q:
        cur, path = q.popleft()
        if cur == goal:
            return path
        for d, nxt in rooms.get(cur, {}).get("exits", {}).items():
            if nxt in rooms and nxt not in seen:
                seen.add(nxt)
                q.append((nxt, path + [(d, nxt)]))
    return None


def locate(title):
    """Best-effort room path for a room title."""
    hits = [p for p, r in MAP["rooms"].items() if r["short"] == title]
    return hits[0] if hits else None


def walk(send, recv, path, label):
    for i, (d, dest) in enumerate(path, 1):
        send(d)
        got = title_of(recv(1.6))
        want = MAP["rooms"][dest]["short"]
        if got and got != want:
            print(f"  ! step {i} went to {got!r}, expected {want!r}")
    print(f"  {label}: {len(path)} steps")


def main():
    stay = "--stay" in sys.argv

    ts, trecv, tsend, tout = connect(*TEST)
    here = title_of(tout)
    print(f"test logged in at {here!r}")

    ws, wrecv, wsend, _ = connect(*WIZ)
    wrecv(1.5)

    # The wizard has to be in the same room to hand items over.
    wsend("summon test"); wrecv(2)
    trecv(1.5)
    print("summoned test to the wizard")

    for path, item_id, verb in GEAR:
        wsend(f"clone {path}"); wrecv(1.5)
        wsend(f"give {item_id} to test"); wrecv(1.5)
    trecv(1.5)
    for _, item_id, verb in GEAR:
        if not verb:                  # carried only (e.g. 避水咒)
            continue
        tsend(f"{verb} {item_id}")
        print(f"  {verb} {item_id}: {trecv(1.5).strip().splitlines()[0]}")

    wsend("quit"); wrecv(1); ws.close()

    # Where are we now? (summon moved us to the wizard's room)
    tsend("look")
    here = title_of(trecv(2.5))
    pos = locate(here)
    print(f"currently at {here!r} -> {pos}")

    if pos:
        p = route(pos, MACHANG)
        if p:
            walk(tsend, trecv, p, "rode to 开封马场")
            tsend("mount ma")
            print("  mount:", trecv(2).strip().splitlines()[0])
            if not stay:
                p2 = route(MACHANG, TIANJIAN)
                if p2:
                    walk(tsend, trecv, p2, "returned to 天监台")
        else:
            print("  ! no route to 马场 from here")

    tsend("look")
    print("\nfinal room:", title_of(trecv(2.5)))
    tsend("i")
    print(trecv(2))
    print("Leaving `test` connected is not possible from a script -- "
          "log in yourself and re-run gear setup if it dropped.")
    tsend("quit"); trecv(1); ts.close()


if __name__ == "__main__":
    main()
