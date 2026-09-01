"""TP-B24 / FR-S19 — the DUT must never transmit unprompted ("no boot banner").

The master is held RELEASED for the whole run and sends nothing. The bus then
rests on the 680 ohm fail-safe bias at ~0.26 V differential, and **any driven
excursion can only be the DUT**. If it emits a boot banner, test bytes, or
anything at all while nobody has asked it a question, it shows up here.

No rail probe is needed: this asks "did it ever drive?", not "when did it boot".
The reset is proved after the fact instead -- uptime is read before and after,
and must have gone BACKWARDS, or the window contained no power cycle and the
run proves nothing. That check is the point; without it a disconnected DUT
passes perfectly.

Run:  .venv-m2k/Scripts/python software/hil/tp_b24.py --unit 40 --seconds 45
      ... and power-cycle the DUT while it is listening.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import libm2k
from m2k_master import M2kMaster

RATE = 100_000                 # 10 samples per bit at 9600 -- ample to see a byte
DRIVEN_V = 0.7                 # bias is 0.26 V; a driver puts out ~1.4 V
CHUNK_S = 0.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--seconds", type=float, default=45.0)
    a = ap.parse_args()

    with M2kMaster() as m:
        before, = m.read_input(a.unit, 0x0007, 1)
        print(f"  uptime before: {before} s")

        ain = m.ctx.getAnalogIn()
        m.ctx.calibrateADC()
        for ch in (0, 1):
            ain.enableChannel(ch, True)
            ain.setRange(ch, libm2k.PLUS_MINUS_25V)
        ain.setSampleRate(RATE)

        # Belt and braces: the master is released and stays released.
        m.dig.setValueRaw(1, libm2k.LOW)     # DE low
        m.dig.setValueRaw(0, libm2k.HIGH)    # TX idle mark
        time.sleep(0.2)

        n = int(CHUNK_S * RATE)
        ain.getSamples(n)                    # discard the in-flight buffer

        print(f"\n  *** POWER-CYCLE THE DUT NOW — listening for "
              f"{a.seconds:.0f} s ***\n")
        t0 = time.monotonic()
        excursions, peak, chunks = [], 0.0, 0
        while time.monotonic() - t0 < a.seconds:
            s = ain.getSamples(n)
            chunks += 1
            t_chunk = time.monotonic() - t0
            run = 0
            for i in range(n):
                d = abs(s[0][i] - s[1][i])
                if d > peak:
                    peak = d
                if d > DRIVEN_V:
                    run += 1
                else:
                    if run > 0.5 * RATE / 9600:      # half a bit or more
                        excursions.append((t_chunk, run / RATE * 1e3))
                    run = 0
            if run:
                excursions.append((t_chunk, run / RATE * 1e3))

        after, = m.read_input(a.unit, 0x0007, 1)

    print(f"  listened {chunks * CHUNK_S:.1f} s, peak differential {peak:.3f} V "
          f"(driven would be ~1.4 V, bias is ~0.26 V)")
    print(f"  uptime after: {after} s (was {before} s)")

    cycled = after < before
    if not cycled:
        print("\n  INCONCLUSIVE — uptime did not go backwards, so no reset "
              "happened inside the listening window. Nothing was tested.")
        return 1
    print(f"  reset confirmed: uptime went {before} -> {after}")

    if excursions:
        print(f"\n  FAIL TP-B24 (FR-S19) — the DUT drove the bus "
              f"{len(excursions)} time(s) while nobody had asked it anything:")
        for t, ms in excursions[:10]:
            print(f"      ~{t:5.1f} s into the window, {ms:.2f} ms of drive")
        return 1
    print(f"\n  PASS TP-B24 (FR-S19) — the bus never left the fail-safe bias "
          f"across a full power cycle. No boot banner, no test bytes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
