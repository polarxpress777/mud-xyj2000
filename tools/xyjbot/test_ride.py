"""Tests for the horse, broken rooms, and getting into 红楼一梦.

Three live bugs:
  * 红楼一梦 was unreachable. enter_dream() waited for 进入了梦的世界,
    which pillow.lpc:26 tell_object()s to the ROOM rather than to the
    player, so nobody ever sees it. What the player actually gets is the
    dream room itself (sleep.lpc:195 -> d/ourhome/honglou/kat).
  * a room whose .lpc doesn't compile (d/moon/bedroom.lpc had an @LONG
    block closed on the same line as the text) dumps a driver traceback
    and leaves you standing still -- a permanent defect, not a gate.
  * sleep.lpc:79 puts you off your horse before the dream, and go.lpc:76
    refuses the whole move when the mount can't follow, so a mounted bot
    reads good exits as walls.

Run with: python3 test_ride.py
"""
import importlib.util, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("bot", HERE / "bots/changan-mieyao-bot.py")
bot = importlib.util.module_from_spec(spec); spec.loader.exec_module(bot)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def reset():
    bot.BROKEN_EXITS.clear()
    bot.RIDE.update(want=False, on=False, name="", left_at=None,
                    fell_off=False)


ROOMS = {
    "d/city/kezhan": {"short": "南城客栈", "area": "d/city", "flags": {},
                      "exits": {"east": "d/city/sleep"}},
    "d/city/sleep": {"short": "客店睡房", "area": "d/city", "flags": {},
                     "exits": {"west": "d/city/kezhan"}},
    "d/ourhome/honglou/kat": {"short": "荡悠悠三更梦", "area": "d/ourhome/honglou",
                              "flags": {}, "exits": {"up": "d/ourhome/honglou/pavilion"}},
}


class FakeAPI:
    def __init__(self, script=None, replies=None):
        self.script = list(script or [])     # lines the next `sleep` yields
        self.replies = dict(replies or {})   # command -> lines
        self.pending, self.logs, self.sent = [], [], []

    def stopped(self): return False
    def drain(self): self.pending = []
    def log(self, m): self.logs.append(m)
    def sleep(self, n): pass

    def wait_line(self, pattern, timeout=10.0):
        rx = re.compile(pattern)
        while self.pending:
            m = rx.search(self.pending.pop(0))
            if m:
                return m
        return None

    def send(self, cmd, quiet=False):
        self.sent.append(cmd)
        if cmd == "sleep":
            self.pending = list(self.script)
        else:
            self.pending = list(self.replies.get(cmd, []))

    def said(self, needle):
        return any(needle in m for m in self.logs)


print("a compile error behind an exit is remembered for the whole session")
reset()
api, blocked = FakeAPI(), set()
crash = ("编译时段错误: /d/moon/bedroom.lpc:42:1: error: End of file in text block\n"
         "执行时段错误: *No program in object '/d/moon/bedroom'!")
check("reported as broken",
      bot.note_step_failure(api, blocked, "d/moon/rain", "up", crash), True)
check("exit blocked for this job", ("d/moon/rain", "up") in blocked, True)
check("and for every later one", ("d/moon/rain", "up") in bot.BROKEN_EXITS, True)
check("said what's wrong", api.said("编译不过"), True)
before = len(api.logs)
bot.note_step_failure(api, blocked, "d/moon/rain", "up", crash)
check("doesn't repeat itself", len(api.logs), before)

print("\nan ordinary shut exit is only blocked for this job")
reset()
api, blocked = FakeAPI(), set()
check("not broken", bot.note_step_failure(api, blocked, "d/city/kezhan", "east",
                                          "店小二拦住你说：客官，先付店钱吧。"), False)
check("blocked now", ("d/city/kezhan", "east") in blocked, True)
check("but not forever", bot.BROKEN_EXITS, set())

print("\nmount state is read off each arrival, no polling")
reset()
api = FakeAPI()
bot.RIDE.update(want=True, on=False, name="黑马")
bot.ride_note(api, "客店睡房 - d/city/sleep\n你骑着黑马走了过来。", "d/city/kezhan")
check("on the horse", bot.RIDE["on"], True)
bot.ride_note(api, "南城客栈 - d/city/kezhan\n你走了过来。", "d/city/sleep")
check("off it again", bot.RIDE["on"], False)
check("and we know where it is", bot.RIDE["left_at"], "d/city/sleep")
check("said so once", api.said("黑马"), True)

