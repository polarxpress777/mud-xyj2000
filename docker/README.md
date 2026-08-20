# Hosting xyj2000f

Player-facing connection instructions live in
[`guide/connecting.md`](../guide/connecting.md) — send that to friends.

## TL;DR for LAN play

You do **not** need Docker for friends to join. The driver already binds
`*:40012` (all interfaces), so on the same wifi they connect to:

```
telnet 192.168.20.20 40012
```

Docker is for packaging/reproducibility, not for LAN access.

## Running under Docker

> [!WARNING]
> **Never run the native driver and the container at the same time.**
> Both write LPC save files into the same `work/data/`, and two drivers
> writing the same player `.o` files will corrupt characters. Stop the
> native one first:
> ```bash
> pkill -f "driver config.fluffos"
> ```

```bash
cd docker
docker compose up -d --build     # first build compiles FluffOS, takes a while
docker compose logs -f
docker compose down
```

Build verified: image `xyj2000-mud` (627 MB), driver
`fluffos 20260729-19ffcc7a-6cf257ce` — the same upstream commit as the
local native build (`6cf257c`).

The mudlib is **bind-mounted**, not baked into the image
(`../libs/xyj2000f/work` → `/mud/work`), so:

- editing `.lpc` files on the host still works with in-game `update`
- player saves written to `work/data/` land on the host automatically

`entrypoint.sh` rewrites the config's absolute `mudlib directory` line to
the container path at startup, so there's only one `config.fluffos` and it
can't drift.

Note: the repo's `config.fluffos` still contains a stale host path from
before the project was renamed (`Mud西游记/...`). The native driver happens
to work because it's started from the right cwd, but that line should be
corrected — under Docker the entrypoint overrides it regardless.

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
