# 西游记2000 经验谈 — player guide, cross-checked against this build

Source: <https://aolai.org/article/2004-10/article-1098810237.htm> (2004).

That guide is written for the original **xyj2000**; we run **xyj2000f**.
Everything below is the guide's advice with a verification pass against
this repo's actual code. Claims are marked:

- **[verified]** — confirmed in this codebase, with the file
- **[differs]** — real here, but the numbers/commands are not what the guide says
- **[unverified]** — plausible, not yet checked against code

---

## Character creation

Recommended 龙宫 (Dragon Palace) build: 体格 25 / 根骨 30 / 悟性 20 / 灵性 15.

Rationale given: *"灵性控制能学多少种武功，一个角色练一种武功足够"* —
spirituality caps how many skills you can train at once, and one martial
art per character is enough.

**[verified]** — 灵性 (`spi`) really does throttle multi-skill learning.
`feature/skill.lpc:219-222`:
```c
spi = query("spi");
if (sizeof(learned) > spi)
    amount /= sizeof(learned) - spi;
```
Every skill you have in progress beyond your `spi` divides *all* skill
gain. Spreading thin is actively punished. See also
[training-targets.md](training-targets.md).

**Note on 体格 (str)**: the guide's 25 is sane. High `str` is *not*
universally good — `d/moon/ontop2.lpc:70` trains dodge by
`improve_skill("dodge", 40 - str)`, so str ≥ 40 makes that trainer give
nothing.

## Early money

Beg from veterans, or sell items. The pawn shop (当铺) is **two rooms
west of 南城客栈**. Use `list sword` rather than a bare `list` — the
full inventory listing is huge. Target 5-10 gold before training.

## 拜师 (joining a sect) — 龙宫 example

```
buy jiudai
w;n;w;w;w;n
give jiudai to yuan
tear book                       # yields 避水咒 (water-breathing)
```
Then the guide's travel alias:
```
#alias golonggong {#16 s;#3 e;dive;e;e;ne;e;e;e;se;se;e;bai long nu}
```
`bai long nu` makes you a 龙宫三代弟子.

**[verified]** — `;` chaining and `#N` repeat both work here
(`feature/alias.lpc`). **[differs]** — our `#N` drains one command per
second *and any new input cancels an in-flight batch*, so don't poll or
type while a long chain is running.

## 灭妖 quest

- **After joining a sect, don't learn skills yet — bank 潜能 first.**
- From 南城客栈: `w;n;n;w` then `ask yuan about mieyao`
- Ride a horse: 轻功 improves and monsters can't chase you
  `#alias kaifeng {w;n;#12 e;s;mount ma}`
- First kill: **+50 武学**, and under 100 潜能
- Failed the quest? Wait 15-20 min and it cancels

**[differs] — the abandon timer is 30 minutes here, not 15-20.**
`d/city/npc/yuantiangang.lpc:128` refuses a new job while
`time() < t + 1800`; past that it drops your difficulty level by one
(line 137) and immediately assigns a fresh target. Completing a quest
instead costs only a **5-minute** cooldown — 10 minutes once
`(daoxing + combat_exp)/2 > 20000` (line 146) — and raises the level.
Levels run 0-9 and wrap to 5 at the top (line 157).

Note the level is stored with `set_temp`, so **logging out resets your
difficulty to 0**, while `mieyao/time_start1` is a persistent `set()` —
quitting does not skip the 30-minute wait.

**[verified]** — 潜能 caps at 100 unspent (`obj/user.lpc:26-28` and
every gain site gate on `potential - learned_points < 100`), so
"bank potential first" has a hard ceiling: past 100 spendable, further
accrual stops until you spend it.

## 内功正循环 (the self-sustaining force loop)

The guide's definition: once your 内功 effective level is high enough,
you can loop `dazuo` → `exert recover` indefinitely.

> **秘诀：西游记2000正循环大概在 60~75 之间**

**[differs] — this build has no `exert recover`.** The healing exertion
here is **`exert heal`**, and 8 force classes implement it
(`daemon/class/*/*/heal.lpc`). For 小无相功
(`daemon/class/puti/wuxiangforce/heal.lpc`):

