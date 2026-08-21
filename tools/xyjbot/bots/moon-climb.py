# moon-climb -- climb the 桂树 at 玉女峰顶 (月宫), training dodge.
#
# Run in-game with: /run moon-climb   (stop with /stop moon-climb)
# You must already be standing in 玉女峰顶 (d/moon/ontop2.lpc) -- climb
# is a room action, so anywhere else the mud just answers 爬什么？.
#
# From do_climb() in d/moon/ontop2.lpc, four distinct outcomes:
#
#   1. "你身子发虚，一头栽了下来，哎呀！"
#      kee < max_kee/3 -- can't climb right now. This is the specific
#      "cannot climb" case you asked about: rest REST_SECS, then retry.
#      Note it also costs 20% max_kee on this failure (receive_damage
#      fires before the notify_fail) -- and if kee was already close to
#      0, that hit can push it negative. The driver's own heartbeat
#      (std/char.lpc:76) catches negative kee on the NEXT tick and knocks
#      you out cold via unconcious() (feature/damage.lpc:239) for
#      random(100-con)+30 seconds, disabled the whole time. A pre-climb
#      hp check (MIN_HP_PCT below) keeps the bot well clear of that
#      threshold instead of discovering it reactively.
#
#   2. "吴刚拦道：此间并非戏耍之处，请勿骚扰我仙家清修"
#      吴刚 blocks you -- happens on every attempt unless you're in the
#      月宫 sect (family/family_name == "月宫") or he's not there. Kee
#      shortage doesn't cause this and rest won't fix it, so it counts
#      toward MAX_FAILS instead of the 60s rest.
#
#   3. "你领悟出一些基本轻功方面的窍门。"
#      Success -- dodge skill improved. Keep going.
#
#   4. "纵身往桂树上一跳，接着爬入树丛中不见了。"
#      dodge >= 40 (or moondance >= 80): you no longer benefit from
#      climbing, and the room MOVES you into the tree (tree1.lpc) --
#      further "climb tree" calls from here would just fail with 爬什么？
#      since you're not in 玉女峰顶 anymore. This is the actual "to max"
#      finish line, same convention as dazuo/mingsi's 瓶颈 stop.

REST_SECS = 60   # wait this long after "你身子发虚" before retrying
MAX_FAILS = 3    # consecutive non-kee blocks (吴刚, busy, wrong room) before giving up
CLIMB_DELAY = 0.1   # seconds between one climb finishing and the next starting
MIN_HP_PCT = 50  # require current 气血 >= this % of max before attempting a climb

LOW_KEE = r"你身子发虚，一头栽了下来"
BLOCKED = r"吴刚拦道"
SUCCESS = r"你领悟出一些基本轻功方面的窍门"
CEILING = r"纵身往桂树上一跳"
OTHER_FAIL = r"爬什么？|你现在正忙着呢"


def run(api):
    fails = 0
    climbs = 0

    while not api.stopped():
        api.sleep(CLIMB_DELAY)

        cur, mx, pct = api.hp(quiet=False)
        if mx and pct < MIN_HP_PCT:
            api.log(f"气血 {cur}/{mx} ({pct}%) 低于 {MIN_HP_PCT}%，休息 {REST_SECS} 秒再爬。")
            api.sleep(REST_SECS)
            continue

        api.drain()
        api.send("climb tree")

        m = api.wait_line(f"{LOW_KEE}|{BLOCKED}|{SUCCESS}|{CEILING}|{OTHER_FAIL}",
                           timeout=5)
        if not m:
            fails += 1
            api.log(f"climb 没有反应（第 {fails} 次）。")
            if fails >= MAX_FAILS:
                api.log("连续失败，停止。")
                return
            api.sleep(5)
            continue

        text = m.group(0)

        if "纵身往桂树上一跳" in text:
            api.log(f"爬了 {climbs} 次后轻功已经练满，你跳进树丛不见了，停止。")
            return

        if "你领悟出" in text:
            climbs += 1
            fails = 0
            api.log(f"第 {climbs} 次领悟了轻功窍门。")
            continue

        if "你身子发虚" in text:
            api.log(f"气不够，栽了下来，休息 {REST_SECS} 秒。")
            api.sleep(REST_SECS)
            continue

        if "吴刚拦道" in text:
            fails += 1
            api.log(f"吴刚拦住了你（第 {fails} 次）。")
            if fails >= MAX_FAILS:
                api.log("连续被吴刚拦住，停止。除非你是月宫弟子，否则他一直会挡着。")
                return
            api.sleep(5)
            continue

        # OTHER_FAIL: wrong room / busy / bad arg.
        fails += 1
        api.log(f"climb 被拒绝：{text}（第 {fails} 次）")
        if fails >= MAX_FAILS:
            api.log("连续失败，停止。请确认你站在玉女峰顶。")
            return
        api.sleep(5)
