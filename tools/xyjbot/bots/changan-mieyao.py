# changan-mieyao -- 长安 灭妖 quest runner with auto-walk,
# retreat, and automatic return to 袁天罡.
#
# Run in-game with: /run changan-mieyao
# Stop with:        /stop changan-mieyao
# Stand with 袁天罡 (yuan) in 长安天监台 when you start it.
#
# Cycle:
#   1. ask 袁天罡 for a job; parse the target's name/id and the AREA
#      (d/city/npc/yuantiangang.lpc -> MISC_D->find_place returns an
#      area label like 长安城, not a room)
#   2. CHECK the target is reachable on foot before setting off. Two
#      gates are errands rather than walls and get run on the spot:
#      龙宫 wants a 避水咒 (酒袋 -> 袁守诚 -> tear book) and 红楼一梦 a
#      黄粱枕 (kill 卢生, pay the innkeeper, sleep). Anything genuinely
#      shut -- climb tree at 玉女峰顶, say -- means the job is given up
#      on the spot, and the bot keeps asking 袁天罡 until his 30-minute
#      timer hands out a new one, rather than burning the half hour
#      walking into a dead end. He offers no way to cancel a job early
#      (yuantiangang.lpc:126-134 just repeats the assignment), so
#      waiting it out IS the abandon.
#   3. WALK that area room by room, looking for the target. Uses
#      rooms.json, built by build_map.py from the mudlib's own exits.
#   4. kill it when found, watching combat status the whole time. If it
#      runs (one 妖怪 in ten gets env/wimpy 40 and bolts at 40% 气血,
#      every round), go.lpc:85 names the exit it took -- follow it there
#      and re-engage, rather than re-searching the area
#   5. if hurt past RETREAT_AT, break off by WALKING out (there is no
#      `flee` command in this mudlib), rest to full, then walk back into
#      the room the monster is still standing in. The character's own
#      env/wimpy can do the same thing behind our back -- char.lpc:96
#      walks you out through a random exit -- and that is handled the
#      same way, minus the retreat we no longer need to make
#   6. collect the horse if something took us off it (sleep does, and so
#      does any room the mount can't follow us into), walk back to
#      天监台, then top up 食物/饮水 if either has
#      dropped under half -- drink jiudai / eat gou rou from inventory,
#      restocking from 店小二 in 南城客栈 (via 相记钱庄 if out of cash)
#      (see RIDE_ID for the horse; set it to "" if you never ride)
#   7. take the next job (waiting out 袁天罡's 5-10 minute post-success
#      cooldown if he's still thanking you)
#
# Why step 6 exists: 饮水 at 0 doesn't slow 气血 regen, it stops it
# (feature/damage.lpc:465), so a thirsty bot rests forever at whatever
# percentage it fled with.
#
# Position tracking: the bot doesn't get told where it is, so it
# localises from `look` output -- room title plus the exit list -- and
# re-localises whenever a move lands somewhere unexpected (wandering
# monsters, teleports, blocked exits all cause that).

import json
import random
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

# Rooms whose RESIDENTS can kill this character -- avoided for that reason
# alone, and only while we are too weak. 海底莽林 (d/sea/maze1-10) holds:
#
#   beast3  370,000 exp, every skill 170, attitude "aggressive"  x3
#   beast2  170,000 exp, dodge 140,       attitude "aggressive"  x2  (roams)
#   beast1   50,000 exp                                          x2
#   kid2 小虾米  60 exp, peaceful                                 x3
#
# feature/attack.lpc:244 makes an "aggressive" NPC auto_fight any player who
# walks in, so beast2 and beast3 attack on sight -- there is no tactic that
# survives that, only absence. beast1 has no attitude set and fights only if
# you type `train` (its do_train, gated on 东海龙宫), which the bot never does.
#
# The gate is arithmetic, not preference: 袁天罡 stops issuing quests once
# (daoxing+combat_exp)/2 passes 50,000, so a character on HIS quest is always
# an order of magnitude below beast3. 李靖's quest has no upper bound, so a
# strong character lifts this restriction by itself.
# The table itself is GENERATED, not hand-written: build_index.py sweeps
# every room for residents with attitude "aggressive" and records the
# strongest one's combat_exp into danger.json, keyed by room path (休息室
# exists four times and 海底莽林 ten, and only some are lethal). 60 rooms
# qualify today, the worst being 盘丝岭's 蝎公 at 3,600,000.
#
# Not covered, and worth knowing: NPCs that attack on a SCRIPT rather than an
# attitude. 马盗 is attitude "heroism" and attacks 25 seconds after you arrive
# via call_out -> command("kill"); no attribute reveals that. He is handled
# separately, by paying his toll.
DANGER_FILE = Path(__file__).resolve().parent.parent / "danger.json"
DANGER = {}                # room path -> strongest aggressive resident's exp
DANGER_MARGIN = 2          # need this multiple of that exp to risk the room
_MY_EXP = [0]              # this character's 武学, refreshed each job

# Mazes: rooms whose exits are randomised at create() time, so the static
# map is useless inside them -- d/nanhai/zhulin*.lpc builds every looping
# exit as "zhulin" + sprintf("%d", random(6)), which build_map records as
# a nonexistent "d/nanhai/zhulin". BFS can route to the entrance
# (road4 north -> zhulin0, pool south -> zhulin15) but not within, so
# these get swept by probing instead of pathing.
MAZE_ROOMS = {"紫竹林"}

# Rooms that are safe to walk through but not to stand in. 石栈道
# (d/westway/shizhan.lpc:27-48) arms a 25-second call_out every time a
# player walks in and then drops EVERYONE in the room through a trapdoor
# into 铁笼中 -- a room with no exits at all until the bars are bent, at
# 30 气血 per attempt and 3000 accumulated force to open (tielong.lpc:55).
# A skill-less 灭妖 character cannot pay that, so a fight there is not
# worth having: handled like a peace room, wait for the target to wander
# out and take it in the next room. The fuse is re-armed on entry, so
# stepping out and back in costs nothing.
TRAP_ROOMS = {"石栈道"}
TRAP_WAIT = 12         # seconds to watch it, well inside the 25s fuse

CAGE_ROOM = "铁笼中"     # where the trapdoor lands you
CAGE_BREAKS = 8        # `break` attempts before asking for help
CAGE_MIN_KEE = 40      # % 气血 to keep in reserve while bending bars

# Rooms that belong to a hunt even though they sit in another directory.
#
# 袁天罡 names an AREA, and MISC_D->find_place() derives that from the
# spawn room's DIRECTORY (adm/daemons/find.map:56 -- d/westway 长安城西),
# so the map's own area labels say where a 妖怪 STARTED. They don't say
# where it is now: yg/yaoguai.lpc sets chat_msg to random_move, so it
# drifts, and the road west runs straight on past the directory boundary
# at 云梯冈 into 五庄观's 山路 and 林荫小道. Searching strictly by
# directory means walking to the edge and turning round while the target
# stands two rooms further on.
AREA_EXTRA = {
    "长安城西": (
        "d/qujing/wuzhuang/shanlu1",     # 山路 -- 云梯冈 north
        "d/qujing/wuzhuang/shanlu2",     # 山路
        "d/qujing/wuzhuang/linyin1",     # 林荫小道
        "d/qujing/wuzhuang/linyin2",     # 林荫小道
    ),
}


# How far to widen the search around the monster's last known room once it
# (or we) broke off. 袁天罡 names the region it SPAWNED in, but the monster
# wanders -- yg/yaoguai.lpc's chat_msg is random_move -- and 23 rooms across
# the ten spawn regions open straight into a different one. 方寸山下
# (d/lingtai/hill) reaches 高老庄's 土路 in a single step, so a monster that
# slips over the line is invisible to a region-confined search forever.
#
# Only applied AFTER a break in contact, since that is when it has had time
# to move and when we have a last-known room worth centring on.
#
# 10, chosen for margin over the derived figure. The mechanics: chat() runs
# every heartbeat for an NPC (std/char.lpc:109, before the tick gate) and
# std/char/npc.lpc:125-135 fires a chat_msg on random(100) < chat_chance.
# The 灭妖 monsters set chat_chance to 3 and their only chat_msg is
# random_move, so at the driver's default 2-second beat that is
# 30 beats/min x 3% = about ONE ROOM PER MINUTE.
#
# A break in contact is a rest plus the walk back -- 3 to 6 minutes, so 3 to
# 6 moves; and since those are random, net displacement goes as sqrt(n), so
# six moves usually lands only 2-3 rooms away. 10 therefore covers a long
# rest that moved in a straight line the whole way, with room to spare.
#
# It is not free. Measured extra rooms pulled into a sweep by widening at a
# border room:
#
#     方寸山下      radius 5: +14      radius 10: +30
#     长安城西门    radius 5:  +6      radius 10: +57
#     土路          radius 5:  +3      radius 10: +20
#
# 长安城 is the one to watch -- +57 on top of 107 is a much slower sweep. If
# hunts start timing out after an escape there, this is the dial.
ESCAPE_RADIUS = 10


def nearby(rooms, center, radius):
    """Every room within `radius` steps of `center`, ignoring area borders."""
    if center not in rooms:
        return set()
    seen, frontier = {center}, [center]
    for _ in range(radius):
        nxt = []
        for cur in frontier:
            for _d, n in rooms[cur]["exits"].items():
                if n in rooms and n not in seen and not avoided(rooms, n):
                    seen.add(n)
                    nxt.append(n)
        frontier = nxt
    return seen


def area_paths(rooms, dirs, place=None):
    """Every room the search treats as part of `place`."""
    inside = {p for p, r in rooms.items() if r["area"] in dirs}
    inside.update(x for x in AREA_EXTRA.get(place, ()) if x in rooms)
    return inside


# 天监台 -- where 袁天罡 stands. The bot walks back here after every job.
YUAN_ROOM = "d/city/tianjiantai"

