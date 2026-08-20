#!/bin/sh
# Back up and restore xyj2000 player state.
#
#   ./backup.sh                      snapshot -> backups/xyj-state-<ts>.tar.gz
#   ./backup.sh restore <file>       restore a snapshot (stops the MUD first)
#   ./backup.sh list                 show snapshots
#   ./backup.sh import               seed volumes from the host work/ tree
#
# The state is three named volumes totalling ~280 KB: characters, accounts
# and boss respawn timers. Everything else the game needs lives in the
# image and is rebuilt from code, so this is a complete backup despite
# being tiny -- see docs/planned/self-contained-image.md.
#
# Volumes are tarred through a throwaway alpine container rather than
# `docker cp`, so this works whether or not the MUD is running.
set -eu

cd "$(dirname "$0")"
# Overridable so the script can be exercised against throwaway volumes
# without touching real player data.
VOLUMES="${XYJ_VOLUMES:-xyj2000_xyj-user xyj2000_xyj-login xyj2000_xyj-boss}"
DIR=backups
KEEP=30

usage() { sed -n '2,10p' "$0"; exit "${1:-0}"; }

case "${1:-backup}" in
  list)
    ls -lh "$DIR" 2>/dev/null || echo "no backups yet"
    exit 0
    ;;

  backup)
    mkdir -p "$DIR"
    OUT="xyj-state-$(date +%Y%m%d-%H%M%S).tar.gz"
    MOUNTS=""
    for v in $VOLUMES; do
      docker volume inspect "$v" >/dev/null 2>&1 || {
        echo "backup: volume $v does not exist -- has the MUD ever run?" >&2
        exit 1
      }
      MOUNTS="$MOUNTS -v $v:/vol/$v:ro"
    done
    # shellcheck disable=SC2086
    docker run --rm $MOUNTS -v "$(pwd)/$DIR:/out" alpine:3.18 \
      tar czf "/out/$OUT" -C /vol .
    echo "backup: $DIR/$OUT ($(du -h "$DIR/$OUT" | cut -f1))"

    # Keep the last $KEEP, so this can run from cron unattended.
    ls -1t "$DIR"/xyj-state-*.tar.gz 2>/dev/null | tail -n "+$((KEEP+1))" \
      | while read -r old; do echo "backup: pruning $old"; rm -f "$old"; done
    ;;

  restore)
    [ $# -eq 2 ] || usage 1
    SRC=$2
    [ -f "$SRC" ] || { echo "restore: no such file: $SRC" >&2; exit 1; }
    printf 'This REPLACES all characters and accounts with %s. Type yes: ' "$SRC"
    read -r reply
    [ "$reply" = "yes" ] || { echo "restore: aborted"; exit 1; }

    docker compose stop 2>/dev/null || true
    MOUNTS=""
    for v in $VOLUMES; do
      docker volume create "$v" >/dev/null
      MOUNTS="$MOUNTS -v $v:/vol/$v"
    done
    # Clear first: a plain untar would leave characters that exist now but
    # not in the snapshot, which is a merge, not a restore.
    # shellcheck disable=SC2086
    docker run --rm $MOUNTS -v "$(cd "$(dirname "$SRC")" && pwd):/in:ro" alpine:3.18 \
      sh -c "rm -rf /vol/*/* /vol/*/.[!.]* 2>/dev/null; tar xzf '/in/$(basename "$SRC")' -C /vol"
    echo "restore: done -- start with 'docker compose up -d'"
    ;;

  import)
    # One-time migration out of the old bind-mount layout, where player
    # state lived in the host tree at libs/xyj2000f/work/data. Prod mode
    # reads named volumes instead, which start EMPTY -- so without this
    # every existing character reads as 没有这个玩家.
    #
    # Dev mode still uses the host tree directly and needs none of this.
    HOST=../libs/xyj2000f/work
    [ -d "$HOST" ] || { echo "import: $HOST not found -- run from docker/" >&2; exit 1; }

    # volume:host-subpath
    PAIRS="xyj2000_xyj-user:data/user xyj2000_xyj-login:data/login xyj2000_xyj-boss:data/npc/boss"

    for pair in $PAIRS; do
      v=${pair%%:*}
      sub=${pair#*:}
      [ -d "$HOST/$sub" ] || { echo "import: skipping $sub (absent on host)"; continue; }
      docker volume create "$v" >/dev/null
      n=$(docker run --rm -v "$v:/v" alpine:3.18 find /v -type f 2>/dev/null | wc -l | tr -d ' ')
      if [ "$n" -gt 0 ] && [ "${2:-}" != "--force" ]; then
        echo "import: $v already holds $n file(s); refusing to overwrite."
        echo "import: back up first, then re-run with: ./backup.sh import --force"
        exit 1
      fi
      docker run --rm -v "$v:/dst" -v "$(cd "$HOST/$sub" && pwd):/src:ro" alpine:3.18 \
        sh -c 'cp -a /src/. /dst/'
      echo "import: $sub -> $v ($(docker run --rm -v "$v:/v" alpine:3.18 find /v -type f | wc -l | tr -d ' ') files)"
    done
    echo "import: done -- restart with 'docker compose up -d'"
    ;;

  *) usage 1 ;;
esac
