# 伏魔山心经 (上) -- how to get it

A force-skill (内功心法) book, teaches `force` up to level 30.
Source: `d/obj/book/forcebook.lpc`. Confirmed against `d/obj/book/README:16`.

Not sold anywhere. It's the reward for a gift quest, and the gift has
to be grown -- there's no vendor for it.

## 1. Get a 黄粱枕 (pillow)

`d/obj/misc/pillow.lpc` -- an ordinary purchasable item (`value` 1000).

Sleeping while carrying it sends you into the dream realm
(`/d/ourhome/honglou/kat`). Absent the pillow, any normal `sleep` also
has a flat 1% chance of the same thing (`feature/damage.lpc:186`,
`random(100) == 1`).

## 2. Find the seed

Dream realm room `d/ourhome/honglou/cave.lpc` (蓼汀花溆) spawns
`/d/obj/misc/seed.lpc` (花籽) as a room object.

```
get seed
```

## 3. Grow it -- water through three stages

`d/obj/misc/seed.lpc`'s `grow()`/`do_water()`. The item's `id` changes
as it grows, so the water target changes too:

```
water seed     # id "seed"  -> (random chance per watering) sprouts to "germ" (绿芽)
water germ     # id "germ"  -> (random chance per watering) grows to "plant" (绿草)
water plant    # id "plant" -> (random chance per watering) blooms into a flower, seed destructed
```

Each `water` costs **10 气血** (`who->add("kee", -10)`); if your kee is
too low it knocks you unconscious instead of just failing
(`d/obj/misc/seed.lpc:142-147`). Don't chain waterings back to back --
watering when `water >= 5` (i.e. it isn't thirsty yet) wastes the
action entirely.

If you leave it too long between waterings it dries out
(`me->set("dried", 1)`) and stops growing for good -- keep checking
back on it.

## 4. Deliver it

Carry the finished flower out of the dream, back to 傲来's 花果山
东方武馆 area, to 东方小二姐 (`d/dntg/hgs/npc/dongfanger.lpc`):

```
give flower to dongfang
```

Her `accept_object()` checks `ob->query("id") == "flower"` and hands
you `/d/obj/book/forcebook.lpc` (伏魔山心经) in return.

## Notes

- A wild-growing flower also exists at `/d/obj/flower/yehua.lpc`,
  found lying in `d/moon/road1/2/3.lpc` (月宫). Its `id` also includes
  `"flower"`, so it technically also satisfies the gift check -- but
  月宫 is a late-game area, not the intended path. The dream-grown
  flower above is the one actually designed for this quest.
- GM shortcut (bypasses all of this, for testing): `clone
  /d/obj/book/forcebook` then `give fumo book to <player>` while in the
  same room as them, as a wizard account.
