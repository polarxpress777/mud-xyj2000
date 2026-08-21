# 练功指南 — Training guide

Two questions, one page: **how high can this skill go**, and **who should I
hit to get there**.

Everything here is read out of the mudlib, not from the website. The files
are byte-identical in both lineages (`xyj2000` and `xyj2000f`), so the line
numbers hold for either.

---

## 1. 技能上限：0 → 300

`门槛` is the stat you must already hold to move *off* that level.
The number is identical for 武学 and 道行 — only which stat is read differs.
道行 has a second reading as elapsed cultivation time (`cmds/usr/hp.lpc:57-59`:
1 点 = 3 时辰, 4 点 = 1 天, 1000 点 = 1 年).

| 技能等级 | 门槛 floor(L³/10) | 武学境界 at that 武学 | 道行境界 at that 道行 | 道行 as time |
|---:|---:|---|---|---|
| 0 | 0 | 初学乍练 | 新入道途 | 没有道行 |
| 10 | 100 | 初学乍练 | 新入道途 | 25天 |
| 20 | 800 | 初窥门径 | 新入道途 | 200天 |
| 30 | 2,700 | 粗通皮毛 | 闻道则喜 | 2年175天 |
| 40 | 6,400 | 粗通皮毛 | 闻道则喜 | 6年100天 |
| 50 | 12,500 | 略知一二 | 闻道则喜 | 12年125天 |
| 60 | 21,600 | 半生不熟 | 初领妙道 | 21年150天 |
| 70 | 34,300 | 半生不熟 | 初领妙道 | 34年75天 |
| 80 | 51,200 | 马马虎虎 | 初领妙道 | 51年50天 |
| 90 | 72,900 | 已有小成 | 略通道行 | 72年225天 |
| 100 | 100,000 | 已有小成 | 略通道行 | 100年 |
| 110 | 133,100 | 渐入佳境 | 渐入佳境 | 133年25天 |
| 120 | 172,800 | 驾轻就熟 | 渐入佳境 | 172年200天 |
| 130 | 219,700 | 驾轻就熟 | 渐入佳境 | 219年175天 |
| 140 | 274,400 | 了然于胸 | 元神初具 | 274年100天 |
| 150 | 337,500 | 出类拔萃 | 元神初具 | 337年125天 |
| 160 | 409,600 | 出类拔萃 | 元神初具 | 409年150天 |
| 170 | 491,300 | 心领神会 | 道心稳固 | 491年75天 |
| 180 | 583,200 | 神乎其技 | 道心稳固 | 583年50天 |
| 190 | 685,900 | 神乎其技 | 道心稳固 | 685年225天 |
| 200 | 800,000 | 出神入化 | 一日千里 | 800年 |
| 210 | 926,100 | 豁然贯通 | 一日千里 | 926年25天 |
| 220 | 1,064,800 | 豁然贯通 | 道高德隆 | 1064年200天 |
| 230 | 1,216,700 | 登峰造极 | 道高德隆 | 1216年175天 |
| 240 | 1,382,400 | 举世无双 | 道高德隆 | 1382年100天 |
| 250 | 1,562,500 | 举世无双 | 脱胎换骨 | 1562年125天 |
| 260 | 1,757,600 | 一代宗师 | 脱胎换骨 | 1757年150天 |
| 270 | 1,968,300 | 震古铄今 | 脱胎换骨 | 1968年75天 |
| 280 | 2,195,200 | 震古铄今 | 霞举飞升 | 2195年50天 |
| 290 | 2,438,900 | 深不可测 | 霞举飞升 | 2438年225天 |
| 300 | 2,700,000 | 深不可测 | 道满根归 | 2700年 |

The cubic is brutal at the top: 0→100 costs 100k 武学, 200→300 costs
1.9M — nineteen times as much for the same hundred levels.

**Level 300 is the design ceiling, and it is deliberate.**
`adm/daemons/rankd.lpc:96-97` says so in a comment: *"this is to make 深不可测
requires 2700k combat_exp, which also means player can learn skill level to
300."* 300³/10 = 2,700,000 exactly. Nothing in the code hard-stops you above
300 — the cubic and the top rank name simply agree to stop there.

---

---

## 2. 怎么涨武学 — how 武学 is actually earned

`adm/daemons/combatd.lpc:491-503` runs on every landed hit, and two things
fall out of it:

1. **You gain 武学 by attacking someone STRONGER than you** — the gain is
   gated on `ap < dp`. Beating something far weaker gains almost nothing.
   The right target sits modestly *above* you, not below.
2. **PvP gives nothing.** The whole block is skipped when both sides are
   players.

Dodge and parry work the same way in reverse (`combatd.lpc:358-363,
410-415`): they improve while you *defend* against someone stronger.

Killing gives 道行 (`nk_gain`), not 武学 — so for 武学 specifically, `fight`
is as good as `kill` and far cheaper, with no death penalty.

### 谁肯陪你练 — who will actually spar

`std/char/npc.lpc:36-71` refuses `fight` outright unless:

| NPC attitude | Accepts `fight`? |
|---|---|
| `friendly` | **No** — 怎么可能是…的对手（这就是店小二不肯的原因） |
| `peaceful` / unset | Yes — 既然…赐教，只好奉陪 |
| `aggressive` / `killer` | Yes — 哼！出招吧！ |
| `heroism` | Yes, even mid-fight |

The NPC must also be at **≥90% of gin/kee/sen**, so a freshly beaten target
refuses until it heals. Back-to-back spars against the same NPC need a gap.

---

## 3. 打谁 — who to hit, by tier

