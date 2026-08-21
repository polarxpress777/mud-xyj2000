# study -- read a book until the skill hits a level cap.
#
# Run in-game with: /run study <等级上限>    e.g. /run study 30
#                   /run study              (no cap: read to the
#                                                book's own max_skill)
# Stop with:        /stop study
#
# You must be holding the book. It uses `study book`; if your book
# answers to a different id, change BOOK below or pass it as the second
# word: /run study 30 qian
#
# Cycle:
#   1. study <book>
#   2. "你的「X」进步了！" -> check `skills`, stop if X reached the cap
#   3. "你现在过于疲倦，无法专心下来研读新知。" -> walk to the nearest
#      sleep_room, sleep, then walk back and carry on
#   4. "你刚睡过一觉, 先活动活动吧。" -> wait SLEEP_RETRY and try again
#      (cmds/std/sleep.lpc:27 enforces 90s between sleeps)
#
# Room rules this respects, from the mudlib:
#   study.lpc:15-17  -- refuses in any no_fight or no_magic room
#   sleep.lpc:16-19  -- `sleep` only works in a room with sleep_room set

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mudmap

BOOK = "book"          # default id; most skill books answer to "book"
SLEEP_RETRY = 15       # seconds to wait on 你刚睡过一觉
MAX_FAILS = 3
STEP_PAUSE = 0.4

TIRED = "你现在过于疲倦，无法专心下来研读新知"
TOO_SOON = "你刚睡过一觉"
IMPROVED = r"你的「(.+?)」进步了"
WOKE = "你一觉醒来"
NOT_HERE = "你要读什么|你无法从这样东西学到任何东西"
WRONG_ROOM = "这里不是读书的地方"
TOO_SHALLOW = "太浅了，没有学到任何东西"
NO_GAIN = "你的武学修为还没到这个境界|你的道行还没到这个境界"


def skill_levels(api):
    """Run `skills` and return {中文名: level} plus {中文名: english_id}."""
    api.drain()
    api.send("skills", quiet=True)
    lines, deadline = [], __import__("time").time() + 6
    import time as _t
    while _t.time() < deadline:
        m = api.wait_line(r".+", timeout=1.0)
        if not m:
            if lines:
                break
            continue
        lines.append(m.string)

    levels, ids = {}, {}
    # "  基本棍法 (stick)      - 初学乍练     1/    0"
    for line in lines:
        m = re.search(r"(\S+)\s*\((\w[\w-]*)\)\s*-\s*\S+\s+(\d+)\s*/", line)
        if m:
            cn = m.group(1).lstrip("□ ").strip()
            levels[cn] = int(m.group(3))
            ids[cn] = m.group(2)
    return levels, ids


def find_sleep_and_return(api, rooms, cap_note=""):
    """Walk to the nearest sleep_room, sleep, walk back. Returns True if
    we slept (so studying can resume)."""
    blocked = set()
    pos = mudmap.locate(api, rooms)
    if not pos:
        api.log("认不出目前的位置，无法自动去睡觉。请手动走到有床的地方。")
        return False
    came_from = pos

    beds = mudmap.rooms_with_flag(rooms, "sleep_room")
    leg = mudmap.route(rooms, pos, beds, blocked)
    if leg is None:
        api.log("找不到能睡觉的地方（附近没有 sleep_room）。")
        return False
    if leg:
        api.log(f"精神不济，去最近的床（{len(leg)} 步）。")
        pos = mudmap.walk(api, rooms, pos, leg, blocked)
        if pos is None:
            api.log("路上走岔了，重新定位。")
            return False

    # sleep, honouring the 90s cooldown (sleep.lpc:27)
    for _ in range(8):
        if api.stopped():
            return False
        api.drain()
        api.send("sleep")
        m = api.wait_line(f"{WOKE}|{TOO_SOON}|这里不是睡觉的地方", timeout=90)
        if not m:
            api.log("睡觉没有反应，放弃这一轮。")
            return False
        if TOO_SOON in m.string:
            api.log(f"刚睡过，等 {SLEEP_RETRY} 秒再睡。")
            api.sleep(SLEEP_RETRY)
            continue
        if "不是睡觉的地方" in m.string:
            api.log("这里不能睡觉，重新找床。")
            return False
        api.log("睡醒了，精神恢复。")
        break
    else:
        return False

    # go back somewhere study is allowed
    ok = mudmap.studyable(rooms)
    if came_from in ok:
        back = mudmap.route(rooms, mudmap.locate(api, rooms) or came_from,
                            {came_from}, blocked)
        if back:
            api.log(f"回到原来的地方（{len(back)} 步）继续读书。")
            mudmap.walk(api, rooms, came_from, back, blocked)
    return True


def run(api, arg=None):
    rooms = mudmap.load()["rooms"]

    cap, book = None, BOOK
    if arg:
        parts = arg.split()
        if parts and parts[0].isdigit():
            cap = int(parts[0])
            parts = parts[1:]
        if parts:
            book = parts[0]
    api.log(f"开始读「{book}」" + (f"，上限 {cap} 级。" if cap else "（读到书的上限为止）。"))

    fails = 0
    reads = 0
    target_cn = None          # the skill this book teaches, learned from 进步了

    while not api.stopped():
        api.drain()
        api.send(f"study {book}", quiet=True)
        m = api.wait_line(
            f"{IMPROVED}|{TIRED}|{WRONG_ROOM}|{NOT_HERE}|{TOO_SHALLOW}|{NO_GAIN}"
            "|你正专心地研读|你现在正忙着呢",
            timeout=15)

        if not m:
            fails += 1
            api.log(f"study 没有反应（第 {fails} 次）。")
            if fails >= MAX_FAILS:
                api.log("连续失败，停止。确认你身上带着这本书。")
                return
            api.sleep(3)
            continue

        line = m.string
        fails = 0

        if re.search(NOT_HERE, line):
            api.log(f"身上没有「{book}」这本书，停止。")
            return

        if TOO_SHALLOW in line:
            api.log("这本书对你来说太浅了，学不到东西了，停止。")
            return

        if re.search(NO_GAIN, line):
            api.log("武学/道行不够，光读没用（需要先去实战积累），停止。")
            return

        if WRONG_ROOM in line:
            api.log("这里不能读书（no_fight/no_magic），先换个地方。")
            pos = mudmap.locate(api, rooms)
            if pos:
                leg = mudmap.route(rooms, pos, mudmap.studyable(rooms), set())
                if leg:
                    mudmap.walk(api, rooms, pos, leg, set())
            else:
                api.sleep(5)
            continue

        if TIRED in line:
            if not find_sleep_and_return(api, rooms):
                api.sleep(10)
            continue

        imp = re.search(IMPROVED, line)
        if imp:
            reads += 1
            target_cn = imp.group(1)
            levels, ids = skill_levels(api)
            lvl = levels.get(target_cn)
            api.log(f"「{target_cn}」进步了 -> {lvl} 级"
                    + (f"（上限 {cap}）" if cap else ""))
            if cap is not None and lvl is not None and lvl >= cap:
                api.log(f"「{target_cn}」已达 {lvl} 级，到达上限，停止。")
                return
            continue

        # 你正专心地研读 / busy -- just keep going
        api.sleep(1)
