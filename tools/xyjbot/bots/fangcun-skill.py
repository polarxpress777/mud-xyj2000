# fangcun-skill -- grind every skill one teacher can teach, evenly.
#
#   /run fangcun-skill puti 30          学到 30 级
#   /run fangcun-skill 云静 50
#   /stop fangcun-skill
#
# Cycle: learn the LOWEST skill that is still under the cap -> when 精神 runs
# low, sleep in 卧室 -> refill in 厨房 -> walk back to the teacher -> repeat.
#
# Two facts from the mudlib shape all of this:
#
#   * cmds/std/learn.lpc:31 refuses anyone who is not the teacher's
#     apprentice, so the bot checks the teacher's 门派 against yours BEFORE
#     starting and stops if they differ. It never joins a sect for you.
#   * learning is bounded by 潜能 - learned_points (learn.lpc:74). Sleeping
#     restores 精神 and 法力 but NOT 潜能 (cmds/std/sleep.lpc wakeup1), so
#     潜能 is a hard budget: when it runs out the bot stops rather than
#     looping forever.
#
# Round-robin, not depth-first: each pass trains whichever teachable skill
# is currently lowest, so they rise together instead of one skill eating the
# whole 潜能 budget.
import json
import re
import time
from pathlib import Path

import mudmap

TEACHERS = Path(__file__).resolve().parent.parent / "teachers.json"

SLEEP_ROOM = "d/lingtai/sleep"        # 卧室 -- the only sleep_room in 方寸山
KITCHEN = "d/lingtai/inside4"         # 厨房 -- 万丰, a 青葫芦, and `yao`

LEARN_BATCH = 5        # repetitions per `learn`; small keeps the rotation even
SEN_FLOOR = 30         # % of 精神 below which learning stalls -- go sleep
FOOD_FLOOR = 40        # % of 食物/饮水 below which we top up in the 厨房

# cmds/usr/skills.lpc:52-59 -- "  基本功夫 (unarmed)  - 初学乍练   12/  144"
SKILL_RE = re.compile(r"\(([a-z][a-z0-9_-]*)\).*?(\d+)\s*/\s*(\d+)\s*$")

# learn.lpc's refusals, and what each one means for the loop
CANT_TEACH = "这项技能你恐怕必须找别人学了"     # teacher lacks it -- skip forever
NO_POTENTIAL = "你的潜能已经发挥到极限了"       # terminal: sleep won't help
NOT_APPRENTICE = "您太客气了|这怎么敢当|指点"    # not their apprentice
TOO_HARD = "依你目前的能力"                    # can't learn this yet


def teacher_family(name):
    """The 门派 of whoever the player named, from teachers.json."""
    if not TEACHERS.exists():
        return None
    table = json.loads(TEACHERS.read_text(encoding="utf-8"))
    key = name.strip().lower()
    return table.get(key) or table.get(key.replace(" ", ""))


def read_block(api, timeout=4.0):
    """Collect one command's reply."""
    lines, deadline = [], time.time() + timeout
    while time.time() < deadline:
        m = api.wait_line(r".+", timeout=1.0)
        if not m:
            if lines:
                break
            continue
        lines.append(m.string)
    return "\n".join(lines)