print("\nmounting: success, already-on, and no horse at all")
reset()
api = FakeAPI(replies={"mount horse": ["你潇洒地一个纵身，稳稳地骑在黑马上！"]})
check("mounted", bot.ride_mount(api), True)
check("remembers the name", bot.RIDE["name"], "黑马")
check("and that we ride", bot.RIDE["want"], True)

reset()
api = FakeAPI(replies={"mount horse": ["你已经骑在黑马上了！"]})
check("a missed 你骑着 line self-corrects", bot.ride_mount(api), True)
check("on", bot.RIDE["on"], True)

reset()
api = FakeAPI(replies={"mount horse": ["你想骑什么？"]})
check("no horse -> no fuss", bot.ride_mount(api), False)
check("doesn't start wanting one", bot.RIDE["want"], False)

print("\nride_recover only goes back for a horse it knows the room of")
reset()
api = FakeAPI()
check("nothing to fetch", bot.ride_recover(api, ROOMS, set()), False)
bot.RIDE.update(want=True, on=False, name="黑马", left_at="d/nowhere")
check("unknown room, no walk", bot.ride_recover(api, ROOMS, set()), False)
check("no commands sent", api.sent, [])

print("\na mount that can't follow gets left behind, not read as a wall")
reset()
bot.RIDE.update(want=True, on=True, name="黑马")


class GateAPI(FakeAPI):
    """go.lpc:76 refuses the whole move while the horse can't pass; on
    foot the same exit works."""
    mounted = True

    def send(self, cmd, quiet=False):
        self.sent.append(cmd)
        if cmd == "dismount horse":
            self.mounted = False
            self.pending = ["你挺身从黑马上跃下来。"]
        elif cmd == "enter":
            self.pending = (["你的座骑走动不了。"] if self.mounted else
                            ["普陀山 - d/nanhai/gate", "这里明显的出口是 out。"])
        else:
            self.pending = []


api = GateAPI()
title, _, text = bot.step_full(api, "enter")
check("got through on foot", title, "普陀山")
check("got off first", api.sent, ["enter", "dismount horse", "enter"])
check("knows it's on foot", bot.RIDE["on"], False)

# The walker calls ride_note() after every step. This is the whole point
# of getting off: the horse is still standing in the room we came FROM,
# and ride_recover() can only go back for it if that room was recorded.
bot.ride_note(api, text, "d/nanhai/road")
check("and remembers where the horse is", bot.RIDE["left_at"], "d/nanhai/road")

print("\nsleep -> 红楼一梦 is detected by the dream room, not by a line "
      "nobody prints")
reset()
bot.RIDE.update(want=True, on=True, name="黑马")
api = FakeAPI(script=["你往被中一钻，开始睡觉。",
                      "不一会儿，你就进入了梦乡。",
                      "",
                      "荡悠悠三更梦 - /d/ourhome/honglou/kat",
                      "　　　　枯藤，老树，昏鸦……",
                      "这里唯一的出口是 up。"])
check("in the dream", bot.sleep_into_dream(api, ROOMS), True)
check("horse left behind, and noted", bot.RIDE["left_at"], "d/city/sleep")
check("off the horse", bot.RIDE["on"], False)
check("names the room it's in", api.said("客店睡房"), True)

print("\nthe pillow not firing is a failure, not a hang")
reset()
api = FakeAPI(script=["你往被中一钻，开始睡觉。", "不一会儿，你就进入了梦乡。",
                      "你一觉醒来，只觉精力充沛。该活动一下了。"])
check("reported", bot.sleep_into_dream(api, ROOMS), False)
check("said why", api.said("没能入梦"), True)

print("\nrefusals come back immediately instead of waiting out SLEEP_WAIT")
reset()
api = FakeAPI(script=["你刚睡过一觉, 先活动活动吧。"])
check("refused", bot.sleep_into_dream(api, ROOMS), False)
reset()
api = FakeAPI(script=["这里不是睡觉的地方。"])
check("wrong room", bot.sleep_into_dream(api, ROOMS), False)

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