# Wipe every skill after each successful kill. Combat raises skills on
# its own (combatd.lpc:497), and monster difficulty scales off your
# highest skill, so leaving them to accumulate makes the grind harder
# with every quest. Set False to keep whatever you pick up.
ABANDON_SKILLS_AFTER_KILL = True

# ...but only while the character is still a blank slate: if ANY skill has
# passed this level, leave the lot alone. yaoguai.lpc:321 sets the monster
# to max_skill * (quest_level + 18) / 20, so 1 and 2 both round down to a
# level-1 monster -- wiping those costs nothing, while wiping a skill you
# actually trained (dodge 40 for the 桂树, say) throws away real work.
WIPE_MAX_LEVEL = 2

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

SUSTENANCE_AT = 80     # % of capacity: at or below this on 食物 OR 饮水,
                       # eat and drink. Was 50, which cut it fine: 饮水 at 0
                       # does not slow 气血 regen, it STOPS it
                       # (feature/damage.lpc:465), so the cost of topping up
                       # early is a sip, and the cost of leaving it is a rest
                       # that never finishes.
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

QUEST_SECS = 600       # yuantiangang.lpc:128 -- an unfinished job blocks
                       # 袁天罡 for this long, so it is also how long the
                       # hunt is worth continuing. Was 1800 (30 min).

# Keep sweeping until it is time to walk home -- do NOT stop after a fixed
# number of passes. 袁天罡 has no cancel (yuantiangang.lpc:126-134), so his
# 30-minute timer lapses whether we search or idle, and the target WANDERS
# (yg/yaoguai.lpc gives it random_move), so every extra pass is a real extra
# chance at a room that was empty when we walked through it.
#
# The one thing that does argue for heading back early: when the timer
# lapses we have to be standing in front of him to ask for the next job.
# The longest legitimate route home on the map is 90 steps, which at this
# pace is well under a minute -- the rest of the reserve is for blocked
# exits, re-localisation and the sustenance stop.
HOMEWARD_RESERVE = 120     # seconds kept back for the walk to 天监台.
                           # Was 180, which was a tenth of the old 1800s job
                           # and is now a fifth of a 600s one -- too much to
                           # give up. The longest route home on the map is 90
                           # steps, well under a minute at this pace; the
                           # rest absorbs a blocked exit or a re-localisation.
# Pacing. The server itself chains a "n#12" batch with call_out(..., 0)
# between instant commands (xyj2000f feature/alias.lpc:170-175), so the
# only real ceiling is the anti-flood guard in process_input(): more than
# 100 commands inside 5 seconds gets "你一次输入太多命令了" and the input
# dropped. One step costs a send plus however long the room takes to
# arrive, so 0.15s of padding lands around 3 commands/second -- an order
# of magnitude under the guard, and roughly a #N batch's cadence.
STEP_PAUSE = 0.15      # seconds between movement commands

# How long to keep reading after the 出口是 line before calling the room
# complete. The mud writes a room in one burst -- title, description,
# exits, then contents -- so this only has to outlast network jitter, but
# it must not be skipped: the contents list is where the target monster
# is named. Ends early as soon as ROOM_IDLE passes with nothing new.
ROOM_GRACE = 0.5
ROOM_IDLE = 0.25

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
# go.lpc:85 announces a fleeing fighter to the room it LEAVES, naming the
# direction in Chinese: 白马精往上落荒而逃了。 That is free intelligence --
# it says which exit to take, so a chase costs one step instead of an
# area-wide re-search with the monster free to keep moving.
FLEE_RE = r"往([^\s，。！,]{1,12}?)落荒而逃了"

# The character's OWN env/wimpy pulling us out of a fight. std/char.lpc:96
# -102 calls GO_CMD->do_flee() from heart_beat whenever 气血 or 精神 drops
# to the `wimpy` percentage, and go.lpc:132-147 announces it with
# 看来该找机会逃跑了 before walking us out through a RANDOM exit. The bot
# never asked for that move, so it kept swinging at a monster in another
# room and its idea of where it stood was a room out of date.
#
# The flee can also fizzle -- go.lpc:141 refuses while 定身, and :145
# rolls dodge/10 + kar against 10 -- in which case we're still in the
# fight and nothing has changed.
WIMPY_RE = "看来该找机会逃跑了"
WIMPY_FAIL_RE = "你逃跑失败|可你被定住了"
WIMPY_SETTLE = 2.0     # seconds to see which of the two it was
WIMPY_LIMIT = 6        # per job, before we tell the player to lower it

# A monster that followed us out of the room and restarted the fight can
# also DIE there, on heart_beat, without the bot ever sending another
# `kill`. yg/yaoguai.lpc:134 tell_object()s the reward straight to the
# owner, so that line arrives wherever we are -- and it is unique to the
# 灭妖 monsters (nothing else in the mudlib prints 点武学经验和), which
# makes it a reliable "your target is dead" signal even when we weren't
# the ones swinging at the time.
REST_RETREATS = 3      # extra rooms to give ground before just resting
REWARD_GRACE = 3       # seconds to wait for the reward after a death line

# Peace rooms. cmds/std/kill.lpc:19 refuses outright with 这里不准战斗
# (cmds/std/fight.lpc:10 says 这里禁止战斗), so a 妖怪 standing in one
# cannot be attacked at all -- 北观礼台 in 开封 is where this turned up.
# It doesn't stay, though: the monster's init() call_outs check_room()
# two seconds after anyone walks in, and check_room() random_move()s it
# out of any no_fight / no_magic room (yaoguai.lpc:604-611). So the move
# is to stand there, watch which way it goes, and follow it out -- and if
# it somehow sits tight, step out and back in, because walking in is what
# arms that call_out in the first place.
# 饮马峪's 马盗 (d/westway/yinma.lpc:31-45) refuses `northwest` to anyone
# who isn't 五庄观 and hasn't paid -- and that one exit is the ONLY road
# to 马道, 酒泉郊外, 石栈道, 嘉峪关, 烽火台 and 云梯冈, half of 长安城西.
# Read as an ordinary shut exit it cost the bot every job whose target
# spawned out west. 200 文 buys two passes (npc/madao.lpc:48-53 sets
# has_paid=2; valid_leave spends one per departure), and he attacks 25
# seconds after you walk in if you don't pay, so paying at once is also
# the safe move.
TOLL_RE = ("不给钱我要杀人啦|要钱还是要命|往哪儿跑！给钱"
           "|快给钱|拿钱来买命|你到底给不给钱")
TOLL_OK = "闪身让道|怪笑"
TOLL_SILVER = 2
TOLL_TARGET = "ma dao"

NOFIGHT_RE = "这里不准战斗|这里禁止战斗"
NOFIGHT_WAIT = 20      # seconds to give it to wander back out
NOFIGHT_TRIES = 5      # nudges before leaving it and searching elsewhere

# An ordinary departure, go.lpc:88 -- 野马怪往西离开。 Same shape as the
# combat one (FLEE_RE) and just as useful: it names the exit taken.
LEAVE_RE = r"往([^\s，。！,]{1,12}?)(?:离开|飞去|落荒而逃)"

# go.lpc:7-28 default_dirs, inverted. It is one-to-many: northup and
# northdown both print 北边 (likewise the other three), so the room's own
# exit list has to break the tie. An exit whose name is NOT in that table
# is printed verbatim, which is already the direction to walk.
CN_DIR = {
    "北": ["north"], "南": ["south"], "东": ["east"], "西": ["west"],
    "北边": ["northup", "northdown"], "南边": ["southup", "southdown"],
    "东边": ["eastup", "eastdown"], "西边": ["westup", "westdown"],
    "东北": ["northeast"], "西北": ["northwest"],
    "东南": ["southeast"], "西南": ["southwest"],
    "上": ["up"], "下": ["down"], "外": ["out"], "里": ["enter"],
    "左": ["left"], "右": ["right"],
}
# Breaking off a fight. There is NO `flee` command in this mudlib --
# cmds/std holds no flee.lpc and the only caller of GO_CMD->do_flee is
# std/char.lpc:96-102's env/wimpy check, so the "flee" this bot used to
# send was silently discarded and "retreating" meant standing still while
# the monster kept swinging. Breaking contact is an ordinary move:
# go.lpc:83-85 just prints 落荒而逃 instead of 离开 when you're fighting,
# and a successful move calls remove_all_enemy() (go.lpc:105). The move
# competes with our own attack rounds -- valid_move.h refuses with
# 你的动作还没有完成 while is_busy() -- so each exit gets a few tries.
BREAK_OFF_TRIES = 4
BREAK_OFF_WAIT = 1.5

# Chasing a monster that ran. yaoguai.lpc:483 gives one mob in ten
# env/wimpy 40, and char.lpc flees it at 40% 气血 EVERY round, so those
# fights are a running battle: two or three hits, it bolts, you follow.
# Each re-engagement lands real damage and it regenerates slowly, so the
# chase does converge -- but bound it anyway.
CHASE_MAX = 40

# A room whose .lpc doesn't compile. `go` dumps 编译时段错误 … followed by
# *No program in object '/d/moon/bedroom'! and leaves you standing where
# you were -- /d/moon/bedroom.lpc closed its @LONG text block on the same
# line as the text, so the driver ran off the end of the file. That is a
# permanent map defect rather than a gate that might open later, so it is
# remembered for the whole session instead of per job.
BROKEN_RE = r"编译时段错误|No program in object"
BROKEN_EXITS = set()

