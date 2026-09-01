"""TP-B32 / FR-MB04 — DUT DE asserted before the first byte, released after the last.

The Saleae would read PC2 directly, but its voltage range cannot be set through
the MCP API on a Logic16. It is not needed: **the DUT drives the bus only while
its DE is asserted**, so the drive envelope is on the M2K's analog inputs, on
the same timebase as the data itself. No extra probe, and nothing inferred from
a second instrument's clock.

    driven      |A-B| ~ 1.4 V   (mark or space, either polarity)
    released    |A-B| ~ 0.26 V  (the fail-safe bias, always mark polarity)

so a magnitude threshold finds the drive window and a sign change finds each
data bit. FR-MB04 allows one character time (11 bits = 1.146 ms) on each side.

Run:  .venv-m2k/Scripts/python software/hil/tp_b32.py --unit 40
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import libm2k
import modbus_rtu_codec as codec
from m2k_master import M2kMaster, BAUD

ANALOG_RATE = 1_000_000          # 1 us resolution; the limit is 1.146 ms
WINDOW_S = 0.10
BIT_S = 1.0 / BAUD
CHAR_S = 11 * BIT_S              # FR-MB04's budget, both sides
DRIVEN_V = 0.7                   # halfway between the 0.26 V bias and 1.4 V driven


def drive_spans(mag, thr, bit_samples):
    """Spans where the bus is being DRIVEN, as (start, end) indices.

    The differential swings +/-1.4 V and passes through zero at every bit
    transition, so |diff| dips under the threshold for a few microseconds on
    each edge. Requiring long runs above the threshold therefore chops one
    drive window into one fragment per bit -- an earlier version did exactly
    that and reported a 7.29 ms frame as a 1.04 ms drive window, then called
    the resulting nonsense an FR-MB04 failure.

    So: threshold first, then CLOSE gaps shorter than two bit times (no real
    release is that brief -- t3.5 alone is 35 bit times), and only then take
    spans long enough to be a frame.
    """
    driven = [v > thr for v in mag]

    # close short gaps
    i, n = 0, len(driven)
    while i < n:
        if driven[i]:
            i += 1
            continue
        j = i
        while j < n and not driven[j]:
            j += 1
        if 0 < i and j < n and (j - i) < 2 * bit_samples:
            for k in range(i, j):
                driven[k] = True
        i = j

    spans, start = [], None
    for i, d in enumerate(driven):
        if d and start is None:
            start = i
        elif not d and start is not None:
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, n))
    # a frame is at least a few characters long; drop noise
    return [s for s in spans if s[1] - s[0] >= 30 * bit_samples]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--reps", type=int, default=10)
    a = ap.parse_args()

    req = codec.read_input_registers(a.unit, 0x0006, 1)   # 7-byte reply
    reply_bytes = 7
    lead_ms, lag_ms, drive_ms = [], [], []

    with M2kMaster() as m:
        ain = m.ctx.getAnalogIn()
        m.ctx.calibrateADC()
        for ch in (0, 1):
            ain.enableChannel(ch, True)
            ain.setRange(ch, libm2k.PLUS_MINUS_25V)
        ain.setSampleRate(ANALOG_RATE)
        n = int(WINDOW_S * ANALOG_RATE)

        for rep in range(a.reps):
            ain.startAcquisition(n)
            try:
                m._transmit(req)
                s = ain.getSamples(n)
            finally:
                ain.stopAcquisition()
            # A is whichever line is high during mark; the selftest derives it
            # the same way. Sign is irrelevant here -- only magnitude and the
            # instant of each sign change matter.
            diff = [s[0][i] - s[1][i] for i in range(n)]
            mag = [abs(v) for v in diff]

            bit_samples = int(BIT_S * ANALOG_RATE)
            spans = drive_spans(mag, DRIVEN_V, bit_samples)
            if len(spans) < 2:
                print(f"  rep {rep}: {len(spans)} drive window(s) — expected 2 "
                      f"(ours, then the DUT's); skipped")
                continue
            lo, hi = spans[-1]                       # the DUT's, after ours

            # Data bits are sign changes inside the driven window.
            flips = [i for i in range(lo + 1, hi)
                     if (diff[i - 1] >= 0) != (diff[i] >= 0)]
            if not flips:
                print(f"  rep {rep}: no data transitions inside the drive window")
                continue
            first_start = flips[0]
            # The frame's last stop bit ends a known number of bit times after
            # its first start bit. Derived from the frame length rather than
            # from the last edge, which is absent when the final data bit is
            # already mark. Over 7 bytes the DUT's 0.8 % fast clock costs 58 us,
            # well inside the 1146 us budget.
            frame_end = first_start + reply_bytes * 10 * BIT_S * ANALOG_RATE

            lead = (first_start - lo) / ANALOG_RATE
            lag = (hi - frame_end) / ANALOG_RATE
            lead_ms.append(lead * 1e3)
            lag_ms.append(lag * 1e3)
            drive_ms.append((hi - lo) / ANALOG_RATE * 1e3)
            print(f"  rep {rep}: DE lead {lead*1e6:7.1f} us, "
                  f"lag {lag*1e6:7.1f} us, drive window {(hi-lo)/ANALOG_RATE*1e3:6.2f} ms",
                  flush=True)

    if not lead_ms:
        print("\nBLOCKED — no usable drive windows measured")
        return 1
    budget_ms = CHAR_S * 1e3
    ok_lead = all(0 < x < budget_ms for x in lead_ms)
    ok_lag = all(0 < x < budget_ms for x in lag_ms)
    print(f"\n  n = {len(lead_ms)}   FR-MB04 budget = one character = "
          f"{budget_ms:.3f} ms on each side")
    print(f"  DE asserted BEFORE the first start bit by "
          f"{min(lead_ms)*1e3:.0f}..{max(lead_ms)*1e3:.0f} us "
          f"(median {statistics.median(lead_ms)*1e3:.0f} us)")
    print(f"  DE released AFTER the last stop bit by "
          f"{min(lag_ms)*1e3:.0f}..{max(lag_ms)*1e3:.0f} us "
          f"(median {statistics.median(lag_ms)*1e3:.0f} us)")
    print(f"  drive window {statistics.median(drive_ms):.2f} ms "
          f"(a 7-byte frame at 9600 is {reply_bytes*10*BIT_S*1e3:.2f} ms)")
    verdict = "PASS" if (ok_lead and ok_lag) else "FAIL"
    print(f"\n{verdict} TP-B32 (FR-MB04)")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
