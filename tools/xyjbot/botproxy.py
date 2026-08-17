#!/usr/bin/env python3
"""botproxy -- run your bots while you play in a plain `nc` session.

    python3 botproxy.py            # listens 40099, mud on 127.0.0.1:40012
    nc 127.0.0.1 40099             # play as usual

`nc` is a dumb pipe with no automation of its own, so this sits in the
middle: it relays both directions verbatim, watches the mud's output for
triggers, and intercepts /commands you type before they reach the game.

  /bots            list your bots
  /<name>          run the bot called <name>
  /auto            master on/off for triggers and timers
  /reload          re-read bots.json (the editor writes it)
  /help

Edit bots in the browser editor (booteditor.py), not here.
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

from ansi import strip_iac
from triggers import load_config

CONFIG = Path(__file__).with_name("bots.json")
LISTEN_PORT = 40099
MUD_HOST, MUD_PORT = "127.0.0.1", 40012


class Session:
    """One player connection: client <-> proxy <-> mud."""

    def __init__(self, client: socket.socket):
        self.client = client
        self.mud = socket.create_connection((MUD_HOST, MUD_PORT))
        self.engine = load_config(CONFIG)
        self.alive = True
        self.buf = b""          # partial line from the mud
        self.inbuf = b""        # partial line from the player

    # -- plumbing -------------------------------------------------------
    def to_player(self, text: str):
        try:
            self.client.sendall(text.encode("utf-8"))
        except OSError:
            self.alive = False

    def to_mud(self, line: str):
        try:
            self.mud.sendall(line.encode("utf-8") + b"\n")
        except OSError:
            self.alive = False

    def note(self, text: str):
        # Cyan so bot activity is distinguishable from game output.
        self.to_player(f"\x1b[36m[bot] {text}\x1b[0m\r\n")

    # -- mud -> player --------------------------------------------------
    def pump_mud(self):
        while self.alive:
            try:
                data = self.mud.recv(4096)
            except OSError:
                break
            if not data:
                break
            self.client.sendall(data)          # relay verbatim first

            # Feed complete lines to the trigger engine. Prompts arrive
            # without a newline, so also test the trailing fragment --
            # those are exactly the lines players trigger on.
            self.buf += strip_iac(data)
            *lines, self.buf = self.buf.split(b"\n")
            now = time.time()
            for raw in lines:
                self.fire(raw.rstrip(b"\r").decode("utf-8", "replace"), now)
            if self.buf:
                self.fire(self.buf.decode("utf-8", "replace"), now)
        self.alive = False

    def fire(self, line: str, now: float):
        for cmd in self.engine.process_line(line, now):
            self.note(f"→ {cmd}")
            self.to_mud(cmd)

    # -- timers ---------------------------------------------------------
    def pump_timers(self):
        while self.alive:
            for cmd in self.engine.tick(time.time()):
                self.note(f"⏱ {cmd}")
                self.to_mud(cmd)
            time.sleep(0.5)

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

    def local_command(self, line: str) -> bool:
        """Handle a /command locally. Returns True if it was consumed."""
        cmd = line.strip()
        if not cmd.startswith("/"):
            return False
        name = cmd[1:].split(" ")[0].lower()

        if name in ("help", ""):
            self.note("/bots 列出机器人  /<名称> 执行  /auto 开关  "
                      "/reload 重新载入  /help")
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

        self.note(f"没有叫「{name}」的机器人（/bots 可列出）")
        return True

    def run(self):
        for fn in (self.pump_mud, self.pump_timers):
            threading.Thread(target=fn, daemon=True).start()
        self.note("botproxy 已连线。输入 /help 查看指令。")
        self.pump_player()
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
