"""TP-C02 / FR-E24 — the plausible band, status bit 6.

The rig has NO electrical headroom: it traverses raw 0–1022, so the band covers
every reachable code and FR-E24 is inert on it by design. That is the point of
the requirement's self-disabling clause, not a gap in it.

So this synthesises the headroom a correctly installed draw-wire would have
(`description.md` §8.1) by writing a deliberately narrow calibration. And rather
than move the window, it **moves the band** — writing a calibration that does or
does not contain the resting raw code. Same arithmetic, and it isolates the
check from every mechanical variable: the carriage never moves, so nothing but
the calibration changes between the passing and failing cases.

Checks, in order:
  1. On the FACTORY DEFAULT calibration the bit never sets, whatever the code.
     This is the self-disabling property, and it is what lets FR-E24 need no
     persisted "was taught" flag.
  2. A narrow band CONTAINING the resting code leaves the bit clear.
  3. A narrow band EXCLUDING it sets the bit after >= 2 windows.
  4. Returning to a containing band clears it.

Run:  .venv-m2k/Scripts/python software/hil/tp_c02.py --unit 40
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from m2k_master import M2kMaster

BIT_FIRST_WINDOW = 0x0001
BIT_RAW_IMPLAUSIBLE = 0x0040

results = []


def record(name, ok, detail):
    results.append((name, "PASS" if ok else "FAIL"))
    print(f"  {'PASS' if ok else 'FAIL'} {name:<28} {detail}", flush=True)


def wait_windows(m, unit, n=4):
    """Let n measurement windows complete, so a >=2-window rule can settle."""
    for _ in range(n):
        t0 = time.monotonic()
        while time.monotonic() - t0 < 3.0:
            if not (m.read_input(unit, 0x0005, 1)[0] & BIT_FIRST_WINDOW):
                break
        time.sleep(1.1)


def band(lo, hi):
    """FR-E24's band, computed here rather than read from the device."""
    span = abs(hi - lo)
    margin = span // 4
    return max(0, min(lo, hi) - margin), max(lo, hi) + margin


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    a = ap.parse_args()
    u = a.unit

    with M2kMaster() as m:
        as_found = m.read_holding(u, 0x0000, 7)
        raw = m.read_input(u, 0x0004, 1)[0]
        print(f"  as-found holdings: {as_found}")
        print(f"  carriage resting at raw {raw} — it does not move during this test\n")

        try:
            # ---- 1. the factory default must be inert --------------------
            m.write_multiple(u, 0x0000, [0, 1000, 10, 10000, 0, 1023])
            wait_windows(m, u, 5)
            st = m.read_input(u, 0x0005, 1)[0]
            lo, hi = band(0, 1023)
            record("default is inert", not (st & BIT_RAW_IMPLAUSIBLE),
                   f"band [{lo}, {hi}] covers every reachable code; "
                   f"status 0x{st:04x}, bit 6 clear")

            # ---- 2. a narrow band CONTAINING the resting code ------------
            lo_c, hi_c = raw - 70, raw + 70          # span 140, >= CAL_MIN_SPAN
            m.write_multiple(u, 0x0000, [0, 1000, 10, 10000, lo_c, hi_c])
            wait_windows(m, u, 4)
            st = m.read_input(u, 0x0005, 1)[0]
            b = band(lo_c, hi_c)
            record("inside a narrow band", not (st & BIT_RAW_IMPLAUSIBLE),
                   f"40005/40006 = {lo_c}/{hi_c} -> band {b}, raw {raw} inside; "
                   f"status 0x{st:04x}")

            # ---- 3. a narrow band EXCLUDING it ---------------------------
            lo_x, hi_x = raw + 230, raw + 370        # far above the resting code
            m.write_multiple(u, 0x0000, [0, 1000, 10, 10000, lo_x, hi_x])
            wait_windows(m, u, 4)
            st = m.read_input(u, 0x0005, 1)[0]
            i = m.read_input(u, 0x0000, 15)
            b = band(lo_x, hi_x)
            record("outside the band reports", bool(st & BIT_RAW_IMPLAUSIBLE),
                   f"40005/40006 = {lo_x}/{hi_x} -> band {b}, raw {i[4]} outside; "
                   f"status 0x{st:04x}, bit 6 SET")

            # the opening path must be untouched by a health indication
            record("opening still published", i[0] != 65535,
                   f"30001 = {i[0]} — FR-E24 reports and nothing more")

            # ---- 4. returning inside clears it ---------------------------
            m.write_multiple(u, 0x0000, [0, 1000, 10, 10000, lo_c, hi_c])
            wait_windows(m, u, 4)
            st = m.read_input(u, 0x0005, 1)[0]
            record("returning inside clears", not (st & BIT_RAW_IMPLAUSIBLE),
                   f"back to band {band(lo_c, hi_c)}; status 0x{st:04x}")
        finally:
            print("\n  restoring holdings ...")
            m.write_multiple(u, 0x0000, as_found[:6])
            print(f"  {m.read_holding(u, 0x0000, 7)[:6]}")

    n_fail = sum(1 for _, v in results if v == "FAIL")
    print(f"\n{len(results) - n_fail} pass, {n_fail} fail")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
