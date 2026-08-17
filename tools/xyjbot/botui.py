"""Full-screen bot builder screen.

List of triggers and timers, with add / edit / delete / enable, plus an
AI-assisted creator so a player can describe a bot in plain Chinese
instead of writing patterns by hand.
"""
from __future__ import annotations

import curses
import os

from ansi import display_width, fit_to_width
from triggers import Trigger, TimerBot, save_config

# AI-assisted creation is staged for a later rollout: it needs the
# anthropic package plus an API key, and generated bots should be reviewed
# before they drive a live character. Opt in with XYJBOT_AI=1.
AI_ENABLED = os.environ.get("XYJBOT_AI") == "1"

HELP = ("↑↓ 选择   Enter 编辑   空白 启用/停用   t 新触发   m 新循环   "
        "d 删除   q 返回")
if AI_ENABLED:
    HELP = ("↑↓ 选择   Enter 编辑   空白 启用/停用   t 新触发   m 新循环   "
            "a AI 生成   d 删除   q 返回")


class BotUI:
    def __init__(self, stdscr, engine, config_path, app=None):
        self.stdscr = stdscr
        self.engine = engine
        self.config_path = config_path
        self.app = app
        self.sel = 0
        self.msg = ""

    # -- helpers --------------------------------------------------------
    def rows(self):
        """Flat list of (kind, object) for display."""
        return ([("trigger", t) for t in self.engine.triggers]
                + [("timer", t) for t in self.engine.timers])

    def prompt(self, label: str, initial: str = "") -> str | None:
        """Single-line input at the bottom. ESC cancels (returns None)."""
        h, w = self.stdscr.getmaxyx()
        buf = initial
        curses.curs_set(1)
        while True:
            line = fit_to_width(f"{label}{buf}", w - 1)
            try:
                self.stdscr.addstr(h - 1, 0, line.ljust(w - 1))
                self.stdscr.move(h - 1, min(display_width(line), w - 1))
            except curses.error:
                pass
            self.stdscr.refresh()
            try:
                ch = self.stdscr.get_wch()
            except curses.error:
                continue
            if isinstance(ch, str):
                if ch == "\x1b":
                    return None
                if ch in ("\n", "\r"):
                    return buf
                if ch in ("\x7f", "\b"):
                    buf = buf[:-1]
                elif ch.isprintable():
                    buf += ch
            elif ch == curses.KEY_BACKSPACE:
                buf = buf[:-1]

    def confirm(self, label: str) -> bool:
        ans = self.prompt(f"{label} (y/n) ")
        return bool(ans) and ans.strip().lower().startswith("y")

    # -- editing --------------------------------------------------------
    def edit_trigger(self, t: Trigger):
        v = self.prompt("名称: ", t.name)
        if v is None:
            return
        t.name = v
        v = self.prompt("触发文字（游戏里出现的句子）: ", t.pattern)
        if v is None:
            return
        t.pattern = v
        v = self.prompt("用正规表示式? (y/n): ", "y" if t.is_regex else "n")
        if v is None:
            return
        t.is_regex = v.strip().lower().startswith("y")
        v = self.prompt("要送出的指令（用 ; 分隔）: ", ";".join(t.actions))
        if v is None:
            return
        t.actions = [a.strip() for a in v.split(";") if a.strip()]
        v = self.prompt("冷却秒数（0 = 不限）: ", str(t.cooldown))
        if v is None:
            return
        try:
            t.cooldown = float(v)
        except ValueError:
            t.cooldown = 0.0
        v = self.prompt("只触发一次? (y/n): ", "y" if t.once else "n")
        if v is None:
            return
        t.once = v.strip().lower().startswith("y")
        self.msg = f"已储存触发「{t.name}」"

    def edit_timer(self, tb: TimerBot):
        v = self.prompt("名称: ", tb.name)
        if v is None:
            return
        tb.name = v
        v = self.prompt("每隔几秒执行: ", str(tb.interval))
        if v is None:
            return
        try:
            tb.interval = float(v)
        except ValueError:
            tb.interval = 0.0
        v = self.prompt("要送出的指令（用 ; 分隔）: ", ";".join(tb.actions))
        if v is None:
            return
        tb.actions = [a.strip() for a in v.split(";") if a.strip()]
        self.msg = f"已储存循环「{tb.name}」"

    def ai_create(self):
        if not AI_ENABLED:
            self.msg = "AI 生成尚未开放（设定 XYJBOT_AI=1 可提前试用）。"
            return
        desc = self.prompt("用中文描述你要的机器人: ")
        if not desc:
            return
        self.msg = "AI 生成中，请稍候..."
        self.draw()
        try:
            from ai import generate_bot
            made = generate_bot(desc)
        except Exception as e:            # noqa: BLE001 - surfaced to user
            self.msg = f"AI 生成失败: {e}"
            return
        if not made:
            self.msg = "AI 没有产生任何设定。"
            return
        for obj in made:
            if isinstance(obj, Trigger):
                self.engine.triggers.append(obj)
            else:
                self.engine.timers.append(obj)
        names = "、".join(o.name for o in made)
        self.msg = f"AI 已建立: {names}（请检查后再启用）"

    # -- main loop ------------------------------------------------------
    def run(self):
        curses.curs_set(0)
        while True:
            self.draw()
            try:
                ch = self.stdscr.get_wch()
            except curses.error:
                continue

            rows = self.rows()
            key = ch if isinstance(ch, str) else ""

            if key in ("q", "\x1b"):
                save_config(self.config_path, self.engine)
                curses.curs_set(1)
                return
            if ch == curses.KEY_UP:
                self.sel = max(0, self.sel - 1)
            elif ch == curses.KEY_DOWN:
                self.sel = min(max(0, len(rows) - 1), self.sel + 1)
            elif key == " " and rows:
                obj = rows[self.sel][1]
                obj.enabled = not obj.enabled
            elif key == "t":
                t = Trigger(name="新触发", pattern="", actions=[])
                self.engine.triggers.append(t)
                self.sel = len(self.engine.triggers) - 1
                self.edit_trigger(t)
            elif key == "m":
                tb = TimerBot(name="新循环", interval=10.0, actions=[])
                self.engine.timers.append(tb)
                self.sel = len(self.engine.triggers) + len(self.engine.timers) - 1
                self.edit_timer(tb)
            elif key == "a":
                self.ai_create()
            elif key == "d" and rows:
                kind, obj = rows[self.sel]
                if self.confirm(f"删除「{obj.name}」?"):
                    if kind == "trigger":
                        self.engine.triggers.remove(obj)
                    else:
                        self.engine.timers.remove(obj)
                    self.sel = max(0, self.sel - 1)
            elif ch in (curses.KEY_ENTER, "\n", "\r") and rows:
                kind, obj = rows[self.sel]
                if kind == "trigger":
                    self.edit_trigger(obj)
                else:
                    self.edit_timer(obj)

    def draw(self):
        stdscr = self.stdscr
        h, w = stdscr.getmaxyx()
        stdscr.erase()

        title = " 机器人设定 / Bot Builder "
        try:
            stdscr.addstr(0, 0, fit_to_width(title, w).ljust(w),
                          curses.A_REVERSE)
        except curses.error:
            pass

        rows = self.rows()
        if not rows:
            hint = ("还没有任何机器人。按 t 新增触发，按 m 新增循环。"
                    if not AI_ENABLED else
                    "还没有任何机器人。按 t 新增触发，或按 a 让 AI 帮你写。")
            try:
                stdscr.addstr(2, 2, hint)
            except curses.error:
                pass

        top = 2
        avail = h - top - 3
        first = max(0, self.sel - avail + 1)
        for i, (kind, obj) in enumerate(rows[first:first + avail]):
            idx = first + i
            mark = "[x]" if obj.enabled else "[ ]"
            if kind == "trigger":
                detail = f"当「{obj.pattern}」→ {' ; '.join(obj.actions)}"
                if obj.is_regex:
                    detail = "(regex) " + detail
                if obj.cooldown:
                    detail += f"  冷却{obj.cooldown:g}s"
                if obj.once:
                    detail += "  仅一次"
                tag = "触发"
            else:
                detail = (f"每 {obj.interval:g} 秒 → "
                          f"{' ; '.join(obj.actions)}")
                tag = "循环"
            text = f"{mark} [{tag}] {obj.name}  {detail}"
            attr = curses.A_REVERSE if idx == self.sel else curses.A_NORMAL
            try:
                stdscr.addstr(top + i, 0, fit_to_width(text, w).ljust(w), attr)
            except curses.error:
                pass

        try:
            stdscr.addstr(h - 3, 0, fit_to_width(self.msg, w).ljust(w),
                          curses.A_BOLD)
            stdscr.addstr(h - 2, 0, fit_to_width(HELP, w).ljust(w),
                          curses.A_REVERSE)
        except curses.error:
            pass
        stdscr.refresh()
