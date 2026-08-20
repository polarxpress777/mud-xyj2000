#!/bin/sh
# Rewrite the host config's absolute `mudlib directory` to the container
# path, instead of maintaining a second copy of config.fluffos that would
# silently drift from the real one.
set -e

SRC=/mud/config.fluffos
OUT=/mud/config.container.fluffos

if [ ! -f "$SRC" ]; then
  echo "entrypoint: $SRC not mounted -- check docker-compose volumes." >&2
  exit 1
fi

sed -E 's|^[[:space:]]*mudlib directory[[:space:]]*:.*|mudlib directory : /mud/work|' \
  "$SRC" > "$OUT"

# The driver refuses to boot without these, and they're gitignored, so a
# fresh clone would otherwise fail on first run.
mkdir -p /mud/work/log /mud/work/data/login /mud/work/data/user /mud/work/data/playerhomes

echo "entrypoint: mudlib=/mud/work  config=$OUT"
exec /fluffos/bin/driver "$OUT" "$@"
