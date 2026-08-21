# CONTEXT.md

Domain vocabulary for this repo. The point of this file is to stop a fresh
session guessing at terms that have exact meanings here — a room name that
exists in four places, a stat that looks like health and isn't, a sect that
is also a directory.

**Source-of-truth order.** Mudlib code > mudlib docs (`libs/*/work/doc/`) >
[xiyouji.org](https://www.xiyouji.org/), the official server's site. In
practice they agree — 普陀山's skills on the site (劫难指, 轮回杖, 莲花心法)
are exactly what `d/city/npc/yg/yg-putuo.lpc` sets. Where they differ, the
code wins, because the code is what runs.

**Reading the site needs the right encoding.** xiyouji.org is **GBK**;
aolai.org (the 水泊梁山 portal hosting its guide archive) is **UTF-8**.
Fetchers that guess return mojibake, and a summariser handed mojibake will
invent plausible-looking content. Use `curl -s URL | iconv -f GBK -t UTF-8`
for xiyouji.org and no conversion for aolai.org.

---

## 1. What this repo is

A restored Chinese MUD — 西游记 (*Journey to the West*) — running on FluffOS,
plus the tooling to host and play it.

| Path | What |
|---|---|
| `libs/xyj2000/`, `libs/xyj2000f/` | Two sibling mudlib lineages. **`xyj2000f` is what the Docker image ships.** Fixes go to both, byte-identical where the file is shared. |
| `libs/*/work/` | The mudlib proper: `d/` world, `cmds/`, `std/`, `adm/`, `doc/` |
| `docker/` | Image, compose, entrypoint. Player state lives in named volumes, never in the image. |
| `tools/xyjbot/` | Python bot harness: proxy, trigger engine, and the 灭妖 quest bot |
| `docs/` | Work pipeline — `needs-building/` → `planned/` → `built/` |
| `AGENTS.md` | The restoration handbook. Long, and authoritative on mudlib conventions. |

The game is played in Chinese. Command names are English (`go`, `kill`,
`ask`), everything the player reads is Chinese.

---

## 2. Vocabulary that must not be guessed

### Stats

Read from the `hp` command; parsed in `tools/xyjbot/botapi.py`.

| Term | Key | What it actually is |
|---|---|---|
| 气血 | `kee` | Health. **Regeneration stops entirely when 饮水 hits 0** (`feature/damage.lpc:465`) — not slows, stops. |
| 精神 | `sen` | Spirit. Second death condition; `env/wimpy` triggers on this too. |
| 内力 | `force` | Internal energy, spent by martial skills |
| 法力 | `mana` | Magic, spent by 法术 (spells) |
| 食物 / 饮水 | `food` / `water` | Capacity is **not** constant — it derives from weight (`feature/damage.lpc:402-418`), so read the denominator, never assume it. |
| 武学 | `combat_exp` | Combat experience. Quest rewards call it 武学经验. |
| 道行 | `daoxing` | Cultivation. **A separate axis from 武学** — many gates test `(daoxing + combat_exp) / 2`. |
| 潜能 | `potential` | Spendable on learning skills |
| 杀气 | `bellicosity` | Accumulated killing intent |

### Terms

- **门派** — sect. Stored as `query("family/family_name")`; the value is the
  sect's Chinese name, e.g. `"五庄观"`. Gates a great deal of content.
- **妖怪 / 妖精** — a demon. In the 灭妖 quest they are generated, not placed:
  `d/city/npc/yg/` builds one from a random name and copies the *player's*
  own stats (`copy_status`), so difficulty scales off your highest skill.
- **灭妖** — the demon-hunting quest 袁天罡 hands out. See §5.
- **取经** — the pilgrimage. Structurally important: see §4.
- **法术 / 武功** — spells / martial arts. Most sects teach both, weighted.
- **道行 vs 修行** — the stat vs the act of cultivating it.

### Room flags that change bot and player behaviour

`no_fight` (peace room — `kill` is refused with 这里不准战斗), `no_magic`,
`no_mieyao` (no 妖怪 spawns here), `sleep_room`, `if_bed`, `outdoors`,
`no_flee`, `no_look`.

---

## 3. The nine sects

From `libs/*/work/doc/help990226/menpai` and the site's own sect pages
(`menpai.php?id=1..8`), cross-checked against `find.map`.

**How to settle any sect question, definitively.** Joining is the
`apprentice` command — aliased to **`bai`** in `adm/daemons/aliasd.lpc:27` —
and a master grants membership with **`create_family("<name>", <generation>,
"<title>")`**. So `grep -rn 'create_family(' d/` enumerates every family in
the game and every NPC who can induct you into it. Neither the site's list
nor the help file is complete; this is.

Fourteen families exist. Nine are the player sects below. The other five are
NPC clans: **火云洞** (see §3.1), **翠云山芭蕉洞** (铁扇公主), **碧波潭**,
**逍遥派** (张道陵, one member) and **山烟寺** (one member, generation 26).

**The family string is not always the display name.** Code that tests
`query("family/family_name")` must use the exact stored value:

| Displayed as | Stored as |
|---|---|
| 阴曹地府 | `阎罗地府` |
| 龙宫 | `东海龙宫` |
| 方寸山 | `方寸山三星洞` |
| 无底洞 | `陷空山无底洞` |

Getting this wrong silently breaks gates like 饮马峪's `!= "五庄观"` check.

| 门派 | Directory | Patriarch / head | Character |
|---|---|---|---|
| 灵台方寸山（三星洞） | `d/lingtai` | 菩提祖师（斜月三星） | 孙悟空's own school. 法术 first, strong 武功; 千钧棒法. Easy to start, then demands 悟性. |
| 南海普陀山 | `d/nanhai` | 观音菩萨 | Buddhist. 劫难指 (unarmed), 轮回杖 (parry), 莲花心法 (force), 大力降魔杵, 隐身术. |
| 月宫 | `d/moon` | 西王母, founded by 嫦娥 | **Women only.** Founded at 昆仑玉女峰 after 嫦娥 sought forgiveness for the elixir. Skills derive from dance: 冷月凝香舞. |
| 将军府 | `d/jjf` | 白发老人 | Tang military — 秦琼, 尉迟恭, 程咬金, 罗成. Weak 法术 (taught by 袁天罡), good 武功, pays a salary. 12 members. Recruits in 长安 through 秦叔宝 (`d/city/npc/shubao.lpc`), so you can join without leaving the city. Absent from the site's list of eight, but unambiguously real in code. |
| 龙宫 | `d/sea` | The four 龙王: 敖广/敖钦/敖顺/敖闰 | Undersea. 龙神搏击; middling 法术. Needs 避水咒 to enter. |
| 阴曹地府 | `d/death` | 地藏菩萨 and the kings of hell | Uncanny and fast to learn; 摄气诀, 烈火鞭. The eighteen hells. |
| 大雪山 | `d/xueshan` | 孔雀明王 and 大鹏明王 | Born of 凤凰 in the frozen north. Poison specialists; 逍遥游. The cold aids cultivation. |
| 陷空山无底洞 | `d/qujing/wudidong` | 地涌夫人 | A demon sect. Disciples must supply human flesh to the cook. Recruits through 蝙蝠精 in 长安 — find the bat, then seek 田鼠/碧鼠/玉鼠. Accepts defectors from other sects. |
| 五庄观 | `d/qujing/wuzhuang` | 镇元大仙, 地仙之祖 | 袖里乾坤 and the 人参果 tree. 太乙仙法. |

### 3.1 火云洞 — the Bull Demon King's family

Real, and joinable: `d/qujing/kusong/npc/honghaier.lpc:63` calls
`create_family("火云洞", 2, "蓝")` and implements `recruit_apprentice`, exactly
as 菩提祖师 does for 方寸山. It is simply undocumented — no 掌门 file, no
`find.map` entry, and no mention on the site.

- **红孩儿（圣婴大王）** — generation 2, at 枯松涧火云洞 (`d/qujing/kusong`,
  33 rooms: 火云堂, 火丁洞, 金甲洞, 白虎潭, 怪石崖, 枯松涧).
  Ranks its disciples 小妖 → 巡山小妖 → 先锋 → 健将.
- **即如火** — generation 3, same cave.
- The family also runs through **牛魔王** (`d/qujing/jilei/npc/niumo.lpc`,
  his father) and the **碧波潭驸马** (`d/qujing/bibotan/npc/fuma.lpc`), while
  his mother **铁扇公主** heads the separate 翠云山芭蕉洞 family
  (`d/qujing/firemount/npc/princess.lpc`). The clan structure follows the
  novel exactly.

**Watch out: there are two 红孩儿.** The other,
`d/nanhai/npc/honghaier.lpc`, belongs to 南海普陀山 — the same character
after 观音 subdues him and makes him 善财童子. A search on the name finds
both, and they are on opposite sides.

---

## 4. Geography

Room counts are from `tools/xyjbot/rooms.json`, built by `build_map.py`.

### Core world

长安 is the hub and where most play starts.

| Area | Directory | Rooms |
|---|---|---|
| 长安城 | `d/city`, `d/eastway` | 65 + 42 |
| 长安城南 | `d/changan` | 58 |
| 长安城西 | `d/westway` | 19 |
| 大唐皇宫 | `d/huanggong` | 32 |
| 开封城 | `d/kaifeng` | 82 |
| 高老庄 | `d/gao` | 34 |
| 傲来国 | `d/dntg/hgs` | 63 |
| 天宫 / 蟠桃园 | `d/sky`, `d/pantao` | 30 + 12 |
| 蓬莱仙岛 / 梅山 | `d/penglai`, `d/meishan` | 29 + 19 |
| 红楼一梦 | `d/ourhome/honglou` | 26 — entered by dreaming, not walking |
| 花果山 / 傲来国 | `d/dntg/hgs` | 63 — see below |

**花果山 is `d/dntg/hgs`, not `d/huaguo`.** `find.map:16` maps `d/huaguo` to
花果山, but that directory exists in **neither lineage** — it is a dangling
entry. The actual content is under `d/dntg/hgs` ("hgs" = HuaGuoShan), which
`find.map` labels 傲来国, the country on the island. Its 64 files include
水帘洞 and 水帘洞内 (the Water Curtain Cave), 仙石 (the stone 孙悟空 was born
from), 傲来台, 傲来国演武场 and 兵器库. So the area is fully built; only the
label is split across two names, one of which points nowhere.

### The 取经 route

**The novel's tribulations are literally directories.** Each episode is one
or more `d/qujing/<slug>` directories, and a 妖怪 can spawn in most of them
once `(daoxing + combat_exp) / 2` passes 30,000.

Grouped as the game's own route overview groups them
(`doc/help/qujing/qujing`, which also carries the 破迷要领 — the puzzle
outline — for each). Where an episode spans several places, the game's
header names them together, e.g. 【玉华县／豹头山／虎口洞／竹节山／九曲盘桓洞】.

| Episode (game's own heading) | Directories | Rooms | Gist |
|---|---|---|---|
| 五庄观 | `wuzhuang` | 59 | 镇元大仙's 人参果 tree. Also a sect. |
| 宝象国／碗子山 | `baoxiang` | 64 | 黄袍怪 holds princess 百花羞 in 波月洞 |
| 平顶山／莲花洞／压龙山／压龙洞 | `pingding` | 35 | 金角/银角大王 and the gourd |
| 乌鸡国／宝林寺 | `wuji` | 51 | The king drowned in the well |
| 车迟国／三清观 | `chechi` | 114 | The contest with the three animal-immortals |
| 通天河／陈家庄 | `tongtian` | 31 | 灵感大王; the great turtle |
| 金兜山／金兜洞 | `jindou` | 19 | 独角兕大王's ring that swallows weapons |
| 女儿国／解阳山 | `nuerguo` | 34 | The Womanland; 子母河 and the antidote spring |
| 毒敌山／琵琶洞 | `dudi` | 21 | The scorpion-spirit, next door to 女儿国 |
| 火焰山／翠云山 | `firemount` | 30 | 铁扇公主's 芭蕉扇 |
| 积雷山／摩云洞 | `jilei` | 20 | 玉面公主 and 牛魔王 |
| 祭赛国／碧波潭 | `jisaiguo`, `bibotan` | 52 + 47 | 九头虫 and the stolen pagoda relic |
| 荆棘岭／木仙庵 | `jingjiling` | 15 | The tree-spirits' poetry |
| 小西天／小雷音寺 | `xiaoxitian` | 19 | 黄眉大王's false Buddha |
| 朱紫国／麒麟山／獬豸洞 | `zhuzi`, `qilin` | 52 + 23 | 悟空 as physician; 赛太岁 |
| 盘丝岭／盘丝洞／黄花观／紫云山 | `pansi` | 57 | The spider-spirits |
| 比丘国／清华庄／清华洞 | `biqiu` | 50 | The king who wanted children's hearts |
| 钦法国 | `qinfa` | 46 | 灭法国 — the king who vowed to kill monks |
| 隐雾山／连环洞 | `yinwu` | 32 | The demons of the maze-like 连环洞 |
| 凤仙郡 | `fengxian` | 39 | The drought and the overturned offering |
| 玉华县／豹头山／虎口洞／竹节山／九曲盘桓洞 | `yuhua`, `baotou`, `zhujie` | 40 + 19 + 29 | The three princes taught; 黄狮精 and 九灵元圣 |
| 金平府／青龙山／玄英洞 | `jinping`, `qinglong` | 35 + 20 | The rhinoceros-spirits at the lantern festival |
| 天竺国／毛颖山／三连穴 | `tianzhu`, `maoying` | 97 + 27 | The jade-hare princess |
| 灵山 | `lingshan` | 58 | Journey's end; the scriptures |
| 无底洞 | `wudidong` | 54 | 金鼻白毛老鼠精. Also a sect. |
| 白虎岭 | `baihuling` | 5 | 白骨精, thrice-slain. **Not in `find.map`** |

Notes on that table:

- **Spelling: use 天竺 everywhere.** `find.map` says 天竺国 and that is what
  the game reports to players; the help file's 天竹国 is a typo. The pinyin
  is unaffected either way — the directory is `d/qujing/tianzhu`.
- **灵山 is the 雷音寺 map.** `d/qujing/lingshan` holds 大雷音寺 and its
  approach; 阿傩 (`npc/anuo.lpc`) and 迦叶 (`npc/jiaye.lpc`) are there — the
  two disciples who ask for a gift before handing over the scriptures.
- **白虎岭 is reached by abduction, not on foot.** `d/qujing/baihuling` is
  small (枯骨洞 — 白骨精's lair — plus 囚洞, 舍利塔, 白虎岭 and a
  `maze_generator.lpc`) and has **no `find.map` entry**. The way in is
  `MISC_D->random_capture()`: a 1-in-5000 roll sends 忽然一阵黄风呼啸而来 and
  drops the player into `/d/qujing/baihuling/jail`. That is why a player can
  log years on the official server and never see it.

---

## 5. NPCs that gate code paths

Not the most important characters in the story — the ones whose behaviour
a change is most likely to break.

- **袁天罡** — `d/city/npc/yuantiangang.lpc`, in 天监台 (`d/city/tianjiantai`).
  Hands out the 灭妖 quest: names a monster and an **area**, 30-minute timer,
  difficulty rises with each success. Stops issuing once
  `(daoxing + combat_exp) / 2` exceeds 50,000.
- **吴刚** — 月宫. Refuses `climb tree` at 玉女峰顶 to non-月宫 disciples,
  which seals off the inner 月宫 entirely.
- **卢生** — 泾水之滨. Carries the 黄粱枕; sleeping with it is the only way
  into 红楼一梦.
- **马盗** — 饮马峪 (`d/westway/yinma`). Blocks `northwest` — the sole road to
  the western half of 长安城西 — until paid 200 文. Attacks after 25 seconds.
- **店小二** — 南城客栈. Sells food and drink; rents the 睡房 for ≥300 文.
- **镇元大仙** — 五庄观. 地仙之祖; the 人参果 tree.

---

## 6. Conventions

- **Rooms** are `.lpc` files inheriting `ROOM`, one per file, directly in an
  area directory. NPCs live in that area's `npc/` subdirectory, objects in
  `obj/`.
- **`adm/daemons/find.map`** maps a directory to an area name. `MISC_D->find_area()`
  walks *up* the tree to the nearest entry; `find_place()` falls back to the
  room's own short name. This matters: 休息室 exists in four areas, 山路 in
  fifteen, so a room name is not a destination.
- **Text blocks** (`@LONG … LONG);`) must close on their own line. One file
  got this wrong and failed to compile for years.
- **Encoding** is UTF-8 throughout both lineages.
- **Both lineages change together.** A fix in `libs/xyj2000` belongs in
  `libs/xyj2000f` too, and vice versa.
- **`tools/xyjbot/rooms.json`** is generated by `build_map.py` from the
  mudlib's own exits. Regenerate it after changing exits; never hand-edit.
