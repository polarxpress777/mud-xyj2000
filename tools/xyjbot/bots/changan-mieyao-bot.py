# changan-mieyao-bot -- 长安 灭妖 quest runner with auto-walk,
# retreat, and automatic return to 袁天罡.
#
# Run in-game with: /run changan-mieyao-bot
# Stop with:        /stop changan-mieyao-bot
# Stand with 袁天罡 (yuan) in 长安天监台 when you start it.
#
# Cycle:
#   1. ask 袁天罡 for a job; parse the target's name/id and the AREA
#      (d/city/npc/yuantiangang.lpc -> MISC_D->find_place returns an
#      area label like 长安城, not a room)
#   2. WALK that area room by room, looking for the target. Uses
#      rooms.json, built by build_map.py from the mudlib's own exits.
#   3. kill it when found, watching combat status the whole time
#   4. if hurt past RETREAT_AT, break off, run away, rest to full, then
#      resume the search where it left off
#   5. walk itself back to 天监台, then top up 食物/饮水 if either has
#      dropped under half -- drink jiudai / eat gou rou from inventory,
#      restocking from 店小二 in 南城客栈 (via 相记钱庄 if out of cash)
#   6. take the next job (waiting out 袁天罡's 5-10 minute post-success
#      cooldown if he's still thanking you)
#
# Why step 5 exists: 饮水 at 0 doesn't slow 气血 regen, it stops it
# (feature/damage.lpc:465), so a thirsty bot rests forever at whatever
# percentage it fled with.
#
# Position tracking: the bot doesn't get told where it is, so it
# localises from `look` output -- room title plus the exit list -- and
# re-localises whenever a move lands somewhere unexpected (wandering
# monsters, teleports, blocked exits all cause that).

import json
import re
import time
from collections import deque
from pathlib import Path

MAP_FILE = Path(__file__).resolve().parent.parent / "rooms.json"

# Rooms the walker must never enter or route through, by room title.
# Empty now: 紫竹林 used to be here, but escape_maze() gets out reliably
# (100% over 12k simulated runs, p99 29 moves), so the grove is searched
# like anywhere else rather than conceded.
AVOID_ROOMS = set()

# Mazes: rooms whose exits are randomised at create() time, so the static
# map is useless inside them -- d/nanhai/zhulin*.lpc builds every looping
# exit as "zhulin" + sprintf("%d", random(6)), which build_map records as
# a nonexistent "d/nanhai/zhulin". BFS can route to the entrance
# (road4 north -> zhulin0, pool south -> zhulin15) but not within, so
# these get swept by probing instead of pathing.
MAZE_ROOMS = {"紫竹林"}

# 天监台 -- where 袁天罡 stands. The bot walks back here after every job.
YUAN_ROOM = "d/city/tianjiantai"

# Wipe every skill after each successful kill. Combat raises skills on
# its own (combatd.lpc:497), and monster difficulty scales off your
# highest skill, so leaving them to accumulate makes the grind harder
# with every quest. Set False to keep whatever you pick up.
ABANDON_SKILLS_AFTER_KILL = True

# --- food and water -----------------------------------------------------
# 饮水 gates 气血 regen outright: feature/damage.lpc:465 returns from
# heal_up() BEFORE touching kee when water hits 0, and :464 does the same
# for 食物 before 精神/法力. A thirsty character therefore heals not
# slowly but NOT AT ALL, which is what wedged rest_until_healed() in an
# endless "休息中…" loop at 50% 气血.
#
# Both are topped up from inventory (drink jiudai / eat gou rou) and
# restocked from 店小二 in 南城客栈, with a stop at 相记钱庄 for cash
# first. All three rooms are inside 长安城, four steps from 天监台.
KEZHAN_ROOM = "d/city/kezhan"    # 南城客栈 -- 店小二 sells 桂花酒袋/红烧狗肉
BANK_ROOM = "d/city/bank"        # 相记钱庄 -- account/withdraw
VENDOR = "xiaoer"

SUSTENANCE_AT = 50     # % of capacity: below this on 食物 OR 饮水, resupply
SUSTENANCE_TO = 90     # % of capacity to top back up to

# /d/moon/obj/jiudai and /d/ourhome/obj/gourou, "value" in 文.
# 100 文 = 1 两银子; buy.lpc wants `buy <key> from <someone>`, where the
# key is 店小二's vendor_goods key, not the item's Chinese name.
JIUDAI_PRICE = 100
GOUROU_PRICE = 100
WITHDRAW_SILVER = 10   # 1000 文 -- five of each, so one trip lasts

# 桂花酒袋 is alcohol: liquid.lpc:60 gives +30 水 a sip but also +5 to the
# `drunk` condition. daemon/condition/drunk.lpc knocks you out past
# con*6 + max_force/50 (124 for this character) and chips 精神 past a
# tenth of that, so sips are capped -- topping 饮水 up from empty needs
# only four anyway.
MAX_SIPS = 5
MAX_BITES = 8          # 红烧狗肉 is 2 bites x 100 食物; a cap, not a target

QUEST_SECS = 1800      # yuantiangang.lpc:127 -- 30 min per job
STEP_PAUSE = 0.6       # seconds between movement commands

# Walking to a named room (天监台, 南城客栈, 相记钱庄). The longest
# legitimate route home on the map is 90 steps (d/qujing/jindou/shanlu6),
# so the budget is that plus room for detours around gated exits; it
# exists to bound a walk that is drifting, not to cut a real one short.
WALK_MAX_STEPS = 150
WALK_MAX_LOST = 8      # give up after this many unrecognisable positions
FIGHT_TIMEOUT = 180
REST_POLL = 30         # seconds between hp checks while resting
HP_RESUME = 95         # % of max 气血 required before hunting again
REST_STALL_LIMIT = 4   # consecutive polls with no 气血 gain before giving up

# combatd.lpc:187-198 status_msg() ladder, worst-first. Anything at or
# below RETREAT_AT means break off the fight NOW.
WOUNDED = [
    "已经陷入半昏迷状态",          # <=10%
    "摇头晃脑、歪歪斜斜",          # <=20%
    "看起来已经力不从心了",        # <=30%
    "已经一副头重脚轻的模样",      # <=30%
    "似乎十分疲惫，看来需要好好休息",  # <=40%
]
RETREAT_RE = "|".join(WOUNDED)