def my_skills(api):
    """{skill id: level} from the `skills` command."""
    api.drain()
    api.send("skills", quiet=True)
    out = {}
    for line in read_block(api).splitlines():
        m = SKILL_RE.search(line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def sect_ok(api, name):
    """Refuse to start unless the teacher shares the player's 门派.

    cmds/usr/title.lpc:14 prints 你目前的头衔及门派 followed by the rank and
    short(1), which carries the sect -- so one `title` answers it.
    """
    entry = teacher_family(name)
    if not entry:
        api.log(f"teachers.json 里没有「{name}」这个人。"
                "先跑 python3 build_index.py，或换个名字试试。")
        return False

    api.drain()
    api.send("title", quiet=True)
    title = read_block(api)
    family = entry["family"]
    # The stored family string and the displayed one differ in length
    # (方寸山三星洞 vs 方寸山), so match either way round.
    if not (family in title or any(part and part in title
                                   for part in (family[:3], family[-3:]))):
        api.log(f"{entry['name']} 是「{family}」的人，你的头衔是：\n"
                f"    {title.strip().splitlines()[-1] if title.strip() else '(读不到)'}\n"
                "不同门派学不了（learn.lpc:31 要先拜师）。这个机器人不会替你拜师，停。")
        return False
    api.log(f"{entry['name']}（{family}）和你同门，开始。")
    return True


def status_pct(api):
    st = api.status()
    def pct(a, b):
        return (st[a] * 100 // st[b]) if st.get(b) else 100
    return pct("sen", "max_sen"), pct("food", "max_food"), pct("water", "max_water")


def learn_once(api, skill, teacher):
    """One `learn` batch. Returns 'ok', 'cant', 'spent', 'blocked' or 'tired'."""
    api.drain()
    api.send(f"learn {skill} from {teacher} for {LEARN_BATCH}", quiet=True)
    reply = read_block(api, 6.0)
    if CANT_TEACH in reply:
        return "cant"
    if NO_POTENTIAL in reply:
        return "spent"
    if re.search(NOT_APPRENTICE, reply) or TOO_HARD in reply:
        return "blocked"
    if "精神" in reply and ("不够" in reply or "太差" in reply):
        return "tired"
    return "ok"


def next_skill(skills, cap, unteachable=()):
    """The skill to train next: the LOWEST one still under the cap.

    This is what "learn them equally" means in practice -- always topping up
    the laggard keeps the set level, where training whichever came first
    would sink the whole 潜能 budget into one skill. Ties break by name so
    the rotation is stable rather than dependent on dict order.

    Returns None when everything teachable is at the cap.
    """
    todo = {s: lv for s, lv in skills.items()
            if lv < cap and s not in unteachable}
    return min(todo, key=lambda s: (todo[s], s)) if todo else None


def go(api, rooms, dest, label):
    """Walk somewhere, re-locating first. Returns True on arrival."""
    pos = mudmap.locate(api, rooms)
    if not pos:
        api.log("认不出现在在哪，等一下再试。")
        return False
    if pos == dest:
        return True
    leg = mudmap.route(rooms, pos, {dest})
    if not leg:
        api.log(f"走不到{label}。")
        return False
    api.log(f"前往{label}（{len(leg)} 步）…")
    return bool(mudmap.walk(api, rooms, pos, leg, set()))


def refill(api, rooms):
    """厨房: `yao` for 包子, drink the 青葫芦, eat, then drop the leftovers.

    The 葫芦 (d/ourhome/obj/hulu) already holds 40 units of 清水 at 20 a sip,
    so it is drunk from directly rather than filled. 万丰's `yao` makes TWO
    包子 (npc/wanfeng.lpc:36-37), and anything uneaten is dropped before
    leaving so the character does not carry food around.
    """
    if not go(api, rooms, KITCHEN, "厨房"):
        return False
    for cmd in ("get hulu", "drink hulu", "drink hulu", "drop hulu",
                "yao", "eat bao", "eat bao"):
        api.drain()
        api.send(cmd, quiet=True)
        read_block(api, 2.0)
    api.drain()
    api.send("drop bao", quiet=True)      # leave nothing in the pack
    read_block(api, 2.0)
    sen, food, water = status_pct(api)
    api.log(f"厨房补给完毕：食物 {food}%、饮水 {water}%。")
    return True


def rest(api, rooms):
    """卧室 is the only sleep_room in 方寸山. Sleeping restores 精神."""
    if not go(api, rooms, SLEEP_ROOM, "卧室"):
        return False
    api.drain()
    api.send("sleep", quiet=True)
    api.wait_line("一觉醒来|进入了梦乡|这里不是睡觉的地方|你刚睡过一觉", timeout=90)
    read_block(api, 3.0)
    sen, _, _ = status_pct(api)
    api.log(f"睡醒了，精神 {sen}%。")
    return True


def run(api, arg=None):
    parts = (arg or "").split()
    if len(parts) < 2 or not parts[-1].isdigit():
        return api.log("用法：/run fangcun-skill <师父> <等级上限>"
                       "  例：/run fangcun-skill puti 30")
    cap = int(parts[-1])
    teacher = " ".join(parts[:-1])

    if not sect_ok(api, teacher):
        return

    rooms = mudmap.load()
    if not rooms:
        return api.log("找不到 rooms.json，先跑 python3 build_map.py。")

    home = mudmap.locate(api, rooms)
    api.log(f"师父在「{rooms[home]['short'] if home in rooms else '这里'}」，"
            f"目标：所有能学的技能到 {cap} 级。")

    unteachable, rounds = set(), 0
    while not api.stopped():
        skills = my_skills(api)
        skill = next_skill(skills, cap, unteachable)
        if skill is None:
            api.log(f"能学的技能都到 {cap} 级了，收工。")
            return
        result = learn_once(api, skill, teacher)
        rounds += 1

        if result == "cant":
            unteachable.add(skill)
            api.log(f"{teacher} 教不了 {skill}，跳过。")
            continue
        if result == "spent":
            api.log("潜能用完了。睡觉不会恢复潜能（只恢复精神法力），"
                    "得先去打怪挣潜能。停。")
            return
        if result == "blocked":
            api.log(f"学不了 {skill} —— 可能还没拜师，或者能力不够。停。")
            return

        if result == "tired" or rounds % 6 == 0:
            sen, food, water = status_pct(api)
            if result == "tired" or sen < SEN_FLOOR:
                api.log(f"精神 {sen}%，去睡一觉。")
                if not rest(api, rooms):
                    return
                if min(food, water) < FOOD_FLOOR and not refill(api, rooms):
                    return
                if not go(api, rooms, home, "师父那儿"):
                    return
                api.log(f"回来了，继续练 {skill}。")
