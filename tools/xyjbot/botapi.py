#!/usr/bin/env python3
"""BotAPI -- the interface a user bot script sees.

A bot is a plain .py file in bots/<name>.py with a module-level
run(api) function. It runs on its own thread, driven by botproxy, so
ordinary blocking Python (while loops, if/else, api.sleep(...)) works
the way you'd write any script -- no async, no callbacks.

Example (bots/qigan-bot.py):

    def run(api):
        while not api.stopped():
            api.send("climb qigan#5")
            cur, mx, pct = api.hp()
            if pct < 50:
                api.sleep(30)
"""
from __future__ import annotations

import queue
import re
import time

from ansi import strip_ansi


class Stopped(Exception):
    """Raised inside api calls once the bot has been told to stop.

    Bot scripts don't need to catch this -- botproxy catches it around
    the whole run() call so /stop unwinds cleanly out of a sleep() or
    wait_line() no matter how deep the script's loop nesting is.
    """


class BotAPI:
    def __init__(self, session, name, stop_event):
        self._session = session
        self.name = name
        self._stop = stop_event
        self._lines = queue.Queue()

    # -- lifecycle --------------------------------------------------
    def stopped(self):
        return self._stop.is_set()

    def _check(self):
        if self._stop.is_set():
            raise Stopped()

    # -- talking to the mud -------------------------------------------
    def send(self, cmd, quiet=False):
        """Send a raw command line to the mud (goes through the same
        connection as the player's own typing).

        quiet=True skips the "-> cmd" echo, for housekeeping commands
        the player didn't ask for and doesn't need narrated.
        """
        self._check()
        if not quiet:
            self._session.note(f"[{self.name}] -> {cmd}")
        self._session.to_mud(cmd)

    def log(self, msg):
        self._session.note(f"[{self.name}] {msg}")

    # -- reading the mud's output --------------------------------------
    def feed(self, line):
        """Called by the session for every incoming line. Non-blocking.

        Strips ANSI here so scripts match on what they *see*: the mud
        colours its status output, e.g. the hp line really arrives as
        ' 气血： \\x1b[33m  92/  200 \\x1b[1;32m( 99%)', and a pattern
        written against the visible text would never match the raw form.
        """
        self._lines.put(strip_ansi(line))

    def drain(self):
        """Discard buffered lines so the next wait_line() only sees
        output that arrives from here on."""
        while True:
            try:
                self._lines.get_nowait()
            except queue.Empty:
                return

    def wait_line(self, pattern, timeout=10.0):
        """Block until a line matching `pattern` (a regex) arrives, or
        return None after `timeout` seconds. Checked for /stop every
        0.5s so a bot can be interrupted mid-wait."""
        rx = re.compile(pattern)
        deadline = time.time() + timeout
        while True:
            self._check()
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            try:
                line = self._lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            m = rx.search(line)
            if m:
                return m

    def sleep(self, secs):
        """Interruptible sleep -- /stop cuts this short instead of
        waiting the full duration out."""
        deadline = time.time() + secs
        while time.time() < deadline:
            self._check()
            time.sleep(min(0.5, deadline - time.time()))

    # -- convenience: HP via the "hp" command ---------------------------
    # ' 气血：   92/  200 ( 99%)' -- spaces can appear on either side of
    # the slash. Note the mud's own trailing percentage is eff_kee/max_kee
    # (how wounded you are), NOT current/max, so pct below is computed
    # from the two numbers rather than read off that display.
    _HP_RE = r"气血[：:]\s*(\d+)\s*/\s*(\d+)"

    def hp(self, timeout=5.0, quiet=False):
        """Sends 'hp' and returns (current, max, pct) parsed from the
        reply. pct is an int 0-100.

        The reply block is shown to the player by default -- it's real
        game output and hiding it loses information. Pass quiet=True to
        swallow the five status lines and leave only the script's own
        api.log() visible, for a bot that polls hp in a tight loop.

        On a parse failure returns (0, 0, 0) *and says so* -- silently
        reporting 0% would look to a script exactly like "nearly dead",
        which sends bots down their rest branch forever.
        """
        self.drain()
        if quiet:
            self._session.arm_gag()
        self.send("hp", quiet=quiet)
        m = self.wait_line(self._HP_RE, timeout=timeout)
        if not m:
            self.log("警告：看不懂 hp 的回应（气血解析失败）。")
            return (0, 0, 0)
        cur, mx = int(m.group(1)), int(m.group(2))
        pct = (cur * 100 // mx) if mx else 0
        return (cur, mx, pct)

    # -- full status block via the "hp" command --------------------------
    # The block is exactly 5 lines (cmds/usr/hp.lpc), ending with the
    # 潜能/杀气 line -- used as the stop marker instead of a fixed line
    # count so a slow/split delivery doesn't cut the block short.
    _STATUS_FIELDS = {
        "kee": (r"气血[：:]\s*(\d+)", int),
        "max_kee": (r"气血[：:]\s*\d+\s*/\s*(\d+)", int),
        "sen": (r"精神[：:]\s*(\d+)", int),
        "max_sen": (r"精神[：:]\s*\d+\s*/\s*(\d+)", int),
        "force": (r"内力[：:]\s*(\d+)", int),
        "max_force": (r"内力[：:]\s*\d+\s*/\s*(\d+)", int),
        "mana": (r"法力[：:]\s*(\d+)", int),
        "max_mana": (r"法力[：:]\s*\d+\s*/\s*(\d+)", int),
        "food": (r"食物[：:]\s*(\d+)", int),
        # 食物/饮水 capacity is max_food_capacity() -- weight/200, floor
        # 100 (feature/damage.lpc:402-418) -- so it is NOT a constant and
        # has to be read off the display rather than assumed. Without the
        # denominator a bot can only compare food/water against a magic
        # number, which is how "am I hungry?" got answered wrongly.
        "max_food": (r"食物[：:]\s*\d+\s*/\s*(\d+)", int),
        "water": (r"饮水[：:]\s*(\d+)", int),
        "max_water": (r"饮水[：:]\s*\d+\s*/\s*(\d+)", int),
        "wuxue": (r"武学[：:]\s*(\d+)", int),
        "potential": (r"潜能[：:]\s*(\d+)", int),
        "bellicosity": (r"杀气[：:]\s*(\d+)", int),
    }

    def status(self, timeout=5.0, quiet=True):
        """Sends 'hp' and returns a dict with kee/max_kee/sen/max_sen/
        force/max_force/mana/max_mana/food/max_food/water/max_water/
        wuxue/potential/bellicosity -- everything hp() gives plus 武学
        and the rest of the block. Missing/unparsed fields default to 0.

        quiet=True (the default here, unlike hp()) since this is meant
        for a bot's own periodic polling, not a one-off the player asked
        for by hand.
        """
        self.drain()
        if quiet:
            self._session.arm_gag()
        self.send("hp", quiet=quiet)

        lines = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._check()
            remaining = deadline - time.time()
            try:
                line = self._lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            lines.append(line)
            if "潜能" in line:
                break
        text = "\n".join(lines)

        out = {}
        for key, (pattern, cast) in self._STATUS_FIELDS.items():
            m = re.search(pattern, text)
            out[key] = cast(m.group(1)) if m else 0
        if not lines:
            self.log("警告：看不懂 hp 的回应（status 解析失败）。")
        return out