ASSIGN_RE = r"近有(.+?)\(([A-Za-z ]+)\)在(.+?)出没"
REWARD_RE = r"你得到了(.+?)点武学经验和(.+?)点潜能"
# The mud varies this line: 这里明显的出口是… for several exits but
# 这里唯一的出口是… when there's only one. Matching only 明显的 made every
# single-exit room parse as "no exits", which silently disabled the exit
# filter during localisation and stranded the walker.
EXITS_RE = r"这里[^出\n]{0,6}出口是\s*(.+?)。"
DEAD_RE = r"惨叫一声，死了|死了。"
# yuantiangang.lpc:146 -- after a success he just thanks you until the
# cooldown lapses: 300s, or 600s once (daoxing+combat_exp)/2 > 20000.
# Not a failure; just wait it out and ask again.
DONE_COOLDOWN = "妖魔已经除尽了"

# A third party joining the fight. feature/attack.lpc:61 prints
# 看起来<名字>想杀死你！ when anything targets you, and cmds/std/kill.lpc:66
# prints <名字>对着你喝道：「…今日不是你死就是我活！」. Wandering
# aggressive NPCs (马盗 and friends) do this mid-fight and will happily
# finish off a character built to fight only floor-level 妖怪.
INTRUDER_RE = r"看起来(.+?)想杀死你|(.+?)对着你喝道"
INTRUDER_WAIT = 45     # seconds to sit one room away before peeking back
INTRUDER_TRIES = 6     # how many times to peek before giving up on the job
COOLDOWN_WAIT = 60     # seconds between re-asks while he's still thanking you


# ---------------------------------------------------------------- map --
def load_map(api):
    if not MAP_FILE.exists():
        api.log(f"找不到 {MAP_FILE.name}，请先跑：python3 build_map.py")
        return None
    return json.loads(MAP_FILE.read_text(encoding="utf-8"))


def parse_exits(text):
    """Pull direction names out of 这里明显的出口是 west、north 和 south。"""
    m = re.search(EXITS_RE, text)
    if not m:
        return set()
    body = re.sub(r"[、和，,]", " ", m.group(1))
    return {w for w in body.split() if re.fullmatch(r"[a-z]+", w)}


def read_room(api, timeout=4):
    """Collect one room description. Returns (title, exit_set, text).

    Returning the FULL text matters: this drains every queued line,
    including the room's contents list where the target monster would be
    named. Callers must scan the returned text for the target themselves
    -- an earlier version threw the text away and the bot walked
    straight past monsters it had already been shown.

    The title line is the one containing ' - ' (the mud prints
    '南城客栈 - /d/city/kezhan'); a blocked move prints a notify_fail
    with no such line, which is how we detect not having moved.
    """
    lines, deadline = [], time.time() + timeout
    while time.time() < deadline:
        m = api.wait_line(r".+", timeout=1.0)
        if not m:
            if lines:
                break
            continue
        lines.append(m.string)
        if "出口是" in m.string:
            # Room CONTENTS are printed after the exits line, so stopping
            # here loses exactly what we care about (the target monster,
            # or an intruder we're waiting out). Keep reading briefly.
            grace = time.time() + 1.2
            while time.time() < grace:
                extra = api.wait_line(r".+", timeout=0.4)
                if not extra:
                    break
                lines.append(extra.string)
            break
    text = "\n".join(lines)
    title = ""
    for line in lines:
        if " - " in line:
            # The prompt has no trailing newline, so the room title often
            # arrives glued to it as "> 天监台 - ...". Strip it, or
            # localisation looks up a room called "> 天监台".
            title = line.split(" - ")[0].lstrip("> ").strip()
            break
    return title, parse_exits(text), text


def look(api, timeout=6):
    api.drain()
    api.send("look", quiet=True)
    return read_room(api, timeout)


def step(api, direction):
    """Move one room. Returns (title, text); title is '' if we didn't
    move (blocked exit, door, sect check, encumbrance).

    Closed doors are opened and the move retried: std/room.lpc:199-216
    refuses with 你必须先把<门名>打开！, and cmds/std/open.lpc:18 accepts
    the direction itself as the target. Without this the walker marks
    the exit permanently impassable and routes the long way round -- or
    gives up, since the only ways into 方寸山 (d/lingtai/gate.lpc) and
    普陀山 (d/nanhai/gate.lpc) are behind closed 石门.
    """
    api.drain()
    api.send(direction, quiet=True)
    title, _, text = read_room(api)

    if not title and "必须先把" in text and "打开" in text:
        api.log(f"{direction} 有扇门关着，先开门。")
        api.drain()
        api.send(f"open {direction}", quiet=True)
        api.wait_line(r"打开|你要打开什么", timeout=4)
        api.drain()
        api.send(direction, quiet=True)
        title, _, text = read_room(api)

    return title, text


# --- maze escape ----------------------------------------------------------
# 紫竹林 (d/nanhai/zhulin*.lpc) can't be pathed with the static map: every
# looping exit is `"zhulin" + sprintf("%d", random(6))`, evaluated at
# create() time, so build_map records a nonexistent "d/nanhai/zhulin".
# The structure is knowable though:
#   zhulin0  south -> road4     (the way out)
#   zhulin15 north -> pool
#   zhulin16/17 enter -> 罗汉堂
#   zhulin1-14  loop back inside, always to zhulin0-5
# Since every random exit lands in zhulin0-5, and zhulin0 is one of them,
# wandering reaches the exit room in a handful of moves. So: try the known
# ways out, otherwise shuffle and try again.
MAZE_EXITS = ("south", "north", "enter")


