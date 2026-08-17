#!/usr/bin/env python3
"""xyjbot -- a full-screen terminal client for 西游记 with a bot builder.

  python3 xyjbot.py [host] [port]      (defaults 127.0.0.1 40012)

Keys
  F2 / Ctrl-B   open the bot builder
  F3 / Ctrl-G   toggle all automation on/off
  PgUp/PgDn     scroll the game pane
  Ctrl-C        quit

Everything is stdlib: curses for the UI, unicodedata for CJK widths.
"""
from __future__ import annotations

import curses
import queue
import socket
import sys
import threading
import time
from pathlib import Path

from ansi import split_ansi, strip_ansi, strip_iac, display_width, \
    fit_to_width, wrap_to_width
from triggers import Engine, Trigger, TimerBot, load_config, save_config

CONFIG_PATH = Path(__file__).with_name("bots.json")
SCROLLBACK = 5000


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------
class MudConnection:
    """Socket reader thread that emits decoded lines onto a queue."""

    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.sock: socket.socket | None = None
        self.lines: queue.Queue[str] = queue.Queue()
        self.alive = False
        self._buf = b""

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        self.sock.settimeout(0.2)
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while self.alive:
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            self._buf += strip_iac(data)
            # Keep any trailing partial line in the buffer. The mud also
            # emits prompts with no newline, so flush those on a short
            # quiet period rather than waiting forever.
            *complete, self._buf = self._buf.split(b"\n")
            for raw in complete:
                self.lines.put(raw.rstrip(b"\r").decode("utf-8", "replace"))
        self.alive = False
        self.lines.put("[连线已中断 / disconnected]")

    def flush_partial(self):
        """Emit a pending prompt fragment (no trailing newline)."""
        if self._buf:
            text = self._buf.decode("utf-8", "replace")
            self._buf = b""
            return text
        return None

    def send(self, text: str):
        if self.sock and self.alive:
            try:
                self.sock.sendall(text.encode("utf-8") + b"\n")
            except OSError:
                self.alive = False

    def close(self):
        self.alive = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
COLOR_PAIRS = {}


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    n = 1
    for fg in range(8):
        curses.init_pair(n, fg, -1)
        COLOR_PAIRS[fg] = curses.color_pair(n)
        n += 1


def sgr_to_attr(params, cur):
    """Fold SGR parameters into a curses attribute."""
    for p in params:
        if p == 0:
            cur = curses.A_NORMAL
        elif p == 1:
            cur |= curses.A_BOLD
        elif p == 4:
            cur |= curses.A_UNDERLINE
        elif p == 7:
            cur |= curses.A_REVERSE
        elif 30 <= p <= 37:
            cur = (cur & ~curses.A_COLOR) | COLOR_PAIRS.get(p - 30, 0)
    return cur


