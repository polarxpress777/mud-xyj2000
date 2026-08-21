# dazuo -- dazuo (打坐练功) to the current 内力 ceiling.
#
# Run in-game with: /run dazuo   (stop with /stop dazuo)
#
# Loop:
#   1. dazuo AMOUNT, up to TIMES times in a row
#   2. if the mud answers "你现在的气太少了，无法产生内息运行全身经脉。"
#      (cmds/std/exercise.lpc:41 -- not enough 气/kee left to start a
#      round), rest REST_SECS then go back to step 1
#   3. if it answers "...似乎内力修为已经遇到了瓶颈。" (exercise.lpc:81 --
#      max_force is already at the ceiling your force-skill level allows,
#      so dazuo can no longer raise it), STOP. That's the actual finish
#      line for "to max" -- more dazuo does nothing until you `learn`
#      the skill higher, which needs a teacher, not this bot.
#   4. otherwise keep going until TIMES rounds are done, then loop
#
# Requires you to already have a force skill selected with `enable`
# (cmds/std/exercise.lpc:35-36) -- dazuo refuses to run without one.

AMOUNT = 40      # 气 spent per `dazuo <AMOUNT>` call -- exercise.lpc requires >= 20
TIMES = 20       # dazuo calls to attempt before starting a fresh batch
REST_SECS = 60   # how long to rest once 气 runs too low to dazuo
MAX_FAILS = 3    # consecutive non-kee failures (busy/no force selected/etc) before giving up

COMPLETE = r"你行功完毕"
LOW_KEE = r"你现在的气太少了，无法产生内息运行全身经脉"
BOTTLENECK = r"似乎内力修为已经遇到了瓶颈"
# Any other rejection: not busy-waiting, wrong room, no force enabled, etc.
# Distinct from LOW_KEE, which is the one case where waiting actually helps.
OTHER_FAIL = r"什么？|你现在正忙着呢|你必须先用 enable|安全区内禁止练功"

# Rough upper bound for one dazuo call to finish: exercise.lpc ticks once
# per second for AMOUNT//20 rounds, then a 1s delay before the "行功完毕"
# message -- pad generously since call_outs queue up under load.
TIMEOUT = max(10, AMOUNT // 20 * 2 + 10)


def run(api):
    fails = 0

    while not api.stopped():
        done = 0
        rested = False

        for _ in range(TIMES):
            if api.stopped():
                return
            api.drain()
            api.send(f"dazuo {AMOUNT}")

            m = api.wait_line(f"{COMPLETE}|{LOW_KEE}|{BOTTLENECK}|{OTHER_FAIL}",
                               timeout=TIMEOUT)
            if not m:
                fails += 1
                api.log(f"dazuo 没有反应（第 {fails} 次）。")
                if fails >= MAX_FAILS:
                    api.log("连续失败，停止。")
                    return
                api.sleep(5)
                continue

            text = m.group(0)
            if "瓶颈" in text:
                # This is the actual finish line: max_force is capped by
                # your current force-skill level, so dazuo has nothing
                # left to give until you learn the skill higher.
                api.log(f"打坐 {done} 次后到达瓶颈，内力已达当前上限，停止。"
                        "需要先 learn 提高技能等级才能继续增长。")
                return

            if "行功完毕" in text:
                done += 1
                fails = 0
                continue

            if "气太少" in text:
                api.log(f"打坐 {done} 次后气不够了，休息 {REST_SECS} 秒。")
                api.sleep(REST_SECS)
                rested = True
                break

            # OTHER_FAIL: something's actually wrong, not just low on 气.
            fails += 1
            api.log(f"dazuo 被拒绝：{text}（第 {fails} 次）")
            if fails >= MAX_FAILS:
                api.log("连续失败，停止。请确认已经 enable 内功，且不在安全区。")
                return
            api.sleep(5)

        if done and not rested:
            api.log(f"这一轮打坐了 {done} 次。")