def sweep_maze(api, maze_name, name, mid, max_moves=80):
    """Wander a randomised maze looking for the quest target.

    Returns "found" if the target turned up (caller should fight it),
    "clear" if the maze was swept without finding it, or "" if we got
    stuck. Either way the caller should re-localise afterwards -- we have
    no reliable position inside.
    """
    api.log(f"{maze_name}是随机迷宫，改用地毯式搜索找 {name}。")
    for _ in range(max_moves):
        if api.stopped():
            return ""
        title, exits, text = look(api)
        if name in text or mid in text.lower():
            api.log(f"在{maze_name}里发现 {name}！")
            return "found"
        if title and title != maze_name:
            return "clear"          # wandered out on our own
        moved = False
        for d in list(MAZE_EXITS) + list(exits):
            if d not in exits:
                continue
            got, gtext = step(api, d)
            api.sleep(STEP_PAUSE)
            if not got:
                continue
            moved = True
            if name in gtext or mid in gtext.lower():
                api.log(f"在{maze_name}里发现 {name}！")
                return "found"
            if got != maze_name:
                return "clear"      # stepped out of the maze
            break
        if not moved:
            return ""
    api.log(f"{maze_name}搜完了没找到 {name}，先出去。")
    return "clear"


def escape_maze(api, maze_name="紫竹林", max_moves=80):
    """Get out of a randomised maze by probing rather than pathing.

    Returns the room title we ended up in, or "" if we never got out.
    """
    api.log(f"发现自己在{maze_name}里，开始找出口。")
    for move in range(max_moves):
        if api.stopped():
            return ""
        title, exits, _ = look(api)
        if title and title != maze_name:
            api.log(f"已走出{maze_name}，现在在「{title}」。")
            return title

        # Known ways out first.
        tried = False
        for d in MAZE_EXITS:
            if d not in exits:
                continue
            tried = True
            got, _ = step(api, d)
            api.sleep(STEP_PAUSE)
            if got and got != maze_name:
                api.log(f"从 {d} 走出{maze_name}，现在在「{got}」。")
                return got
            if got:
                break        # moved, still inside -- re-read and retry

        # No known exit here: shuffle deeper. Every looping exit lands in
        # zhulin0-5, and zhulin0 is the one with the way out.
        if not tried:
            for d in exits:
                got, _ = step(api, d)
                api.sleep(STEP_PAUSE)
                if got:
                    break

    api.log(f"走了 {max_moves} 步还没出{maze_name}，放弃，请手动走出来。")
    return ""


def avoided(rooms, path):
    return rooms.get(path, {}).get("short") in AVOID_ROOMS


def travel(rooms, start, goals, blocked=frozenset()):
    """Shortest path across the WHOLE map, ignoring area boundaries.

    Used to get from wherever you are to the area the monster is in --
    bfs() deliberately stays inside `dirs` while sweeping an area, but
    reaching that area in the first place has to cross them.
    """
    if start in goals:
        return []
    seen, q = {start}, deque([(start, [])])
    while q:
        cur, path = q.popleft()
        for d, nxt in rooms.get(cur, {}).get("exits", {}).items():
            if (cur, d) in blocked or nxt in seen or nxt not in rooms:
                continue
            if avoided(rooms, nxt):
                continue
            seen.add(nxt)
            step = path + [(d, nxt)]
            if nxt in goals:
                return step
            q.append((nxt, step))
    return None


def candidates(rooms, dirs, title, exits):
    """Rooms in the searched area matching what we can see.

    Exits are matched as a SUBSET, not for equality: rooms hide exits
    behind conditions (valid_leave, doors, sect checks), so what `look`
    prints can be a strict subset of what the source declares. Demanding
    equality made 南城客栈 unlocalisable in live testing.
    """
    # Without a room title we know nothing -- returning "every room in
    # the area" lets the caller silently pick a wrong one and strand the
    # walker, which is exactly what happened in live testing.
    if not title:
        return []

    exact, loose = [], []
    for path, r in rooms.items():
        if dirs is not None and r["area"] not in dirs:
            continue
        # A room whose short name we failed to parse must never act as a
        # wildcard that matches every title -- that put the walker in a
        # exit-less room and left it looping "走不到未搜索的房间".
        if r["short"] != title:
            continue
        declared = set(r["exits"])
        if exits and not exits <= declared:
            continue
        (exact if exits == declared else loose).append(path)
    return exact + loose


def signature(rooms, path):
    """What a room looks like from the doorway: title plus declared
    exits. Two rooms with the same signature are indistinguishable to
    the bot, which is the whole reason recalibration is needed."""
    r = rooms.get(path)
    return (r["short"], frozenset(r["exits"])) if r else ("", frozenset())


def probe_dir(rooms, cands, tried=()):
    """The exit worth stepping through to tell `cands` apart.

    Prefers a direction every candidate declares -- stepping somewhere
    only some of them have would fail for the others and teach us
    nothing -- and among those, the one whose destinations look most
    different from each other.
    """
    sets = [set(rooms[p]["exits"]) for p in cands]
    pool = (set.intersection(*sets) - set(tried)) or (set.union(*sets) - set(tried))
    best, best_n = None, 0
    for d in sorted(pool):
        sigs = {signature(rooms, rooms[p]["exits"].get(d)) for p in cands}
        if len(sigs) > best_n:
            best, best_n = d, len(sigs)
    return best


