"""The proxy must not let the character be idle-kicked.

std/char.lpc:140 force-quits any player whose driver-side query_idle()
passes IDLE_TIMEOUT (include/user.h:13 -- 1200 seconds), and that quit
DROPS THE ENTIRE INVENTORY on the floor. Observed live: a 桂花酒袋, 毒蒺藜,
皮袍, 毡帽, 圆口布鞋, 镔铁棍 and 牛皮盾 all dropped in 天监台 at once.

The guard is a bare newline sent after KEEPALIVE_AFTER seconds of silence:
input as far as the driver is concerned, and the mud prints nothing back.

Run with: python3 tests/test_keepalive.py
"""
import importlib.util
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent      # tools/xyjbot
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("bp", HERE / "botproxy.py")
bp = importlib.util.module_from_spec(spec); spec.loader.exec_module(bp)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


class Stub:
    """Just enough of the session for keepalive() -- no sockets."""
    def __init__(self, silent_for):
        self.last_sent = time.time() - silent_for
        self.sent = []

    def to_mud(self, line):
        self.sent.append(line)
        self.last_sent = time.time()


keepalive = bp.Session.keepalive if hasattr(bp, "Session") else None
if keepalive is None:                     # find the class whatever it is called
    keepalive = next(v.keepalive for v in vars(bp).values()
                     if isinstance(v, type) and hasattr(v, "keepalive"))

print(f"KEEPALIVE_AFTER = {bp.KEEPALIVE_AFTER}s")
check("well inside the mud's 1200s timeout", bp.KEEPALIVE_AFTER < 1200, True)
check("and not so eager it spams", bp.KEEPALIVE_AFTER >= 60, True)

print("\nquiet for a moment: nothing sent")
s = Stub(silent_for=5)
keepalive(s)
check("no keepalive yet", s.sent, [])

print("\nquiet past the threshold: one bare newline")
s = Stub(silent_for=bp.KEEPALIVE_AFTER + 1)
keepalive(s)
check("sent an empty line", s.sent, [""])

print("\n...and it does not repeat while traffic keeps flowing")
keepalive(s)
check("still just the one", s.sent, [""])

print("\nit can be turned off")
old, bp.KEEPALIVE_AFTER = bp.KEEPALIVE_AFTER, 0
s = Stub(silent_for=9999)
keepalive(s)
check("disabled means silent", s.sent, [])
bp.KEEPALIVE_AFTER = old

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
