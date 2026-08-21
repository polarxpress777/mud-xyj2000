# 武学、道行 与 技能上限

What actually stops a skill from going up, from level 0 to level 300.

Everything below is read out of the mudlib, not the website. The files are
byte-identical in both lineages (`xyj2000` and `xyj2000f`), so the line
numbers cited hold for either.

---

## 1. The one law

```c
if (my_skill * my_skill * my_skill / 10 > (int)me->query("combat_exp"))   // martial
if (my_skill * my_skill * my_skill / 10 > (int)me->query("daoxing"))      // magic
```

`cmds/std/learn.lpc:145,148` · `cmds/std/study.lpc:40,45` ·
`cmds/std/practice.lpc:37`

**To push a skill from level L to L+1 you need `floor(L³/10)` points of the
gating stat.** Below that number the skill simply refuses to move — you get
「你的武学修为还没到这个境界」 or 「你的道行还没到这个境界」 and nothing is
spent.

Turned around: with X points of the stat, your ceiling is
**`L_max = ∛(10X)`**.

Which stat gates a skill is `SKILL_D(skill)->type()`:

| `type()` | Gated by | Skills |
|---|---|---|
| `"magic"` | 道行 (`daoxing`) | 法术, 大乘佛法, 太乙仙法, 道家仙法, 登仙大法, 碧海神通, 月宫仙法, 勾魂术, 天魔大法, 妖法, 八卦咒 (12 of 112 skill files; 登仙大法 has two) |
| `"knowledge"` | **nothing** | 读书识字, 养颜术, 魔法 |
| `"martial"` (default) | 武学 (`combat_exp`) | everything else — all weapons, 内功, 轻功, 招架, and every 门派 special |

`std/skill.lpc:40` — `type()` defaults to `"martial"`, so an unmarked skill
is a 武学 skill. **内功 (`force`) is martial**, not magic: 内力 is bought with
武学, 法力 with 道行.

---

## 2. The table, 0 → 300 in tens

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

## 3. Why the 武学境界 name *is* your skill cap

`RANK_D->describe_exp` (`rankd.lpc:92-104`) grades 武学 on `exp*2/675`, tiers
at n³. `SKILL->level_description` (`std/skill.lpc:178`) grades a skill on
`level/15`, off the **same 20-name list**. Solve the two and they coincide
perfectly: **tier n is reached at exactly the 武学 needed for skill level
15n.**

So the 境界 the `score` screen prints for your 武学 tells you your cap
directly — it is the description your skills can just reach.

| 武学境界 | 武学 required | = skill cap |
|---|---:|---:|
| 初学乍练 | 0 | 0 |
| 初窥门径 | 338 | 15 |
| 粗通皮毛 | 2,700 | 30 |
| 略知一二 | 9,113 | 45 |
| 半生不熟 | 21,600 | 60 |
| 马马虎虎 | 42,188 | 75 |
| 已有小成 | 72,900 | 90 |
| 渐入佳境 | 115,763 | 105 |
| 驾轻就熟 | 172,800 | 120 |
| 了然于胸 | 246,038 | 135 |
| 出类拔萃 | 337,500 | 150 |
| 心领神会 | 449,213 | 165 |
| 神乎其技 | 583,200 | 180 |
| 出神入化 | 741,488 | 195 |
| 豁然贯通 | 926,100 | 210 |
| 登峰造极 | 1,139,063 | 225 |
| 举世无双 | 1,382,400 | 240 |
| 一代宗师 | 1,658,138 | 255 |
| 震古铄今 | 1,968,300 | 270 |
| 深不可测 | 2,314,913 | 285 |

道行 has no such coincidence — it is graded on `daoxing/2000` with 16 tiers
(`rankd.lpc:71`), so each tier is worth ~27.1 magic levels:

| 道行境界 | 道行 required | 折算 | = magic cap |
|---|---:|---|---:|
| 新入道途 | 0 | — | 0 |
| 闻道则喜 | 2,000 | 2年 | 27 |
| 初领妙道 | 16,000 | 16年 | 54 |
| 略通道行 | 54,000 | 54年 | 81 |
| 渐入佳境 | 128,000 | 128年 | 108 |
| 元神初具 | 250,000 | 250年 | 135 |
| 道心稳固 | 432,000 | 432年 | 162 |
| 一日千里 | 686,000 | 686年 | 190 |
| 道高德隆 | 1,024,000 | 1024年 | 217 |
| 脱胎换骨 | 1,458,000 | 1458年 | 244 |
| 霞举飞升 | 2,000,000 | 2000年 | 271 |
| 道满根归 | 2,662,000 | 2662年 | 298 |
| 不堕轮回 | 3,456,000 | 3456年 | 325 |
| 已证大道 | 4,394,000 | 4394年 | 352 |
| 反璞归真 | 5,488,000 | 5488年 | 380 |
| 天人合一 | 6,750,000 | 6750年 | 407 |

The last four 道行 tiers price magic levels above 300 — content the skill
system never designed for. Reaching 天人合一 takes 2.5× the 道行 that already
caps 法术 at 300.

---

## 4. The three other ceilings

The stat gate is the *outer* wall. Three more sit inside it.

### 4.1 潜能 — the learn budget

`learn` spends one 潜能 point per iteration (`learn.lpc:80-84, 156`); the budget
is `potential - learned_points` and 「你的潜能已经发挥到极限了」 when it hits
zero. Combat refills it only up to a 100-point buffer
(`combatd.lpc:495-502`: `if (potential - learned_points < 100) potential++`).

