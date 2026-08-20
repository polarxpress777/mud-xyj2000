# Architecture review — xyj2000

How the system is actually put together, verified by running it. Written
to be read before designing anything in [PRD.md](PRD.md).

## The layers

```
  you / a bot script
        |
        v
  botproxy.py :40099        host Python. Relays bytes, runs triggers and
        |                   timers, owns /<botname> and /bots commands.
        |                   Bot scripts run here on threads (botapi.py).
        v
  FluffOS driver :40012     C. Compiles and executes LPC, owns the
        |                   heartbeat, call_out queue and sockets.
        v
  the mudlib  work/*.lpc    the game: rooms, NPCs, commands, and ALSO
        |                   the schema and the persistence code.
        v
  work/data/*.o             flat-file saves. The database.
```

Two facts about this stack drive most of the design problems:

1. **The mudlib is simultaneously the code and the database.** There is
   no schema, no migration, no separation. `work/` contains 4938 source
   files *and* 1361 tracked save files, in one tree.
2. **The driver is a single process with one heartbeat.** Everything —
   combat, regeneration, queued commands, prewarm — is scheduled on the
   same `call_out`/heartbeat machinery, and they contend.

## Seam 1 — code and state share a directory

**Now.** `docker-compose.yml` bind-mounts the whole `work/` tree. That
one mount carries immutable game source *and* mutable player state.

**Consequences.**
- The image cannot be self-contained (PRD P0-1): baking `work/` in would
  freeze player saves into the image.
- Backups cannot be taken by copying the mount; you must know which
  subpaths are state (`data/`, `log/`) and which are code.
- `.gitignore` already encodes this knowledge, painfully and by hand —
  ~40 rules distinguishing "runtime churn" from "shipped content",
  including a comment recording a case where the distinction was got
  wrong and broke Chinese-name registration.

**The line, where it actually falls:**

| Path | Nature |
|---|---|
| `work/**/*.lpc`, `work/include/` | code — immutable, versioned |
| `work/data/user/`, `data/login/`, `data/playerhomes/` | player state — must persist, must be backed up |
| `work/data/**/*.o` (NPC, zhangmen, boss) | *derived* state — regenerated from code |
| `work/log/` | disposable |

The derived-state row is the subtle one and the reason the split is not
purely mechanical. Those `.o` files are rewritten by the driver at boot.
Their serialisation is **stable across boots** (verified: identical
md5s over a restart), so they can be committed without churn — but they
are not authored content either.

**Resolved 2026-08-20.** The line is drawn: code in the image, the
280 KB of genuine player state in three named volumes. The derived-state
row is what made this non-obvious, and it is why the volumes are narrow
rather than one mount at `data/`. See
[../built/self-contained-image.md](../built/self-contained-image.md).

## Seam 2 — the bot's world model is derived from source, offline

`build_map.py` parses 4938 `.lpc` files and emits `rooms.json` (2505
rooms). The bot then navigates purely from that snapshot.

**This is a good seam** — it keeps map-building out of the hot path and
makes navigation testable offline without a running MUD, which is how
`relocalise()` got measured across the entire map (75.9% → 98.0%) without
a driver.

**But it is a snapshot, and it lies in three known ways:**

1. **Rooms it cannot see.** It matched only `inherit ROOM`, silently
   dropping 11 rooms that inherit `BANK`/`HOCKSHOP`/`CLASS_GUILD` —
   including 相记钱庄, which the walker could therefore never route to.
   Fixed, but the class of bug remains: the parser has to keep pace with
   how the mudlib is written.
2. **Exits that are not `set("exits")`.** Command-based transitions
   (`dive`, teleports, gated doors) are invisible. `SPECIAL_EXITS` hand-
   patches four of them. This is the likely major cause of PRD P2-1
   (only 967/2505 rooms can route home).
3. **Exits computed at runtime.** `d/nanhai/zhulin*` builds each exit as
   `"zhulin" + random(6)` at `create()` time; `d/kaifeng/maze` generates
   a 3D maze. No static parse can ever represent these — hence the
   separate `escape_maze()`/`sweep_maze()` probing path.

