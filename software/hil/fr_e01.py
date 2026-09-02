"""FR-E01 — the opening is absolute: correct after reset with no homing move.

    "The reported opening shall be absolute -- derived from a reading that has
     no dependence on prior samples -- so it is correct immediately after any
     reset with no homing move or reference run."

    Verification: power-cycle with the window held at a fixed opening; the first
    published 30001 is within FR-E03 tolerance of the pre-reset value, with no
    movement of the window.

THE WINDOW MUST NOT BE PARKED AT ZERO. FR-S23 initialises 30001-30004 to 0 and
holds them at 0 until the first window completes. So at an opening of 0,
"correct immediately after reset" and "still showing the uninitialised value"
are the same reading, and the row would pass against a device that measured
nothing at all. This refuses to run below MIN_OPENING for that reason.

Nor at the extremes generally: a value the firmware could produce by accident is
a bad witness. Mid-travel is the strongest place to test from.

Run:  .venv-m2k/Scripts/python software/hil/fr_e01.py --unit 40
Then power-cycle the DUT when prompted. Do not touch the carriage.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from m2k_master import M2kMaster

BIT_FIRST_WINDOW = 0x0001

#: Below this the pre-reset value is too close to FR-S23's initial 0 to be
#: distinguishable from it. 50.0 mm is far above the noise and far from either
#: extreme.
MIN_OPENING = 500

#: FR-E03 tolerance stands in as the "within tolerance" bound. The wiper drifts
#: a raw count or two over minutes, and one raw count is ~9.8 units here.
TOLERANCE = 50


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--seconds", type=float, default=120.0)
    a = ap.parse_args()
    u = a.unit

    with M2kMaster() as m:
        before = m.read_input(u, 0x0000, 15)
        open_before, raw_before, up_before = before[0], before[4], before[7]
        print(f"  before: 30001 = {open_before}, 30005 = {raw_before}, "
              f"uptime {up_before} s, status 0x{before[5]:04x}")

        if open_before < MIN_OPENING:
            print(f"\n  REFUSING to run: 30001 = {open_before} is below "
                  f"{MIN_OPENING} (50.0 mm).")
            print(f"  FR-S23 initialises the measurement registers to 0, so at "
                  f"an opening this close")
            print(f"  to zero a correct reading and an uninitialised one are "
                  f"indistinguishable — the")
            print(f"  row would pass against a device that measured nothing.")
            print(f"\n  Move the carriage to mid-travel and run again.")
            return 1

        print(f"\n  *** POWER-CYCLE THE DUT NOW — do NOT touch the carriage ***")
        print(f"  waiting up to {a.seconds:.0f} s\n")

        # Wait for the device to go away and come back, proved by uptime.
        t0 = time.monotonic()
        back = None
        while time.monotonic() - t0 < a.seconds:
            try:
                s = m.read_input(u, 0x0007, 1)[0]
                if s < up_before:
                    back = time.monotonic() - t0
                    break
            except Exception:                                # noqa: BLE001
                pass
            time.sleep(0.1)

        if back is None:
            print(f"  no reset seen within {a.seconds:.0f} s — uptime never went "
                  f"backwards. Nothing tested.")
            return 1
        print(f"  reset detected at t = {back:.1f} s")

        # Catch the FIRST published value: poll until status bit 0 clears.
        first = None
        t1 = time.monotonic()
        while time.monotonic() - t1 < 20.0:
            try:
                i = m.read_input(u, 0x0000, 15)
            except Exception:                                # noqa: BLE001
                continue
            if not (i[5] & BIT_FIRST_WINDOW):
                first = i
                break
            time.sleep(0.05)

        if first is None:
            print("  status bit 0 never cleared — no window completed after the "
                  "reset")
            return 1

        open_after, raw_after = first[0], first[4]
        settle = time.monotonic() - t1
        print(f"  after:  30001 = {open_after}, 30005 = {raw_after}, "
              f"uptime {first[7]} s, status 0x{first[5]:04x}")
        print(f"  first published window arrived {settle:.2f} s after the device "
              f"answered again")

    d_open = abs(int(open_after) - int(open_before))
    d_raw = abs(int(raw_after) - int(raw_before))
    ok = d_open <= TOLERANCE
    print()
    print(f"  30001 moved {d_open} (0.1 mm) across the power cycle "
          f"(tolerance {TOLERANCE} = {TOLERANCE/10:.1f} mm)")
    print(f"  30005 moved {d_raw} raw counts, which bounds how much the carriage "
          f"itself drifted")
    print()
    print(f"  {'PASS' if ok else 'FAIL'} FR-E01 — the opening was correct on the "
          f"FIRST published window after reset,")
    print(f"       with no homing move and no reference run."
          if ok else
          f"       the first value disagreed with the pre-reset opening.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