# --- riding --------------------------------------------------------------
# mount.lpc:56 confirms with 稳稳地骑在<马>上, and from then on go.lpc:118
# prints 你骑着<马>走了过来 on EVERY move -- so the mount state can be read
# off each arrival for free, no polling. Being on the horse is worth
# keeping: mount.lpc:59 adds the mount's ride/dodge to apply/dodge, and
# dodge is most of what keeps a skill-less 灭妖 character alive.
#
# Three things separate you from it: `sleep` (sleep.lpc:79 clears ridee
# before the dream, so 红楼一梦 is entered on foot), a room the horse
# can't follow you into (go.lpc:76 你的座骑走动不了), and dismounting.
RIDE_ID = "horse"        # `mount horse`; set to "" to never ride
RIDE_ARRIVE = "你骑着"    # go.lpc:118, printed to us on every mounted move
RIDE_OK = "稳稳地"        # mount.lpc:56, the successful mount

# Where the horse is and whether we're on it. Module-level because
# step_full() has to be able to get off a horse that can't follow.
# `fell_off` bridges the one place that knows we got off (step_full, which
# has no idea where it is) to the one that knows where we were (ride_note,
# which the walker calls with the room we left). Without it the horse was
# abandoned with no record of the room, and ride_recover could never fetch
# it -- in exactly the case this exists for, a gate the mount can't pass.
RIDE = {"want": False, "on": False, "name": "", "left_at": None,
        "fell_off": False}

INTRUDER_WAIT = 45     # seconds to sit one room away before peeking back
INTRUDER_TRIES = 6     # how many times to peek before giving up on the job
COOLDOWN_WAIT = 60     # seconds between re-asks while he's still thanking you
GIVEUP_POLL = 120      # seconds between re-asks after giving up on a job

# Gated transitions THIS character can always make, by command name
# (build_map.py's SPECIAL_EXITS marks which are gates). `dive` and `sleep`
# need no entry here -- GATE_PREP below earns those passes on demand --
# but add "climb tree" if you join 月宫, since 吴刚 then waves you up the
# 桂树 and the inner 月宫 stops being a write-off.
USABLE_GATES = set()


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
            grace = time.time() + ROOM_GRACE
            while time.time() < grace:
                extra = api.wait_line(r".+", timeout=ROOM_IDLE)
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


def step_full(api, direction):
    """Move one room. Returns (title, exits, text); title is '' if we
    didn't move (blocked exit, door, sect check, encumbrance).

    Closed doors are opened and the move retried: std/room.lpc:199-216
    refuses with 你必须先把<门名>打开！, and cmds/std/open.lpc:18 accepts
    the direction itself as the target. Without this the walker marks
    the exit permanently impassable and routes the long way round -- or
    gives up, since the only ways into 方寸山 (d/lingtai/gate.lpc) and
    普陀山 (d/nanhai/gate.lpc) are behind closed 石门.
    """
    api.drain()
    api.send(direction, quiet=True)
    title, exits, text = read_room(api)

    if not title and "必须先把" in text and "打开" in text:
        api.log(f"{direction} 有扇门关着，先开门。")
        api.drain()
        api.send(f"open {direction}", quiet=True)
        api.wait_line(r"打开|你要打开什么", timeout=4)
        api.drain()
        api.send(direction, quiet=True)
        title, exits, text = read_room(api)

    if not title and re.search(TOLL_RE, text):
        api.log(f"马盗拦路收买路钱，先给他 {TOLL_SILVER} 两银子。")
        api.drain()
        api.send(f"give {TOLL_SILVER} silver to {TOLL_TARGET}", quiet=True)
        reply = read_reply(api)
        if re.search(TOLL_OK, reply):
            api.drain()
            api.send(direction, quiet=True)
            title, exits, text = read_room(api)
        else:
            api.log(f"钱没给成（{reply.strip().splitlines()[-1] if reply.strip() else '他没反应'}）。"
                    f"身上带够 {TOLL_SILVER} 两银子才走得了西边那半个长安城西。")

    if not title and "座骑" in text:
        # go.lpc:76 -- the mount can't go where we're going, and go.lpc
        # refuses the WHOLE move rather than leaving it behind. Get off
        # and walk. Without this the walker reads a perfectly good exit
        # as permanently shut and routes around it (or gives up on the
        # area) for as long as we stay in the saddle.
        api.log("坐骑过不去，先下马再走。")
        api.drain()
        api.send(f"dismount {RIDE_ID}", quiet=True)
        read_reply(api)
        RIDE["on"] = False
        RIDE["fell_off"] = True
        api.drain()
        api.send(direction, quiet=True)
        title, exits, text = read_room(api)

    return title, exits, text


def step(api, direction):
    """step_full() without the exit list -- what most callers want."""
    title, _, text = step_full(api, direction)
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

# The three ways OUT of 紫竹林, and the room next door that leads back in:
#   zhulin0  south -> road4 小路      (road4 north)
#   zhulin15 north -> pool 池塘边     (pool south)
#   zhulin16/17 enter -> 罗汉塔       (luohanw1 out)
# A sweep that takes any of them the moment it sees one barely searches
# the grove at all -- zhulin0 is where most of the random exits land, so
# the old sweep usually walked straight out on move one or two.
MAZE_REENTRY = {"小路": "north", "池塘边": "south", "罗汉塔": "out"}

# Exit signatures that identify a room with a way out. zhulin0 is the only
# room in the grove whose exits are exactly these three (zhulin1-5 have
# four diagonals, zhulin6-15 have the four compass points), so `south`
# there can be recognised and skipped while sweeping. Rooms with `enter`
# (zhulin16/17) are just as recognisable.
MAZE_DOOR_SIG = frozenset({"northeast", "northwest", "south"})

# 18 rooms, all identical to look at, and the monster wanders while you
# search. A random walk needs well over one move per room to cover them,
# and every step is cheap now (STEP_PAUSE), so budget generously.
MAZE_SWEEP_MOVES = 200
MAZE_REENTRIES = 12       # times to walk back in after falling out


def maze_choices(exits):
    """Directions to try from a maze room, ways out last.

    Keeps the grove's own loops in play and leaves `south`-out-of-zhulin0
    and `enter`-to-罗汉塔 as a last resort, so a sweep spends its budget
    inside instead of escaping on the first move.
    """
    inner, outer = [], []
    for d in exits:
        if d == "enter" or (d == "south" and set(exits) == MAZE_DOOR_SIG):
            outer.append(d)
        else:
            inner.append(d)
    random.shuffle(inner)
    return inner + outer


def sweep_maze(api, maze_name, name, mid, max_moves=MAZE_SWEEP_MOVES):
    """Wander a randomised maze looking for the quest target.

    Returns "found" if the target turned up (caller should fight it),
    "clear" if the budget ran out without finding it, or "" if we got
    stuck. Either way the caller should re-localise afterwards -- we have
    no reliable position inside.

    Falling out of the grove is not the end of the sweep: 紫竹林 has three
    exits and every internal exit is random, so leaving is easy and
    accidental. As long as budget remains we walk back in and carry on.
    """
    api.log(f"{maze_name}是随机迷宫（{max_moves} 步预算），改用地毯式搜索找 {name}。")
    title, exits, text = look(api)
    reentries = 0

    for _ in range(max_moves):
        if api.stopped():
            return ""
        if name in text or mid in text.lower():
            api.log(f"在{maze_name}里发现 {name}！")
            return "found"

        if title != maze_name:
            back = MAZE_REENTRY.get(title)
            if not back or reentries >= MAZE_REENTRIES:
                return "clear"
            reentries += 1
            api.log(f"走出到「{title}」了，从 {back} 拐回{maze_name}接着找"
                    f"（第 {reentries} 次）。")
            title, exits, text = step_full(api, back)
            api.sleep(STEP_PAUSE)
            if not title:
                return "clear"
            continue

        moved = False
        for d in maze_choices(exits):
            got, gexits, gtext = step_full(api, d)
            api.sleep(STEP_PAUSE)
            if not got:
                continue
            title, exits, text, moved = got, gexits, gtext, True
            break
        if not moved:
            return ""

    api.log(f"{maze_name}走了 {max_moves} 步没找到 {name}，先出去。")
    return "clear"


def maze_escape_choice(exits, rng=random):
    """Which way to try next when LEAVING a maze. Look first, then choose.

    The grove's looping exits are built as "zhulin" + random(6) inside
    create(), so each room's southwest lands in a room fixed at load time --
    it is NOT re-rolled per move. That is why a fixed preference order
    cannot work: always taking southwest walks the same deterministic path
    every time, and a deterministic walk in a fixed graph falls into a cycle.
    Observed live as nine identical rooms in a row, going nowhere.

    So: take a real door when the room shows one, and otherwise choose
    UNIFORMLY at random over every exit.

      * zhulin0 is the only room whose exits are exactly northeast,
        northwest and south -- there, south is the door to 小路.
      * zhulin16/17 are the only ones with `enter` (to 罗汉塔).
      * everything else: any exit, with equal probability.

    Preferring the southward diagonals was tried and measured worse, which
    is worth recording because it sounds right: restricting the choice to
    southwest/southeast means northwest and northeast can NEVER be taken, so
    the walk explores a subgraph and gets stuck in it. Over 360 simulated
    escapes from every room of a freshly rolled grove:

        fixed order (the original bug)   242/360 never escaped
        southward diagonals only          42/360
        60% southward, 40% any            11/360
        uniform over all exits             3/360   <- and 0/720 at 150 moves

    Every start CAN reach a door (verified: 0 of 360 are structurally
    trapped), so a walk that fails is a walk that was not allowed to look
    everywhere.
    """
    ex = set(exits)
    if ex == MAZE_DOOR_SIG:
        return "south"
    if "enter" in ex:
        return "enter"
    return rng.choice(sorted(ex)) if ex else ""


