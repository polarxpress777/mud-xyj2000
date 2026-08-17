#!/bin/bash
# Tests for the ";" command-chaining and "#" command-repeat features.
#
#   w;e;s;u   -> run each command in left-to-right order
#   s#13      -> run "s" 13 times
#
# Both abort the remainder if a step fails (blocked exit, "你的动作还没有
#完成", over-encumbered, etc -- all of which make command() return 0) or
# if the player is dragged into combat, so a partially-blocked chain can't
# scatter the character somewhere unintended.
#
# Exercised through the real telnet interface, i.e. the seam a player
# actually types at.
#
# Usage: ./test_command_chain.sh   (exit 0 = pass, 1 = fail)

set -u

LIB_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$LIB_DIR/../.." && pwd)"
DRIVER="$HOME/src/fluffos/build/src/driver"
PORT=40012
BOOT_LOG=$(mktemp -t xyj_chain_boot)

cleanup() {
  [ -n "${DRIVER_PID:-}" ] && kill -TERM "$DRIVER_PID" 2>/dev/null
  wait "${DRIVER_PID:-}" 2>/dev/null
}
trap cleanup EXIT

pkill -f "driver config.fluffos" 2>/dev/null
sleep 2
cd "$LIB_DIR" || exit 1
"$DRIVER" config.fluffos > "$BOOT_LOG" 2>&1 &
DRIVER_PID=$!

for _ in $(seq 1 40); do
  lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 1
done
if ! lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "FAIL: driver never started listening on $PORT"
  exit 1
fi
# Wait for the boot-time prewarm sweep to finish. While it runs the driver
# is compiling ~4900 files and responses lag badly enough to time out a
# scripted session, which looks exactly like a feature failure.
for _ in $(seq 1 120); do
  tail -1 "$LIB_DIR/work/log/PREWARM" 2>/dev/null | grep -q "prewarm done" && break
  sleep 2
done
sleep 2

# Runs a scripted session; prints its output.
play() {
  python3 "$PROJECT_DIR/scripts/mudclient.py" 127.0.0.1 $PORT \
    --timeout 40 --idle 1.2 \
    --send "gb" --send "no" --send "fluffos" --send "Mud@2026" "$@" \
    --send "quit" 2>&1
}

FAILED=0

check() { # check <description> <expected-count> <actual-count>
  if [ "$2" -eq "$3" ]; then
    echo "PASS: $1 (saw $3)"
  else
    echo "FAIL: $1 -- expected $2, saw $3"
    FAILED=1
  fi
}

# --- Test 1: ";" runs every command in order -------------------------
# 南城客栈 exits: west -> 朱雀大街, east -> 客房, up -> wiz. Walk west
# then back east, then look: we end up back in 南城客栈 having passed
# through 朱雀大街.
# Baseline note: the player LOGS IN at 南城客栈, so that room is already
# printed once before any command runs.
OUT1=$(play --send "goto /d/city/kezhan" --send "west;east;look")
N_CENTER=$(printf '%s' "$OUT1" | grep -c "朱雀大街 -")
N_KEZHAN=$(printf '%s' "$OUT1" | grep -c "南城客栈 -")
check "';' chain visits the intermediate room" 1 "$N_CENTER"
# login + goto + the ";east" arrival back + the ";look"
check "';' chain returns and looks" 4 "$N_KEZHAN"

# --- Test 2: "#" repeats the command N times -------------------------
# login + goto + 3 repeated looks = 5.
OUT2=$(play --send "goto /d/city/kezhan" --send "look#3")
N_LOOK=$(printf '%s' "$OUT2" | grep -c "南城客栈 -")
check "'look#3' repeats three times" 5 "$N_LOOK"

# --- Test 3: a failing step aborts the rest of the chain -------------
# 卧室 (/d/lingtai/sleep) has exactly one exit: north. Going east must
# fail, and the trailing "look" must NOT run.
OUT3=$(play --send "goto /d/lingtai/sleep" --send "east;look")
N_SLEEP=$(printf '%s' "$OUT3" | grep -c "卧室 -")
check "failed step aborts the rest (no extra look)" 1 "$N_SLEEP"
if printf '%s' "$OUT3" | grep -q "后续指令"; then
  echo "PASS: player is told the remaining commands were cancelled"
else
  echo "FAIL: no cancellation notice shown to player"
  FAILED=1
fi

# --- Test 4: repeats are capped, not unbounded -----------------------
# A huge repeat must be refused/clamped rather than flooding the mud.
OUT4=$(play --send "goto /d/city/kezhan" --send "look#9999")
N_HUGE=$(printf '%s' "$OUT4" | grep -c "南城客栈 -")
if [ "$N_HUGE" -le 53 ]; then
  echo "PASS: oversized repeat clamped (saw $N_HUGE)"
else
  echo "FAIL: oversized repeat not clamped (saw $N_HUGE)"
  FAILED=1
fi

# --- Test 5: ordinary commands still work ----------------------------
# Guards against the parser mangling input that contains neither ; nor #.
OUT5=$(play --send "goto /d/city/kezhan" --send "look")
if printf '%s' "$OUT5" | grep -q "南城客栈 -"; then
  echo "PASS: plain commands unaffected"
else
  echo "FAIL: plain commands broken"
  FAILED=1
fi

echo "---"
if [ $FAILED -eq 0 ]; then
  echo "ALL PASS"
  exit 0
fi
echo "TEST FAILED"
exit 1
