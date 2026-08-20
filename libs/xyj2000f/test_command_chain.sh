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

# --- Test 6: instant commands don't idle a second between repeats ----
# The gap between queued commands used to be a flat 1 second, so "s#12"
# spent twelve seconds walking twelve rooms. Movement and look finish the
# moment they return -- no start_busy(), no pending/* flag -- so they now
# chain on the next backend cycle instead.
#
# Timed as a DIFFERENCE between a short and a long repeat: login, boot and
# the client's idle timeout dominate any single run, but they are constant
# across the two, so the extra 10 repeats are what the delta measures.
T_START=$(date +%s)
play --send "goto /d/city/kezhan" --send "look#2" >/dev/null
T_SHORT=$(( $(date +%s) - T_START ))
T_START=$(date +%s)
play --send "goto /d/city/kezhan" --send "look#12" >/dev/null
T_LONG=$(( $(date +%s) - T_START ))
DELTA=$(( T_LONG - T_SHORT ))
echo "timing: look#2 took ${T_SHORT}s, look#12 took ${T_LONG}s, delta ${DELTA}s"
# At the old flat 1s gap the extra ten repeats cost ~10s. Allow generous
# headroom for a loaded machine while still failing if the gap came back.
if [ "$DELTA" -le 4 ]; then
  echo "PASS: 10 extra instant repeats cost ${DELTA}s (was ~10s at the flat 1s gap)"
else
  echo "FAIL: 10 extra instant repeats cost ${DELTA}s -- the per-command gap is back"
  FAILED=1
fi

# --- Test 7: non-instant actions still wait for each other -----------
# The speedup must not fire dazuo repeats into a still-busy character.
# exercise.lpc:46-47 sets start_busy() AND pending/exercising, so if the
# gap logic wrongly treated a busy action as instant, repeats 2 and 3
# would die on 你现在正忙着呢 and the batch would be cancelled.
#
# Preconditions from cmds/std/exercise.lpc, all easy to get wrong:
#   :16 no_fight/no_magic rooms refuse with 安全区内禁止练功 -- so this
#       runs in 天监台, NOT 南城客栈 like the tests above
#   :38 the cost must be at least 20 气
# A longer idle than play() uses, because three cycles genuinely take
# several seconds -- that is the point of the test.
OUT7=$(python3 "$PROJECT_DIR/scripts/mudclient.py" 127.0.0.1 $PORT \
  --timeout 90 --idle 12 \
  --send "gb" --send "no" --send "fluffos" --send "Mud@2026" \
  --send "goto /d/city/tianjiantai" --send "dazuo 20#3" \
  --send "quit" 2>&1)
N_DAZUO=$(printf '%s' "$OUT7" | grep -ac "运气用功")
check "'dazuo 20#3' completes all three busy cycles" 3 "$N_DAZUO"
if printf '%s' "$OUT7" | grep -q "后续指令已取消"; then
  echo "FAIL: dazuo 20#3 was cancelled -- busy actions are not being waited for"
  FAILED=1
else
  echo "PASS: dazuo 20#3 not cancelled (busy actions still waited for)"
fi

echo "---"
if [ $FAILED -eq 0 ]; then
  echo "ALL PASS"
  exit 0
fi
echo "TEST FAILED"
exit 1