**669 NPCs** pass the filter above and have skills. Listed cheapest-first
within each band; 平均技能 is the mean of every skill the NPC sets.

For the full list — searchable, grouped by region — open
**[training-guide.html](training-guide.html)** in a browser.

### 平均技能 1–20  (78 个)

| NPC | 平均技能 | 道行 | 武学 | 区域 | 房间 |
|---|---:|---:|---:|---|---|
| 卢生 | 5 | 0 | 100 | 长安城南 | 泾水之滨 |
| 妇人 | 5 | 0 | 500 | 傲来国 | 民宅 |
| 浣衣女 | 5 | 0 | 1,500 | 长安城 | 仙泉 |
| 宫女 | 5 | 0 | 2,500 | 女儿国 | 后宫 |
| yao2 | 5 | 0 | 5,000 | （未命名区域） | 前洞 |
| yao1 | 9 | 0 | 20,000 | （未命名区域） | 刑房 |
| chongzi | 10 | 0 | 100 | 大雪山 | 雪岭 |
| 蝴蝶 | 10 | 0 | 100 | 大雪山 | 雪岭 |

### 平均技能 21–40  (68 个)

| NPC | 平均技能 | 道行 | 武学 | 区域 | 房间 |
|---|---:|---:|---:|---|---|
| 剃度僧 普通百姓 | 21 | 50,000 | 10,000 | 普陀山 | 小院 |
| yao | 21 | 0 | 50,000 | 毒敌山 | 洞厅 |
| 老妇 | 23 | 0 | 1,000 | 隐雾山 | 茅屋 |
| 家丁 | 25 | 0 | 1,800 | 高老庄 | 偏房 |
| 张及第 秀才 | 25 | 0 | 4,000 | 无底洞 | 学堂 |
| 土匪 | 25 | 0 | 5,000 | 高老庄 | 小树林 |
| 游方僧人 | 25 | 10,000 | 8,000 | 傲来国 | 北菀街 |
| 打手 | 26 | 0 | 10,000 | 长安城 | 三花堂 |

### 平均技能 41–70  (119 个)

| NPC | 平均技能 | 道行 | 武学 | 区域 | 房间 |
|---|---:|---:|---:|---|---|
| 偏将 傲来国 | 42 | 10,000 | 25,000 | 傲来国 | 兵器库 |
| 黄衣童子 | 42 | 0 | 30,000 | 阴曹地府 | 幽司 |
| 慧琉 道长 | 42 | 60,000 | 45,000 | 方寸山 | 练功室 |
| 冰谷巡使 | 42 | 30,000 | 50,000 | 长安城 | 吉祥杂货铺 |
| 樵子 | 43 | 0 | 10,000 | 隐雾山 | 后园 |
| 老道士 | 43 | 50,000 | 20,000 | 方寸山 | 练功室 |
| 和尚 | 43 | 200,000 | 100,000 | 长安城 | 朱雀大街 |
| 香兰 | 45 | 0 | 5,500 | 开封城 | 香兰亭 |

### 平均技能 71–110  (123 个)

| NPC | 平均技能 | 道行 | 武学 | 区域 | 房间 |
|---|---:|---:|---:|---|---|
| 陈光蕊 大阐都纲 | 72 | 100,000 | 40,000 | 开封城 | 祭贤场 |
| 黑无常 送魂使者 | 72 | 200,000 | 120,000 | 阴曹地府 | 酆都城门 |
| 铁拐李 | 72 | 300,000 | 120,000 | 五庄观 | 殿前广场 |
| 张果老 | 74 | 500,000 | 120,000 | 长安城 | 十字街头 |
| 金甲卫士 | 74 | 0 | 160,000 | 大唐皇宫 | 白玉阶 |
| 亲兵 将军府 | 74 | 0 | 160,000 | 将军府 | 麒麟阁 |
| 美后 比丘国 | 74 | 500,000 | 410,000 | 比丘国 | 玉殿 |
| 程咬金 开国元勋 | 74 | 200,000 | 800,000 | 将军府 | 东营房 |

### 平均技能 111–+  (92 个)

| NPC | 平均技能 | 道行 | 武学 | 区域 | 房间 |
|---|---:|---:|---:|---|---|
| 日值功曹 | 111 | 650,000 | 650,000 | （未命名区域） | 天宫城墙 |
| 日值功曹 | 111 | 0 | 650,000 | 天宫 | 天宫墙外 |
| 阴长生 寂灭司主 | 112 | 400,000 | 800,000 | 阴曹地府 | 寂灭司 |
| 孔雀公主 明王护法 | 112 | 500,000 | 800,000 | 大雪山 | 小木屋 |
| 王方平 轮回司主 | 112 | 600,000 | 850,000 | 阴曹地府 | 轮回司 |
| 蜜 虫怪 | 113 | 40,000 | 35,000 | 盘丝岭 | 洞内 |
| 蚂 虫怪 | 113 | 40,000 | 35,000 | 盘丝岭 | 洞内 |
| 卢 虫怪 | 113 | 40,000 | 35,000 | 盘丝岭 | 洞内 |

---

## Where the numbers come from

The 技能上限 table is computed from the mudlib's own formula; the NPC tables
are generated by `tools/xyjbot/build_guide.py` from `game.db`, which
`tools/xyjbot/build_index.py` builds by reading every room and NPC file. To
refresh after a mudlib change:

```
python3 tools/xyjbot/build_index.py
python3 tools/xyjbot/build_guide.py
```

`（未命名区域）` means the NPC's directory has no entry in
`adm/daemons/find.map` — the room is real, the region simply has no name.
