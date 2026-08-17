#!/usr/bin/env python3
"""Tests for the trigger/bot engine.

Run: python3 test_triggers.py   (exit 0 = pass)

The engine is the seam worth testing: it turns incoming game lines into
outgoing commands, with no terminal or socket involved. The curses UI on
top of it is deliberately not covered here.
"""
import sys
import tempfile
import pathlib

from triggers import Trigger, TimerBot, Engine, load_config, save_config
from ansi import strip_ansi, display_width, fit_to_width

FAILURES = []


def check(desc, got, want):
    if got == want:
        print(f"PASS: {desc}")
    else:
        print(f"FAIL: {desc}\n      got:  {got!r}\n      want: {want!r}")
        FAILURES.append(desc)


def check_true(desc, cond):
    check(desc, bool(cond), True)


# --- Chinese substring matching (the main use case) --------------------
eng = Engine()
eng.triggers.append(Trigger(
    name="continue-meditating",
    pattern="你行功完毕，吸一口气，缓缓站了起来。",
    actions=["dazuo"],
))
check("plain Chinese line fires the trigger",
      eng.process_line("你行功完毕，吸一口气，缓缓站了起来。", now=1.0),
      ["dazuo"])
check("unrelated line does not fire",
      eng.process_line("店小二笑咪咪地说道：这位小兄弟。", now=2.0),
      [])
check("Chinese substring matches inside a longer line",
      eng.process_line("＞你行功完毕，吸一口气，缓缓站了起来。＜", now=3.0),
      ["dazuo"])

# --- Regex with a Chinese capture group ---------------------------------
eng2 = Engine()
eng2.triggers.append(Trigger(
    name="flee-on-low-hp",
    pattern=r"你的气血还剩下?\s*(\d+)",
    is_regex=True,
    actions=["flee"],
))
check("regex trigger fires and is not confused by Chinese",
      eng2.process_line("你的气血还剩下 45 点。", now=1.0),
      ["flee"])

# capture groups are substitutable into the action
eng3 = Engine()
eng3.triggers.append(Trigger(
    name="echo-number",
    pattern=r"剩下\s*(\d+)\s*点",
    is_regex=True,
    actions=["say 还剩 $1"],
))
check("regex capture group substitutes into the action",
      eng3.process_line("你的气血还剩下 45 点。", now=1.0),
      ["say 还剩 45"])

# --- disabled triggers stay silent --------------------------------------
eng4 = Engine()
eng4.triggers.append(Trigger(name="off", pattern="打坐", actions=["x"],
                             enabled=False))
check("disabled trigger does not fire",
      eng4.process_line("你开始打坐。", now=1.0), [])

# --- cooldown throttles repeats -----------------------------------------
eng5 = Engine()
eng5.triggers.append(Trigger(name="cd", pattern="打坐", actions=["dazuo"],
                             cooldown=10.0))
check("first fire passes", eng5.process_line("打坐", now=100.0), ["dazuo"])
check("second fire inside cooldown is suppressed",
      eng5.process_line("打坐", now=105.0), [])
check("fire after cooldown passes again",
      eng5.process_line("打坐", now=111.0), ["dazuo"])

# --- once-only triggers --------------------------------------------------
eng6 = Engine()
eng6.triggers.append(Trigger(name="one", pattern="打坐", actions=["a"],
                             once=True))
check("once trigger fires the first time",
      eng6.process_line("打坐", now=1.0), ["a"])
check("once trigger never fires again",
      eng6.process_line("打坐", now=2.0), [])

# --- quit must be usable as a bot action (explicit requirement) ---------
eng7 = Engine()
eng7.triggers.append(Trigger(name="bail", pattern="你死了", actions=["quit"]))
check("quit is a legal bot action",
      eng7.process_line("你死了！", now=1.0), ["quit"])

# --- multiple actions, in order -----------------------------------------
eng8 = Engine()
eng8.triggers.append(Trigger(name="multi", pattern="完毕",
                             actions=["hp", "dazuo"]))
check("multiple actions run in order",
      eng8.process_line("行功完毕", now=1.0), ["hp", "dazuo"])

# --- grinding loop via timer --------------------------------------------
eng9 = Engine()
eng9.timers.append(TimerBot(name="grind", interval=5.0, actions=["dazuo"]))
check("timer does not fire before its interval",
      eng9.tick(now=1.0), [])
check("timer fires once the interval elapses",
      eng9.tick(now=7.0), ["dazuo"])
check("timer does not fire again immediately",
      eng9.tick(now=8.0), [])
check("timer fires again after another interval",
      eng9.tick(now=13.0), ["dazuo"])

eng10 = Engine()
eng10.timers.append(TimerBot(name="off", interval=1.0, actions=["x"],
                             enabled=False))
check("disabled timer never fires", eng10.tick(now=999.0), [])

# --- master switch -------------------------------------------------------
eng11 = Engine()
eng11.triggers.append(Trigger(name="t", pattern="打坐", actions=["a"]))
eng11.timers.append(TimerBot(name="g", interval=1.0, actions=["b"]))
eng11.enabled = False
check("master switch off silences triggers",
      eng11.process_line("打坐", now=1.0), [])
check("master switch off silences timers", eng11.tick(now=99.0), [])

# --- ANSI + CJK width helpers -------------------------------------------
check("ANSI colour codes stripped",
      strip_ansi("\x1b[1;33m你发现系统ＢＵＧ\x1b[2;37;0m"),
      "你发现系统ＢＵＧ")
check_true("triggers match despite ANSI in the raw line",
           Engine(triggers=[Trigger(name="a", pattern="行功完毕",
                                    actions=["x"])])
           .process_line("\x1b[1;33m你行功完毕\x1b[0m", now=1.0) == ["x"])
check("CJK counts as double width", display_width("你好"), 4)
check("ASCII counts as single width", display_width("hi"), 2)
check("mixed width", display_width("hi你好"), 6)
check("fit_to_width never splits a wide char in half",
      display_width(fit_to_width("你好世界", 5)), 4)
check("fit_to_width keeps what fits", fit_to_width("abcdef", 3), "abc")

# --- persistence round-trip ---------------------------------------------
with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d) / "cfg.json"
    original = Engine(
        triggers=[Trigger(name="中文触发", pattern="你行功完毕",
                          actions=["dazuo"], cooldown=2.5)],
        timers=[TimerBot(name="磨练", interval=30.0, actions=["lian"])],
    )
    save_config(p, original)
    loaded = load_config(p)
    check("trigger survives save/load with Chinese intact",
          loaded.triggers[0].name, "中文触发")
    check("trigger pattern survives", loaded.triggers[0].pattern, "你行功完毕")
    check("cooldown survives", loaded.triggers[0].cooldown, 2.5)
    check("timer survives", loaded.timers[0].name, "磨练")
    check("loading a missing file yields an empty engine",
          len(load_config(pathlib.Path(d) / "nope.json").triggers), 0)

print("---")
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASS")
