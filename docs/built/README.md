# built

Shipped and verified. Each entry states what changed, why, and **the
number that proves it**.

Newest first.

---

## 2026-08-20 — Self-contained image + named state volumes

Design: [self-contained-image.md](self-contained-image.md). Closes PRD
P0-1, P0-2, P0-3, P1-1, P1-2.

The image now bakes the mudlib in and volume-mounts only what the driver
writes player state to. The whole database turned out to be **280 KB**
(`data/user` 28K, `data/login` 28K, `data/npc/boss` 224K); the other
6.4 MB under `data/` is derived and regenerated at boot, so it ships in
the image.

**Verified:**

| Test | Result |
|---|---|
| `docker run` from `/tmp`, no repo checkout | playable, `(healthy)` |
| character survives `docker rm -f` + recreate | logs back in |
| backup → delete character → restore | account recognised again |
| dev overlay live `.lpc` edit | appears and reverts in-container |
| prod mode | host tree correctly invisible |

Also: driver pinned to `6cf257ce…` (was `master`), TCP healthcheck,
container logs capped at 5x10 MB, listener moved to `127.0.0.1`, and
`work/log` on a volume rather than tmpfs so logs survive the restart you
need them for.

`./backup.sh` does snapshot / list / restore / import, tarring volumes
through a throwaway container so it works whether or not the MUD runs.

**Two things this got wrong first, worth remembering:**

- Compose merges `volumes` **by target**. The dev overlay listed only
  `/mud/work`, so the named volumes stayed mounted on top of it and host
  characters were invisible while image data was correctly shadowed. The
  overlay must re-point every state path.
- Switching prod to volumes stranded all 7 existing characters in the
  host tree — every login read 没有这个玩家. "Host state is invisible in
  prod" was verified as a *passing test* without noticing it also meant
  *migration was missing*. Fixed by `./backup.sh import`, which refuses
  to overwrite a non-empty volume without `--force`.

**Fixed alongside:** `.gitignore`'s `libs/*/work/**/log` was excluding
`work/doc/efuns/log` and `.../floats/log` — man pages for the `log()`
efun, i.e. shipped content, not logs. Narrowed to `libs/*/work/log/**`.

---

## 2026-08-19 — Bot: navigation, sustenance and hang removal

Six defects in `tools/xyjbot/bots/changan-mieyao-bot.py` and its
supporting tools. Each was reported as "the bot got stuck".

### 1. Thirst silently froze healing

`rest_until_healed()` waited forever for 气血 that could never arrive.
`feature/damage.lpc:465` returns from `heal_up()` **before** the kee line
whenever 饮水 is 0 — regeneration is not slowed, it is off. The save file
showed the smoking gun: `kee:136 max_kee:272 food:0 water:0`.

**Built.** Sustenance handling: `drink jiudai` / `eat gou rou` from
inventory after each quest, restocking from 店小二 in 南城客栈 with a trip
to 相记钱庄 when out of cash. Plus a stall guard — the rest loop gives up
after 4 polls with no gain instead of spinning.

**Verified.** `tools/xyjbot/test_sustenance.py`, 8 cases against the
mudlib's own reply strings — including that the final sip prints *both*
"咕噜噜" and "喝得一滴也不剩", so "empty" must not match a good drink.

### 2. `bfs()` conflated "already here" with "no route"

`[]` (standing in an unsearched room) and `None` (unreachable) were both
caught by `if not path`. Arriving in the target area therefore looked
like failure, triggering a re-guess that walked back out — the observed
`长安城东门 → 大官道 → 长安城东门` loop.

**Verified.** `test_localise.py` section E.

### 3. Position guessed blindly among identical rooms

`candidates[0]` on an ambiguous title is a 1-in-7 guess east of 长安. Now
`relocalise()` holds the candidate set, steps through a shared exit, and
filters by what was actually seen.

**Verified,** whole map, 2482 titled rooms:

| | correct |
|---|---|
| old `candidates[0]` | 1884 (75.9%) |
| `relocalise()` | 2432 (**98.0%**) |

Average cost 0.76 probe moves; unambiguous rooms cost zero.

### 4. Long walks could not survive being shoved

`walk_to()` treated a routing failure as fatal, spent one of only three
retries per shove, and recorded blocked exits against a possibly-drifted
position — poisoning the route graph until no way home survived. That is
why the bot sat in 高老庄 with 天监台 27 steps away.

**Verified,** 75 runs per condition:

| | before | after |
|---|---|---|
| clean | 100% | 100% |
| 25% shove | 49% | **100%** |
| 40% shove | — | **100%** |
| 25% shove + passable gates | 32% | **100%** |

Severed routes still fail — correctly — but bounded and with a reason.

### 5. `build_map.py` could not see 11 rooms

It matched only `inherit ROOM`. 相记钱庄 uses `inherit BANK`, so the bank
was absent from the map entirely while `d/city/baihu-w1` exited south
into it. Now matches `ROOM|BANK|HOCKSHOP|CLASS_GUILD`. 长安城 went 62 → 65
rooms.

### 6. `no_mieyao` was recorded but never read

Quest targets never spawn in those rooms (`d/kaifeng/maze.lpc:27` and
friends), yet the sweep walked them anyway — including two that build
exits at runtime and cannot be walked back out of. Now skipped as goals,
still routable.

**Route audit, 开封城:** 7 steps from 天监台, 80/82 rooms sweepable,
0 dangling exits.

---

## 2026-08-19 — `#N` command repeat runs at speed

Queued commands were paced by a flat `call_out(..., 1)`, so `s#12` spent
twelve seconds walking twelve rooms. The justifying comment — that the
busy flag only lands on the next heartbeat — was false: `start_busy()`
(`feature/action.lpc:6`) is a synchronous assignment, readable the moment
`command()` returns.

Now the gap depends on what the command did: instant commands chain on
the next backend cycle, busy actions still poll at 1s.

**Verified** live against the real driver, measured as a delta so login
and boot cancel out:

| | before | after |
|---|---|---|
| 10 extra instant repeats | ~10s | **0s** |
| `dazuo 20#3` | 3 cycles | 3 cycles, not cancelled |

Also capped a whole batch at `MAX_BATCH 100`: the queue self-chains
`call_out(0)`, the same pattern that dies at the driver's 1000 nesting
limit in `prewarmd`. A 300-command chain clamps to exactly 100.

**Tests:** `libs/xyj2000f/test_command_chain.sh`, 7 checks.

---

## 2026-08-19 — Native driver boots again

`config.fluffos` pointed at `Mud西游记/...` from before the repo rename
and hard-failed with `Bad mudlib directory` — while `docker/README.md`
claimed it "happens to work". Now a relative `work`, which the Docker
entrypoint overrides anyway.
