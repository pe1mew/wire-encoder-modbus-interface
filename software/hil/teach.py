"""FR-E18 / FR-E19 — endpoint capture and the commanded teach handshake.

Newly runnable: the teach sequence needs BOTH stops physically reached, which
the window emulator now allows.

FR-E18: on each debounced entry into "one sensor active", the raw wiper code is
captured to **30013** if that stop is the closed end or **30014** if it is the
open end — decided by the DIRECTION OF THE LAST MOVEMENT (FR-E10). That is why
30012's sign is not cosmetic.

FR-E19, the handshake, in order:
    (a) write 1 to 40007  -> bit 5 sets, previous captures discarded
    (b) while armed, each stop captures its endpoint
    (c) when BOTH are captured **and** the master has READ both 30013 and 30014,
        the firmware commits them to 40005/40006, persists, clears bit 5 and
        resets 40007 to 0
    (d) write 0 to 40007 aborts, leaving 40005/40006 untouched

THE POLLING HERE READS ONLY 30001-30012, DELIBERATELY. `regs.c` sets the
"master has read it" flag inside the register read itself, so a routine
15-register block poll would satisfy clause (c) continuously and the commit
would fire the instant both endpoints were captured. The waiting-for-the-master
half of the handshake would then never be observed — the test would pass while
testing nothing. Reading a narrower block is what makes (b) and (c) separable.

Run:  .venv-m2k/Scripts/python software/hil/teach.py --unit 40 --seconds 120
Then drive the window to BOTH stops while it logs.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import modbus_rtu_codec as codec
from m2k_master import M2kMaster

BIT_END_REACHED = 0x0008
BIT_TEACH_ACTIVE = 0x0020
REG_TEACH = 0x0006          # 40007
REG_AT_CLOSED = 0x000C      # 30013
REG_AT_OPEN = 0x000D        # 30014

results = []


def row(name, req, ok, detail):
    results.append((name, "PASS" if ok else "FAIL"))
    print(f"  {'PASS' if ok else 'FAIL'} {name:<10} ({req}) {detail}", flush=True)


def signed(v):
    return v - 65536 if v >= 32768 else v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--seconds", type=float, default=120.0)
    a = ap.parse_args()
    u = a.unit

    with M2kMaster() as m:
        as_found = m.read_holding(u, 0x0000, 7)
        print(f"  as-found holdings: {as_found}")
        print(f"  calibration before teach: 40005={as_found[4]}, 40006={as_found[5]}")

        # ---- (a) arm -----------------------------------------------------
        m.write_single(u, REG_TEACH, 1)
        st = m.read_input(u, 0x0005, 1)[0]
        armed = m.read_holding(u, REG_TEACH, 1)[0]
        row("arm", "FR-E19a", bool(st & BIT_TEACH_ACTIVE) and armed == 1,
            f"40007=1 armed teach: status 0x{st:04x} bit 5 set, 40007 reads {armed}")

        # ---- the stale-capture guard, before any new capture --------------
        # 30013/30014 keep their values from an earlier traverse — they are
        # diagnostics, not state. Arming clears the internal "captured" flags,
        # so reading plausible-looking stale numbers must NOT commit anything.
        # Firmware comment: "a stale capture from an earlier session can never
        # be committed." This asserts it rather than assuming it.
        stale_closed = m.read_input(u, REG_AT_CLOSED, 1)[0]
        stale_open = m.read_input(u, REG_AT_OPEN, 1)[0]
        time.sleep(0.5)
        st = m.read_input(u, 0x0005, 1)[0]
        cal = m.read_holding(u, 0x0000, 7)
        row("stale", "FR-E19a", bool(st & BIT_TEACH_ACTIVE)
            and cal[4] == as_found[4] and cal[5] == as_found[5],
            f"reading stale captures ({stale_closed}, {stale_open}) after arming "
            f"did NOT commit: bit 5 still set, 40005/40006 unchanged")

        print()
        print(f"  Drive the window to BOTH stops. {a.seconds:.0f} s.")
        print("  (polling 30001-30012 only, so reading the captures cannot")
        print("   accidentally satisfy the commit condition)")
        print()
        print("   t(s)  30001  30012   status  note")

        t0 = time.monotonic()
        prev_st = None
        stops = []
        while time.monotonic() - t0 < a.seconds:
            try:
                i = m.read_input(u, 0x0000, 12)     # NOT 15 — see the docstring
            except Exception:                        # noqa: BLE001
                continue
            t = time.monotonic() - t0
            st, opening, rate = i[5], i[0], signed(i[11])
            at_stop = bool(st & BIT_END_REACHED)
            if prev_st is None or at_stop != bool(prev_st & BIT_END_REACHED):
                note = "AT STOP" if at_stop else "left the stop"
                if at_stop:
                    stops.append((t, opening, rate))
                print(f"  {t:5.1f}  {opening:6d} {rate:+6d}   0x{st:04x}  {note}",
                      flush=True)
            prev_st = st
            time.sleep(0.1)

        print()
        row("stops", "FR-E18", len(stops) >= 2,
            f"{len(stops)} stop entries observed while armed"
            + ("" if len(stops) >= 2 else " — both stops are needed"))

        # ---- (c) the commit must WAIT for the master to read -------------
        st = m.read_input(u, 0x0005, 1)[0]
        row("wait", "FR-E19c", bool(st & BIT_TEACH_ACTIVE),
            "bit 5 STILL set after both captures — the commit correctly waits "
            "for the master to read 30013 and 30014"
            if st & BIT_TEACH_ACTIVE else
            "bit 5 already cleared before the captures were read — the commit "
            "did not wait")

        at_closed = m.read_input(u, REG_AT_CLOSED, 1)[0]
        at_open = m.read_input(u, REG_AT_OPEN, 1)[0]
        print(f"\n  captured: 30013 (closed) = {at_closed}, "
              f"30014 (open) = {at_open}")

        # give the firmware a loop pass or two to act on the reads
        time.sleep(0.5)
        st = m.read_input(u, 0x0005, 1)[0]
        after = m.read_holding(u, 0x0000, 7)
        committed = (after[4] == at_closed and after[5] == at_open)
        row("commit", "FR-E19c", committed and not (st & BIT_TEACH_ACTIVE)
            and after[6] == 0,
            f"after reading both: 40005={after[4]}, 40006={after[5]}, "
            f"bit 5 {'clear' if not (st & BIT_TEACH_ACTIVE) else 'STILL SET'}, "
            f"40007={after[6]}")
        row("direction", "FR-E18",
            at_closed < at_open,
            f"the closed end captured the LOWER raw code ({at_closed} < "
            f"{at_open}) — the direction of last movement chose the register"
            if at_closed < at_open else
            f"30013={at_closed} is not below 30014={at_open}; the "
            f"direction decision may be inverted")

        # ---- (d) abort -----------------------------------------------------
        before_abort = m.read_holding(u, 0x0000, 7)
        m.write_single(u, REG_TEACH, 1)
        m.write_single(u, REG_TEACH, 0)
        time.sleep(0.3)
        st = m.read_input(u, 0x0005, 1)[0]
        after_abort = m.read_holding(u, 0x0000, 7)
        row("abort", "FR-E19d",
            not (st & BIT_TEACH_ACTIVE) and after_abort[:6] == before_abort[:6],
            "writing 0 to 40007 cleared bit 5 and left 40005/40006 untouched")

        print("\n  restoring the as-found calibration ...")
        m.write_multiple(u, 0x0000, as_found[:6])
        print(f"  {m.read_holding(u, 0x0000, 7)[:6]}")

    n_fail = sum(1 for _, v in results if v == "FAIL")
    print(f"\n{len(results) - n_fail} pass, {n_fail} fail")
    print("\n  NOT covered: FR-E19's refusal to commit a pair violating FR-E06.")
    print("  It needs two stops whose raw codes differ by <64 counts, which this")
    print("  rig cannot produce — its traverse spans the full ADC range.")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
