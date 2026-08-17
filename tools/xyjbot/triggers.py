"""Trigger / bot engine.

Two kinds of automation:

  Trigger  -- reactive: a line arrives from the mud, and if it matches,
              commands are sent back. The majority of real bot flows.
  TimerBot -- proactive: send commands every N seconds. Grinding loops.

The engine is deliberately free of any socket or terminal knowledge so
it can be tested directly (see test_triggers.py). Time is passed in
rather than read from the clock, so cooldown behaviour is testable
without sleeping.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ansi import strip_ansi


@dataclass
class Trigger:
    name: str
    pattern: str
    actions: list[str] = field(default_factory=list)
    is_regex: bool = False
    enabled: bool = True
    # Minimum seconds between fires. 0 = no limit. Guards against a
    # trigger that matches its own output and loops forever.
    cooldown: float = 0.0
    # Fire at most once per session.
    once: bool = False

    # runtime only, not persisted
    last_fired: float = field(default=-1e9, repr=False, compare=False)
    fire_count: int = field(default=0, repr=False, compare=False)

    def matches(self, line: str) -> re.Match | None:
        if self.is_regex:
            try:
                return re.search(self.pattern, line)
            except re.error:
                return None
        return _PlainMatch(line, self.pattern) if self.pattern in line else None


class _PlainMatch:
    """Minimal Match stand-in so plain and regex paths share one shape."""

    def __init__(self, line: str, pattern: str):
        self._line = line
        self._pattern = pattern

    def group(self, n=0):
        return self._pattern if n == 0 else ""

    def groups(self):
        return ()


@dataclass
class TimerBot:
    name: str
    interval: float
    actions: list[str] = field(default_factory=list)
    enabled: bool = True

    last_fired: float = field(default=-1e9, repr=False, compare=False)


def _substitute(action: str, m) -> str:
    """Replace $1..$9 with regex capture groups."""
    if m is None:
        return action
    groups = m.groups()
    out = action
    for i, g in enumerate(groups, start=1):
        if g is not None:
            out = out.replace(f"${i}", g)
    return out


@dataclass
class Engine:
    triggers: list[Trigger] = field(default_factory=list)
    timers: list[TimerBot] = field(default_factory=list)
    # Master switch, so everything can be killed from one keystroke.
    enabled: bool = True

    def process_line(self, raw_line: str, now: float) -> list[str]:
        """Return commands to send in response to one line from the mud."""
        if not self.enabled:
            return []
        # Match against the visible text: the mud wraps most output in
        # colour codes, and a pattern typed by a human never includes them.
        line = strip_ansi(raw_line)
        out: list[str] = []
        for t in self.triggers:
            if not t.enabled:
                continue
            if t.once and t.fire_count:
                continue
            if t.cooldown and (now - t.last_fired) < t.cooldown:
                continue
            m = t.matches(line)
            if not m:
                continue
            t.last_fired = now
            t.fire_count += 1
            for a in t.actions:
                out.append(_substitute(a, m))
        return out

    def tick(self, now: float) -> list[str]:
        """Return commands due from timer bots."""
        if not self.enabled:
            return []
        out: list[str] = []
        for tb in self.timers:
            if not tb.enabled or tb.interval <= 0:
                continue
            if (now - tb.last_fired) < tb.interval:
                continue
            # First tick starts the clock rather than firing immediately,
            # so enabling a bot doesn't blast a command instantly.
            if tb.last_fired <= -1e8:
                tb.last_fired = now
                continue
            tb.last_fired = now
            out.extend(tb.actions)
        return out

    def reset_runtime(self) -> None:
        for t in self.triggers:
            t.last_fired = -1e9
            t.fire_count = 0
        for tb in self.timers:
            tb.last_fired = -1e9


_PERSISTED_TRIGGER = ("name", "pattern", "actions", "is_regex", "enabled",
                      "cooldown", "once")
_PERSISTED_TIMER = ("name", "interval", "actions", "enabled")


def save_config(path: Path, engine: Engine) -> None:
    data = {
        "triggers": [
            {k: v for k, v in asdict(t).items() if k in _PERSISTED_TRIGGER}
            for t in engine.triggers
        ],
        "timers": [
            {k: v for k, v in asdict(tb).items() if k in _PERSISTED_TIMER}
            for tb in engine.timers
        ],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False keeps Chinese readable if the user hand-edits.
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def load_config(path: Path) -> Engine:
    path = Path(path)
    if not path.exists():
        return Engine()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Engine()
    eng = Engine()
    for d in data.get("triggers", []):
        eng.triggers.append(Trigger(
            name=d.get("name", ""),
            pattern=d.get("pattern", ""),
            actions=list(d.get("actions", [])),
            is_regex=bool(d.get("is_regex", False)),
            enabled=bool(d.get("enabled", True)),
            cooldown=float(d.get("cooldown", 0.0)),
            once=bool(d.get("once", False)),
        ))
    for d in data.get("timers", []):
        eng.timers.append(TimerBot(
            name=d.get("name", ""),
            interval=float(d.get("interval", 0.0)),
            actions=list(d.get("actions", [])),
            enabled=bool(d.get("enabled", True)),
        ))
    return eng
