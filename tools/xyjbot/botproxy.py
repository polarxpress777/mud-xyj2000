#!/usr/bin/env python3
"""botproxy -- run your bots while you play in a plain `nc` session.

    python3 botproxy.py            # listens 40099, mud on 127.0.0.1:40012
    nc 127.0.0.1 40099             # play as usual

`nc` is a dumb pipe with no automation of its own, so this sits in the
middle: it relays both directions verbatim, watches the mud's output for
triggers, and intercepts /commands you type before they reach the game.

Two kinds of bot live here:
  - regex triggers/timers, edited as JSON via the browser form (bots.json)
  - real Python scripts in bots/<name>.py with a run(api) function,
    for logic that needs loops/conditionals/state (see botapi.py)

  /bots            list trigger/timer bots (JSON)
  /<name>          run a trigger/timer bot's actions once
  /list            list Python bots (bots/*.py) and whether they're running
  /run <name>      start a Python bot on its own thread
  /stop <name>     stop a running Python bot
  /auto            master on/off for triggers and timers
  /reload          re-read bots.json (the editor writes it)
  /help

Edit trigger/timer bots in the browser editor (boteditor.py). Python
bots are just files -- write them in bots/<name>.py with any editor.
"""
from __future__ import annotations

import re
import difflib
import socket
import threading
import time
from pathlib import Path

from ansi import strip_ansi, strip_iac
from botmanager import BotManager
from triggers import load_config

# Idle-kick guard. include/user.h:13 sets IDLE_TIMEOUT to 1200s and
# std/char.lpc:140 enforces it by force-quitting -- which drops everything
# you are carrying. 0 disables the keepalive.
KEEPALIVE_AFTER = 400      # seconds of silence before a bare newline

CONFIG = Path(__file__).with_name("bots.json")
LISTEN_PORT = 40099
MUD_HOST, MUD_PORT = "127.0.0.1", 40012

# The five lines `hp` prints. This mudlib has no way to read hp without
# running the command (the prompt is a hardcoded "> " in
# feature/message.lpc), so a polling bot has to send `hp` -- but the
# player doesn't need the block pasted in every loop, so it gets gagged.
STATUS_RE = re.compile(r"^\s*(气血|精神|食物|饮水|潜能)[：:]")


