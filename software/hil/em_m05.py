"""EM-M05 — does an end switch stay continuously active while parked at a limit?

    "End-switch actuation shall be repeatable, and each switch shall stay
     CONTINUOUSLY ACTIVE from its actuation point to the mechanical limit."

This is the controlled version of an observation that was previously
over-interpreted. A rig fault was once inferred from bit 3 clearing while 30001
had not yet changed — which a switch releasing as the operator moves off it
explains just as well, one window ahead of the position register. The two are
only separable when **nothing is moving**, so this run requires exactly that.

Method: park the carriage at a limit, hands off, and watch. Two things must hold
for the whole window:

  * status bit 3 stays SET, with no dropout however brief;
  * 30005 stays put, which is what proves the carriage really was stationary --
    without it, "the switch held" and "the operator nudged it back on" are the
    same observation.

A dropout of even one sample is a failure worth knowing about: bit 3 is what a
master reads to decide the window is shut, and it is read at that moment more
than any other.

Run:  .venv-m2k/Scripts/python software/hil/em_m05.py --unit 40 --seconds 30
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from m2k_master import M2kMaster

BIT_END_REACHED = 0x0008
BIT_SWITCH_FAULT = 0x0010

#: Raw counts the carriage may wander and still count as parked. The still-rig
#: noise floor measured +-1 count; 3 allows for it without allowing motion.
STILL_TOLERANCE = 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--seconds", type=float, default=30.0)
    a = ap.parse_args()
    u = a.unit

    with M2kMaster() as m:
        first = m.read_input(u, 0x0000, 15)
        if not (first[5] & BIT_END_REACHED):
            print(f"  status 0x{first[5]:04x} — bit 3 is NOT set, so the carriage "
                  f"is not at a limit.")
            print(f"  30001 = {first[0]}, 30005 = {first[4]}. Park it at a stop "
                  f"and run again.")
            return 1

        print(f"  parked: 30001 = {first[0]}, 30005 = {first[4]}, "
              f"status 0x{first[5]:04x} (bit 3 set)")
        print(f"  watching {a.seconds:.0f} s — HANDS OFF the carriage\n")

        raws, dropouts, samples = [], [], 0
        t0 = time.monotonic()
        while time.monotonic() - t0 < a.seconds:
            try:
                i = m.read_input(u, 0x0000, 15)
            except Exception:                                # noqa: BLE001
                continue
            t = time.monotonic() - t0
            samples += 1
            raws.append(i[4])
            if not (i[5] & BIT_END_REACHED):
                dropouts.append((t, i[4], i[5]))
                print(f"  {t:6.2f}s  *** bit 3 CLEARED — 30005 = {i[4]}, "
                      f"status 0x{i[5]:04x}", flush=True)
            elif samples % 40 == 0:
                print(f"  {t:6.2f}s  bit 3 held, 30005 = {i[4]}", flush=True)
            time.sleep(0.1)

    wander = max(raws) - min(raws)
    parked = wander <= STILL_TOLERANCE
    print()
    print(f"  {samples} samples over {a.seconds:.0f} s")
    print(f"  30005 spanned {min(raws)}..{max(raws)} = {wander} counts "
          f"(tolerance {STILL_TOLERANCE})")
    print(f"  bit 3 dropouts: {len(dropouts)}")
    print()

    if not parked:
        print(f"  INCONCLUSIVE — the carriage moved {wander} counts, so a held "
              f"bit 3 cannot be\n  distinguished from the operator keeping it on "
              f"the switch. Park it and repeat.")
        return 1

    ok = not dropouts
    print(f"  {'PASS' if ok else 'FAIL'} EM-M05 — the switch "
          + ("stayed continuously active for the whole window while the carriage "
             "was demonstrably stationary"
             if ok else
             f"RELEASED {len(dropouts)} time(s) with the carriage stationary. "
             f"Bit 3 is what a master reads to decide the window is shut."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