class App:
    def __init__(self, stdscr, host, port):
        self.stdscr = stdscr
        self.conn = MudConnection(host, port)
        self.engine = load_config(CONFIG_PATH)
        self.buffer: list[str] = []      # raw lines, ANSI intact
        self.scroll = 0                  # 0 = pinned to bottom
        self.input = ""
        self.status = "F2 机器人  F3 开关自动  PgUp/PgDn 翻页  Ctrl-C 离开"
        self.host, self.port = host, port

    # -- buffer ---------------------------------------------------------
    def add_line(self, text: str):
        self.buffer.append(text)
        if len(self.buffer) > SCROLLBACK:
            del self.buffer[: len(self.buffer) - SCROLLBACK]

    def add_note(self, text: str):
        self.add_line(f"\x1b[36m[bot] {text}\x1b[0m")

    def handle_incoming(self, line: str, now: float):
        """Display one line from the mud and let triggers act on it.

        Used for both newline-terminated lines and flushed prompt
        fragments -- the mud's prompts ("Select GB or BIG5", "请输入密码")
        arrive with no trailing newline, and those are exactly the lines
        players most want to trigger on, so they must go through here too.
        """
        self.add_line(line)
        for cmd in self.engine.process_line(line, now):
            self.add_note(f"→ {cmd}")
            self.conn.send(cmd)

    # -- drawing --------------------------------------------------------
    def draw(self):
        stdscr = self.stdscr
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        game_h = h - 2

        # Wrap from the bottom up so the newest text is always visible.
        rendered: list[list[tuple[str, int]]] = []
        for raw in self.buffer[-(SCROLLBACK):]:
            attr = curses.A_NORMAL
            segs: list[tuple[str, int]] = []
            for kind, val in split_ansi(raw):
                if kind == "sgr":
                    attr = sgr_to_attr(val, attr)
                else:
                    segs.append((val, attr))
            plain = "".join(s for s, _ in segs)
            if display_width(plain) <= w:
                rendered.append(segs)
            else:
                # Re-wrap long lines, carrying the attribute of the
                # segment each chunk came from.
                for chunk in wrap_to_width(plain, w):
                    rendered.append([(chunk, segs[0][1] if segs else
                                      curses.A_NORMAL)])

        start = max(0, len(rendered) - game_h - self.scroll)
        view = rendered[start:start + game_h]
        for y, segs in enumerate(view):
            x = 0
            for text, attr in segs:
                if x >= w:
                    break
                piece = fit_to_width(text, w - x)
                if not piece:
                    continue
                try:
                    stdscr.addstr(y, x, piece, attr)
                except curses.error:
                    pass
                x += display_width(piece)

        # status bar
        auto = "开" if self.engine.enabled else "关"
        n_on = sum(1 for t in self.engine.triggers if t.enabled)
        n_tm = sum(1 for t in self.engine.timers if t.enabled)
        bar = (f" 自动:{auto}  触发:{n_on}  循环:{n_tm}  "
               f"{self.host}:{self.port}  {self.status}")
        try:
            stdscr.addstr(h - 2, 0, fit_to_width(bar, w).ljust(w),
                          curses.A_REVERSE)
        except curses.error:
            pass

        prompt = "> " + self.input
        try:
            stdscr.addstr(h - 1, 0, fit_to_width(prompt, w - 1))
        except curses.error:
            pass
        stdscr.move(h - 1, min(display_width(prompt), w - 1))
        stdscr.refresh()

    # -- main loop ------------------------------------------------------
    def run(self):
        # timeout() rather than nodelay(): function keys arrive as
        # multi-byte escape sequences (F2 is "\x1bOQ" or "\x1b[12~"), and
        # in fully non-blocking mode curses returns before the rest of the
        # sequence lands, so it can never assemble them into KEY_F2. A
        # short blocking wait also stops this loop from busy-spinning.
        self.stdscr.timeout(50)
        self.stdscr.keypad(True)
        try:
            self.conn.connect()
        except OSError as e:
            self.add_line(f"无法连线 {self.host}:{self.port} -- {e}")

        last_flush = time.time()
        while True:
            now = time.time()

            # drain incoming lines, run triggers on each
            got = False
            while True:
                try:
                    line = self.conn.lines.get_nowait()
                except queue.Empty:
                    break
                got = True
                self.handle_incoming(line, now)
            if got:
                last_flush = now

            # Prompts arrive without a newline; flush them after a short
            # pause and run them through triggers like any other line.
            if now - last_flush > 0.25:
                partial = self.conn.flush_partial()
                if partial:
                    self.handle_incoming(partial, now)
                last_flush = now

            for cmd in self.engine.tick(now):
                self.add_note(f"⏱ {cmd}")
                self.conn.send(cmd)

            self.draw()

            try:
                ch = self.stdscr.get_wch()
            except curses.error:
                continue        # timeout() expired: no key this tick

            if not self.handle_key(ch):
                break

        self.conn.close()

    def handle_key(self, ch) -> bool:
        h, w = self.stdscr.getmaxyx()
        if isinstance(ch, str):
            if ch == "\x03":                      # Ctrl-C
                return False
            if ch in ("\n", "\r"):
                # Local slash-commands are handled here rather than sent
                # to the mud. These always work: unlike function keys and
                # control chars, nothing between the keyboard and this
                # process (tmux, screen, ssh, the terminal emulator) can
                # intercept an ordinary typed word.
                raw = self.input          # send this: never lowercased,
                cmd = raw.strip().lower()  # so ids/names keep their case
                self.input = ""
                self.scroll = 0
                if cmd in ("/bot", "/bots"):
                    self.bot_screen()
                    return True
                if cmd == "/auto":
                    self.engine.enabled = not self.engine.enabled
                    self.add_note("自动化：" +
                                  ("开" if self.engine.enabled else "关"))
                    return True
                if cmd == "/help":
                    self.add_note("/bot 机器人设定   /auto 开关自动化   "
                                  "/quit 离开   (也可用 F2 / F3 / Ctrl-O)")
                    return True
                if cmd == "/quit":
                    return False
                self.conn.send(raw)
                return True
            if ch in ("\x7f", "\b"):
                self.input = self.input[:-1]
                return True
            if ch == "\x0f":                      # Ctrl-O (Ctrl-B is tmux's
                self.bot_screen()                 # prefix, so avoid it)
                return True
            if ch == "\x07":                      # Ctrl-G
                self.engine.enabled = not self.engine.enabled
                return True
            if ch.isprintable():
                self.input += ch
            return True

        if ch == curses.KEY_F2:
            self.bot_screen()
        elif ch == curses.KEY_F3:
            self.engine.enabled = not self.engine.enabled
        elif ch == curses.KEY_BACKSPACE:
            self.input = self.input[:-1]
        elif ch == curses.KEY_PPAGE:
            self.scroll += (h - 3)
        elif ch == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - (h - 3))
        elif ch == curses.KEY_RESIZE:
            pass
        return True

    # -- bot builder ----------------------------------------------------
    def bot_screen(self):
        from botui import BotUI
        BotUI(self.stdscr, self.engine, CONFIG_PATH, self).run()
        save_config(CONFIG_PATH, self.engine)


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 40012

    def _run(stdscr):
        init_colors()
        curses.curs_set(1)
        App(stdscr, host, port).run()

    # Ctrl-C at the terminal raises SIGINT rather than arriving as a
    # keystroke, so catch it here and exit quietly instead of dumping a
    # traceback over the restored terminal.
    try:
        curses.wrapper(_run)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
