#!/usr/bin/env python3
"""Regression test for gmedit / set sanity guards.

    python3 test_gmedit_guards.py          # needs the mud running on 40012

Guards exist because GM edits had silently produced impossible states:
maximum_force=6 alongside max_force=2500, junk dbase keys from mistyped
skill names (moonshengton), and env vars from `set force 300`.

Every test uses a unique throwaway key or restores what it touched, so
runs don't pollute each other -- an earlier version of this test failed
spuriously because a previous run had already created the key it was
checking was rejected.
"""
import socket
import sys
import time

HOST, PORT = "127.0.0.1", 40012
WIZ, PASS = "fluffos", "Mud@2026"


class Session:
    def __init__(self):
        self.s = socket.create_connection((HOST, PORT), timeout=10)
        self._recv(2)
        self.send("gb"); self._recv(2)
        self.send("no"); self._recv(2)
        self.send(WIZ); self._recv(2)
        self.send(PASS)
        # A previous run that closed its socket without `quit` leaves the
        # character "online"; login then asks to displace it.
        if "取而代之" in self._recv(2.5):
            self.send("y"); self._recv(2.5)

    def _recv(self, t=2.0):
        self.s.settimeout(t)
        buf = b""
        try:
            while True:
                c = self.s.recv(4096)
                if not c:
                    break
                buf += c
        except socket.timeout:
            pass
        return buf.decode("utf-8", "replace")

    def send(self, line):
        self.s.sendall(line.encode() + b"\n")
        time.sleep(0.35)

    def run(self, cmd, t=2.0):
        self.send(cmd)
        return self._recv(t).strip()

    def close(self):
        self.send("quit"); self._recv(1); self.s.close()


def main():
    s = Session()
    s.run("update /cmds/wiz/gmedit")
    s.run("update /cmds/usr/set")

    results = []

    def check(label, cmd, expect):
        out = s.run(cmd)
        ok = expect in out
        results.append((ok, label, out.splitlines()[0] if out else ""))

    # Make sure the throwaway keys really are absent first, so a previous
    # run can't make a "should be rejected" case pass trivially.
    for k in ("moonshengton", "neverusedkey123"):
        s.run(f"gmedit {WIZ} {k} DELETE")

    # --- guards that must block ---------------------------------------
    check("typo'd skill name rejected",
          f"gmedit {WIZ} moonshengton 300", "没有")
    check("unknown key rejected",
          f"gmedit {WIZ} neverusedkey123 1", "没有")
    check("chinese label rejected",
          f"gmedit {WIZ} 潜能 50", "没有")
    check("max_force above skill cap",
          f"gmedit {WIZ} max_force 99999", "最高只能是")
    check("max_mana above skill cap",
          f"gmedit {WIZ} max_mana 99999", "最高只能是")
    check("maximum_force below max_force",
          f"gmedit {WIZ} maximum_force 1", "不能低于")
    check("negative stat rejected",
          f"gmedit {WIZ} max_kee -5", "不能设成负数")
    check("pool above its max rejected",
          f"gmedit {WIZ} kee 999999", "不能超过")
    check("room-only prop rejected",
          f"gmedit {WIZ} sleep_room 1", "房间属性")

    # --- things that must STILL work ----------------------------------
    # no_magic is deliberately allowed: updated.lpc:38 sets it on every
    # character at login ("player body is a safe room").
    check("no_magic still settable (intentional)",
          f"gmedit {WIZ} no_magic 1", "已设定")
    check("existing prop still settable",
          f"gmedit {WIZ} food 250", "已设定")
    check("skill still settable",
          f"gmedit {WIZ} lotusforce 300", "已设定")
    check("absent prop reads as absent, not 0",
          f"gmedit {WIZ} neverusedkey123", "不存在")
    check("-f overrides the guard",
          f"gmedit -f {WIZ} neverusedkey123 1", "已设定")

    # --- set() env guard ----------------------------------------------
    check("junk env var rejected", "set zzzjunkvar 1", "可能是打错")
    check("whitelisted env var still ok", "set wimpy 30", "设定环境变数")

    # cleanup
    s.run(f"gmedit {WIZ} neverusedkey123 DELETE")
    s.close()

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, label, first in results:
        print(("PASS  " if ok else "FAIL  ") + label)
        if not ok:
            print("        got:", first)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
