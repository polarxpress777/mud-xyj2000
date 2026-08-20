# qigan-bot -- climb the 旗杆 in 傲来国, backing off when HP gets low.
#
# Run in-game with: /run qigan-bot   (stop with /stop qigan-bot)
#
# Loop:
#   1. climb qigan, CLIMBS_PER_ROUND times
#   2. hp -- check current 气血 against max
#   3. if HP >= REST_BELOW%, go straight back to step 1
#      otherwise rest REST_SECS before climbing again
#
# Deliberately does NOT use the mud's "climb qigan#5" repeat syntax:
# feature/alias.lpc drains a #N batch one command per second AND cancels
# any batch still in flight the moment another input line arrives, so the
# bot's own `hp` poll would silently kill the remaining climbs. Looping
# here instead keeps the count exact and the timing ours.
#
# You must already be standing where the 旗杆 is -- `climb` is a room
# action, so anywhere else the mud just answers 什么？.

CLIMBS_PER_ROUND = 5
REST_BELOW = 50   # percent of max 气血
REST_SECS = 60
MAX_FAILS = 3

CLIMBED = r"顺着旗杆向上爬去"
REJECTED = r"什么？|你要爬什么|无法执行"


def run(api):
    fails = 0

    while not api.stopped():
        done = 0
        for _ in range(CLIMBS_PER_ROUND):
            if api.stopped():
                return
            api.drain()
            api.send("climb qigan")
            # do_climb() is synchronous (d/dntg/hgs/center.lpc) -- it
            # echoes and finishes in the same call, so the echo arriving
            # is proof the climb actually happened.
            if api.wait_line(CLIMBED, timeout=5):
                done += 1
                continue
            fails += 1
            api.log(f"climb 没有反应或被拒绝（第 {fails} 次）。")
            break

        if done:
            fails = 0
            api.log(f"爬了 {done} 次。")
        elif fails >= MAX_FAILS:
            api.log("连续失败，停止。请确认你站在傲来国的旗杆旁。")
            return
        else:
            api.sleep(5)
            continue

        cur, mx, pct = api.hp(quiet=False)
        if mx == 0:
            api.log("读不到气血，停止。")
            return

        if pct >= REST_BELOW:
            continue

        api.log(f"气血不足{REST_BELOW}%，休息 {REST_SECS} 秒。")
        api.sleep(REST_SECS)
