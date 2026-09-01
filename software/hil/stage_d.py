"""Stage D verification — FR-E02 publish cadence, FR-S30 window abort, FR-E03 stability.

All three are reachable over Modbus alone, with no bench intervention.

The cadence and the abort are measured together, because FR-S30 gives a clean
observable for FR-E02: writing 40002 re-asserts status bit 0 (no completed
window), and the bit clears when the next window closes. The time between the
write and the bit clearing IS the window duration.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import modbus_rtu_codec as codec
from m2k_master import M2kMaster

BIT_FIRST_WINDOW = 0x0001
BIT_WIPER_FAULT = 0x0004
results = []


def record(name, req, ok, detail):
    results.append((name, req, "PASS" if ok else "FAIL", detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name:<10} {detail}", flush=True)


def window_time(m, u, ms):
    """Write 40002 = ms and time how long status bit 0 takes to clear."""
    m.write_single(u, 0x0001, ms)
    t0 = time.monotonic()
    # FR-S30: the bit must be set immediately after the write
    s0 = m.read_input(u, 0x0005, 1)[0]
    asserted = bool(s0 & BIT_FIRST_WINDOW)
    deadline = t0 + (ms / 1000.0) * 3 + 5
    cleared = None
    while time.monotonic() < deadline:
        s = m.read_input(u, 0x0005, 1)[0]
        if not (s & BIT_FIRST_WINDOW):
            cleared = time.monotonic() - t0
            break
    return asserted, cleared


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    a = ap.parse_args()
    u = a.unit

    with M2kMaster() as m:
        as_found = m.read_holding(u, 0x0000, 7)
        print(f"  as-found holdings: {as_found}\n")
        try:
            # ---- FR-E03 / FR-E13 stability -----------------------------
            raws = [m.read_input(u, 0x0004, 1)[0] for _ in range(60)]
            span = max(raws) - min(raws)
            record("stability", "FR-E03", span <= 3,
                   f"30005 over 60 reads: min {min(raws)}, max {max(raws)}, "
                   f"span {span} LSB (criterion <=3), median "
                   f"{statistics.median(raws):.0f}")

            st = m.read_input(u, 0x0005, 1)[0]
            record("wiper", "FR-E07", not (st & BIT_WIPER_FAULT),
                   f"status 0x{st:04x} — bit 2 clear, so we_sample()'s pull "
                   f"test trusts the front-end")

            # ---- FR-S30 + FR-E02 --------------------------------------
            for ms in (3000, 700):
                asserted, cleared = window_time(m, u, ms)
                record("TP-S30", "FR-S30", asserted,
                       f"writing 40002 = {ms} re-asserted status bit 0")
                if cleared is None:
                    record("TP-E02", "FR-E02", False,
                           f"window never completed within the timeout")
                else:
                    # one poll is ~110 ms, so that is the measurement floor
                    ok = abs(cleared - ms / 1000.0) <= max(0.35, 0.25 * ms / 1000.0)
                    record("TP-E02", "FR-E02", ok,
                           f"40002 = {ms} ms -> window closed after "
                           f"{cleared*1000:.0f} ms (poll granularity ~110 ms)")
        finally:
            print("\n  restoring holdings ...")
            m.write_multiple(u, 0x0000, as_found[:6])
            print(f"  {m.read_holding(u, 0x0000, 7)[:6]}")

    n_fail = sum(1 for _, _, v, _ in results if v == "FAIL")
    print(f"\n{len(results)-n_fail} pass, {n_fail} fail")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
