# Self-contained image + named state volumes

**Solves:** [PRD](../needs-building/PRD.md) P0-1 (image not self-contained),
P0-3 (no backup), P1-2 (driver unpinned). Unblocks P1-4.
**Crosses:** architecture review Seam 1 (code and state share a directory).

## The problem in one line

`work/` is both the game's source code and its database, and the current
image mounts the whole thing, so `docker run xyj2000-mud` exits
immediately.

## Approach

Bake the mudlib into the image; mount **only** the paths the driver
writes player state to.

Measured, not assumed — everything gitignored-and-present under `work/`:

| Path | Size | Fate | Why |
|---|---|---|---|
| `data/user/` | 28K | **volume** | characters |
| `data/login/` | 28K | **volume** | accounts, contains password hashes |
| `data/npc/boss/` | 224K | **volume** | boss respawn timers |
| `log/` | 10M | **tmpfs** | recreated every boot |
| rest of `data/` | 6.4M | **image** | derived; the driver rewrites it at boot |

The entire database is **280 KB**.

The 6.4 MB of other `.o` files look like state but are not: the driver
regenerates them from code, and their serialisation is stable across
boots (verified by md5 over a restart), which is why they can sit in the
image without churning.

## Three volumes, not one at `data/`

Docker seeds a named volume from image content **on first run only**.
Mounting one volume at `data/` would capture the 6.4 MB of derived files
at first boot and then shadow them forever — a later image with updated
game data would be silently ignored. Narrow mounts avoid this: only the
280 KB that must never come from an image is volume-backed.

## Two modes

| | compose file | mudlib source | use |
|---|---|---|---|
| **prod** | `docker-compose.yml` | baked into image | hosting |
| **dev** | `+ docker-compose.dev.yml` | bind-mounted from host | live `.lpc` editing + in-game `update` |

The dev overlay restores exactly today's behaviour, so nothing is lost —
it just stops being the default.

**Implementation trap found while building this:** Compose merges
`volumes` **by target**. A dev overlay listing only `/mud/work` leaves
the named volumes mounted on top of it, so the image's game data is
correctly shadowed but the host's characters are *not* visible. The
overlay must re-point every state path, not just the root.

## Rejected alternatives

- **Two images (app + "db").** A volume is not an image, and there is no
  second process to run one. That pattern is for a database *server*;
  this driver reads and writes flat files in-process.
- **One volume at `work/`.** What we do now. Nothing is self-contained,
  and backups require knowing which subpaths are state.
- **One volume at `data/`.** Simpler to write, but the first-run seeding
  rule above makes game-data updates undeliverable.
- **Relocating state outside `work/`.** Cleanest in theory; the mudlib
  hardcodes these paths, so it means patching the game to fix packaging.
- **`docker cp` backups.** Requires a running container; a volume tar
  does not.

## Done tests

1. On a machine with no clone: `docker run -d -p 40012:40012 -v …` gives
   a playable MUD.
2. Create a character → `docker rm -f` → re-run → the character exists.
3. `docker compose -f docker-compose.yml -f docker-compose.dev.yml up`:
   editing a host `.lpc` and running in-game `update` takes effect.
4. Backup, delete a character's save, restore, log in as that character.
5. `FLUFFOS_REF` is a full SHA and the built driver reports it.

## Notes

- Pin `FLUFFOS_REF=6cf257cedbb38e4b122ad79df08742c6629860aa` — the commit
  the verified native driver was built from, not `master`.
- `data/login/` holds password hashes; it must be excluded from the image
  via `.dockerignore`, not merely shadowed by a volume at runtime.
- Build context becomes the repo root (the mudlib must be copyable), so a
  `.dockerignore` is required or ~89 MB of `libs/` ships to the daemon.