# 300. A random walk has an unbounded tail, so no budget GUARANTEES escape --
# what a budget buys is a rate. Measured over 2160 simulated escapes from
# every room of the grove, across three independent RNG runs:
#
#     budget 150   2/2160 stuck    median 7, p99 72, max 129
#     budget 300   0/2160 stuck    median 7, p99 72, max 220
#     budget 500   0/2160 stuck    (no better -- the tail is already covered)
#
# The median escape is 7 moves, so the budget costs nothing in the ordinary
# case and only matters for the unlucky tail. Failing gracefully (say so and
# ask the player) beats giving up at 150 once in five hundred runs.
def escape_maze(api, maze_name="紫竹林", max_moves=300):
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

        # Look, THEN choose -- and choose randomly unless this room is
        # showing an actual door (see maze_escape_choice).
        d = maze_escape_choice(exits)
        if not d:
            api.log(f"{maze_name}这间房间看不到任何出口，重新看一次。")
            continue
        got, _ = step(api, d)
        api.sleep(STEP_PAUSE)
        if got and got != maze_name:
            api.log(f"从 {d} 走出{maze_name}，现在在「{got}」。")
            return got

    api.log(f"走了 {max_moves} 步还没出{maze_name}，放弃，请手动走出来。")
    return ""


def avoided(rooms, path):
    if rooms.get(path, {}).get("short") in AVOID_ROOMS:
        return True
    resident = DANGER.get(path)
    return bool(resident) and _MY_EXP[0] < resident * DANGER_MARGIN


def assess_danger(api):
    """Refresh which lethal rooms this character may enter. Once per job.

    The threshold rises with the character, so nothing is conceded
    permanently: 袁天罡 caps his quests at (daoxing+combat_exp)/2 = 50,000, so
    his questers stay out of almost all of these, while a 李靖 quester with
    millions of 武学 walks in freely and the restriction lifts by itself.
    """
    if not DANGER and DANGER_FILE.exists():
        DANGER.update(json.loads(DANGER_FILE.read_text(encoding="utf-8")))

    _MY_EXP[0] = api.status().get("wuxue", 0)
    if not DANGER:
        return 0
    shut = sum(1 for e in DANGER.values() if _MY_EXP[0] < e * DANGER_MARGIN)
    api.log(f"武学 {_MY_EXP[0]}：{len(DANGER)} 间有主动攻击的房间里，"
            f"{shut} 间暂时绕开（打不过就别进）。")
    return shut


def note_step_failure(api, blocked, pos, direction, text):
    """Remember an exit we could not take. Returns True if the room
    behind it is broken rather than merely shut.

    A compile error is forever (until someone edits the mudlib), so it
    goes in BROKEN_EXITS and every later job starts out avoiding it. A
    door or a sect check only blocks this trip.
    """
    if pos is None:
        return False
    blocked.add((pos, direction))
    if not re.search(BROKEN_RE, text):
        api.log(f"{direction} 走不通，绕路。")
        return False
    if (pos, direction) not in BROKEN_EXITS:
        BROKEN_EXITS.add((pos, direction))
        api.log(f"{pos} 的 {direction} 后面那间房间编译不过"
                "（mudlib 里的语法错误，不是走不过去），以后都绕开。")
    return True


# --------------------------------------------------------------- ride --
def ride_note(api, text, was_at):
    """Read the mount state off a room we just walked into.

    go.lpc:118 tells the rider 你骑着<马>走了过来 on every mounted move,
    so its ABSENCE from an arrival is the signal that the horse stayed
    behind -- whether we got off deliberately (step_full), were put off
    (sleep), or it simply couldn't follow.
    """
    if not RIDE["want"]:
        return
    if RIDE_ARRIVE in text:
        RIDE["on"] = True
        RIDE["left_at"] = None
        RIDE["fell_off"] = False
    elif RIDE["on"] or RIDE["fell_off"]:
        RIDE["fell_off"] = False
        ride_lost(api, was_at)


def ride_lost(api, where, label=None):
    """Note that we're on foot and where the horse is standing."""
    if not RIDE["want"]:
        return
    already_off = not RIDE["on"] and RIDE["left_at"]
    RIDE["on"] = False
    if already_off:
        return
    RIDE["left_at"] = where
    api.log(f"{RIDE['name'] or '坐骑'}留在了{label or where or '刚才那间房'}，"
            "先记下，回头去牵。")


def ride_mount(api):
    """Get on the mount standing in this room. Returns True if we end up
    on it -- including 'we already were', which is how a missed
    你骑着… line self-corrects."""
    if not RIDE_ID:
        return False
    api.drain()
    api.send(f"mount {RIDE_ID}", quiet=True)
    reply = read_reply(api)

    if RIDE_OK in reply or ("你已经" in reply and "上了" in reply):
        was_on = RIDE["on"]
        RIDE["want"] = RIDE["on"] = True
        RIDE["left_at"] = None
        RIDE["fell_off"] = False
        m = re.search(r"[骑坐乘]在(.+?)上", reply)
        if m:
            RIDE["name"] = m.group(1)
        if not was_on and RIDE_OK in reply:
            api.log(f"上马了（{RIDE['name'] or RIDE_ID}）。")
        return True

    RIDE["on"] = False
    return False


def ride_recover(api, rooms, blocked):
    """Go back for a horse we had to leave behind. Returns True if we
    are back on it."""
    where = RIDE["left_at"]
    if not RIDE["want"] or RIDE["on"] or where not in rooms:
        return False
    label = rooms[where]["short"]
    api.log(f"{RIDE['name'] or '坐骑'}还留在{label}，先去牵回来。")
    if not walk_to(api, rooms, blocked, where, label):
        api.log(f"没走到{label}，坐骑先放着吧。")
        return False
    if ride_mount(api):
        return True
    api.log(f"{label}里没找到坐骑，可能被别人牵走了。")
    RIDE["left_at"] = None
    return False


def flee_dirs(word, exits):
    """Exits a 往<word>落荒而逃了 line could mean, best first.

    `exits` is what this room actually offers (map exits, or the names
    `look` printed). When it is known it settles 北边's northup/northdown
    ambiguity and rejects a word that names a runtime-built exit the
    static map never saw -- better to fall back to the ordinary search
    than to walk off in a direction we cannot account for.
    """
    cands = list(CN_DIR.get(word, []))
    if not cands and re.fullmatch(r"[a-z][a-z ]*", word):
        cands = [word]          # an exit go.lpc had no Chinese name for
    if exits:
        return [d for d in cands if d in exits]
    return cands


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


def reachable_from(rooms, start, gated_ok=False, passes=()):
    """Every room you can WALK to from `start`.

    By default this refuses the GATED transitions build_map splices in --
    `dive` (需避水咒), `sleep` (需黄粱枕), `climb tree` (吴刚 only lets
    月宫弟子 past) -- because a room behind one of those is not reachable
    "normally" for this character. Transitions that merely cost something
    everyone has, like `swim`'s 20 气血, are ordinary exits here; they are
    recorded in "special" but not in "gated", so 普陀山 stays searchable.
    """
    seen, q = {start}, deque([start])
    while q:
        cur = q.popleft()
        gates = rooms.get(cur, {}).get("gated", {})
        for d, nxt in rooms.get(cur, {}).get("exits", {}).items():
            if nxt not in rooms or nxt in seen or avoided(rooms, nxt):
                continue
            if not gated_ok and d in gates and d not in USABLE_GATES \
                    and d not in passes:
                continue
            seen.add(nxt)
            q.append(nxt)
    return seen


def route_gates(rooms, start, goals, passes=()):
    """Which gated transitions a route to `goals` would have to use.

    Returns a list of "<command>（<prerequisite>）" strings, [] if a
    perfectly ordinary route exists, or None if there is no route at all.
    """
    if start in goals:
        return []
    path = travel(rooms, start, goals)
    if path is None:
        return None
    gates, cur = [], start
    for d, nxt in path:
        note = rooms.get(cur, {}).get("gated", {}).get(d)
        if note and d not in USABLE_GATES and d not in passes:
            gates.append(f"{d}（{note}）")
        cur = nxt
    return gates


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


def escape_cage(api, tries=CAGE_BREAKS):
    """Get out of 铁笼中, where 石栈道's trapdoor drops anyone who lingers.

    The cage declares no exits (tielong.lpc:12); `out` only appears once
    `break` has accumulated 3000 of force_factor*5+str, at 30 气血 a go.
    A weak character can't buy its way out, so this tries a bounded
    number of times, keeps 气血 in reserve, and otherwise says plainly
    that it needs a hand -- which beats looping 走不到未搜索的房间 for the
    rest of the quest, which is what a map with no exits produces.
    """
    api.log("掉进铁笼里了（石栈道的机关），试着扳开栏杆。")
    for _ in range(tries):
        if api.stopped():
            return False
        st = api.status()
        if st["max_kee"] and st["kee"] * 100 // st["max_kee"] < CAGE_MIN_KEE:
            api.log(f"气血只剩 {st['kee']}/{st['max_kee']} 了，再扳要出人命。")
            break
        api.drain()
        api.send("break", quiet=True)
        r = api.wait_line("钻出去了|已经打开了|铁栏杆", timeout=4)
        if r and ("钻出去" in r.string or "已经打开" in r.string):
            break

    api.drain()
    api.send("out", quiet=True)
    title, _, _ = read_room(api)
    if title and title != CAGE_ROOM:
        api.log(f"钻出铁笼了，现在在「{title}」。")
        return True
    api.log("扳不开铁笼 —— 这个角色力气不够（每扳一次还要掉 30 点气血）。"
            "请手动过来搭把手（/d/westway/tielong，一起 break），"
            "或者先 /stop 我。")
    return False


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
    if title == CAGE_ROOM:
        if not escape_cage(api):
            return None
        title, exits, _ = look(api)
    if title in MAZE_ROOMS:
        # A maze cannot be localised: 紫竹林's 18 rooms share one name and
        # build their exits with random(6) at create() time, so probing just
        # walks in circles -- which is what walking home from the grove did,
        # looping 「紫竹林」有 10 间同名房间，往 east 走一步确认是哪一间 until
        # the walker ran out of retries. Get out first, then localise.
        if not escape_maze(api, title):
            return None
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