def relocalise(api, rooms, dirs=None, max_probes=14):
    """Work out which room we're actually in, probing when the title is
    ambiguous. Returns the room we are standing in AFTER any probing (we
    move while doing it), or None if it stayed ambiguous.

    长安以东 is five rooms all called 大官道 with identical west/east
    exits, so `look` cannot tell them apart and taking candidates[0] was
    a one-in-five guess. Guessing wrong makes the next move land
    somewhere the map didn't predict, which triggers another guess --
    the observed dongmen -> 大官道 -> dongmen -> ... loop.

    The fix is how a robot localises: hold the whole candidate set, step
    through an exit they all share, and drop every candidate whose map
    neighbour in that direction doesn't match the room we actually
    arrived in. A corridor of identical rooms collapses to one candidate
    as soon as the walk reaches either end.

    max_probes is 14 because the longest ambiguous run on the map is
    小雁塔内 -- fifteen storeys, each titled identically with up/down
    exits, so it takes fourteen flights to reach one that looks
    different. If probing still leaves a tie the best remaining
    candidate is returned WITH a warning rather than None: callers
    answer None by looking again in ten seconds, which for a genuinely
    indistinguishable room is the old hang wearing a different hat.
    """
    title, exits, _ = look(api)
    if title in AVOID_ROOMS:
        title = escape_maze(api, title)
        if not title:
            return None
        title, exits, _ = look(api)

    cands = candidates(rooms, dirs, title, exits)
    if not cands:
        return None

    tried = []
    for _ in range(max_probes):
        if len(cands) == 1:
            return cands[0]
        if api.stopped():
            return None
        direction = probe_dir(rooms, cands, tried)
        if not direction:
            break
        api.log(f"「{title}」有 {len(cands)} 间同名房间，"
                f"往 {direction} 走一步确认是哪一间。")
        arrived, text = step(api, direction)
        api.sleep(STEP_PAUSE)
        if not arrived:
            # Gated exit: it told us nothing about which room we're in,
            # so keep the candidate set and try a different direction.
            tried.append(direction)
            continue

        seen = parse_exits(text)
        moved = [rooms[p]["exits"][direction] for p in cands
                 if direction in rooms[p]["exits"]]
        # Exact-then-loose, for the same reason candidates() does it: a
        # room can hide exits behind a condition, so a subset match has
        # to stay legal -- but preferring equality first is what tells
        # 泾水之滨's dead end (only `west`) apart from the nine
        # identically-named rooms that also have `east`. Subset matching
        # alone treats "fewer exits than the map declares" as no
        # evidence at all, and the tie never breaks.
        exact, loose = [], []
        for t in dict.fromkeys(moved):
            if t not in rooms or rooms[t]["short"] != arrived:
                continue
            declared = set(rooms[t]["exits"])
            if seen == declared:
                exact.append(t)
            elif not seen or seen <= declared:
                loose.append(t)
        kept = exact or loose
        if kept:
            cands, title, exits = kept, arrived, seen
        else:
            # Every candidate was wrong. Start over from where we now
            # stand rather than compounding the error.
            cands = candidates(rooms, dirs, arrived, seen)
            title, exits = arrived, seen
            if not cands:
                return None
        tried = []

    if len(cands) > 1:
        api.log(f"「{title}」还是分不清是哪一间（剩 {len(cands)} 种可能），"
                f"暂且当作 {cands[0]}。")
    return cands[0] if cands else None


def bfs(rooms, dirs, start, goals, blocked=frozenset()):
    """Shortest path start -> nearest goal, as [(dir, room), ...].

    `blocked` holds (room, direction) pairs already found impassable, so
    the walker stops re-routing through a gate it cannot pass.
    """
    if start in goals:
        return []
    seen, q = {start}, deque([(start, [])])
    while q:
        cur, path = q.popleft()
        for d, nxt in rooms.get(cur, {}).get("exits", {}).items():
            if (cur, d) in blocked:
                continue
            if nxt in seen or nxt not in rooms or rooms[nxt]["area"] not in dirs:
                continue
            if avoided(rooms, nxt):
                continue
            seen.add(nxt)
            step = path + [(d, nxt)]
            if nxt in goals:
                return step
            q.append((nxt, step))
    return None


# ------------------------------------------------------------- combat --
def rest_until_healed(api):
    """Break off, run somewhere quiet, and wait for 气血 to come back.

    Gives up instead of waiting forever. 气血 regen is not merely slowed
    by thirst but switched off (feature/damage.lpc:465 returns from
    heal_up() before the kee line whenever 饮水 is 0), so "wait longer"
    is not a strategy that can ever succeed -- this loop used to spin
    printing 休息中… at a fixed 50% until the bot was killed by hand.
    So: drink first if we're carrying anything, and bail out if 气血
    stops climbing.
    """
    api.log("受伤了，撤退。")
    for _ in range(3):
        api.send("flee")
        api.sleep(1.5)

    stalled, last_kee = 0, -1
    while not api.stopped():
        st = api.status()
        if st["max_kee"] and st["kee"] * 100 // st["max_kee"] >= HP_RESUME:
            api.log("气血已恢复，继续找。")
            return True

        if pct(st["water"], st["max_water"]) < SUSTENANCE_AT:
            water, _ = drink_up(api)
            api.log(f"渴了，先喝口酒（饮水 {water}%）。")

        stalled = stalled + 1 if st["kee"] <= last_kee else 0
        last_kee = st["kee"]
        if stalled >= REST_STALL_LIMIT:
            api.log(f"气血卡在 {st['kee']}/{st['max_kee']} 不动了"
                    f"（食物 {pct(st['food'], st['max_food'])}%、"
                    f"饮水 {pct(st['water'], st['max_water'])}%）。"
                    "饮水见底时气血根本不会恢复，别再干等了。")
            return False

        api.log(f"休息中… 气血 {st['kee']}/{st['max_kee']}，"
                f"{REST_POLL} 秒后再看。")
        api.sleep(REST_POLL)
    return False


def abandon_all_skills(api):
    """Drop every skill the character has picked up.

    Monster difficulty is your HIGHEST skill level scaled by the quest
    level (yaoguai.lpc:317-330), and combat itself raises skills whether
    or not you ever `learn` -- combatd.lpc:497 calls improve_skill() on
    successful hits, which is how a "no skills" character still ended up
    with 基本棍法. Wiping them after each kill keeps
    query_skills() empty, so copy_status() takes its `else max_level = 1`
    branch and monsters stay at the floor.

    cmds/std/abandon.lpc asks y/n for any skill at level >= 10, so the
    prompt has to be answered or the session hangs waiting on input_to().
    """
    api.drain()
    api.send("skills", quiet=True)

    lines, deadline = [], time.time() + 6
    while time.time() < deadline:
        m = api.wait_line(r".+", timeout=1.0)
        if not m:
            if lines:
                break
            continue
        lines.append(m.string)

    # "  基本棍法 (stick)   - 初学乍练    1/    0"
    ids = re.findall(r"\(([a-z][a-z0-9_-]*)\)", "\n".join(lines))
    ids = [s for s in dict.fromkeys(ids)]        # de-dupe, keep order
    if not ids:
        return 0

    dropped = 0
    for sid in ids:
        if api.stopped():
            break
        api.drain()
        api.send(f"abandon {sid}", quiet=True)
        r = api.wait_line(r"\(y/n\)|决定放弃继续学习|并没有学过这项技能", timeout=4)
        if r and "(y/n)" in r.string:
            api.send("y", quiet=True)
            r = api.wait_line(r"决定放弃继续学习|并没有学过", timeout=4)
        if r and "决定放弃" in r.string:
            dropped += 1

    if dropped:
        api.log(f"已放弃 {dropped} 项技能（{', '.join(ids[:6])}"
                f"{'…' if len(ids) > 6 else ''}），维持妖怪难度在最低。")
    return dropped