```c
me->receive_curing("kee", 10 + (int)me->query_skill("force") / 5);
me->add("force", -50);
```

So the real loop on this build is:
```
dazuo <n>        # 气血 -> 内力
exert heal       # 50 内力 -> (10 + force_skill/5) 气血
```
`exert heal` additionally requires: not in combat, `force >= 50`, and
`eff_kee >= max_kee/2` (it refuses when you're too badly wounded).

The 60-75 threshold is **[unverified]** here, but is directionally
consistent: at force skill 60-75 one `exert heal` returns 22-25 気血 for
50 内力, while `dazuo` yields `(force_skill/10 + con/3 + rand(3)) * 2`
per 20 気血 spent — the exchange only becomes favourable once the skill
term dominates.

## NK (killing NPCs for 道行) progression

The guide's ladder:

1. NPCs whose names start with 小
2. 丫环 / 家丁 / 小兵 / 普陀僧 — to ~70天 道行
3. "Robot" series: 平顶 gui/chong/hu/long, 女儿国牛二, 盘丝七姐妹 — ~70天
4. 小西天小童 — can carry you past **300年** 道行
5. 五庄观 八仙 / 张果老 — 70天
6. Hell 十大冥王 — 100天 道行

**[verified]** — killing awards **道行**, not 武学
(`combatd.lpc:869-889`, `nk_gain()`). For 武学 specifically you want
`fight`/`kill` exchanges against stronger opponents, not kills — see
[training-targets.md](training-targets.md).

Also **[verified]**: `nk_gain()` returns 0 if the NPC is in *your own
sect* (`fam == fam1`), or if someone else fainted it first. No
farming your own 门派.

## 龙宫 treasures

| Item | Effect | How |
|---|---|---|
| **红丹瓶** | `drink ping` → +500-800 潜能, +8-10 杀气 | `ask jing wudi about 腰牌`, then `insert yao pai` at the south rockery |
| **绿丹瓶** | `get all from ping`, `eat dan` → +100 潜能 | — |
| **定海神针 (金箍棒)** | `wield bang` — other players can't `find` you | long chain, see below |
| **八瓣梅花锤 / 九股托天叉** | `wield hammer` / `wield fork`, damage 60 | to read as books: `ask gui badou about fu` for 金龙符, then `apply hammer`/`apply fork` |
| **九彩云龙珠** | `touch long zhu` → force to level 150 | kill nine dragon sons for 紫蓝青绿黄橙赤银金 pearls, then `combine` |

定海神针 chain:
```
fly sky;w;w
ask po about 起风          # -> yao -> feng ling fu
e;s;answer 看热闹;s;s
ji feng ling fu
kun bingqi                  # give to 芭将军
ask ao guang about weapon
                            # spar 夜叉 (100000 武学, any style)
follow xiao jin yu          # through the seabed maze
get bang
```
All **[unverified]** against this build — the 龙宫 area exists
(`d/dntg/donghai/`), but I have not confirmed these specific items or
command chains here.

## Other training

- **云房**: `lianwu` trains 轻功; stop when it says 轻功已经很高
- **力量**: fish (花皮鲨 etc.) near the 龙宫 掌门, routes
  `eu;n;n;n;e;e;s;s` and `dive;e;e;ne;sw;s`

## 长生不死 (immortality)

Fortune-telling from age 19: `w;n;w;w;w;n`, `ask yuan about 算命`,
`give 10 gold to yuan`.

The guide lists three routes: eat 36 人参果, reach **3600年 道行**, or
(reportedly) clear every 关卡.

**[differs] — the real threshold here is 3456年, not 3600.**
`adm/daemons/updated.lpc:17-21` grants `live_forever` once your 道行
rank reaches 不堕轮回, and `adm/daemons/rankd.lpc:22` puts that at
`1728x2=3456`. Since `hp` shows 道行年 = `daoxing/1000`
(`cmds/usr/hp.lpc:57`), that's `daoxing` 3,456,000.

**[verified]** — immortality genuinely removes the death clock:
`feature/damage.lpc:56` returns early from `check_gameover()` when
`life/live_forever` is set, so age can exceed `life/life_time` without
retiring the character. Every death still costs 1 `life_time` point
(`damage.lpc:380-382`) until then.
