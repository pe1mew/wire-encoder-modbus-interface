"""TP-C01 / FR-E23 — the position path follows the carriage, status bit 7.

The fault this exists for cannot be produced electrically: a draw-wire that is
tangled, snapped, seized or slipping leaves the potentiometer **electrically
perfect**. It passes the FR-E07 pull test, reads a stable plausible constant,
and satisfies FR-E03's ≤3 LSB stability. Nothing at the pin can see it.

Detaching the draw-wire from the carriage reproduces it exactly: the window
moves, the end switches witness the movement, and the wiper does not follow.

A *departure sequence* is at-a-stop → away for ≥2 windows → at-a-stop. One full
open-and-close cycle is TWO sequences. Three consecutive low-excursion
sequences set bit 7; one good sequence clears it.

Bit 6 must stay CLEAR throughout: the factory-default calibration makes FR-E24
self-disabling, so this is the *mechanism stuck* signature — bit 7 alone.

Run:  .venv-m2k/Scripts/python software/hil/tp_c01.py --unit 40 --seconds 240
Then drive the window through both stops repeatedly with the wire detached;
re-attach and traverse once more before the time runs out.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from m2k_master import M2kMaster

BIT_END_REACHED = 0x0008
BIT_RAW_IMPLAUSIBLE = 0x0040
BIT_POSITION_STUCK = 0x0080


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--seconds", type=float, default=240.0)
    a = ap.parse_args()
    u = a.unit

    stops = 0
    raws = []
    stuck_first = None
    stuck_cleared = None
    bit6_ever = False

    with M2kMaster() as m:
        first = m.read_input(u, 0x0000, 15)
        print(f"  start: 30005 = {first[4]}, status 0x{first[5]:04x}")
        print(f"  holdings {m.read_holding(u, 0x0000, 7)[:6]}")
        print()
        print("  Drive the window through BOTH stops, repeatedly, wire DETACHED.")
        print("  One open+close cycle = two departure sequences; three are needed.")
        print("  Then RE-ATTACH the wire and traverse once more.")
        print()
        print("   t(s)  30005  status  bit3  bit6  bit7  note")

        t0 = time.monotonic()
        prev = None
        while time.monotonic() - t0 < a.seconds:
            try:
                i = m.read_input(u, 0x0000, 15)
            except Exception:                                # noqa: BLE001
                continue
            t = time.monotonic() - t0
            st, raw = i[5], i[4]
            raws.append(raw)
            at_stop = bool(st & BIT_END_REACHED)
            b6 = bool(st & BIT_RAW_IMPLAUSIBLE)
            b7 = bool(st & BIT_POSITION_STUCK)
            if b6:
                bit6_ever = True
            if b7 and stuck_first is None:
                stuck_first = t
            if stuck_first is not None and not b7 and stuck_cleared is None:
                stuck_cleared = t

            key = (at_stop, b6, b7)
            if key != prev:
                if prev is not None and at_stop and not prev[0]:
                    stops += 1
                note = ("BIT 7 SET — position not following" if b7 and
                        (prev is None or not prev[2]) else
                        "bit 7 cleared" if not b7 and prev and prev[2] else
                        "at a stop" if at_stop else "left the stop")
                print(f"  {t:5.1f}  {raw:5d}  0x{st:04x}   {int(at_stop)}     "
                      f"{int(b6)}     {int(b7)}   {note}", flush=True)
            prev = key
            time.sleep(0.1)

    span = max(raws) - min(raws) if raws else 0
    print()
    print(f"  {len(raws)} samples; 30005 spanned {min(raws)}..{max(raws)} "
          f"= {span} counts")
    print(f"  arrivals at a stop: {stops}")
    print()

    fails = []

    def row(name, ok, detail):
        print(f"  {'PASS' if ok else 'FAIL'} {name:<26} {detail}")
        if not ok:
            fails.append(name)

    if stops < 4:
        print("  INCONCLUSIVE — fewer than 4 arrivals at a stop, so three "
              "departure sequences\n  cannot have completed. Drive both stops "
              "more times.")
        return 1

    row("bit 7 set", stuck_first is not None,
        f"reported at t = {stuck_first:.1f} s" if stuck_first is not None
        else "NEVER set — the wiper was not seen as stuck")
    row("bit 6 stayed clear", not bit6_ever,
        "FR-E24 self-disabling on the default calibration, so this is the "
        "'mechanism stuck' signature: bit 7 alone"
        if not bit6_ever else "bit 6 ALSO set, which the default calibration "
                              "should make impossible")
    if stuck_cleared is not None:
        row("bit 7 cleared", True,
            f"cleared at t = {stuck_cleared:.1f} s after the wire was "
            f"re-attached and the carriage moved")
    else:
        print("  INFO bit 7 never cleared — re-attach the wire and traverse "
              "once to see it clear")

    print(f"\n  {len(fails)} check(s) failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
