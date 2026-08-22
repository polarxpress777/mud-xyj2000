#!/usr/bin/env python3
"""Run every offline suite in this directory.

    python3 tests/run_all.py            # all of them
    python3 tests/run_all.py chase ride # only matching names

Each suite is a standalone script that prints its own PASS/FAIL lines and
exits non-zero on failure, so this only has to run them and tally. Suites
needing a live server (see NEEDS_SERVER) are skipped unless named.

Suites are run in separate processes on purpose: several of them mutate
module-level state in the bot (RIDE, DANGER, BROKEN_EXITS), and sharing an
interpreter would let one suite's leftovers decide another's result.
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEEDS_SERVER = {"test_mieyao_live", "test_dangpu_live"}
TIMEOUT = 180


def main(patterns):
    suites = sorted(p for p in HERE.glob("test_*.py"))
    if patterns:
        suites = [p for p in suites if any(x in p.stem for x in patterns)]
    else:
        suites = [p for p in suites if p.stem not in NEEDS_SERVER]

    failed, skipped = [], []
    width = max((len(p.stem) for p in suites), default=10)
    for p in suites:
        started = time.time()
        try:
            r = subprocess.run([sys.executable, str(p)], cwd=HERE.parent,
                               capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            print(f"  {p.stem:<{width}}  TIMEOUT after {TIMEOUT}s")
            failed.append(p.stem)
            continue
        secs = time.time() - started
        last = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
        mark = "ok  " if r.returncode == 0 else "FAIL"
        print(f"  {p.stem:<{width}}  {mark}  {secs:5.1f}s  {last}")
        if r.returncode != 0:
            failed.append(p.stem)
            for line in r.stdout.splitlines():
                if "FAIL" in line:
                    print(f"      {line.strip()}")
            if r.stderr.strip():
                print(f"      stderr: {r.stderr.strip().splitlines()[-1]}")

    if not patterns:
        skipped = sorted(NEEDS_SERVER)
    print()
    if skipped:
        print(f"skipped (needs a live server): {', '.join(skipped)}")
    if failed:
        print(f"{len(failed)} of {len(suites)} FAILED: {', '.join(failed)}")
        return 1
    print(f"all {len(suites)} suites pass")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
