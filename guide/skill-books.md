# Skill books

Every book in `d/obj/book/` that teaches a skill, what it teaches, and
how to actually get one. Data read from each file's
`set("skill", ([ ... ]))` mapping.

## How reading works

```
study <book>
```

`cmds/std/study.lpc` gates every read:

- **literate > 0 required** for any book at all -- 你是个文盲 otherwise.
- **`exp_required`** -- martial books check `combat_exp`, magic books
  check `daoxing` (`dx_required`). Below it: 你的武学修为还没到这个境界.
- **Diminishing returns by level**: martial books also refuse when
  `level³/10 > combat_exp`, so a high skill needs real fighting
  experience to keep progressing, not just more reading.
- **`max_skill`** -- once your level exceeds it: 太浅了，没有学到任何东西.
- **精神 cost** per attempt is
  `sen_cost + sen_cost * (difficulty - int) / 20`, minimum 5. Higher
  悟性 (`int`) makes every book cheaper to study; low 悟性 on a hard
  book can cost several times the base.

## The books

| Book | Skill | Max | exp/dx req | diff | sen | Where |
|---|---|---:|---:|---:|---:|---|
| 〖三字经〗 | literate | 20 | — | 20 | 20 | **Buy** — 长安书店 (孔方兄 / 独孤饮); also 月宫 eroom |
| 〖千字文〗 | literate | 50 | 1000 | 30 | 25 | `ask guangxi about 千字文` — 方寸山藏经阁 |
| 〖女儿经〗 | literate | 50 | 1000 | 30 | 30 | Room object, 月宫 eroom |
| 〖刀法入门〗 | blade | 20 | 100 | 20 | 20 | **Buy** — 长安书店 |
| 〖拳法入门〗 | unarmed | 20 | 100 | 20 | 20 | **Buy** — 长安书店 |
| 〖拳经〗 | unarmed | 50 | 300 | 25 | 25 | Give **猪肉包 (zhurou bao)** to 范青屏 |
| 〖青莲剑谱〗 | sword | 50 | 1000 | 30 | 30 | Give **non-empty alcohol** to 李白 (not 牛皮酒袋 — he refuses it) |
| 〖格斗秘诀〗 | parry | 60 | 5000 | 25 | 20 | 高家庄 (head NPC) |
| 〖枪法简介〗 | spear | 60 | 10000 | 25 | 25 | жjjf 密室 |
| 〖杖法简要〗 | staff | 60 | 5000 | 25 | 25 | Room object, 南海书院 |
| 碎布头 | stick | 30 | 1000 | 20 | 20 | Give **松果 (songguo)** to 老道士 — **方寸山三星洞 disciples only** |
| 〖伏魔山心经〗 | force | 30 | 200 | 25 | 25 | Give a **flower** to 东方小二姐 — see [fumo-shanxinjing.md](fumo-shanxinjing.md) |
| 〖道德经〗 | spells | 50 | — | 25 | 25 | `ask guangxi about 道德经`; also 车迟藏经阁 |
| 〖无字天书〗 | spells | 40 | — | 25 | 20 | 寿臣 (长安) |
| 〖风水〗 | spells | 20 | — | 25 | 20 | 阿七 (花果山) |
| 〖金刚经〗 | buddhism | 40 | — | 30 | 30 | Room object, 南海书院 |
| 【纯阳心得】 | taiyi | 40 | — | 30 | 40 | 吕洞宾 (五庄观) |
| 〖旧书〗 | whip | 20 | — | 20 | 20 | eastway/wangnan3 |
| makeupbook | makeup | 150 | — | 20 | 15 | 百花仙子 (蓬莱) |
| 空白帐本 (一) | kugu-blade | 50 | 10000 | 35 | 35 | 无底洞 only |
| 空白帐本 (二) | kugu-blade | 120 | 50000 | 40 | 35 | 无底洞 only |
| 空白帐本 (三) | kugu-blade | 180 | 150000 | 40 | 40 | 无底洞 only |

`sample_basic.lpc` / `testbook.lpc` are duplicates of 〖青莲剑谱〗 and
〖女儿经〗 used for testing -- not separately obtainable.

## Notes

- **The only books you can simply buy** are 三字经, 刀法入门 and
  拳法入门, from the bookstore in 长安 (`d/city/bookstore.lpc`). Everything
  else is a gift trade, a sect reward, or lying in a room somewhere.
- **Highest ceilings** outside sect-locked content: parry 60
  (〖格斗秘诀〗), spear 60, staff 60. 无底洞's kugu-blade line goes to 180
  but is restricted to that area.
- **Cheapest early win**: buy a 猪肉包 from 店小二 in 南城客栈, give it to
  范青屏, get 〖拳经〗 -- unarmed to 50 for 300 combat_exp.
- Books teaching a skill you're already past are not wasted items, just
  useless to you -- they can still be given away or sold.
