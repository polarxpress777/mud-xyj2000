#!/usr/bin/env python3
"""Live test of the 董记当铺 newbie-gear restock.

    python3 tests/test_dangpu_live.py

The shop (d/city/dangpu.lpc, inheriting std/room/hockshop.lpc) has no
stock of its own -- everything on `list` is what players sold. This
tests the restock that gives it a standing supply of the six starter
items, two apiece.

The seam is what a player can see: `list` and `buy` inside the shop.
The only wizard-only move is triggering a restock on demand --
`call /d/city/dangpu->reset()` -- so the test doesn't have to sit
through the driver's 883s reset clock (config.fluffos:51).

Needs the container up on 40012.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from setup_test_char import WIZ, connect  # noqa: E402

DANGPU = "/d/city/dangpu"      # 董记当铺, the one with a restock list

# The other five HOCKSHOP rooms, which declare no "restock" and so must
# behave exactly as they did before. 长安寄存店 is one too, but it is a
# left-luggage office with no shopfront, so it is not walked here.
# (room, label) -- every one of these titles contains 当铺, so arrival is
# checked on that and the label only names the shop in the output.
OTHER_SHOPS = [
    ("/d/kaifeng/dangpu", "开封当铺"),
    ("/d/changan/tmppawn", "三喜当铺"),
    ("/d/qujing/tianzhu/dangpu", "天竺当铺"),
    ("/d/dntg/hgs/pownshop", "黑风山当铺"),
]

# (list/buy argument, 中文名) -- ids from each item's set_name(). 战袍 and
# 兽皮披风 both answer to "cloth", so neither is addressed by that.
ITEMS = [
    ("tiekui", "铁盔"),
    ("zhan pao", "战袍"),
    ("tengjia", "藤甲"),
    ("pifeng", "兽皮披风"),
    ("pixue", "水牛皮靴"),
    ("kuang", "竹筐"),
]

C_NUM = "零一二三四五六七八九十"
STOCK_RE = re.compile(r"还剩([" + C_NUM + r"]+)")

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def cn_to_int(s):
    """chinese_number() inverse for the 0..19 range this test needs."""
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + C_NUM.index(s[1])
    if len(s) == 3 and s[1] == "十":
        return C_NUM.index(s[0]) * 10 + C_NUM.index(s[2])
    if len(s) == 2 and s[1] == "十":
        return C_NUM.index(s[0]) * 10
    return C_NUM.index(s)


def stock(send, recv, arg, name):
    """Pieces of `name` the shop currently offers, 0 if it offers none.

    Filtered `list` so the reply is one line -- a bare `list` goes
    through start_more() and would need paging.
    """
    send(f"list {arg}")
    for line in recv(1.5).splitlines():
        if name in line:
            m = STOCK_RE.search(line)
            if m:
                return cn_to_int(m.group(1))
    return 0


def main():
    s, recv, send, _ = connect(*WIZ)
    recv(1.0)
    send(f"goto {DANGPU}")
    out = recv(1.5)
    if "董记当铺" not in out:
        print(f"  FAIL  could not reach 董记当铺: {out.strip()[:120]!r}")
        return 1

    send(f"call {DANGPU}->reset()")
    recv(1.5)

    # 1. every starter item is on the shelf, two apiece.
    for arg, name in ITEMS:
        check(f"{name} stocked after reset", stock(send, recv, arg, name), 2)

    # 2. buying the shelf empty and letting the clock tick refills it.
    send("buy tiekui"); recv(1.2)
    send("buy tiekui"); recv(1.2)
    check("铁盔 after buying both", stock(send, recv, "tiekui", "铁盔"), 0)
    send(f"call {DANGPU}->reset()")
    recv(1.5)
    check("铁盔 after restock", stock(send, recv, "tiekui", "铁盔"), 2)

    # 3. a restock tops up, it never trims: gear a player sold in above
    #    the standing 2 stays put.
    send("sell tiekui"); recv(1.2)
    check("铁盔 after selling one in", stock(send, recv, "tiekui", "铁盔"), 3)
    send(f"call {DANGPU}->reset()")
    recv(1.5)
    check("铁盔 surplus survives restock", stock(send, recv, "tiekui", "铁盔"), 3)

    # 4. the stock lives in a 聚宝盒 that hockshop.lpc builds lazily and
    #    that holds it in set_temp, so after a reboot there is no box and
    #    no stock until someone shops. Destroying the box reproduces that
    #    state: the next plain `list` -- no reset(), no wizard help --
    #    must already show a full shelf. (This also clears the surplus
    #    from step 3, leaving the shop as we found it.)
    send("dest box"); recv(1.2)
    check("铁盔 on a fresh box, without a reset",
          stock(send, recv, "tiekui", "铁盔"), 2)
    send("dest tiekui"); recv(1.2)

    # 5. the mechanism lives in hockshop.lpc, which every pawnshop
    #    inherits -- but only 董记 declares a "restock", so the others
    #    must still stock nothing but what players sold them.
    for room, name in OTHER_SHOPS:
        send(f"goto {room}")
        out = recv(1.5)
        if "当铺" not in out:
            print(f"  FAIL  could not reach {name}: {out.strip()[:120]!r}")
            fails.append(f"reach {name}")
            continue
        check(f"{name} not restocked", stock(send, recv, "tiekui", "铁盔"), 0)

    send("quit"); recv(0.8)
    s.close()

    print()
    if fails:
        print(f"FAILED: {len(fails)} check(s): {', '.join(fails)}")
        return 1
    print(f"all {len(ITEMS) + 5 + len(OTHER_SHOPS)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
