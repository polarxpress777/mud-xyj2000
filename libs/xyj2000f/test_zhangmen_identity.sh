#!/bin/bash
# Regression test for the zhangmen create_identity() corruption bug.
#
# Symptom being guarded against: on a player's first entry into a room
# holding a "zhangmen"-family NPC, create_identity() cloned a heavyweight
# master NPC (puti: 15 skills, 3 carry_object chains, create_family) from
# scratch. That deep create blew the driver's call-depth budget and
# aborted partway, so create_family() never ran on the clone. Back in
# init_identity(), `family/family_name` then read as 0 and the title was
# built as "0" + zname(me) -> "0掌门大师兄", with the abort surfacing to
# the player as "你发现系统ＢＵＧ".
#
# Tests the observable behaviour through the real telnet interface (the
# seam a player actually uses), not internals.
#
# Usage: ./test_zhangmen_identity.sh
# Exit 0 = pass, 1 = fail.

set -u

LIB_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$LIB_DIR/../.." && pwd)"
DRIVER="$HOME/src/fluffos/build/src/driver"
PORT=40012
BOOT_LOG=$(mktemp -t xyj_test_boot)
OUT=$(mktemp -t xyj_test_out)

cleanup() {
  [ -n "${DRIVER_PID:-}" ] && kill -TERM "$DRIVER_PID" 2>/dev/null
  wait "${DRIVER_PID:-}" 2>/dev/null
}
trap cleanup EXIT

# A fresh driver is essential: the bug only fires on a room/NPC's
# first-ever compile after boot, so a warm driver would hide it.
pkill -f "driver config.fluffos" 2>/dev/null
sleep 2

cd "$LIB_DIR" || exit 1
"$DRIVER" config.fluffos > "$BOOT_LOG" 2>&1 &
DRIVER_PID=$!

# Wait for the port to accept connections.
for _ in $(seq 1 30); do
  if lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then break; fi
  sleep 1
done
if ! lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "FAIL: driver never started listening on $PORT"
  exit 1
fi
# Let the boot-time prewarm sweep finish so it can't race the walkthrough.
sleep 25

# Mark the log position now, so assertion 3 inspects only what happens
# during the player's own session. Errors logged earlier belong to boot
# and the prewarm sweep -- those are paid before anyone can connect and
# are deliberately out of scope here.
BOOT_LOG_OFFSET=$(wc -c < "$BOOT_LOG")

# Walk into the room holding zhangmen, exactly as a player would.
python3 "$PROJECT_DIR/scripts/mudclient.py" 127.0.0.1 $PORT \
  --timeout 40 --idle 1.5 \
  --send "gb" --send "no" --send "fluffos" --send "Mud@2026" \
  --send "goto /d/lingtai/inside2" \
  --send "look" \
  --send "quit" > "$OUT" 2>&1

FAILED=0

# Assertion 1: the player must never be shown the generic bug message.
if grep -q "你发现系统ＢＵＧ" "$OUT"; then
  echo "FAIL: player saw 你发现系统ＢＵＧ on entering /d/lingtai/inside2"
  FAILED=1
else
  echo "PASS: no 你发现系统ＢＵＧ shown to player"
fi

# Assertion 2: no NPC title corrupted with a leading "0" (the tell that
# family/family_name read as 0 during a partially-aborted master load).
if grep -qE "^[[:space:]]*0[^[:space:]]*(掌门|大师兄|大师姐)" "$OUT"; then
  echo "FAIL: corrupted NPC title with leading 0 (e.g. 0掌门大师兄):"
  grep -nE "^[[:space:]]*0[^[:space:]]*(掌门|大师兄|大师姐)" "$OUT"
  FAILED=1
else
  echo "PASS: no 0-prefixed NPC title"
fi

# Assertion 3: zhangmen must not be blamed for a recursion abort *during
# the player's session*. Boot/prewarm-time aborts are excluded by design:
# they happen before any player can connect and are never player-visible.
SESSION_LOG=$(mktemp -t xyj_test_session)
tail -c "+$((BOOT_LOG_OFFSET + 1))" "$BOOT_LOG" > "$SESSION_LOG"
if grep -a "Too deep recursion" -A1 "$SESSION_LOG" | grep -aq "zhangmen"; then
  echo "FAIL: zhangmen recursion abort during the player's session:"
  grep -a "Too deep recursion" -A1 "$SESSION_LOG" | grep -a "zhangmen" | sort -u
  FAILED=1
else
  echo "PASS: no zhangmen recursion abort during player session"
fi

# Assertion 4: the NPC must actually be present and correctly titled --
# guards against "fixing" the bug by making the NPC fail to spawn at all.
if grep -q "大弟子(Zhang men)" "$OUT"; then
  echo "PASS: zhangmen NPC present in room"
else
  echo "FAIL: zhangmen NPC missing from room entirely"
  FAILED=1
fi

echo "---"
if [ $FAILED -eq 0 ]; then
  echo "ALL PASS"
else
  echo "TEST FAILED (output: $OUT, boot log: $BOOT_LOG)"
  trap - EXIT
  cleanup
  exit 1
fi
exit 0