Levelling costs `(L+1)²+1` learned-units (`feature/skill.lpc:229-230`), and each
潜能 point buys `random(悟性)+1` units — averaging `(悟性+1)/2`, so **悟性 is
a straight divisor on the cost of everything**.

| 区间 | learned-units | 潜能 @悟性30 | practice attempts instead |
|---|---:|---:|---:|
| 0→10 | 385 | 25 | 220 |
| 10→20 | 2,485 | 160 | 692 |
| 20→30 | 6,585 | 425 | 1,186 |
| 30→40 | 12,685 | 818 | 1,683 |
| 40→50 | 20,785 | 1,341 | 2,181 |
| 50→60 | 30,885 | 1,993 | 2,680 |
| 60→70 | 42,985 | 2,773 | 3,179 |
| 70→80 | 57,085 | 3,683 | 3,679 |
| 80→90 | 73,185 | 4,722 | 4,178 |
| 90→100 | 91,285 | 5,889 | 4,678 |
| 100→150 | 797,925 | 51,479 | 30,887 |
| 150→200 | 1,550,425 | 100,027 | 43,384 |
| 200→250 | 2,552,925 | 164,705 | 55,882 |
| 250→300 | 3,805,425 | 245,511 | 68,380 |

(practice column: `skill_basic/5 + 1` units per attempt at
`skill_basic ≈ L` — `practice.lpc:56`.)

Total 0→300 on `learn` alone: **9,045,050 units ≈ 583,000 潜能**. That budget
does not exist. Past roughly level 50 **`practice` is the only realistic
route** — it costs no 潜能 at all — and `learn` is for skills `practice`
cannot touch.

### 4.2 基本技能 — the special-skill ceiling

```c
me->improve_skill(skillname, skill_basic / 5 + 1, skill_basic > skill ? 0 : 1);
```
`practice.lpc:56`. `weak_mode` is 1 when the basic skill is **not** above the
special skill, and `feature/skill.lpc:214, 229` refuses to level a player in weak
mode. So **a 门派 special can never out-level its basic skill via practice**:
raise 拳脚/剑法/内功/法术 first, then the special follows.

`valid_learn` in individual skills enforces the same thing for `learn` —
e.g. `daemon/skill/taiyi.lpc:7-11` requires `spells > taiyi` and `spells ≥ 10`.

### 4.3 Teachers, books, and 悟性

- **From a player:** capped at level 100 (`learn.lpc:125`), and you cannot
  learn a skill you don't already have.
- **From a book:** each 秘笈 carries its own `max_skill`, `exp_required` /
  `dx_required` and `difficulty` (`study.lpc:40-45, 71`). See
  `guide/skill-books.md`.
- **悟性 (`int`)** sets learn speed and the 精神 cost (`sen_cost = 300/悟性`).
- **`spi`** caps how *many* skills you can carry: once you have more than
  `spi` skills, all gains are divided by `sizeof(learned) - spi`
  (`feature/skill.lpc:220-222`). Breadth is paid for in depth.

---

## 5. What the levels buy

- **Effective skill in combat is not the raw level.** `query_skill()` returns
  `raw/2 + <mapped skill raw>` (`feature/skill.lpc:94-105`), so an enabled
  special plus its basic is what fights. 拳脚 300 + 劫难指 300 → 450.
- **内力上限 = (force/2 + mapped)×10**, **法力上限 = (spells/2 + mapped)×10**
  (`feature/skill.lpc:64-92`). Both basics at 300 → 4,500 max_force /
  max_mana.
- **Attack power** is `level³/3 + combat_exp`, scaled by 精神
  (`combatd.lpc:250-260`). At level 300 the skill term is 9,000,000 against
  2,700,000 of 武学 — **at the top, level dominates 武学 3:1**; at level 30
  the ratio is reversed. 武学 is the key, the skill is the door.
- **武人/法师 guild bonus** on top (`std/char.lpc:183-211`): +5% below 100,
  rising to +15 & 1/5 above 200, at the cost of −10% on the other axis.

## 6. Gates that read both axes at once

Quite a lot of content tests `(daoxing + combat_exp) / 2` — the average, so
neither axis alone carries you:

| Threshold | Effect |
|---:|---|
| 5,000 道行 | `check` (顺风耳) starts working — `cmds/std/check.lpc:16` |
| 30,000 avg | 妖怪 begin spawning in the 取经 areas |
| 50,000 avg | 袁天罡 stops issuing 灭妖 quests |

## 7. Death

`combatd.lpc:915-916`: death costs **1/40 of 武学 and 1/40 of 道行**, plus
half your unspent 潜能, plus (unless a `kar` roll saves you) one level off
**every** skill. At 2.7M 武学 that is 67,500 points per death. The 道行 half alone is on the
order of 80 hours of uninterrupted `xiudao` at 法术 300 (~16 道行 per ~70s
session — `cmds/std/xiudao.lpc:44-50`, estimated, not measured in game). The
cubic means a death near level 300 can put the level itself out of reach
until you have earned it back.

---

## Where the numbers come from

| Fact | File |
|---|---|
| The L³/10 gate | `cmds/std/{learn,study,practice}.lpc` |
| Level-up cost `(L+1)²`, 悟性 & `spi` effects | `feature/skill.lpc:207-233` |
| 境界 names and thresholds | `adm/daemons/rankd.lpc` |
| Skill-level names (`level/15`) | `std/skill.lpc:140-190` |
| 道行 → 年/天/时辰 | `cmds/usr/hp.lpc:57-59` |
| 道行 gain from 修道 / killing | `cmds/std/xiudao.lpc`, `combatd.lpc:812,879` |
| 武学 gain from combat | `combatd.lpc:361-503`, and `guide/training-targets.md` |