class Session:
    """One player connection: client <-> proxy <-> mud."""

    def __init__(self, client: socket.socket):
        self.client = client
        self.mud = socket.create_connection((MUD_HOST, MUD_PORT))
        self.engine = load_config(CONFIG)
        self.pybots = BotManager(self)
        self.alive = True
        self.last_sent = time.time()
        self.buf = b""          # partial line from the mud
        self.inbuf = b""        # partial line from the player
        self.frag_sent = 0      # bytes of the current partial line already relayed
        self.gag_lines = 0      # status lines still to swallow
        self.gag_deadline = 0.0

    # -- plumbing -------------------------------------------------------
    def to_player(self, text: str):
        try:
            self.client.sendall(text.encode("utf-8"))
        except OSError:
            self.alive = False

    def to_mud(self, line: str):
        try:
            self.mud.sendall(line.encode("utf-8") + b"\n")
            self.last_sent = time.time()
        except OSError:
            self.alive = False

    def to_player_bytes(self, data: bytes):
        try:
            self.client.sendall(data)
        except OSError:
            self.alive = False

    def note(self, text: str):
        # Cyan so bot activity is distinguishable from game output.
        self.to_player(f"\x1b[36m[bot] {text}\x1b[0m\r\n")

    # -- output gagging -------------------------------------------------
    def arm_gag(self, nlines=6, seconds=3.0):
        """Swallow the next few status lines instead of showing them.

        Bounded by both a line count and a wall-clock deadline, so a
        reply that never arrives can't leave real game output gagged.
        """
        self.gag_lines = nlines
        self.gag_deadline = time.time() + seconds

    def gag_active(self):
        return self.gag_lines > 0 and time.time() < self.gag_deadline

    # -- mud -> player --------------------------------------------------
    def pump_mud(self):
        while self.alive:
            try:
                data = self.mud.recv(4096)
            except OSError:
                break
            if not data:
                break

            self.buf += strip_iac(data)
            now = time.time()

            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                text = strip_ansi(line.rstrip(b"\r").decode("utf-8", "replace"))

                # frag_sent > 0 means part of this line already went out as
                # a prompt fragment; it has to be finished either way, or
                # the player is left looking at a truncated line.
                if (self.gag_active() and not self.frag_sent
                        and STATUS_RE.match(text)):
                    self.gag_lines -= 1
                else:
                    self.to_player_bytes(line[self.frag_sent:] + b"\n")
                self.frag_sent = 0

                self.fire(text, now)

            # The trailing fragment is the prompt. Hold it while a gag is
            # armed so it lands after the swallowed block, not before it.
            if self.buf and not self.gag_active():
                new = self.buf[self.frag_sent:]
                if new:
                    self.to_player_bytes(new)
                    self.frag_sent = len(self.buf)
                    # Prompts never end in a newline, so triggers would
                    # never see them if only complete lines were fed.
                    # Bots deliberately don't get partial lines: half a
                    # status line parses as plausible-but-wrong numbers.
                    self.fire_triggers_only(
                        strip_ansi(self.buf.decode("utf-8", "replace")), now)
        self.alive = False

    def fire(self, line: str, now: float):
        self.pybots.feed(line)
        self.fire_triggers_only(line, now)

    def fire_triggers_only(self, line: str, now: float):
        for cmd in self.engine.process_line(line, now):
            self.note(f"→ {cmd}")
            self.to_mud(cmd)

    # -- timers ---------------------------------------------------------
    def pump_timers(self):
        while self.alive:
            for cmd in self.engine.tick(time.time()):
                self.note(f"⏱ {cmd}")
                self.to_mud(cmd)
            self.keepalive()
            time.sleep(0.5)

    def keepalive(self):
        """Send a bare newline if nothing has gone to the mud in a while.

        std/char.lpc:140 dumps any player whose driver-side query_idle()
        passes IDLE_TIMEOUT (include/user.h:13 -- 1200 seconds), and the
        forced quit DROPS THE WHOLE INVENTORY on the floor. That is a real
        loss: it cost a 桂花酒袋, 镔铁棍, 牛皮盾 and the rest in one go.

        An empty line is input as far as the driver is concerned, so it
        resets the idle clock, and the mud prints nothing back for it -- no
        noise in the player's session. Sent at a third of the timeout so a
        missed one is harmless.

        This protects the player whether or not a bot is running: sitting at
        the keyboard reading is exactly as idle as being away.

        It does deliberately defeat the server's idle policy. That is the
        owner's call to make; set KEEPALIVE_AFTER to 0 to turn it off.
        """
        if not KEEPALIVE_AFTER:
            return
        if time.time() - self.last_sent >= KEEPALIVE_AFTER:
            self.to_mud("")

    # -- player -> mud --------------------------------------------------
    def pump_player(self):
        while self.alive:
            try:
                data = self.client.recv(4096)
            except OSError:
                break
            if not data:
                break
            self.inbuf += strip_iac(data)
            while b"\n" in self.inbuf:
                raw, self.inbuf = self.inbuf.split(b"\n", 1)
                line = raw.rstrip(b"\r").decode("utf-8", "replace")
                if not self.local_command(line):
                    self.to_mud(line)
        self.alive = False

    LOCAL_COMMANDS = ("help", "auto", "reload", "list", "run", "stop", "bots")

    def local_command(self, line: str) -> bool:
        """Handle a /command locally. Returns True if it was consumed."""
        cmd = line.strip()
        if not cmd.startswith("/"):
            return False
        name = cmd[1:].split(" ")[0].lower()

        if name in ("help", ""):
            self.note("/bots 列出触发机器人  /list 列出 Python 机器人  "
                      "/run <名称> 启动  /stop <名称> 停止  "
                      "/auto 开关  /reload 重新载入  /help")
            return True
        if name == "auto":
            self.engine.enabled = not self.engine.enabled
            self.note("自动化：" + ("开" if self.engine.enabled else "关"))
            return True
        if name == "reload":
            self.engine = load_config(CONFIG)
            self.note(f"已重新载入 {len(self.engine.triggers)} 个触发、"
                      f"{len(self.engine.timers)} 个循环")
            return True
        if name == "list":
            self.pybots.status()
            return True
        if name == "run":
            rest = cmd[len("/run"):].strip()
            if not rest:
                return self.note("指令格式：/run <机器人名称> [参数]") or True
            target, _, bot_arg = rest.partition(" ")
            self.pybots.start(target, bot_arg.strip() or None)
            return True
        if name == "stop":
            target = cmd[len("/stop"):].strip()
            if not target:
                self.pybots.stop_all()
                self.note("已停止所有 Python 机器人。")
                return True
            self.pybots.stop(target)
            return True
        if name == "bots":
            if not self.engine.triggers and not self.engine.timers:
                self.note("还没有任何机器人。用浏览器编辑器建立。")
            for t in self.engine.triggers:
                self.note(f"[触发] /{t.name}  当「{t.pattern}」→ "
                          + " ; ".join(t.actions))
            for tb in self.engine.timers:
                self.note(f"[循环] /{tb.name}  每 {tb.interval:g} 秒 → "
                          + " ; ".join(tb.actions))
            return True

        # /<bot name> -- run that bot's actions now.
        for t in self.engine.triggers:
            if t.name.lower() == name:
                for a in t.actions:
                    self.note(f"→ {a}")
                    self.to_mud(a)
                return True
        for tb in self.engine.timers:
            if tb.name.lower() == name:
                for a in tb.actions:
                    self.note(f"→ {a}")
                    self.to_mud(a)
                return True

        # Not a command and not a trigger name. Before giving up, work out
        # what was probably meant: a mistyped verb reads as a bot name here,
        # so "/ran changan-mieyao" used to answer 没有叫「ran」的机器人 --
        # which points at the verb while the eye is on the bot name, and
        # reads as "the bot is gone".
        arg = cmd[1:].partition(" ")[2].strip()
        near = difflib.get_close_matches(name, self.LOCAL_COMMANDS, n=1, cutoff=0.6)
        pybots = self.pybots.available()

        if arg and arg in pybots:
            # The argument names a real bot, so the intent is unambiguous
            # whatever the verb was meant to be -- always /run, never the
            # nearest-looking command (/bot would have suggested /bots).
            self.note(f"没有 /{name} 这个指令。要启动机器人请打：/run {arg}")
        elif name in pybots:
            self.note(f"「{name}」是 Python 机器人，要用：/run {name}")
        elif near:
            self.note(f"没有 /{name} 这个指令，你是不是要打 /{near[0]}？"
                      "（/help 看全部）")
        else:
            self.note(f"没有 /{name} 这个指令，也没有叫「{name}」的触发机器人。"
                      "/help 看指令，/bots 和 /list 列出机器人。")
        return True

    def run(self):
        for fn in (self.pump_mud, self.pump_timers):
            threading.Thread(target=fn, daemon=True).start()
        self.note("botproxy 已连线。输入 /help 查看指令。")
        self.pump_player()
        self.pybots.stop_all()
        for s in (self.client, self.mud):
            try:
                s.close()
            except OSError:
                pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", LISTEN_PORT))
    srv.listen(5)
    print(f"botproxy: nc 127.0.0.1 {LISTEN_PORT}  "
          f"-> mud {MUD_HOST}:{MUD_PORT}   (Ctrl-C to stop)")
    try:
        while True:
            client, _ = srv.accept()
            threading.Thread(target=Session(client).run, daemon=True).start()
    except KeyboardInterrupt:
        print("\nbotproxy stopped.")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
