# mingsi -- mingsi (冥思练法) to the current 法力 ceiling.
#
# Run in-game with: /run mingsi   (stop with /stop mingsi)
#
# Same shape as dazuo, mana side instead of force side:
#   1. mingsi AMOUNT, up to TIMES times in a row
#   2. if the mud answers "你现在神智不清,不能再想入非非了。"
#      (cmds/std/meditate.lpc:41 -- not enough 精神/sen left to start a
#      round), rest REST_SECS then go back to step 1
#   3. if it answers "...似乎法力的提升已经到了瓶颈。" (meditate.lpc:81 --
#      max_mana is already at the ceiling your spells-skill level allows,
#      so mingsi can no longer raise it), STOP. That's the actual finish
#      line for "to max" -- more mingsi does nothing until you `learn`
#      the skill higher, which needs a teacher, not this bot.
#   4. otherwise keep going until TIMES rounds are done, then loop
#
# Requires you to already have a spells skill selected with `enable`
# (cmds/std/meditate.lpc:35-36) -- mingsi refuses to run without one.

AMOUNT = 40      # 精神 spent per `mingsi <AMOUNT>` call -- meditate.lpc requires >= 20
TIMES = 20       # mingsi calls to attempt before starting a fresh batch
REST_SECS = 60   # how long to rest once 精神 runs too low to mingsi
MAX_FAILS = 3    # consecutive non-精神 failures (busy/no spells enabled/etc) before giving up

COMPLETE = r"你行功完毕，从冥思中回过神来"
LOW_SEN = r"你现在神智不清,不能再想入非非了"
BOTTLENECK = r"似乎法力的提升已经到了瓶颈"
# Any other rejection: not busy-waiting, wrong room, no spells enabled, etc.
# Distinct from LOW_SEN, which is the one case where waiting actually helps.
OTHER_FAIL = r"什么？|你现在正忙着呢|你必须先用 enable|这里不是修炼法力的地方"

# Rough upper bound for one mingsi call to finish: meditate.lpc ticks once
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
            api.send(f"mingsi {AMOUNT}")

            m = api.wait_line(f"{COMPLETE}|{LOW_SEN}|{BOTTLENECK}|{OTHER_FAIL}",
                               timeout=TIMEOUT)
            if not m:
                fails += 1
                api.log(f"mingsi 没有反应（第 {fails} 次）。")
                if fails >= MAX_FAILS:
                    api.log("连续失败，停止。")
                    return
                api.sleep(5)
                continue

            text = m.group(0)
            if "瓶颈" in text:
                # This is the actual finish line: max_mana is capped by
                # your current spells-skill level, so mingsi has nothing
                # left to give until you learn the skill higher.
                api.log(f"冥思 {done} 次后到达瓶颈，法力已达当前上限，停止。"
                        "需要先 learn 提高技能等级才能继续增长。")
                return

            if "行功完毕" in text:
                done += 1
                fails = 0
                continue

            if "神智不清" in text:
                api.log(f"冥思 {done} 次后精神不够了，休息 {REST_SECS} 秒。")
                api.sleep(REST_SECS)
                rested = True
                break

            # OTHER_FAIL: something's actually wrong, not just low on 精神.
            fails += 1
            api.log(f"mingsi 被拒绝：{text}（第 {fails} 次）")
            if fails >= MAX_FAILS:
                api.log("连续失败，停止。请确认已经 enable 法术，且不在安全区。")
                return
            api.sleep(5)

        if done and not rested:
            api.log(f"这一轮冥思了 {done} 次。")
