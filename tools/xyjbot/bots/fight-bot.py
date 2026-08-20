# fight-bot -- spar with an NPC to conclusion, rest to full, repeat only
# while it's still teaching you something.
#
# Run in-game with: /run fight-bot <npc名称>   (e.g. /run fight-bot wugang)
# Stop with:         /stop fight-bot
#
# Uses `fight` (切磋/比武), not `kill`. Per cmds/std/fight.lpc's own help:
# 点到为止，只会消耗体力，不会真的受伤 -- stamina only, no real injury, so
# no death penalty and no lost skill levels if it goes badly. 武学
# (combat_exp) still climbs, because combatd.lpc:494/500 awards it per
# exchange regardless of which verb started the fight.
#
# Loop:
#   1. fight <name> and wait for it to actually end -- someone knocked
#      out, or a surrender -- not just "a message arrived".
#   2. poll hp every CHECK_INTERVAL seconds until 气血 is back to 100%.
#      Real recovery time, not a fixed cooldown: a rough spar rests longer.
#   3. compare 武学 against what it was before this fight. Higher ->
#      go again. Unchanged or lower -> STOP, this opponent has nothing
#      left to teach you right now.
#
# Combat-end detection is text-matched against adm/daemons/combatd.lpc's
# announce() and cmds/std/surrender.lpc, since a bot can only see what's
# printed to the screen, same as you.

VERB = "fight"         # change to "kill" for a real (lethal) fight
CHECK_INTERVAL = 30    # seconds between hp polls once a fight has ended
MAX_FAILS = 3          # consecutive rejections before giving up
FIGHT_TIMEOUT = 600    # give up waiting on a single fight after this long

FAINTED = r"跌在地上一动也不动了"
SURRENDERED = r"不打了，不打了，我投降"
DIED = r"死了。"       # shouldn't happen while sparring, but end cleanly if it does
FIGHT_END = f"{FAINTED}|{SURRENDERED}|{DIED}"

# cmds/std/fight.lpc's refusal paths. 并不想跟你较量 is the important one:
# accept_fight() returning 0 means this NPC simply won't spar with you.
REJECT_KEYS = ("你想攻击谁", "并不是生物", "已经无法战斗了", "你不能攻击自己",
               "你现在正忙着呢", "这里禁止战斗", "并不想跟你较量",
               # kill-mode equivalents, in case VERB is switched
               "你想杀谁", "这里没有这个人", "并不是活物", "这里不准战斗")
REJECTED = "|".join(REJECT_KEYS)


def run(api, arg):
    if not arg:
        api.log("用法：/run fight-bot <npc名称>，例如 /run fight-bot wugang")
        return

    target = arg.strip()
    fails = 0
    rounds = 0
    last_wuxue = None

    while not api.stopped():
        api.drain()
        api.send(f"{VERB} {target}")

        m = api.wait_line(f"{FIGHT_END}|{REJECTED}", timeout=FIGHT_TIMEOUT)
        if not m:
            api.log(f"等了 {FIGHT_TIMEOUT} 秒战斗还没结束，可能卡住了，停止。")
            return

        text = m.group(0)
        if any(k in text for k in REJECT_KEYS):
            fails += 1
            api.log(f"{VERB} {target} 被拒绝：{text}（第 {fails} 次）")
            if fails >= MAX_FAILS:
                if "并不想跟你较量" in text:
                    api.log(f"{target} 不接受切磋。改用 kill 才打得起来"
                             "（把 bots/fight-bot.py 里的 VERB 改成 kill），"
                             "但那是真的会受伤的。停止。")
                else:
                    api.log(f"连续失败，停止。请确认 {target} 就在这个房间里。")
                return
            api.sleep(5)
            continue

        fails = 0
        rounds += 1
        api.log(f"第 {rounds} 场切磋结束（{text}）。开始等血回满。")

        # Recovery loop: poll until 气血 is full again.
        while not api.stopped():
            st = api.status()
            if st["max_kee"] and st["kee"] >= st["max_kee"]:
                break
            api.log(f"气血 {st['kee']}/{st['max_kee']}，还没满，"
                     f"{CHECK_INTERVAL} 秒后再看。")
            api.sleep(CHECK_INTERVAL)

        st = api.status()
        wuxue = st["wuxue"]
        api.log(f"气血已满。武学：{wuxue}"
                 + (f"（上次 {last_wuxue}）" if last_wuxue is not None else ""))

        if last_wuxue is not None and wuxue <= last_wuxue:
            api.log(f"武学没有提升（{last_wuxue} -> {wuxue}），"
                     f"继续和 {target} 切磋已经没有帮助了，停止。")
            return

        last_wuxue = wuxue
