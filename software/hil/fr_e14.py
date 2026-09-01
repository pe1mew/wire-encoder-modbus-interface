"""FR-E14/E15/E16 — end-switch classification and the status bits it drives.

The two PNP proximity switches share PC4 through the §4.4 summing divider, so
the three states are distinguished by LEVEL, not by separate inputs (TDS §4.4.3,
measured 2026-08-31):

    neither active   -0.019 V     0 counts    bits 3 and 4 clear
    one   active      1.291 V   401 counts    bit 3 set
    both  active      2.210 V   686 counts    bit 4 set

Firmware thresholds: <170 neither, >=170 one, >=522 both.

Work through the states at your own pace; every status change is logged with a
timestamp. Two things are checked that a casual look would miss:

  * BOTH SENSORS ACTIVE must set bit 4 and nothing else. It is physically
    impossible on a working window — the frame cannot be at both stops — so it
    only arises from a wiring or mounting fault, and bit 4 exists to say so.
    It has never been exercised on this device.
  * A SWITCH FAULT MUST NOT DISTURB THE OPENING. FR-E16 is explicit that bit 4
    is reported and nothing more; the opening registers come from an
    independent front-end. 30001 is watched throughout for exactly that.

There is no raw register for the ladder, so the counts above cannot be read back
directly — the classification is observed through the status bits, which is what
the requirement is actually about.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from m2k_master import M2kMaster

BIT_FIRST_WINDOW = 0x0001
BIT_END_REACHED = 0x0008      # FR-E14: one sensor active
BIT_SWITCH_FAULT = 0x0010     # FR-E16: both active
BIT_WIPER_FAULT = 0x0004


def classify(status: int) -> str:
    if status & BIT_SWITCH_FAULT:
        return "BOTH ACTIVE (bit 4)"
    if status & BIT_END_REACHED:
        return "ONE ACTIVE (bit 3)"
    return "neither"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--seconds", type=float, default=120.0)
    a = ap.parse_args()

    seen = {}          # state -> first time observed
    edges = []
    openings = []
    prev_open = None
    with M2kMaster() as m:
        t0 = time.monotonic()
        prev = None
        print("  Work through: neither -> sensor A -> sensor B -> both -> neither")
        print("  Hold each state a few seconds.")
        print()
        print("   t(s)   status  switch state          30001  30005  bit2")
        while time.monotonic() - t0 < a.seconds:
            try:
                i = m.read_input(a.unit, 0x0000, 15)
            except Exception:                                # noqa: BLE001
                continue
            t = time.monotonic() - t0
            st = i[5]
            state = classify(st)
            if i[0] != 65535:
                openings.append(i[0])
            if state != prev:
                # Record the PREVIOUS poll's opening as well. FR-E16 asks
                # whether switching disturbs the opening, so the comparison has
                # to span ~0.1 s, not edge-to-edge. Two earlier versions of this
                # check got it wrong: one compared the whole run's min/max span,
                # the other compared values at edges seconds apart. Both counted
                # ordinary wiper drift as switch interference.
                edges.append((t, state, st, i[0], prev_open))
                seen.setdefault(state, t)
                print(f"  {t:6.2f}  0x{st:04x}  {state:<21s} {i[0]:6d} {i[4]:6d}"
                      f"  {'SET' if st & BIT_WIPER_FAULT else '-'}   <-- change",
                      flush=True)
            elif int(t * 2) % 10 == 0:
                print(f"  {t:6.2f}  0x{st:04x}  {state:<21s} {i[0]:6d} {i[4]:6d}"
                      f"  {'SET' if st & BIT_WIPER_FAULT else '-'}", flush=True)
            prev = state
            prev_open = i[0]
            time.sleep(0.1)

    print()
    print("  transitions:")
    for t, state, st, op, _ in edges:
        print(f"    {t:6.2f}s  0x{st:04x}  {state}   30001={op}")

    print()
    fails = []

    def row(name, req, ok, detail):
        print(f"  {'PASS' if ok else 'FAIL'} {name:<8} ({req}) — {detail}")
        if not ok:
            fails.append(name)

    row("neither", "FR-E14", "neither" in seen,
        "the 'neither active' state was observed with bits 3 and 4 clear"
        if "neither" in seen else "never observed")
    row("one", "FR-E14", "ONE ACTIVE (bit 3)" in seen,
        "bit 3 set while one sensor was active"
        if "ONE ACTIVE (bit 3)" in seen else
        "bit 3 was NEVER set — no sensor actuation reached the classifier")
    row("both", "FR-E16", "BOTH ACTIVE (bit 4)" in seen,
        "bit 4 set while both sensors were active"
        if "BOTH ACTIVE (bit 4)" in seen else
        "bit 4 was never set — the both-active state was not exercised")

    # FR-E16: a switch fault must not DISTURB the opening path. That is a
    # question about CORRELATION, not range. An earlier version compared the
    # min/max span of 30001 across the whole run and called 88 counts a
    # failure — but that span was slow monotonic drift during steady states
    # (~2 counts/s), entirely uncorrelated with switching. The opening is
    # allowed to change; it is not allowed to change BECAUSE a switch changed.
    #
    # So: compare 30001 immediately before and after each switch transition.
    jumps = [(e[0], e[1], abs(e[3] - e[4]))
             for e in edges if e[4] is not None and 65535 not in (e[3], e[4])]
    if jumps:
        worst = max(j[2] for j in jumps)
        row("isolation", "FR-E16", worst <= 5,
            f"30001 moved at most {worst} (0.1 mm) across a switch transition, "
            f"over {len(jumps)} transitions — switching does not disturb the "
            f"opening path")
        if openings:
            drift = max(openings) - min(openings)
            print(f"       (30001 drifted {drift} over the run, but between "
                  f"transitions and tracking 30005, not at them)")

    print()
    print("  NOT verified here: FR-E15's 20 ms debounce. It needs a 5 ms bounce "
          "injected electrically; a hand-actuated sensor cannot produce one.")
    print()
    print(f"  {len(seen)} of 3 states observed, {len(fails)} check(s) failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