def bfs(rooms, inside, start, goals, blocked=frozenset()):
    """Shortest path start -> nearest goal, as [(dir, room), ...].

    `inside` is the set of rooms the sweep may walk through (see
    area_paths) -- the search stays in its area rather than wandering
    off across the map. `blocked` holds (room, direction) pairs already
    found impassable, so the walker stops re-routing through a gate it
    cannot pass.
    """
    if start in goals:
        return []
    seen, q = {start}, deque([(start, [])])
    while q:
        cur, path = q.popleft()
        for d, nxt in rooms.get(cur, {}).get("exits", {}).items():
            if (cur, d) in blocked:
                continue
            if nxt in seen or nxt not in rooms or nxt not in inside:
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
def rest_until_healed(api, rooms, pos, blocked, retreat=True, name=None):
    """Break off, run somewhere quiet, and wait for 气血 to come back.

    Returns (ok, pos). The retreat is a real move now, so the room we
    ran to is the map neighbour we chose -- there is no need to throw
    the position away and re-localise (which costs a `look` plus up to
    fourteen probing steps in a corridor of identically-named rooms,
    all while the monster wanders further off).

    Gives up instead of waiting forever. 气血 regen is not merely slowed
    by thirst but switched off (feature/damage.lpc:465 returns from
    heal_up() before the kee line whenever 饮水 is 0), so "wait longer"
    is not a strategy that can ever succeed -- this loop used to spin
    printing 休息中… at a fixed 50% until the bot was killed by hand.
    So: drink first if we're carrying anything, and bail out if 气血
    stops climbing.

    retreat=False means we are already out of the fight -- the
    character's own env/wimpy walked us out -- so there is nothing to
    break off from and `pos` is whatever the caller still knows
    (usually nothing).

    Returns (status, pos), where status is "ok" (healed, carry on),
    "killed" (the target followed us, the fight restarted by itself and
    it lost -- the job is DONE) or "" (give up). Resting is not a quiet
    place: the aggressive types follow, so this watches for both.
    """
    if retreat:
        api.log("受伤了，撤退。")
        pos = break_off(api, rooms, pos, blocked)
    else:
        api.log("已经脱离战斗，就地休息。")

    stalled, last_kee, gave_ground = 0, -1, 0
    while not api.stopped():
        # Did the fight come with us? The monster's own die() reports the
        # reward to us wherever we are (yg/yaoguai.lpc:134), so a kill
        # that happened while we sat here still counts -- without this
        # the bot spent the rest of the half hour hunting a corpse.
        news = api.wait_line(f"{REWARD_RE}|{re.escape(name)}" if name
                             else REWARD_RE, timeout=0.2)
        if news:
            if re.search(REWARD_RE, news.string):
                api.log("休息的时候它自己追上来送死了，任务完成。")
                return "killed", pos

            # The mud prints the death line BEFORE the reward line, and the
            # death line carries the monster's NAME:
            #     黑狮怪惨叫一声，死了。
            #     你得到了三百二十五点武学经验和一百二十四点潜能！
            # So a name match is not evidence it is alive. Reading only the
            # first matching line made the bot retreat from a corpse and
            # discard the reward behind it, then hunt the corpse for the
            # rest of the quest.
            if name and re.search(DEAD_RE, news.string):
                api.wait_line(REWARD_RE, timeout=REWARD_GRACE)
                api.log(f"{name} 追过来送死了，任务完成。")
                return "killed", pos

            if gave_ground < REST_RETREATS:
                gave_ground += 1
                api.log(f"{name} 追过来了，再退一间房再歇（第 {gave_ground} 次）。")
                pos = break_off(api, rooms, pos, blocked)
                continue
            api.log(f"{name} 一直跟着，退不掉了，就地硬歇着。")

        st = api.status()
        if st["max_kee"] and st["kee"] * 100 // st["max_kee"] >= HP_RESUME:
            api.log("气血已恢复，继续找。")
            return "ok", pos

        if pct(st["water"], st["max_water"]) <= SUSTENANCE_AT:
            water, _ = drink_up(api)
            api.log(f"渴了，先喝口酒（饮水 {water}%）。")

        stalled = stalled + 1 if st["kee"] <= last_kee else 0
        last_kee = st["kee"]
        if stalled >= REST_STALL_LIMIT:
            api.log(f"气血卡在 {st['kee']}/{st['max_kee']} 不动了"
                    f"（食物 {pct(st['food'], st['max_food'])}%、"
                    f"饮水 {pct(st['water'], st['max_water'])}%）。"
                    "饮水见底时气血根本不会恢复，别再干等了。")
            return "", pos

        api.log(f"休息中… 气血 {st['kee']}/{st['max_kee']}，"
                f"{REST_POLL} 秒后再看。")
        api.sleep(REST_POLL)
    return "", pos


