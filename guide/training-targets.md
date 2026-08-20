# Who to fight to raise 武学

武学 on the `hp` screen is `combat_exp` (`cmds/usr/hp.lpc:51-55`).

## How 武学 is actually earned

`adm/daemons/combatd.lpc:491-503`, on every landed hit:

```c
if (!userp(me) || !userp(victim)) {          // at least one side is an NPC
  if ((ap < dp) && random(...) > 150) {
    my["combat_exp"] += 1;                    // attacker gains
    ...
  }
  if (random(your["max_kee"] + your["kee"]) < damage) {
    your["combat_exp"] += 1;                  // defender gains
  }
}
```

Two things follow, and they drive everything below:

1. **`ap < dp` — you gain 武学 by attacking someone STRONGER than you.**
   Beating up something far weaker gains almost nothing. The right
   target is modestly *above* your level, not below it.
2. **PvP gives nothing.** The whole block is skipped when both sides are
   players (`!userp(me) || !userp(victim)`).

Dodge/parry work the same way in reverse (`combatd.lpc:358-363, 410-415`):
you improve them while *defending* against someone stronger.

Killing gives 道行 (`nk_gain`), not 武学 — so for 武学 specifically,
`fight` is as good as `kill`, and far cheaper (no death penalty).

## Who will actually spar with you

`std/char/npc.lpc:36-71` — `fight` is refused outright unless:

| NPC attitude | Accepts `fight`? |
|---|---|
| `friendly` | **No** — 怎么可能是…的对手 (this is why 店小二 refuses) |
| `peaceful` / unset | **Yes** — 既然…赐教，只好奉陪 |
| `aggressive` / `killer` | **Yes** — 哼！出招吧！ |
| `heroism` | Yes, even mid-fight |

Also required: the NPC must be at **≥90% of gin/kee/sen**. A freshly
beaten NPC refuses until it heals — so back-to-back spars against the
same target need a gap.

477 NPCs pass this filter. Best per tier:

## Tier 1 — starting out (your skills ~1-20)

| NPC | avg skill | exp | Where |
|---|---:|---:|---|
| 猴子 / 小猴子 | 15 | 50 | `dntg/hgs/npc/hou.lpc` — 花果山 |
| 蝴蝶 | 10 | 100 | `xueshan/npc/hudie.lpc` |
| 卢生 | 4 | 100 | `changan/npc/lusheng.lpc` |
| 李定 | 10 | 500 | `changan/npc/qiaofu.lpc` |
| 张梢 | 17 | 500 | `changan/npc/fisher.lpc` |
| 武馆弟子 | 10 | 600 | `dntg/hgs/npc/dizi.lpc` — 花果山武馆 |

## Tier 2 — skills ~20-40

| NPC | avg skill | exp | Where |
|---|---:|---:|---|
| 老妇 | 23 | 1000 | `qujing/yinwu/npc/laofu.lpc` |
| 家丁 | 25 | 1800 | `gao/npc/jiading.lpc` — 高家庄 |
| 掌厨僧 / 知客僧 | 22 | 5000 | `nanhai/npc/*.lpc` — 南海 |
| 白衣秀士 | 30 | 5000 | `city/npc/whitexiu.lpc` — 长安 |
| 庙祝 | 26 | 5000 | `meishan/npc/miaozhu.lpc` |

## Tier 3 — skills ~40-70

| NPC | avg skill | exp | Where |
|---|---:|---:|---|
| 百足蜈蚣 / 赤练小蛇 | 60 | 100 | `xueshan/npc/*.lpc` — low exp, high skill: good value |
| 庄东 / 签客 / 白髯鸡仙 / 青鬏龟童 | 50 | 5000 | `city/npc/*.lpc` — all in 长安 |
| 香兰 | 45 | 5500 | `kaifeng/npc/xianglan.lpc` |
| 管家 | 50 | 9500 | `qujing/chechi/npc/daguan.lpc` — heroism |

## Tier 4 — skills ~70-110

| NPC | avg skill | exp | Where |
|---|---:|---:|---|
| 穷汉 | 80 | 3000 | `qujing/wudidong/npc/bianfu.lpc` |
| 青髯老人 | 80 | 10000 | `westway/npc/laoren.lpc` |
| 魏征 | 80 | 60000 | `city/npc/weizhen.lpc` — 长安 |
| 雷公 / 电母 | 96 | 70000 | `dntg/sky/npc/*.lpc` |
| 恶龙 | 100 | 50000 | `qujing/wudidong/npc/dragon.lpc` — aggressive |

## Tier 5 — skills 110+

盘丝洞's seven sons (蜜/蚂/卢/班/蜢/蜡/蜻, `qujing/pansi/npc/son*.lpc`)
sit at skill ~113 with exp 35000 and are **aggressive** — they start the
fight themselves. 造酒仙官 (130, `dntg/yaochi`) is peaceful. Above that,
魔礼 brothers (220-240) and 六耳猕猴 (260) are endgame.

## Practical notes

- **The `fight-bot` automates this**: `/run fight-bot <npc id>` spars,
  waits for full 气血, and stops when 武学 stops rising — see
  `tools/xyjbot/bots/fight-bot.py`.
- **Use the English id**, not the Chinese name: `fight hou`, not `fight 猴子`.
- **A target that stops giving 武学 has become too weak for you** —
  the `ap < dp` rule means you've outgrown it. Move up a tier.
- Low-exp/high-skill NPCs (小金鱼 60/10, 百足蜈蚣 60/100) are unusually
  good value: high `dp` for the `ap < dp` check without a dangerous
  overall power level.
