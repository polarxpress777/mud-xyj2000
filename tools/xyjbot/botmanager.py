#!/usr/bin/env python3
"""BotManager -- loads and runs the .py scripts in bots/.

Each bots/<name>.py must define run(api) or run(api, arg). /run <name>
loads it fresh -- along with botapi and any shared helper beside this
file, such as mudmap -- so /run after an edit picks up the change with no
separate reload step. Helpers matter: a bot's `import mudmap` is served
from sys.modules, so re-executing only the bot file would leave it running
whatever was on disk when botproxy started. It then drives the bot on its
own daemon thread via botapi.BotAPI. /run <name> <rest of line> passes <rest of line> as arg
to a two-parameter run() -- e.g. /run fight wugang. Bots that only
take run(api) are called without it; existing single-argument bots
don't need to change.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import re
import sys
import threading
from pathlib import Path

import botapi

BOTS_DIR = Path(__file__).with_name("bots")
LOCAL_DIR = Path(__file__).resolve().parent
NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# The proxy's OWN machinery. These are load-bearing for the connection --
# triggers holds parsed config, ansi is in the relay path, botmanager is
# this file -- so reloading them mid-session risks dropping the very game
# session the reload exists to preserve. botapi is here because start()
# already reloads it separately, on purpose (see the comment there).
PROXY_MODULES = {"botproxy", "botmanager", "botapi", "triggers", "ansi",
                 "botui", "boteditor", "ai", "xyjbot"}


def is_helper(name, mod):
    """Is this a shared module a bot might import, and thus worth reloading?

    A bot's `import mudmap` is served from sys.modules, so re-executing the
    bot file rebinds the SAME module object -- which is why a fixed and
    tested mudmap.py kept crashing the fangcun bot with the old code. Any
    module sitting beside this file is fair game; the proxy's own are not.
    """
    if name in PROXY_MODULES or name.startswith("xyjbot_bot_"):
        return False
    path = getattr(mod, "__file__", None)
    if not path:
        return False
    try:
        return Path(path).resolve().parent == Path(LOCAL_DIR).resolve()
    except (OSError, ValueError):
        return False


class BotManager:
    def __init__(self, session):
        self.session = session
        # name -> (Thread, stop_event, BotAPI)
        self.running: dict[str, tuple] = {}

    def available(self):
        if not BOTS_DIR.exists():
            return []
        return sorted(p.stem for p in BOTS_DIR.glob("*.py"))

    def _load(self, name):
        if not NAME_RE.match(name):
            return None
        path = BOTS_DIR / f"{name}.py"
        if not path.exists():
            return None
        # Reload shared helpers BEFORE executing the bot, so the bot's own
        # imports bind current code whichever form they take -- `import
        # mudmap` and `from mudmap import route` alike. Doing it afterwards
        # would leave from-imports holding the old function objects.
        # Transitive by construction: every local module in sys.modules is
        # reloaded, not just the ones this bot names.
        for mod_name, mod in list(sys.modules.items()):
            if not is_helper(mod_name, mod):
                continue
            try:
                importlib.reload(mod)
            except Exception as e:
                self.session.note(f"{mod_name}.py 有错误，无法载入：{e}")
                return None

        # A fresh module_from_spec each time -- so /run after an edit
        # picks up the new code without a separate /reload step.
        spec = importlib.util.spec_from_file_location(f"xyjbot_bot_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def start(self, name, arg=None):
        if name in self.running:
            self.session.note(f"{name} 已经在跑了（先 /stop {name}）。")
            return
        mod = self._load(name)
        if mod is None:
            # _load explains a broken helper itself; only the missing-file
            # case is left for us to report.
            if not (BOTS_DIR / f"{name}.py").exists():
                self.session.note(f"找不到 bots/{name}.py。")
            return
        if not hasattr(mod, "run"):
            self.session.note(f"bots/{name}.py 里没有 run(api) 函数。")
            return

        nparams = len(inspect.signature(mod.run).parameters)
        if nparams >= 2:
            run_args = (arg,)
        else:
            if arg:
                self.session.note(f"{name} 不接受参数，忽略「{arg}」。")
            run_args = ()

        # Reload botapi too, so editing the API doesn't mean restarting
        # the proxy (which would drop the player's game session). Each
        # bot captures the BotAPI/Stopped pair from one reload, so a
        # thread stays self-consistent even if a later /run reloads again.
        try:
            api_mod = importlib.reload(botapi)
        except Exception as e:
            self.session.note(f"botapi.py 有错误，无法载入：{e}")
            return
        stop_event = threading.Event()
        api = api_mod.BotAPI(self.session, name, stop_event)
        stopped_exc = api_mod.Stopped

        def target():
            self.session.note(f"[{name}] 启动。")
            try:
                mod.run(api, *run_args)
                self.session.note(f"[{name}] 执行完毕。")
            except stopped_exc:
                self.session.note(f"[{name}] 已停止。")
            except Exception as e:  # bot script bug shouldn't kill the session
                self.session.note(f"[{name}] 出错停止：{e}")
            finally:
                self.running.pop(name, None)

        t = threading.Thread(target=target, daemon=True)
        self.running[name] = (t, stop_event, api)
        t.start()

    def stop(self, name):
        entry = self.running.get(name)
        if not entry:
            self.session.note(f"{name} 没有在跑。")
            return
        entry[1].set()

    def stop_all(self):
        for name in list(self.running):
            self.stop(name)

    def feed(self, line):
        for _, _, api in self.running.values():
            api.feed(line)

    def status(self):
        avail = self.available()
        if not avail:
            self.session.note("bots/ 目录里还没有任何 .py 机器人。用浏览器编辑器新建一个。")
            return
        for name in avail:
            state = "运行中" if name in self.running else "停止"
            self.session.note(f"[{state}] {name}")