def abandon_all_skills(api):
    """Drop every skill the character has picked up.

    Monster difficulty is your HIGHEST skill level scaled by the quest
    level (yaoguai.lpc:317-330), and combat itself raises skills whether
    or not you ever `learn` -- combatd.lpc:497 calls improve_skill() on
    successful hits, which is how a "no skills" character still ended up
    with 基本棍法. Wiping them after each kill keeps
    query_skills() empty, so copy_status() takes its `else max_level = 1`
    branch and monsters stay at the floor.

    Only runs while every skill is still at or below WIPE_MAX_LEVEL: past
    that the character has real training worth keeping, and throwing it
    away is a bigger loss than the difficulty it costs.

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

    # cmds/usr/skills.lpc:52-59 prints one line per skill:
    #   "  基本棍法 (stick)                  - 初学乍练      1/    0"
    # i.e. id in parens, then level/学习进度 at the end of the line.
    levels = {}
    for line in lines:
        m = re.search(r"\(([a-z][a-z0-9_-]*)\).*?(\d+)\s*/\s*(\d+)\s*$", line)
        if m:
            levels.setdefault(m.group(1), int(m.group(2)))
    ids = list(levels)
    if not ids:
        return 0

    top = max(levels.values())
    if top > WIPE_MAX_LEVEL:
        highest = ", ".join(f"{k} {v}" for k, v in
                            sorted(levels.items(), key=lambda kv: -kv[1])[:3])
        api.log(f"最高技能已经 {top} 级（{highest}），超过 {WIPE_MAX_LEVEL}，"
                "不动它们。")
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


def break_off(api, rooms, pos, blocked):
    """Walk out of a fight. Returns the room we end up in, or None if we
    moved somewhere the map didn't predict; `pos` unchanged means every
    exit refused us and we are still standing in the fight.

    See BREAK_OFF_TRIES for why this is a `go` and not a `flee`.
    """
    exits = {}
    if pos in rooms:
        usable = {d: t for d, t in rooms[pos]["exits"].items()
                  if t in rooms and not avoided(rooms, t)}
        # Exits known to be shut go last, not away: `blocked` also holds
        # exits that merely refused us once (a closed door, a swing we
        # hadn't finished), and being cornered in a fight is exactly when
        # a second try is worth making.
        exits = ({d: t for d, t in usable.items() if (pos, d) not in blocked}
                 or usable)
    if not exits:
        # No idea where we are -- take what `look` says the room has and
        # accept that the destination will need re-localising.
        _, seen, _ = look(api)
        exits = dict.fromkeys(seen)

    for d, dest in exits.items():
        for _ in range(BREAK_OFF_TRIES):
            if api.stopped():
                return None
            arrived, text = step(api, d)
            if arrived:
                api.log(f"往 {d} 脱离战斗。")
                ride_note(api, text, pos)
                return dest if dest and arrived == rooms[dest]["short"] else None
            if "动作还没有完成" not in text:
                break            # a real wall; try a different exit
            api.sleep(BREAK_OFF_WAIT)   # mid-swing, ask again in a moment
    api.log("四面都出不去，逃不掉，只能原地硬撑。")
    return pos


def chase(api, rooms, pos, blocked, name, mid, word):
    """Follow a monster that just ran off. Returns (pos, found).

    One hop: go.lpc told us which exit it took, and that is the only
    thing we know for certain. If it isn't there it has moved on under
    its own steam (yg/yaoguai.lpc's chat_msg calls random_move), and the
    ordinary area search resumes -- but from HERE, one room from the
    monster, instead of from wherever a re-localisation left us.
    """
    exits = rooms[pos]["exits"] if pos in rooms else None
    if exits is None:
        _, seen, _ = look(api)
        exits = dict.fromkeys(seen)

    for d in flee_dirs(word, exits):
        if (pos, d) in blocked:
            continue
        arrived, text = step(api, d)
        api.sleep(STEP_PAUSE)
        if not arrived:
            note_step_failure(api, blocked, pos, d, text)
            continue
        ride_note(api, text, pos)
        dest = exits.get(d)
        here = dest if dest in rooms and arrived == rooms[dest]["short"] else None
        return here, (name in text or mid in text.lower())

    api.log(f"「{word}」这个方向地图上没有，改回正常搜索。")
    return pos, False


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
    pos, steps, lost, noroute = None, 0, 0, 0
    warned_gap = False
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
            # Two very different faults print here, and telling them apart
            # is what makes a missing map edge findable. If the position was
            # just re-derived from `look` and there is STILL no route, the
            # map is wrong -- re-localising cannot help, and saying
            # 重新定位 sends the reader hunting for a localisation bug.
            # That is exactly how the one-way 普陀山 swim hid for two
            # sessions behind the identically-named 小路 rooms.
            noroute += 1
            if noroute == 2 and not warned_gap:
                # Say it ONCE and carry on. Giving up here looked tidy and
                # cost a walk in testing: at a 40% shove rate a healthy walk
                # produces transient no-route failures, and the existing
                # WALK_MAX_LOST bound already ends a hopeless one.
                warned_gap = True
                api.log(f"地图上从「{rooms[pos]['short']}」（{pos}）找不到到"
                        f"{label}的路 —— 如果一直这样，多半是地图缺边"
                        "（看 build_map.py 的 SPECIAL_EXITS），不是定位错。")
            api.log(f"从「{rooms[pos]['short']}」暂时找不到去{label}的路，"
                    "重新定位后再试一次。")
            reason = "地图上没有路线"
            pos, lost = None, lost + 1
            continue

        direction, nxt = leg[0]
        here_before = pos
        arrived, text = step(api, direction)
        api.sleep(STEP_PAUSE)
        steps += 1

        if arrived == rooms[nxt]["short"]:
            ride_note(api, text, here_before)
            noroute = 0
            pos = nxt
        elif not arrived:
            # Confirm where we actually are before blaming the exit.
            # Marking (pos, direction) impassable while pos is a drifted
            # guess poisons the route graph for the rest of the quest:
            # every later travel() detours around a gate that was never
            # really shut, until no route home survives at all.
            here = relocalise(api, rooms)
            if here is not None and direction in rooms[here]["exits"]:
                note_step_failure(api, blocked, here, direction, text)
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
    """Top 食物/饮水 back up if either is at or below SUSTENANCE_AT.

    Called at 天监台 between quests, because that is the one point in the
    cycle where position is known, nothing is chasing us, and a detour
    costs no quest time. Ends back at 天监台; returns False only if it
    could not get back there.
    """
    food, water, st = sustenance(api)
    if not st["max_food"] or not st["max_water"]:
        api.log("警告：看不懂 hp 的食物/饮水上限，跳过补给。")
        return True
    if food > SUSTENANCE_AT and water > SUSTENANCE_AT:
        return True

    api.log(f"食物 {food}%、饮水 {water}% —— 先补给。"
            "（饮水见底时气血完全不会恢复。）")

    # Inventory first: no walking needed if we're already carrying some.
    if water <= SUSTENANCE_AT:
        water, _ = drink_up(api)
    if food <= SUSTENANCE_AT:
        food, _ = eat_up(api)
    if food > SUSTENANCE_AT and water > SUSTENANCE_AT:
        api.log(f"补给完毕：食物 {food}%、饮水 {water}%。")
        return True

    restock(api, rooms, blocked, food <= SUSTENANCE_AT, water <= SUSTENANCE_AT)

    food, water, _ = sustenance(api)
    api.log(f"补给完毕：食物 {food}%、饮水 {water}%。")
    if food <= SUSTENANCE_AT or water <= SUSTENANCE_AT:
        api.log("警告：还是没吃饱喝足，气血恢复可能会很慢甚至停住。")
    return walk_back_to_yuan(api, rooms, blocked)


# ---------------------------------------------------------- gate passes --
# Two of the ten spawn areas sit behind a prerequisite rather than a wall,
# and both prerequisites are things a character can simply go and get. So
# instead of writing those jobs off, the bot earns the pass and goes.
#
#   龙宫 (d/sea)  -- 避水咒. 袁守诚 (d/city/caotang.lpc, 袁氏草堂) trades
#       〖无字天书〗 for a 桂花酒袋 (npc/shouchen.lpc:174-181), and tearing
#       the book open yields the 咒 (d/obj/book/nowords.lpc:41-47). The 咒
#       is NOT consumed by do_dive() -- it only checks present() -- so one
#       lasts forever.
#   红楼一梦 (d/ourhome/honglou) -- 黄粱枕, carried by 卢生 in 泾水之滨
#       (d/changan/wside3). Sleep in any sleep_room holding it and
#       wakeup1() (cmds/std/sleep.lpc:184-195) drops you into the dream.
#       The pillow IS destroyed on the way in, so this is redone per job.
CAOTANG_ROOM = "d/city/caotang"      # 袁氏草堂 -- 袁守诚
LUSHENG_ROOM = "d/changan/wside3"    # 泾水之滨 -- 卢生, 100 exp, peaceful
SLEEP_ROOM = "d/city/sleep"          # 客店睡房, east of 南城客栈
RENT_SILVER = 3                      # xiaoer.lpc:139 wants >= 300 文
DREAM_ROOM = "d/ourhome/honglou/kat"   # 荡悠悠三更梦 -- where you wake up
SLEEP_WAIT = 75                      # sleep.lpc:86 -- call_out up to 10+45s


def carrying(api, keyword):
    """Is `keyword` in our inventory right now?"""
    api.drain()
    api.send("i", quiet=True)
    return keyword in read_reply(api)


def buy_one_jiudai(api, rooms, blocked):
    """A 桂花酒袋 in hand, with a bank trip if we're short."""
    if not walk_to(api, rooms, blocked, KEZHAN_ROOM, "南城客栈"):
        return False
    result = buy_from_xiaoer(api, "jiudai", "桂花酒袋")
    if result == "broke":
        if not withdraw_at_bank(api, rooms, blocked):
            return False
        if not walk_to(api, rooms, blocked, KEZHAN_ROOM, "南城客栈"):
            return False
        result = buy_from_xiaoer(api, "jiudai", "桂花酒袋")
    return result == "ok"


def get_bishuizhou(api, rooms, blocked):
    """Earn the 避水咒 that opens the dive into 龙宫."""
    if carrying(api, "避水咒"):
        return True
    api.log("要下东海得有避水咒，先去办：买桂花酒袋 -> 送袁守诚 -> 撕天书。")

    if not carrying(api, "无字天书"):
        if not buy_one_jiudai(api, rooms, blocked):
            api.log("买不到桂花酒袋，拿不到避水咒。")
            return False
        if not walk_to(api, rooms, blocked, CAOTANG_ROOM, "袁氏草堂"):
            return False
        api.drain()
        api.send("give jiudai to yuan", quiet=True)
        reply = read_reply(api)
        if "无字天书" not in reply and not carrying(api, "无字天书"):
            api.log(f"袁守诚没收酒袋：{reply.strip().splitlines()[-1] if reply.strip() else '没有回应'}")
            return False
        api.log("袁守诚收了酒袋，回赠〖无字天书〗。")

    api.drain()
    api.send("tear book", quiet=True)
    read_reply(api)
    if carrying(api, "避水咒"):
        api.log("撕开天书，拿到避水咒了。")
        return True
    api.log("撕天书没拿到避水咒。")
    return False


def get_pillow(api, rooms, blocked):
    """Take a 黄粱枕 off 卢生 -- the way into 红楼一梦."""
    if carrying(api, "黄粱枕"):
        return True
    api.log("要进红楼一梦得有黄粱枕，先去泾水之滨找卢生。")
    if not walk_to(api, rooms, blocked, LUSHENG_ROOM, "泾水之滨"):
        return False

    api.drain()
    api.send("kill lu sheng")
    deadline = time.time() + FIGHT_TIMEOUT
    dead = False
    while time.time() < deadline and not api.stopped():
        m = api.wait_line(f"{DEAD_RE}|{RETREAT_RE}|这里没有这个人", timeout=5)
        if not m:
            continue
        if "这里没有这个人" in m.string:
            api.log("卢生不在（可能刚被人杀过），等下一轮再试。")
            return False
        if re.search(DEAD_RE, m.string):
            dead = True
            break
        if re.search(RETREAT_RE, m.string) and "你" in m.string and "卢生" not in m.string:
            api.log("打卢生居然打不过，撤。")
            return False
    if not dead:
        return False

    api.drain()
    api.send("get pillow from corpse", quiet=True)
    read_reply(api)
    if carrying(api, "黄粱枕"):
        api.log("拿到黄粱枕了。")
        return True
    api.log("尸体上没摸到黄粱枕。")
    return False


def enter_dream(api, rooms, blocked):
    """Pillow in hand, rent paid, asleep -- and wake up in 红楼一梦.

    Unlike the 避水咒 this is the journey itself, not just a pass: the
    dream is entered by waking (sleep.lpc:184-195), so the walker can
    never do it as a plain step -- 10 to 55 seconds pass with the player
    disabled, far longer than a room read waits.
    """
    if not get_pillow(api, rooms, blocked):
        return False
    if not walk_to(api, rooms, blocked, KEZHAN_ROOM, "南城客栈"):
        return False

    # 店小二 wants >= 300 文 before he'll let anyone past into the 睡房.
    api.drain()
    api.send(f"give {RENT_SILVER} silver to {VENDOR}", quiet=True)
    reply = read_reply(api)
    if "客官请上房歇息" not in reply:
        if "你身上没有这样东西" in reply or "你没有那么多" in reply:
            if not withdraw_at_bank(api, rooms, blocked):
                return False
            if not walk_to(api, rooms, blocked, KEZHAN_ROOM, "南城客栈"):
                return False
            api.drain()
            api.send(f"give {RENT_SILVER} silver to {VENDOR}", quiet=True)
            reply = read_reply(api)
        if "客官请上房歇息" not in reply:
            api.log("店钱没给成，进不了睡房。")
            return False
    api.log(f"付了 {RENT_SILVER} 两店钱。")

    arrived, _ = step(api, "east")
    api.sleep(STEP_PAUSE)
    if arrived != rooms[SLEEP_ROOM]["short"]:
        api.log("进不了客店睡房。")
        return False

    return sleep_into_dream(api, rooms)


def sleep_into_dream(api, rooms):
    """Sleep in the 客店睡房 with the 黄粱枕 and wake up in 红楼一梦.

    Returns True once we are standing in the dream.
    """
    api.drain()
    api.send("sleep", quiet=True)

    # sleep.lpc:64-77 answers 你往被中一钻…你就进入了梦乡, then
    # disable_player()s us for random(45-con)+10 seconds before wakeup1()
    # runs. The pillow's own 进入了梦的世界 line NEVER reaches the player:
    # pillow.lpc:26 tell_object()s it to the room object, not to us. This
    # code waited for exactly that string, so every attempt at 红楼一梦
    # ended in "睡下去就没下文了" and the job was thrown away.
    #
    # What we actually see is the dream room itself -- wakeup1()
    # (sleep.lpc:195) moves us into d/ourhome/honglou/kat and its
    # description is printed on arrival. If the pillow somehow didn't
    # fire we get 你一觉醒来 and are still in the 睡房 instead.
    dream = rooms[DREAM_ROOM]["short"] if DREAM_ROOM in rooms else "荡悠悠三更梦"
    m = api.wait_line(f"{re.escape(dream)}|一觉醒来|进入了梦的世界"
                      "|这里不是睡觉的地方|你刚睡过一觉|你正忙着呢"
                      "|战斗中不能睡觉|精神太差|气血不足",
                      timeout=SLEEP_WAIT)
    if not m:
        api.log("睡下去就没下文了，放弃这一轮。")
        return False
    if dream not in m.string and "进入了梦的世界" not in m.string:
        api.log(f"没能入梦：{m.string.strip()}")
        return False
    read_reply(api, timeout=2.0)

    # sleep.lpc:79-83 takes you off the horse before the dream, and the
    # horse stays in the 睡房 -- 红楼一梦 is entered on foot whatever you
    # rode in on. Remember where it is so it can be collected afterwards.
    ride_lost(api, SLEEP_ROOM,
              rooms[SLEEP_ROOM]["short"] if SLEEP_ROOM in rooms else None)
    api.log(f"入梦了，人已经在红楼一梦（{dream}）里。")
    return True


# The dive into 龙宫 (d/changan/eastseashore.lpc:127-130) opens for a 避水咒
# with unit 张 OR for family 龙宫 / 东海龙宫. cmds/usr/title.lpc:14 prints
# 你目前的头衔及门派 followed by the rank and short(1), which carries the
# sect, so one `title` answers whether we are a disciple. Cached: it cannot
# change mid-session without a 拜师.
DRAGON_FAMILIES = ("龙宫", "东海龙宫")
_TITLE_CACHE = {}


def player_title(api):
    """The player's title line, which names their 门派. Read once."""
    if "title" not in _TITLE_CACHE:
        api.drain()
        api.send("title", quiet=True)
        _TITLE_CACHE["title"] = read_reply(api)
    return _TITLE_CACHE["title"]


def is_dragon_disciple(api):
    return any(f in player_title(api) for f in DRAGON_FAMILIES)


# Gate command -> how to earn it. Returning True means the route through
# that transition is open for THIS job.
GATE_PREP = {
    "dive": get_bishuizhou,
    "sleep": enter_dream,
}


def wait_for_exit(api, name, timeout):
    """Watch for `name` walking out of the room we're both in.

    Returns the Chinese direction from go.lpc:88, or None if it stayed.
    """
    m = api.wait_line(f"{re.escape(name)}.{{0,16}}?{LEAVE_RE}", timeout=timeout)
    return m.group(1) if m else None


def wimpy_fizzled(api):
    """After 看来该找机会逃跑了, did the flee actually fail?

    Returns True if we're still standing in the fight. The two failure
    lines (go.lpc:142, :146) are printed immediately; a successful flee
    prints the new room instead, so a short listen tells them apart.
    """
    deadline = time.time() + WIMPY_SETTLE
    while time.time() < deadline:
        m = api.wait_line(f"{WIMPY_FAIL_RE}|.+", timeout=WIMPY_SETTLE)
        if not m:
            break
        if re.search(WIMPY_FAIL_RE, m.string):
            return True
    return False


def fight_target(api, mid, name):
    """Attack, watching for the retreat triggers. Returns 'killed',
    'hurt', 'lost', 'wimpy', 'nofight', 'intruder:<name>' or
    'fled:<方向>'."""
    api.drain()
    api.send(f"kill {mid}")
    deadline = time.time() + FIGHT_TIMEOUT
    while time.time() < deadline and not api.stopped():
        m = api.wait_line(
            f"{REWARD_RE}|{RETREAT_RE}|{DEAD_RE}|{FLEE_RE}|{WIMPY_RE}"
            f"|{NOFIGHT_RE}|这里没有这个人|{INTRUDER_RE}",
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
        # A peace room: the kill never even started, so there is nothing
        # to wait out. Without this the loop sat here for the full
        # FIGHT_TIMEOUT while the monster strolled off.
        if re.search(NOFIGHT_RE, line):
            return "nofight"

        # Someone other than the quest target started on us.
        bad = re.search(INTRUDER_RE, line)
        if bad:
            who = (bad.group(1) or bad.group(2) or "").strip()
            if who and name not in who and who not in name:
                return f"intruder:{who}"
        # It bolted. Without this the fight loop sat there re-reading an
        # empty room until FIGHT_TIMEOUT (three minutes) and then called
        # the monster "lost" -- by which time it was several random_moves
        # away and the whole area had to be searched again.
        ran = re.search(FLEE_RE, line)
        if ran and name and name in line:
            return "fled:" + ran.group(1)

        # WE ran, on our own env/wimpy. Which exit do_flee() picked is
        # never told to us -- go.lpc:100 tells the room we LEFT -- so
        # there is no direction to record, only the fact that we are
        # somewhere else now and out of the fight (go.lpc:105 calls
        # remove_all_enemy on a successful move).
        if re.search(WIMPY_RE, line):
            if wimpy_fizzled(api):
                continue           # 逃跑失败 / 被定住: still toe to toe
            return "wimpy"

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
    pending_told = None     # target of the last "还没交差" message

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
            # Said once per target: this branch is also where a job we
            # gave up on lands, and it is re-entered every GIVEUP_POLL
            # seconds until the timer runs out -- fifteen copies of the
            # same paragraph is not information.
            if who != pending_told:
                api.log(f"上一个任务（{who}）还没交差，袁天罡最多再等 "
                        f"{QUEST_SECS // 60} 分钟才会换新的。"
                        "我先在原地盯着，看到它就动手；你也可以自己去找它。")
                pending_told = who
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
                api.log(f"地图里找不到【{place}】，无法自动搜索。")
                dirs = []

        # ---- can we even get there? -----------------------------------
        # Checked BEFORE walking, from 天监台, because the alternative is
        # what actually happened at 湖边 (d/moon/lotuspond): the room sits
        # behind `climb tree` at 玉女峰顶, which 吴刚 refuses to anyone
        # outside 月宫, so the walker burned the full 30 minutes looping
        # "从这里走不到未搜索的房间，重新定位" in 崎岖小路. If the target
        # is only reachable through a gated transition -- or not on the
        # map at all -- the job is a write-off: sit tight and keep asking
        # until 袁天罡's 30-minute timer lapses and he issues a new one.
        # (The abandoned job costs one difficulty level, yuantiangang.lpc
        # :137-143, which is a fair price for not wasting half an hour.)
        inside = area_paths(rooms, dirs, place) if dirs else set()
        if inside and len(inside) > sum(1 for p in rooms
                                        if rooms[p]["area"] in dirs):
            api.log(f"（搜索范围含 {len(AREA_EXTRA.get(place, ()))} 间邻区房间，"
                    "妖怪会走出区界。）")

        if targets:
            goal_rooms = set(targets)      # he named the room itself
        elif dirs:
            goal_rooms = {p for p in inside
                          if rooms[p]["short"] not in AVOID_ROOMS
                          and not rooms[p]["flags"].get("no_mieyao")}
        else:
            goal_rooms = set()

        passes = set()
        walkable = reachable_from(rooms, YUAN_ROOM)
        gates = route_gates(rooms, YUAN_ROOM, goal_rooms) if goal_rooms else None

        # Some gates aren't walls, they're errands: 避水咒 for 龙宫,
        # 黄粱枕 for 红楼一梦. Run the errand, then re-check.
        if not (goal_rooms & walkable) and gates:
            wanted = [g.split("（")[0] for g in gates]
            if all(w in GATE_PREP for w in wanted):
                for w in wanted:
                    if api.stopped():
                        return
                    # 龙宫 by request: treat non-disciples as hard-gated
                    # rather than running the 避水咒 errand. The mudlib does
                    # allow a 避水咒 (eastseashore.lpc:127-130), so this
                    # gives up jobs that are winnable -- deliberate.
                    if w == "dive" and not is_dragon_disciple(api):
                        api.log("不是龙宫弟子，龙宫这条路按硬关卡处理"
                                "（和吴刚的桂树一样），这趟不去了。")
                        break
                    if GATE_PREP[w](api, rooms, set()):
                        passes.add(w)
                    else:
                        break
                walkable = reachable_from(rooms, YUAN_ROOM, passes=passes)
                gates = route_gates(rooms, YUAN_ROOM, goal_rooms, passes=passes)

        if not (goal_rooms & walkable):
            if gates:
                why = "要" + "、".join(gates)
            elif gates == []:
                why = "路上有绕不开的关卡"
            else:
                why = "地图上根本没有路"
            api.log(f"【{place}】从天监台走不过去（{why}），这趟不去了。"
                    f"每 {GIVEUP_POLL} 秒问一次袁天罡，等这个任务超时后换新的"
                    "（你也可以自己过去打，我在这边等着）。")
            api.sleep(GIVEUP_POLL)
            continue

        # Get on the horse before setting off: it is worth a chunk of
        # dodge (mount.lpc:59) to a character that deliberately has no
        # skills. Only asked once unless we know there IS a horse -- if
        # the player doesn't ride, 你想骑什么 comes back and that's that.
        if RIDE_ID and (RIDE["want"] or jobs == 1):
            ride_mount(api)
        assess_danger(api)

        started = time.time()
        killed = False
        pos = None
        visited = set()
        blocked = set(BROKEN_EXITS)
        found_here = False
        warned_unreachable = False
        unreachable = 0
        sweeps = 0
        chases = 0
        last_seen = None       # where the target was last actually seen
        widened = False        # search past the region after a break in contact
        wimpies = 0
        peace = 0

        # ---- hunt -----------------------------------------------------
        while (not api.stopped()
               and time.time() - started < QUEST_SECS - HOMEWARD_RESERVE):
            # Is it right here? Either queued output mentions it, or the
            # last move's room description did. The reward line is in
            # there too: the target can die without us ever sending
            # another `kill` -- it follows us out of the room, the fight
            # restarts on heart_beat and it loses -- and the bot used to
            # go on searching for the corpse until the half hour ran out.
            hit = None
            if not found_here:
                hit = api.wait_line(
                    f"{REWARD_RE}|{re.escape(name)}|{re.escape(mid)}",
                    timeout=1)
                if hit and re.search(REWARD_RE, hit.string):
                    api.log(f"{name} 已经死了（奖励到手了），不用再找。")
                    killed = True
                    if ABANDON_SKILLS_AFTER_KILL:
                        abandon_all_skills(api)
                    break
            if found_here or hit:
                found_here = False
                if pos:
                    last_seen = pos
                if pos and rooms[pos]["short"] in TRAP_ROOMS:
                    # Standing here is what springs the trapdoor. Use the
                    # peace-room handling: watch which way it goes and
                    # take it next door.
                    api.log(f"{name} 在{rooms[pos]['short']}，这里有机关"
                            "（待久了会掉进铁笼），不在这儿动手。")
                    r = "nofight"
                else:
                    api.log(f"发现 {name}，动手！")
                    r = fight_target(api, mid, name)
                if r == "killed":
                    api.log(f"击杀 {name} 成功！")
                    killed = True
                    if ABANDON_SKILLS_AFTER_KILL:
                        abandon_all_skills(api)
                    break
                if r == "hurt":
                    fight_pos = pos
                    rested, pos = rest_until_healed(api, rooms, pos, blocked,
                                                    name=name)
                    if not rested:
                        return
                    if rested == "killed":
                        killed = True
                        if ABANDON_SKILLS_AFTER_KILL:
                            abandon_all_skills(api)
                        break
                    # The monster is still standing where we left it
                    # (only the aggressive types follow), so un-tick that
                    # room: it becomes the nearest unsearched goal and
                    # the ordinary walker takes us straight back to
                    # finish the job, one step away.
                    widened = True
                    visited.discard(fight_pos)
                    if pos and pos != fight_pos:
                        visited.add(pos)
                    continue
                if r == "nofight":
                    peace += 1
                    trap = bool(pos and rooms[pos]["short"] in TRAP_ROOMS)
                    if not trap:
                        api.log(f"{name} 站在不准战斗的房间里，打不了。"
                                "等它自己挪窝，跟出去再打。")
                    word = wait_for_exit(api, name,
                                         TRAP_WAIT if trap else NOFIGHT_WAIT)
                    if word:
                        api.log(f"{name} 往{word}走了，跟上。")
                        pos, found_here = chase(api, rooms, pos, blocked,
                                                name, mid, word)
                        if pos:
                            visited.add(pos)
                        continue
                    if pos and peace <= NOFIGHT_TRIES:
                        # check_room()'s call_out is armed by init(),
                        # which only runs when someone walks IN. Step out
                        # and let the walker bring us back -- that's the
                        # nudge that moves it.
                        api.log("它赖着不动，我先出去，再进来一次。")
                        visited.discard(pos)
                        away, _ = retreat_one_room(api, rooms, pos, blocked)
                        pos = away
                        continue
                    api.log(f"{name} 一直待在不能动手的地方，先去别处找，"
                            "回头再来看。")
                    if pos:
                        visited.add(pos)
                    continue
                if r == "wimpy":
                    # Same situation as "hurt", minus the retreat: the
                    # wimpy check already walked us out, through an exit
                    # nobody told us about. So rest, forget where we
                    # think we are, and let the walker route back to the
                    # room the monster is still in.
                    fight_pos = pos
                    wimpies += 1
                    api.log(f"气血/精神掉到 wimpy 线，自动逃出了战斗"
                            f"（第 {wimpies} 次），先休息再回去。")
                    rested, _ = rest_until_healed(api, rooms, None, blocked,
                                                  retreat=False, name=name)
                    if not rested:
                        return
                    if rested == "killed":
                        killed = True
                        if ABANDON_SKILLS_AFTER_KILL:
                            abandon_all_skills(api)
                        break
                    pos = None          # do_flee picked the exit, not us
                    widened = True
                    visited.discard(fight_pos)
                    if wimpies >= WIMPY_LIMIT:
                        api.log(f"这一趟已经被 wimpy 拽出战斗 {wimpies} 次了。"
                                "wimpy 设得比 HP_RESUME("
                                f"{HP_RESUME}%) 高的话，打一下就跑，"
                                "永远打不完 —— 用 wimpy <数字> 调低一点。")
                    continue
                if r.startswith("fled:"):
                    word = r.split(":", 1)[1]
                    chases += 1
                    if chases > CHASE_MAX:
                        api.log(f"{name} 已经跑了 {CHASE_MAX} 次，不追了，"
                                "改为在这一带正常搜索。")
                        pos = None
                        continue
                    api.log(f"{name} 往{word}逃了，追（第 {chases} 次）。")
                    pos, found_here = chase(api, rooms, pos, blocked,
                                            name, mid, word)
                    if found_here and pos:
                        last_seen = pos
                    else:
                        widened = True
                    if pos:
                        visited.add(pos)
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

            # After a break in contact, search outward from where the thing
            # actually was, not just inside the region 袁天罡 named.
            search = inside
            if widened and last_seen:
                search = inside | nearby(rooms, last_seen, ESCAPE_RADIUS)

            # Not in the target area yet? Walk there first.
            if pos not in search:
                leg = travel(rooms, pos, search, blocked)
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
                    here_before = pos
                    arrived, seen_text = step(api, d)
                    api.sleep(STEP_PAUSE)
                    if arrived == rooms[dest]["short"]:
                        ride_note(api, seen_text, here_before)
                    if name in seen_text or mid in seen_text.lower():
                        found_here = True
                        break
                    if arrived == rooms[dest]["short"]:
                        pos = dest
                    elif not arrived:
                        note_step_failure(api, blocked, pos, d, seen_text)
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
                goals = {p for p in search
                         if p not in visited
                         and rooms[p]["short"] not in AVOID_ROOMS
                         and not rooms[p]["flags"].get("no_mieyao")}
            if not goals:
                sweeps += 1
                left = int(QUEST_SECS - HOMEWARD_RESERVE
                           - (time.time() - started))
                api.log(f"【{place}】第 {sweeps} 遍搜完了，没找到 {name}，"
                        f"再搜一遍（还剩 {max(0, left // 60)} 分钟）。")
                visited = {pos}
                continue
            path = bfs(rooms, search, pos, goals, blocked)
            if path is None and targets:
                # The named room itself is unreachable from here. That
                # is not a localisation error and re-localising cannot
                # fix it: 湖边 (d/moon/lotuspond) and the rest of the
                # inner 月宫 sit behind `climb tree` at 玉女峰顶, which
                # 吴刚 refuses to non-月宫 disciples, so BFS to the sole
                # goal returned None from 崎岖小路 every single round.
                # Widen to the whole area instead -- the monster wanders
                # (yaoguai.lpc chat_msg -> random_move), so it may well
                # come out to somewhere we CAN walk to.
                api.log(f"走不到【{place}】本身（要爬树/特殊方式进入，"
                        "或路被拦住了），改为搜索整个区域，等它自己出来。")
                targets = None
                continue
            if path is None:
                # Usually we just mislocalised, so relocalise and retry.
                # If even the widened area search keeps failing, stop
                # resetting every 2s -- say so once and watch instead.
                unreachable += 1
                if unreachable < 3:
                    api.log("从这里走不到未搜索的房间，重新定位。")
                    pos, visited = None, set()
                    api.sleep(2)
                    continue
                if not warned_unreachable:
                    api.log(f"【{place}】所在区域里剩下的房间从这里都走不到。"
                            "我在原地盯着，看到它就动手；你也可以手动过去。")
                    warned_unreachable = True
                api.sleep(5)
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

            unreachable = 0          # we can still get somewhere new
            direction, dest = path[0]
            here_before = pos
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
                ride_note(api, seen_text, here_before)
                pos = dest
                visited.add(dest)
                # The horse we had to leave behind is standing in some
                # room of this area; if the search walks past it, get
                # back on rather than making a special trip later.
                if (RIDE["want"] and not RIDE["on"] and RIDE["name"]
                        and RIDE["name"] in seen_text):
                    ride_mount(api)
            elif not arrived:
                # Never moved: the exit is gated (a door, valid_leave, a
                # sect check, over-encumbrance) or the room behind it
                # doesn't compile. Remember it so BFS stops routing
                # through it -- this is what desynced the walker in live
                # testing, where 南城客栈's `east` is blocked until
                # you've paid the innkeeper.
                note_step_failure(api, blocked, pos, direction, seen_text)
            else:
                # Moved, but not where the map predicted (wandering
                # monster shoved us, teleport, one-way exit). Re-localise.
                api.log(f"到了「{arrived}」，和地图不符，重新定位。")
                pos = None

        if not killed:
            api.log(f"搜了 {sweeps} 遍没找到 {name}。趁着最后几分钟先回天监台，"
                    "到点好接下一个任务（这一趟难度降一级）。")

        # ---- collect the horse, then walk back to 袁天罡 --------------
        # Done before the return walk, not after: 客店睡房 (where 红楼一梦
        # takes it off us) is four rooms from 天监台 and on the way, and
        # 袁天罡's post-success cooldown is running regardless.
        if not api.stopped():
            ride_recover(api, rooms, blocked)

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
