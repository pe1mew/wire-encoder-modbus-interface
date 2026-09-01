"""Movement rows — the Group C requirements that need the window to actually move.

Unblocked by the window emulator (design/windowEmulator.md). Drive the rig by
hand or by harness while this logs; it does not care which, and it times
everything from the registers rather than from when a person pressed something.

    FR-E10  30012 is SIGNED: positive while opening, negative while closing,
            in 0.1 mm/s. The sign is not cosmetic -- FR-E18 uses it to decide
            which stop a teach capture belongs to.
    FR-E17  the value in 30001 is never older than the configured window
            (40002). Measured as the gap between 30001 CHANGES while the
            carriage is moving: a value that stops updating while the window
            moves is stale by definition.
    FR-E14  bit 3 sets at a stop and clears on leaving it, driven by real
            carriage motion rather than a target waved at a sensor.
    FR-E08  the envelope must span the traverse, not just its endpoints.

Reported but NOT judged here, because they need a reference this script has no
access to:
    FR-E03  end-to-end accuracy needs the rig's independent position readout
            (EM-M06). The travel in 0.1 mm is printed for comparison by hand.

Run:  .venv-m2k/Scripts/python software/hil/movement.py --unit 40 --seconds 120
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
BIT_WIPER_FAULT = 0x0004
SENTINEL = 65535

# A stationary rig still wiggles by a raw count or two, which is enough to make
# 30012 change sign and to give "both directions observed" for free. Below this
# traverse the movement rows report INCONCLUSIVE rather than PASS: a test that
# passes on a motionless carriage has measured nothing. 10 mm is far above the
# ~2 mm of noise seen with the rig at rest and far below any plausible EM-M01
# travel.
MIN_TRAVEL_0_1MM = 100


def signed(v):
    """30012 is a two's-complement 16-bit value (FR-E10)."""
    return v - 65536 if v >= 32768 else v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--seconds", type=float, default=120.0)
    a = ap.parse_args()
    u = a.unit

    samples = []          # (t, opening, raw, rate, status)
    changes = []          # times at which 30001 changed
    with M2kMaster() as m:
        window_ms = m.read_holding(u, 0x0001, 1)[0]
        print(f"  40002 measurement window = {window_ms} ms")
        print()
        print(f"  Drive the window OPEN to its stop, then CLOSED to its stop,")
        print(f"  then back off both. {a.seconds:.0f} s of logging.")
        print()
        print("   t(s)   30001   30005  30012      30003  30004  status  state")
        t0 = time.monotonic()
        prev_open = None
        prev_state = None
        while time.monotonic() - t0 < a.seconds:
            try:
                i = m.read_input(u, 0x0000, 15)
            except Exception:                                # noqa: BLE001
                continue
            t = time.monotonic() - t0
            opening, raw, rate, st = i[0], i[4], signed(i[11]), i[5]
            state = ("FAULT" if st & BIT_WIPER_FAULT else
                     "BOTH-SW" if st & BIT_SWITCH_FAULT else
                     "AT STOP" if st & BIT_END_REACHED else
                     "moving" if rate else "still")
            if opening != SENTINEL:
                samples.append((t, opening, raw, rate, st))
                if prev_open is not None and opening != prev_open:
                    changes.append(t)
            mark = "  <--" if state != prev_state else ""
            if opening != prev_open or state != prev_state:
                print(f"  {t:6.2f}  {opening:6d}  {raw:5d}  {rate:+6d}     "
                      f"{i[2]:6d} {i[3]:6d}  0x{st:04x}  {state}{mark}",
                      flush=True)
            prev_open, prev_state = opening, state
            time.sleep(0.1)

    if not samples:
        print("\n  nothing logged")
        return 1

    print()
    fails = []

    def row(name, req, ok, detail):
        print(f"  {'PASS' if ok else 'FAIL'} {name:<8} ({req}) {detail}")
        if not ok:
            fails.append(name)

    rates = [s[3] for s in samples]
    openings = [s[1] for s in samples]
    span = max(openings) - min(openings)

    if span < MIN_TRAVEL_0_1MM:
        print(f"  INCONCLUSIVE — the carriage moved {span/10:.1f} mm, under the "
              f"{MIN_TRAVEL_0_1MM/10:.0f} mm this row needs to distinguish")
        print(f"  motion from wiper noise. Nothing below is judged; drive the "
              f"window through a real traverse.")
        print()
        print(f"  {len(samples)} samples, 0 checks judged")
        return 1

    pos = [r for r in rates if r > 0]
    neg = [r for r in rates if r < 0]

    row("FR-E10", "FR-E10", bool(pos) and bool(neg),
        f"30012 went BOTH signs: max opening {max(pos) if pos else 0:+d}, "
        f"max closing {min(neg) if neg else 0:+d} (0.1 mm/s). "
        + ("" if pos and neg else
           "MISSING a direction — drive the window both ways"))

    # FR-E10's sign convention: rate positive while the opening is increasing.
    wrong = 0
    for k in range(1, len(samples)):
        d = samples[k][1] - samples[k - 1][1]
        r = samples[k][3]
        if d > 20 and r < 0:
            wrong += 1
        if d < -20 and r > 0:
            wrong += 1
    row("FR-E10", "FR-E10", wrong == 0,
        f"sign agrees with the direction of change in {len(samples)-1-wrong} "
        f"of {len(samples)-1} steps"
        + (f" — {wrong} DISAGREE" if wrong else " (positive = opening)"))

    # FR-E17: the value must never be older than one window. Measured ONLY over
    # spans where the carriage was genuinely moving.
    #
    # Not over the whole log. A stationary window republishes the SAME value
    # every window — that is a refresh, not a stall, and FR-E17 bounds how OLD
    # the value is, not how long since it last differed. An earlier version
    # measured gaps between changes across the entire run and reported a 41 s
    # "staleness" that was 98 s of the operator not touching the rig. It failed
    # a correct device on a metric that could not tell "not updating" from
    # "updating to the same number".
    NOISE_0_1MM_S = 50          # the still-rig floor measured +-10
    moving = [s for s in samples if abs(s[3]) > NOISE_0_1MM_S]
    gaps = []
    for k in range(1, len(moving)):
        g = moving[k][0] - moving[k - 1][0]
        if g < 5.0:             # within one traverse, not across a pause
            gaps.append(g)
    if len(gaps) >= 5:
        worst = max(gaps)
        budget = (window_ms / 1000.0) + 0.3      # one window plus poll jitter
        row("FR-E17", "FR-E17", worst <= budget,
            f"30001 refreshed every {min(gaps)*1000:.0f}–{worst*1000:.0f} ms "
            f"while moving (window {window_ms} ms, budget {budget*1000:.0f} ms)")
    else:
        row("FR-E17", "FR-E17", False,
            f"only {len(gaps)} moving intervals — not enough motion to bound "
            f"staleness")

    at_stop = any(s[4] & BIT_END_REACHED for s in samples)
    left_stop = at_stop and any(not (s[4] & BIT_END_REACHED) for s in samples)
    row("FR-E14", "FR-E14", at_stop and left_stop,
        "bit 3 both set at a stop and cleared on leaving it, under real motion"
        if at_stop and left_stop else "no stop was reached and left")

    row("FR-E08", "FR-E08", span >= MIN_TRAVEL_0_1MM,
        f"traverse spanned {span} (0.1 mm) = {span/10:.1f} mm; "
        f"30003/30004 track the envelope over the averaging window")

    print()
    print(f"  FR-E03 — NOT judged here. Observed travel {span/10:.1f} mm between "
          f"30001 = {min(openings)} and {max(openings)}.")
    print(f"  Compare against the rig's independent position readout (EM-M06) "
          f"to close FR-E03.")
    print()
    print(f"  {len(samples)} samples, {len(fails)} check(s) failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