**Design consequence.** Anything that widens bot coverage should first
*measure* which of (1)/(2)/(3) dominates. They need completely different
fixes, and the PRD says so.

## Seam 3 — the bot cannot see its own position

The MUD never tells a client where it is. The bot infers position from
room title + visible exits, which is ambiguous by construction: 840 of
2482 titled rooms share their (title, exits) signature with another room.

This is genuinely the hardest part of the system, and it is now handled
the way a robot handles it: hold a candidate set, take a discriminating
step, filter by what was actually observed (`relocalise()`).

**Residual risk.** 50 rooms still resolve wrongly (98.0% correct), all in
symmetric mazes. Those get a logged warning and a best guess. That is the
right trade — returning "unknown" made callers retry forever, which was
the original hang in a different costume.

## Seam 4 — the driver's scheduler is a shared, bounded resource

Every deferred action goes through `call_out`. Two independent bugs this
session were the *same* bug in this seam:

- `prewarmd.lpc:70` self-chains `call_out(..., 0)` ~988 deep and dies at
  the driver's 1000 nesting limit.
- `feature/alias.lpc`'s command queue does the same thing, and once the
  gap became `call_out(0)` an unbounded `;`-chain could reach that limit
  too. Capped at `MAX_BATCH 100`.

**Lesson worth writing down:** `call_out(fn, 0)` is not "run soon", it is
"recurse". Any self-chaining `call_out(0)` needs a bound, and the bound
must be well under 1000.

**Related.** The 1-second gap between queued commands was justified by a
comment asserting the busy flag lands on the next heartbeat. It does not:
`start_busy()` (`feature/action.lpc:6`) is a synchronous assignment. The
comment had outlived its truth and cost a second per command for years.

## Seam 5 — hosting concerns live inside the game

`entrypoint.sh` rewrites `config.fluffos` at boot rather than keeping a
second copy — a good call, since a duplicated config drifts. But other
operational concerns have no home at all: no healthcheck, no log
rotation, no backup, no supervision for `botproxy.py`.

The `config.fluffos` path bug is the cautionary tale. It pointed at
`Mud西游记/...` from before the repo rename and **hard-fails the native
driver** (`Bad mudlib directory`), while `docker/README.md` asserted it
"happens to work". The container masked the breakage because the
entrypoint overwrites that line — so the documented-and-believed state
and the real state had silently diverged.

## Risk register

| Risk | Severity | Standing |
|---|---|---|
| Player state has no backup | **high** | closed 2026-08-20 — `docker/backup.sh` |
| Wedged driver undetected | **high** | closed 2026-08-20 — TCP healthcheck |
| Image not runnable standalone | medium | closed 2026-08-20 — mudlib baked in |
| Logs unbounded | medium | closed 2026-08-20 — 5x10 MB cap |
| Driver version unpinned | medium | closed 2026-08-20 — pinned to 6cf257ce |
| Prewarm broken since Aug 16 | medium | open (P1-3) |
| Bot proxy dies with its terminal | medium | open (P1-4) |
| ~60% of map cannot route home | low | open (P2-1), bot degrades honestly |
| Map parser drifts from mudlib idiom | low | mitigated by tests, recurring by nature |
| Position ambiguity in mazes | low | accepted — 98% correct, warns on the rest |

## What is structurally sound

Worth stating, so it does not get "fixed":

- **The offline map/nav split.** Enables real testing without a MUD, and
  that is why navigation could be measured over 2482 rooms at all.
- **Bind-mounted state with host ownership.** Saves land on the host as
  `polar staff`, no root-owned files — the common Docker failure mode is
  simply absent.
- **`entrypoint.sh` rewriting one config** instead of maintaining two.
- **Flat-file persistence.** Correct for this driver; a database would
  fight the object model for no gain. `docker/README.md` argues it well.
- **The bot degrading loudly.** Every failure path now logs a reason and
  gives up bounded, rather than looping. That property was won three
  separate times this session and should be defended in review.