def retreat_one_room(api, rooms, pos, blocked):
    """Break contact by stepping into any adjacent room.

    Returns (new_pos, direction_back) or (None, None) if every exit is
    shut. One room is enough -- combat doesn't follow through an exit
    unless the NPC chooses to, and staying adjacent keeps the walk back
    short.
    """
    for d, dest in rooms[pos]["exits"].items():
        if (pos, d) in blocked or dest not in rooms:
            continue
        if avoided(rooms, dest):
            continue
        arrived, _ = step(api, d)
        api.sleep(STEP_PAUSE)
        if arrived == rooms[dest]["short"]:
            # find the way back for the peek
            back = next((bd for bd, bt in rooms[dest]["exits"].items()
                         if bt == pos), None)
            return dest, back
    return None, None


def wait_out_intruder(api, rooms, danger_pos, intruder, blocked):
    """Retreat a room, then keep peeking back until the intruder leaves.

    Returns True if the danger room is clear again (safe to resume),
    False if we gave up or lost our footing.
    """
    api.log(f"「{intruder}」插进来打我，先退到隔壁避一避。")
    safe_pos, back_dir = retreat_one_room(api, rooms, danger_pos, blocked)
    if not safe_pos:
        api.log("四周都走不掉，只能硬着头皮打。")
        return False

    for attempt in range(1, INTRUDER_TRIES + 1):
        if api.stopped():
            return False
        api.sleep(INTRUDER_WAIT)
        if not back_dir:
            api.log("找不到回去的路，重新定位。")
            return False

        arrived, text = step(api, back_dir)
        api.sleep(STEP_PAUSE)
        if arrived != rooms[danger_pos]["short"]:
            api.log("回去的路不对，重新定位。")
            return False

        if intruder not in text:
            api.log(f"「{intruder}」已经走了，继续任务。")
            return True

        api.log(f"「{intruder}」还在（第 {attempt} 次查看），再退回去等。")
        safe_pos, back_dir = retreat_one_room(api, rooms, danger_pos, blocked)
        if not safe_pos:
            return False

    api.log(f"「{intruder}」赖着不走，放弃这一轮。")
    return False


def walk_to(api, rooms, blocked, dest, label):
    """Walk to a specific room, wherever we currently are. Returns True
    on arrival.

    Verifies each arrival the same way the hunt does -- a monster can
    shove you mid-route, and a gated exit has to be marked and routed
    around rather than silently desyncing the position. Position is
    re-derived from `look` at the top of each attempt, so this is safe to
    call after a flee or a teleport with no idea where we are.
    """
    api.log(f"前往{label}…")
    pos, steps, lost = None, 0, 0
    reason = "认不出位置"

    while steps < WALK_MAX_STEPS and lost < WALK_MAX_LOST and not api.stopped():
        if pos is None:
            pos = relocalise(api, rooms)
            if pos is None:
                lost += 1
                api.sleep(2)
                continue
        if pos == dest:
            api.log(f"已到{label}。")
            return True

        leg = travel(rooms, pos, {dest}, blocked)
        if leg is None:
            # No route from where we THINK we are. After a long walk
            # through identically-named rooms that almost always means
            # the position drifted rather than the map being
            # disconnected, so re-localise instead of abandoning the
            # walk -- giving up here is what stranded the bot out in
            # 高老庄 with 天监台 only 27 steps away.
            api.log(f"从「{rooms[pos]['short']}」暂时找不到去{label}的路，"
                    "重新定位。")
            reason = "找不到路线（可能有出口过不去）"
            pos, lost = None, lost + 1
            continue

        direction, nxt = leg[0]
        arrived, _ = step(api, direction)
        api.sleep(STEP_PAUSE)
        steps += 1

        if arrived == rooms[nxt]["short"]:
            pos = nxt
        elif not arrived:
            # Confirm where we actually are before blaming the exit.
            # Marking (pos, direction) impassable while pos is a drifted
            # guess poisons the route graph for the rest of the quest:
            # every later travel() detours around a gate that was never
            # really shut, until no route home survives at all.
            here = relocalise(api, rooms)
            if here is not None and direction in rooms[here]["exits"]:
                blocked.add((here, direction))
                api.log(f"{direction} 走不通，绕路。")
            pos = here
            if pos is None:
                lost += 1
        else:
            # Shoved by a wandering monster, or a one-way exit. Routine
            # on a long walk, so it costs a re-localisation and nothing
            # else -- an earlier version spent one of only three retries
            # on every shove and ran out long before arriving.
            api.log(f"到了「{arrived}」，和地图不符，重新定位。")
            pos = None

    if steps >= WALK_MAX_STEPS:
        api.log(f"走了 {steps} 步还到不了{label}，放弃。")
    else:
        api.log(f"{lost} 次{reason}，走不到{label}。")
    return False


def walk_back_to_yuan(api, rooms, blocked):
    """Walk back to 天监台 so the next job can be collected without the
    player having to travel. Returns True once 袁天罡 is in the room."""
    return walk_to(api, rooms, blocked, YUAN_ROOM, "天监台")


# --------------------------------------------------------- sustenance --
def read_reply(api, timeout=3.0):
    """Collect the mud's answer to a one-shot command.

    Same shape as read_room()'s loop, but with no exits line to stop on:
    read until the mud falls quiet for a beat. Commands like `eat` and
    `buy` answer in one or two lines, so a short quiet gap is the end.
    """
    lines, deadline = [], time.time() + timeout
    while time.time() < deadline:
        m = api.wait_line(r".+", timeout=0.6)
        if not m:
            if lines:
                break
            continue
        lines.append(m.string)
    return "\n".join(lines)


