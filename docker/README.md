# Hosting xyj2000f

Player-facing connection instructions live in
[`guide/connecting.md`](../guide/connecting.md) — send that to friends.

## TL;DR

```bash
cd docker
docker compose up -d --build     # first build compiles FluffOS, takes a while
docker compose logs -f
./backup.sh                      # snapshot player state (~4 KB)
docker compose down              # volumes survive
```

Connects on `127.0.0.1:40012`. Player-facing instructions:
[`guide/connecting.md`](../guide/connecting.md).

> [!WARNING]
> **Never run the native driver and a dev-mode container at the same
> time.** Both write LPC saves into the same `work/data/`, and two
> drivers writing the same `.o` files corrupt characters. Stop the
> native one first: `pkill -f "driver config.fluffos"`.
> Prod mode is unaffected — it uses volumes, not the host tree.

## Two modes

| | command | mudlib from | player saves in |
|---|---|---|---|
| **prod** (default) | `docker compose up -d` | the image | named volumes |
| **dev** | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` | the host tree | the host tree |

Prod is self-contained: `docker run -p 40012:40012 xyj2000-mud` works
with no checkout of this repo. Dev restores live `.lpc` editing with
in-game `update`.

The dev overlay re-points **every** state path at the host, not just
`/mud/work`. Compose merges `volumes` by target, so listing only
`/mud/work` leaves the named volumes mounted on top of it and the host's
characters stay invisible — a half-and-half state that looks like it
works until you wonder where your character went.

## What is in the image vs in a volume

The whole database is **280 KB**. Everything else the game needs is
regenerated from code at boot, so it ships in the image.

| Path | Size | Where | Why |
|---|---|---|---|
| `data/user/` | 28K | volume | characters |
| `data/login/` | 28K | volume | accounts, holds password hashes |
| `data/npc/boss/` | 224K | volume | boss respawn timers |
| `log/` | — | volume | must survive a restart to debug a crash-loop |
| rest of `data/` | 6.4M | image | derived; driver rewrites it at boot |

Three narrow volumes rather than one at `data/` on purpose: Docker seeds
a named volume from image content **on first run only**, so a volume at
`data/` would freeze the 6.4 MB of derived files at first boot and shadow
every later image update.

`data/login` is also excluded from the image via `.dockerignore` — a
runtime volume shadows it, but shadowing is not the same as never
shipping password hashes in a distributable artifact.

## Backups

```bash
./backup.sh                              # -> backups/xyj-state-<ts>.tar.gz
./backup.sh list
./backup.sh restore backups/xyj-....tar.gz
```

Tars the volumes through a throwaway container, so it works whether or
not the MUD is running, and keeps the last 30 (safe to cron). Restore
clears the volumes first — a plain untar would merge, leaving characters
that exist now but not in the snapshot.

Verified end to end: back up, delete a character's save, restore, and the
account is recognised again at the login prompt.

## Pinning

`FLUFFOS_REF` is pinned to `6cf257cedbb38e4b122ad79df08742c6629860aa`,
the commit the native driver was verified against. The running container
reports it:

```bash
docker logs xyj2000-mud | grep entrypoint:
```

## Health

A `HEALTHCHECK` opens a TCP connection to 40012. `restart:
unless-stopped` alone only reacts to the process *exiting*; a driver that
is up but no longer accepting logins would otherwise stay "running"
forever. Container stdout is capped at 5 x 10 MB.

## About "a database"

There isn't one, and you almost certainly don't want to add one.

This mudlib persists **everything** as LPC flat-file object saves (`.o`)
under `work/data/` — about 6.3 MB total:

```
work/data/user/p/polar.o     player characters
work/data/login/             login records
work/data/board/  mail/      boards, mail
work/data/playerhomes/       player housing
```

That directory *is* the database. Persistence goes through `F_SAVE` /
`save_object()`, called from all over the mudlib (`obj/user.lpc`,
`gmd.lpc`, `combatd.lpc`, ...). Retrofitting Postgres/MySQL would mean
rewriting every one of those call sites — a large project with no
gameplay benefit, and it would break the `gmedit` offline-load path.

**What to do instead:**

- Durability: `work/data/` is on the host. Snapshot or back it up
  (`tar czf backup-$(date +%F).tgz libs/xyj2000f/work/data`), or commit
  it. Note `.gitignore` currently excludes `data/{login,user,playerhomes}`
  so real player data is *not* in git by default — deliberate, but it
  means backups are on you.
- FluffOS *does* ship DB efuns (`sqlite-dev` / `mariadb-dev` are in the
  build deps above, giving `db_connect()` etc.). Reasonable if you later
  want a DB-backed *feature* — a web leaderboard, stats site, audit log —
  reading alongside the flat files. Not a replacement for player saves.
- If you want a DB container anyway, add a `postgres` service to
  `docker-compose.yml`; it'll share the compose network. Nothing in the
  mudlib will use it until you write LPC that does.

## Clients: is rlwrap + nc required?

No. The server speaks plain telnet over TCP. Any of these work:

| Client | Notes |
|---|---|
| `telnet <ip> 40012` | Preinstalled on most systems. Fine. |
| `nc <ip> 40012` | Raw pipe — **no line editing, no history** (arrow-up won't recall commands). |
| `rlwrap nc <ip> 40012` | Adds readline: history, arrow keys, editing. This is the only thing rlwrap is for. |
| **Mudlet** | Recommended for friends. Proper UTF-8/Chinese, scrollback, its own Lua trigger/alias scripting. |
| TinTin++ | Terminal MUD client, also scriptable. |

`tools/xyjbot/botproxy.py` is a **personal** tool: it binds `127.0.0.1`
only and its bots are shared per-process, so it's not a multiplayer front
door. Friends should connect to `40012` directly.

## Firewall

macOS firewall is currently disabled, so nothing blocks LAN connections.
If it gets enabled, allow the `driver` binary (or Docker) to accept
incoming connections.

## Security

There is no encryption and passwords cross the network in the clear.
That's acceptable on a trusted home wifi. **Do not port-forward 40012 to
the public internet** — this is a 1990s codebase with no modern hardening.
