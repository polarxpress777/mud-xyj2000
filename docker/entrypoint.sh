#!/bin/sh
# Normalise the config's absolute `mudlib directory` to the container
# path, then start the driver.
#
# The rewrite stays even though the config is now baked in, because the
# dev overlay bind-mounts the HOST config over it -- and the host copy
# carries a host path. Rewriting one line at boot beats maintaining a
# second config that silently drifts from the real one.
set -e

SRC=/mud/config.fluffos
OUT=/mud/config.container.fluffos

if [ ! -f "$SRC" ]; then
  echo "entrypoint: $SRC missing -- the image is malformed." >&2
  exit 1
fi

sed -E 's|^[[:space:]]*mudlib directory[[:space:]]*:.*|mudlib directory : /mud/work|' \
  "$SRC" > "$OUT"

# The driver refuses to boot without these. They are volume mount points
# in production and empty on a fresh volume, so create them either way.
mkdir -p /mud/work/log \
         /mud/work/data/login \
         /mud/work/data/user \
         /mud/work/data/playerhomes \
         /mud/work/data/npc/boss

echo "entrypoint: mudlib=/mud/work  config=$OUT  fluffos=${FLUFFOS_REF:-unknown}"
exec /fluffos/bin/driver "$OUT" "$@"
