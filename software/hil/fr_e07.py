"""FR-E07 — wiper fault machine: hold the last opening <=2 s, then 65535 + bit 2.

THE HOLD IS INVISIBLE IN 30001, BY DESIGN. FR-E07 sets status bit 2 only AFTER
the 2 s expires, so while the last opening is being held the registers look
exactly like normal operation. An earlier version of this test hunted for
"bit 2 set but 30001 not yet the sentinel" and found nothing, because the
requirement forbids that state existing.

The instrument is **30011**, reading age: seconds since the last VALID reading
(FR-S36). It resets on every good publish and counts up during the hold, so the
age at the instant the sentinel appears IS the hold, plus the window(s) that had
to close around it.

The measurement window is set SHORT (default 200 ms) for the duration of this
test so window granularity does not swamp a 2 s requirement. At the 1000 ms
default the same measurement read 4 s and could not distinguish "a 2 s hold plus
slow windows" from "a hold that runs long".

Run it, then disconnect the wiper while it polls. 40002 is restored at the end.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from m2k_master import M2kMaster

BIT_WIPER_FAULT = 0x0004
SENTINEL = 65535


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--seconds", type=float, default=45.0)
    ap.add_argument("--window-ms", type=int, default=200)
    a = ap.parse_args()

    edges = []
    with M2kMaster() as m:
        as_found = m.read_holding(a.unit, 0x0000, 7)
        m.write_single(a.unit, 0x0001, a.window_ms)      # 40002
        print(f"  40002 set to {a.window_ms} ms for this test "
              f"(was {as_found[1]} ms)")
        try:
            t0 = time.monotonic()
            prev = None
            print()
            print(f"  polling {a.seconds:.0f} s — wiper CONNECTED, let it "
                  f"recover, then DISCONNECT it")
            print()
            print("   t(s)   30001  30005  status  age  state")
            while time.monotonic() - t0 < a.seconds:
                try:
                    i = m.read_input(a.unit, 0x0000, 15)
                except Exception:                            # noqa: BLE001
                    continue
                t = time.monotonic() - t0
                fault = bool(i[5] & BIT_WIPER_FAULT)
                sentinel = i[0] == SENTINEL
                age = i[10]
                key = (fault, sentinel)
                state = ("FAULT+sentinel" if fault and sentinel else
                         "FAULT, no sentinel" if fault else
                         "sentinel, no bit2" if sentinel else "ok")
                if prev is None:
                    # Establish the starting state WITHOUT recording an edge.
                    # Otherwise a device that is already faulted when polling
                    # begins reports a "transition" on its first reading, and
                    # the settled state gets timed as though it were one.
                    prev = key
                    print(f"  {t:6.2f}  {i[0]:6d} {i[4]:6d}  0x{i[5]:04x}  "
                          f"{age:3d}      starting state: {state}", flush=True)
                    continue
                if key != prev:
                    edges.append((t, fault, sentinel, i[0], age, prev))
                    print(f"  {t:6.2f}  {i[0]:6d} {i[4]:6d}  0x{i[5]:04x}  "
                          f"{age:3d}  <-- {state}", flush=True)
                elif int(t * 2) % 6 == 0:
                    print(f"  {t:6.2f}  {i[0]:6d} {i[4]:6d}  0x{i[5]:04x}  "
                          f"{age:3d}      {state}", flush=True)
                prev = key
                time.sleep(0.1)
        finally:
            print()
            print("  restoring holdings ...")
            m.write_multiple(a.unit, 0x0000, as_found[:6])
            print(f"  {m.read_holding(a.unit, 0x0000, 7)[:6]}")

    print()
    print("  transitions:")
    for t, f, s, v, age, was in edges:
        print(f"    {t:6.2f}s  bit2={'SET' if f else 'clr'}  30001={v}  "
              f"30011={age}s" + ("  (sentinel)" if s else ""))

    # Only a fault that FOLLOWED a healthy state can be timed. A device already
    # faulted when polling started has no measurable hold — the disconnect
    # happened before anyone was watching.
    faults = [(t, age) for t, f, s, v, age, was in edges
              if f and s and was == (False, False)]
    if not faults:
        print()
        print("  INCONCLUSIVE — no healthy-to-faulted transition was captured, "
              "so the hold cannot be timed. Reconnect the wiper, let bit 2 "
              "clear, then disconnect while this is polling.")
        return 1

    t_f, age_f = faults[-1]
    # The sentinel may only be published at the window boundary AFTER the timer
    # expires, so one extra window is legitimate. Budget: the 2 s timer, two
    # windows, and 1 s because 30011 counts whole seconds.
    budget = 2.0 + 2 * (a.window_ms / 1000.0) + 1.0
    ok = age_f <= budget
    print()
    print(f"  at the sentinel, 30011 read {age_f} s — time since the last VALID "
          f"reading, i.e. the FR-E07 hold plus the window(s) around it")
    print(f"  budget {budget:.1f} s = 2 s timer + 2 x {a.window_ms} ms window "
          f"+ 1 s of 30011 granularity")
    print()
    print(f"  {'PASS' if ok else 'FAIL'} FR-E07 hold")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