def pct(cur, mx):
    return (cur * 100 // mx) if mx else 0


def sustenance(api):
    """(food%, water%, status) as percentages of capacity."""
    st = api.status()
    return pct(st["food"], st["max_food"]), pct(st["water"], st["max_water"]), st


def drink_up(api, target=SUSTENANCE_TO):
    """Sip the 酒袋 until 饮水 is topped up. Returns (water%, reason).

    reason is 'ok' (at target or full), 'empty' (酒袋 drained), or
    'none' (no 酒袋 on us -- `drink` is added by the object's own init(),
    so with nothing to drink from the verb isn't even bound).
    """
    for _ in range(MAX_SIPS):
        if api.stopped():
            break
        api.drain()
        api.send("drink jiudai", quiet=True)
        reply = read_reply(api)
        if "你已经喝太多了" in reply:
            break
        # The failure form is "<名>已经被喝得一滴也不剩了"; the success
        # form for the last sip is "你已经将<名>里的<酒>喝得一滴也不剩了"
        # and comes WITH the 咕噜噜 line, so test the failure form only.
        if "已经被喝得一滴也不剩" in reply:
            return pct_water(api), "empty"
        if "咕噜噜地喝了几口" not in reply:
            return pct_water(api), "none"
        if pct_water(api) >= target:
            break
    return pct_water(api), "ok"


def pct_water(api):
    st = api.status()
    return pct(st["water"], st["max_water"])


def eat_up(api, target=SUSTENANCE_TO):
    """Eat 红烧狗肉 until 食物 is topped up. Returns (food%, reason),
    reason as in drink_up ('gone' once the portion is finished)."""
    for _ in range(MAX_BITES):
        if api.stopped():
            break
        api.drain()
        api.send("eat gou rou", quiet=True)
        reply = read_reply(api)
        if "你已经吃太饱了" in reply:
            break
        if "已经没什么好吃的了" in reply:
            return pct_food(api), "gone"
        if "吃了几口" not in reply and "吃得干干净净" not in reply:
            return pct_food(api), "none"
        if pct_food(api) >= target:
            break
    return pct_food(api), "ok"


def pct_food(api):
    st = api.status()
    return pct(st["food"], st["max_food"])


def buy_from_xiaoer(api, key, label):
    """`buy <key> from xiaoer`. Returns 'ok', 'broke', or 'no'.

    cmds/std/buy.lpc:23 insists on the `<item> from <someone>` form, and
    the item has to be 店小二's vendor_goods KEY (jiudai/gourou), not the
    Chinese name -- feature/vendor.lpc:8 looks it up by key.
    """
    api.drain()
    api.send(f"buy {key} from {VENDOR}", quiet=True)
    reply = read_reply(api)
    if "买下一" in reply:
        api.log(f"买了一份{label}。")
        return "ok"
    if "你的钱不够" in reply or "没有足够的零钱" in reply:
        return "broke"
    api.log(f"买不到{label}：{reply.strip().splitlines()[-1] if reply.strip() else '没有回应'}")
    return "no"


def withdraw_at_bank(api, rooms, blocked):
    """Walk to 相记钱庄, take cash out, and report whether we got any.

    std/room/bank.lpc:127 wants `withdraw <数量> <货币单位>`, the unit
    being a file under /obj/money (silver = 100 文 each).
    """
    if not walk_to(api, rooms, blocked, BANK_ROOM, "相记钱庄"):
        api.log("走不到相记钱庄。")
        return False
    api.drain()
    api.send(f"withdraw {WITHDRAW_SILVER} silver", quiet=True)
    reply = read_reply(api)
    if "从银号里取出" in reply:
        api.log(f"从钱庄取了 {WITHDRAW_SILVER} 两银子。")
        return True
    api.log("钱庄取款失败（存款不足？）。")
    return False


def restock(api, rooms, blocked, need_food, need_drink):
    """Buy and consume at 南城客栈, with a trip to the bank if broke.

    The bank stop is made only when 店小二 actually refuses for lack of
    money -- 天监台->客栈 is four steps and 天监台->钱庄->客栈 is eight,
    so withdrawing unconditionally would burn a round trip every cycle
    on a character already carrying silver.
    """
    if not walk_to(api, rooms, blocked, KEZHAN_ROOM, "南城客栈"):
        api.log("走不到南城客栈，这轮不补给了。")
        return

    for key, label, needed, consume in (
            ("jiudai", "桂花酒袋", need_drink, drink_up),
            ("gourou", "红烧狗肉", need_food, eat_up)):
        if not needed or api.stopped():
            continue
        result = buy_from_xiaoer(api, key, label)
        if result == "broke":
            if not withdraw_at_bank(api, rooms, blocked):
                return
            if not walk_to(api, rooms, blocked, KEZHAN_ROOM, "南城客栈"):
                return
            result = buy_from_xiaoer(api, key, label)
        if result != "ok":
            continue
        level, reason = consume(api)
        # A fresh 酒袋 that reports empty means the old one is still the
        # one being drunk from; ditch it so the new one is what `drink`
        # finds. (present() picks the first match in inventory order.)
        if reason == "empty":
            api.log("酒袋空了，丢掉再来一个。")
            api.send("drop jiudai", quiet=True)
            read_reply(api, timeout=2.0)
            if buy_from_xiaoer(api, "jiudai", "桂花酒袋") == "ok":
                consume(api)


def keep_fed(api, rooms, blocked):
    """Top 食物/饮水 back up if either has fallen below SUSTENANCE_AT.

    Called at 天监台 between quests, because that is the one point in the
    cycle where position is known, nothing is chasing us, and a detour
    costs no quest time. Ends back at 天监台; returns False only if it
    could not get back there.
    """
    food, water, st = sustenance(api)
    if not st["max_food"] or not st["max_water"]:
        api.log("警告：看不懂 hp 的食物/饮水上限，跳过补给。")
        return True
    if food >= SUSTENANCE_AT and water >= SUSTENANCE_AT:
        return True

    api.log(f"食物 {food}%、饮水 {water}% —— 先补给。"
            "（饮水见底时气血完全不会恢复。）")

    # Inventory first: no walking needed if we're already carrying some.
    if water < SUSTENANCE_AT:
        water, _ = drink_up(api)
    if food < SUSTENANCE_AT:
        food, _ = eat_up(api)
    if food >= SUSTENANCE_AT and water >= SUSTENANCE_AT:
        api.log(f"补给完毕：食物 {food}%、饮水 {water}%。")
        return True

    restock(api, rooms, blocked, food < SUSTENANCE_AT, water < SUSTENANCE_AT)

    food, water, _ = sustenance(api)
    api.log(f"补给完毕：食物 {food}%、饮水 {water}%。")
    if food < SUSTENANCE_AT or water < SUSTENANCE_AT:
        api.log("警告：还是没吃饱喝足，气血恢复可能会很慢甚至停住。")
    return walk_back_to_yuan(api, rooms, blocked)


def fight_target(api, mid, name):
    """Attack, watching for the retreat triggers. Returns 'killed',
    'hurt' or 'lost'."""
    api.drain()
    api.send(f"kill {mid}")
    deadline = time.time() + FIGHT_TIMEOUT
    while time.time() < deadline and not api.stopped():
        m = api.wait_line(
            f"{REWARD_RE}|{RETREAT_RE}|{DEAD_RE}|这里没有这个人|{INTRUDER_RE}",
            timeout=5)
        if not m:
            continue
        # m.string is the WHOLE line; m.group(0) is only the matched
        # fragment. Both sides' wound messages share that fragment --
        # combatd.lpc:218 emits "( $N" + status_msg(), so ours reads
        # "( 你似乎十分疲惫…" and the monster's "( 马鹿精似乎十分疲惫…".
        # Matching on the fragment alone made the bot flee whenever it
        # was WINNING.
        line = m.string
        t = m.group(0)

        if re.search(REWARD_RE, line):
            return "killed"
        if "这里没有这个人" in line:
            return "lost"

        # Someone other than the quest target started on us.
        bad = re.search(INTRUDER_RE, line)
        if bad:
            who = (bad.group(1) or bad.group(2) or "").strip()
            if who and name not in who and who not in name:
                return f"intruder:{who}"
        if re.search(RETREAT_RE, line):
            if name and name in line:
                continue            # the monster is hurting, press on
            if "你" in line:
                return "hurt"
        if re.search(DEAD_RE, line):
            r = api.wait_line(REWARD_RE, timeout=10)
            if r:
                return "killed"
    return "lost"


# ---------------------------------------------------------------- run --
def run(api):
    data = load_map(api)
    if not data:
        return
    rooms, areas = data["rooms"], data["areas"]
    jobs = 0

    while not api.stopped():
        # ---- get a job ------------------------------------------------
        api.drain()
        api.send("ask yuan about mieyao")
        m = api.wait_line(
            f"{ASSIGN_RE}|请速去天廷协助灭妖|在下不是请您去收服|{DONE_COOLDOWN}",
            timeout=10)
        if m and DONE_COOLDOWN in m.string:
            api.log(f"袁天罡还在道谢（任务冷却中，最多 5-10 分钟）。"
                    f"{COOLDOWN_WAIT} 秒后再问。")
            api.sleep(COOLDOWN_WAIT)
            continue
        if not m:
            api.log("袁天罡没有回应 —— 你站在他旁边吗？（长安天监台）")
            api.sleep(10)
            continue
        if "天廷协助" in m.group(0):
            api.log("道行/武学已超过 50000，袁天罡不再派灭妖任务。停止。")
            return
        a = re.search(ASSIGN_RE, m.group(0))
        if not a:
            # A job from an earlier session is still pending. 袁天罡 names
            # the target but not where it is, and won't issue a new one
            # until the 30-minute timer lapses (yuantiangang.lpc:128), so
            # there's nothing to walk toward -- watch passively and jump
            # on it if it wanders past, rather than re-asking every 10s.
            pend = re.search(r"收服(.+?)吗", m.string)
            who = pend.group(1) if pend else "上一个目标"
            api.log(f"上一个任务（{who}）还没交差，袁天罡最多再等 30 分钟才会换新的。"
                    "我先在原地盯着，看到它就动手；你也可以自己去找它。")
            hit = api.wait_line(re.escape(who), timeout=120) if pend else None
            if hit:
                api.log(f"{who} 出现了，动手！")
                fight_target(api, who, who)
            continue

        name, mid, place = a.group(1), a.group(2).strip().lower(), a.group(3)
        jobs += 1
        api.log(f"任务 {jobs}：{name}（{mid}）在【{place}】")

        # MISC_D->find_place() (adm/daemons/miscd.lpc:64-93) returns the
        # AREA label from find.map when the spawn room's directory is
        # listed there, and otherwise falls back to the ROOM's own short
        # name. So 【长安城】 means "search this whole area" while
        # 【玉女峰】 names specific rooms -- far better, go straight there.
        dirs = areas.get(place, [])
        targets = None
        if dirs:
            api.log(f"这是区域名，对应目录 {dirs}，开始搜索。")
        else:
            named = [p for p, r in rooms.items() if r["short"] == place]
            if named:
                dirs = sorted({rooms[p]["area"] for p in named})
                targets = set(named)
                api.log(f"这是房间名，共 {len(named)} 间同名房间"
                        f"（{dirs}），直接过去找。")
            else:
                api.log(f"地图里找不到【{place}】，无法自动搜索。"
                        "请手动过去，我会在看到它时动手。")
                dirs = []

        started = time.time()
        killed = False
        pos = None
        visited = set()
        blocked = set()
        found_here = False
        warned_unreachable = False

        # ---- hunt -----------------------------------------------------
        while not api.stopped() and time.time() - started < QUEST_SECS:
            # Is it right here? Either queued output mentions it, or the
            # last move's room description did.
            hit = found_here or api.wait_line(
                f"{re.escape(name)}|{re.escape(mid)}", timeout=1)
            found_here = False
            if hit:
                api.log(f"发现 {name}，动手！")
                r = fight_target(api, mid, name)
                if r == "killed":
                    api.log(f"击杀 {name} 成功！")
                    killed = True
                    if ABANDON_SKILLS_AFTER_KILL:
                        abandon_all_skills(api)
                    break
                if r == "hurt":
                    if not rest_until_healed(api):
                        return
                    pos = None       # we fled somewhere unknown
                    continue
                if r.startswith("intruder:"):
                    intruder = r.split(":", 1)[1]
                    # We need our position to retreat and find the way
                    # back to this room afterwards.
                    if pos is None:
                        pos = relocalise(api, rooms)
                    if pos and wait_out_intruder(api, rooms, pos,
                                                 intruder, blocked):
                        continue         # clear again -- have another go
                    pos = None           # lost track, or gave up on it
                continue

            if not dirs:
                api.sleep(2)
                continue

            # Localise if we don't know where we are. Search the WHOLE
            # map, not just the target area -- we start at 天监台 in 长安,
            # which is usually nowhere near where the monster spawned.
            if pos is None:
                # relocalise() handles the maze case and the ambiguous
                # -title case, and may walk a few rooms while probing.
                pos = relocalise(api, rooms)
                if pos is None:
                    api.log("认不出现在这个房间，10 秒后再试。")
                    api.sleep(10)
                    continue
                api.log(f"定位：{rooms[pos]['short']}（{pos}）")
                visited.add(pos)

            # Not in the target area yet? Walk there first.
            if rooms[pos]["area"] not in dirs:
                entry = {p for p, r in rooms.items() if r["area"] in dirs}
                leg = travel(rooms, pos, entry, blocked)
                if not leg:
                    # Some areas (龙宫 via dive, 方寸山, 普陀山, 红楼一梦,
                    # 高老庄) are only reachable through non-exit
                    # transitions the map can't know about. Say so ONCE,
                    # then fall back to watching quietly -- repeating this
                    # every 15s for the whole 30-minute quest is just spam.
                    if not warned_unreachable:
                        api.log(f"从「{rooms[pos]['short']}」走不到【{place}】"
                                "（这个区域要用 dive/特殊方式进入）。"
                                "请手动过去，我会在看到它时动手。")
                        warned_unreachable = True
                    api.sleep(5)
                    continue
                api.log(f"前往【{place}】，共 {len(leg)} 步…")
                for d, dest in leg:
                    if api.stopped():
                        return
                    arrived, seen_text = step(api, d)
                    api.sleep(STEP_PAUSE)
                    if name in seen_text or mid in seen_text.lower():
                        found_here = True
                        break
                    if arrived == rooms[dest]["short"]:
                        pos = dest
                    elif not arrived:
                        blocked.add((pos, d))
                        pos = None
                        break
                    else:
                        pos = None
                        break
                continue

            # Walk to the nearest room we haven't checked yet, avoiding
            # exits already found to be impassable.
            # When 袁天罡 named specific rooms, check those first and only
            # widen to the whole area if the monster isn't in any of them
            # (it wanders -- yaoguai.lpc's chat_msg calls random_move).
            goals = set()
            if targets:
                goals = {p for p in targets if p not in visited}
                if not goals:
                    api.log("同名房间都找过了，扩大到整个区域搜索。")
                    targets = None
            if not goals:
                # no_mieyao rooms are skipped as GOALS but stay routable:
                # yaoguai never spawn in them (d/kaifeng/maze.lpc:27 and
                # friends set the flag for exactly that), so walking to
                # one can never find the target -- and two of them
                # (禹王林, maze) build their exits at runtime, so the
                # static map cannot walk back out again.
                goals = {p for p, r in rooms.items()
                         if r["area"] in dirs and p not in visited
                         and r["short"] not in AVOID_ROOMS
                         and not r["flags"].get("no_mieyao")}
            if not goals:
                api.log(f"【{place}】已经全部走过一遍，重新再找。")
                visited = {pos}
                continue
            path = bfs(rooms, dirs, pos, goals, blocked)
            if path is None:
                api.log("从这里走不到未搜索的房间，重新定位。")
                pos, visited = None, set()
                api.sleep(2)
                continue
            if not path:
                # bfs() returns [] for "you are already standing in one
                # of the goals" and None for "no route exists". Treating
                # both as failure was an infinite loop: arriving in the
                # target area put us in an unsearched room, [] was read
                # as unreachable, the walker reset and re-guessed the
                # room from an ambiguous title, guessed a neighbour, and
                # walked back out of the area again.
                visited.add(pos)
                continue

            direction, dest = path[0]
            arrived, seen_text = step(api, direction)
            api.sleep(STEP_PAUSE)

            # Scan what we were just shown -- step() drained those lines,
            # so the separate monster check at the top of the loop can no
            # longer see them.
            if name in seen_text or mid in seen_text.lower():
                found_here = True

            if arrived in MAZE_ROOMS:
                # Inside a randomised maze the map can't help. Sweep it by
                # probing, then mark the whole maze searched so BFS doesn't
                # keep routing us back in.
                res = sweep_maze(api, arrived, name, mid)
                for p_, r_ in rooms.items():
                    if r_["short"] in MAZE_ROOMS:
                        visited.add(p_)
                if res == "found":
                    found_here = True
                elif res != "clear":
                    escape_maze(api, arrived)
                pos = None          # position unknown after a sweep
            elif arrived == rooms[dest]["short"]:
                pos = dest
                visited.add(dest)
            elif not arrived:
                # Never moved: the exit is gated (a door, valid_leave, a
                # sect check, over-encumbrance). Remember it so BFS stops
                # routing through it -- this is what desynced the walker
                # in live testing, where 南城客栈's `east` is blocked
                # until you've paid the innkeeper.
                blocked.add((pos, direction))
                api.log(f"{direction} 走不通，绕路。")
            else:
                # Moved, but not where the map predicted (wandering
                # monster shoved us, teleport, one-way exit). Re-localise.
                api.log(f"到了「{arrived}」，和地图不符，重新定位。")
                pos = None

        if not killed:
            api.log("30 分钟到了，任务失败（下次难度降一级）。")

        # ---- walk back to 袁天罡 --------------------------------------
        if not walk_back_to_yuan(api, rooms, blocked):
            # Couldn't route there (lost, or a gate in the way) -- fall
            # back to waiting for the player to walk back manually.
            api.log("自己走不回天监台，请手动回去找袁天罡，我看到他就接下一个任务。")
            while not api.stopped():
                if api.wait_line("袁天罡", timeout=30):
                    break

        # ---- eat and drink before taking the next job -----------------
        # Deliberately AFTER the return walk rather than at the kill
        # site: here the position is known, nothing is in combat, and
        # 袁天罡's post-success cooldown is running anyway, so a detour
        # to 南城客栈 costs nothing that wasn't already being waited out.
        if not api.stopped() and not keep_fed(api, rooms, blocked):
            api.log("补给后走不回天监台，请手动回去找袁天罡。")
            while not api.stopped():
                if api.wait_line("袁天罡", timeout=30):
                    break
