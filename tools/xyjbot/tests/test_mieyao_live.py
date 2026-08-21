#!/usr/bin/env python3
"""Live end-to-end test of mieyao-bot with the standard test loadout.

    python3 -u test_mieyao_live.py [seconds]

Equipment does not survive logout (std/equip.lpc query_autoload()==0),
so gearing up and running the bot have to happen in ONE session. This
connects `test` through botproxy (so /run works), has the wizard hand
over the gear, mounts a horse, returns to 袁天罡, then starts the bot and
streams whatever it does.
"""
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sys
sys.path.insert(
    0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from ansi import strip_ansi
from setup_test_char import MAP, GEAR, MACHANG, TIANJIAN, route, locate, title_of

PROXY = ("127.0.0.1", 40099)
MUD = ("127.0.0.1", 40012)
WATCH_SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 240


def connect(addr, user, pw):
    s = socket.create_connection(addr, timeout=10)

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
    if "取而代之" in out:
        send("y")
        out = recv(2.5)
    return s, recv, send, out


def main():
    ts, trecv, tsend, tout = connect(PROXY, "test", "test1")
    print(f"[setup] test connected via botproxy at {title_of(tout)!r}")

    ws, wrecv, wsend, _ = connect(MUD, "fluffos", "Mud@2026")
    wrecv(1.5)
    wsend("summon test"); wrecv(2)
    trecv(1.5)
    for path, item_id, _ in GEAR:
        wsend(f"clone {path}"); wrecv(1.2)
        wsend(f"give {item_id} to test"); wrecv(1.2)
    wsend("quit"); wrecv(1); ws.close()

    trecv(1.5)
    for _, item_id, verb in GEAR:
        if not verb:
            continue
        tsend(f"{verb} {item_id}"); trecv(1.2)
    print("[setup] geared up")

    tsend("look")
    pos = locate(title_of(trecv(2.5)))
    if pos:
        p = route(pos, MACHANG)
        for d, _ in (p or []):
            tsend(d); trecv(1.0)
        tsend("mount ma")
        print("[setup] mount:", trecv(2).strip().splitlines()[0])
        for d, _ in (route(MACHANG, TIANJIAN) or []):
            tsend(d); trecv(1.0)

    tsend("look")
    print(f"[setup] at {title_of(trecv(2.5))!r} -- starting bot\n")
    print("=" * 60)

    tsend("/run changan-mieyao")
    end = time.time() + WATCH_SECS
    while time.time() < end:
        chunk = trecv(5)
        if chunk.strip():
            for line in chunk.splitlines():
                if line.strip():
                    print(line)
    print("=" * 60)
    tsend("/stop changan-mieyao"); trecv(2)
    tsend("quit"); trecv(1); ts.close()


if __name__ == "__main__":
    main()
