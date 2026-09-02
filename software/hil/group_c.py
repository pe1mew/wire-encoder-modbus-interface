"""Group C — the measurement rows, unblocked by integration stages D and E.

Most of Group C needs the window to MOVE, which this bench cannot do on demand.
But the scaling requirements do not: FR-E04 is a pure function of the raw code
and the three calibration registers, so driving the CALIBRATION against a fixed
wiper exercises the whole path end to end — driver, scaling, publication — with
a prediction that can be computed independently here.

That is a real test, not a substitute for one. It is what catches a sign error,
a clamp on the wrong side, or an offset applied at the wrong point.

Covered here:
    FR-S24  coherent snapshot: 30001 is the scaling of the SAME response's 30005
    FR-E04  the scaling formula, both mounting senses, at and beyond both stops
    FR-E05  calibration is runtime-configurable and takes effect immediately
    FR-E09  30005 is pre-scaling — calibration changes must not move it
    FR-E20  30015 is the percentage of the INSTANTANEOUS opening

Needs the window to move, so NOT covered:
    FR-E01  absolute after reset with no homing move (needs a power cycle)
    FR-E03  electronics accuracy — needs a PRECISION DIVIDER in place of the
            pot at 5 ratios, not the emulator. The mechanism's own linearity
            is explicitly a separate §6 item, not FR-E03.
    FR-E10  signed movement rate (needs actual movement)
    FR-E17  maximum age of a read value (needs a changing value to be stale)
    FR-E18/E19  teach handshake (needs both stops actually reached)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import modbus_rtu_codec as codec
from m2k_master import M2kMaster

results = []


def record(name, req, ok, detail):
    results.append((name, req, "PASS" if ok else "FAIL", detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name:<10} ({req}) {detail}", flush=True)


def wait_for_new_window(m, unit, tries=60):
    """Block until a window has completed UNDER THE NEW CONFIGURATION.

    Writing a calibration or window register re-asserts status bit 0 (FR-S30 /
    FR-E05), and 30001 keeps its previous value until the next window closes.
    So this waits for bit 0 to be SET first, then for it to clear.

    Waiting only for "bit 0 clear" is a race and reads the PRE-write value: at
    the first poll after the write the firmware may not have run regs_service
    yet, so the bit is still clear from the previous window and the loop exits
    immediately. That is exactly what made an earlier version of this file
    report an FR-E04 failure against correct firmware.
    """
    for _ in range(tries):                       # wait for the change to register
        if m.read_input(unit, 0x0005, 1)[0] & 0x0001:
            break
    for _ in range(tries):                       # then for the new window to close
        if not (m.read_input(unit, 0x0005, 1)[0] & 0x0001):
            return True
    return False


def expect_opening(raw, offset, travel, raw_closed, raw_open):
    """FR-E04, computed here rather than read from the device.

    opening = offset + ((raw - raw_closed) x travel) / (raw_open - raw_closed)

    The distance is taken as a magnitude and CLAMPED TO THE SPAN before the
    multiply — that clamp is what bounds the intermediate product, and it is
    also what makes a reading beyond either calibration point saturate rather
    than run past the travel.
    """
    span = abs(int(raw_open) - int(raw_closed))
    if span == 0:
        return None
    if raw_open >= raw_closed:
        d = int(raw) - int(raw_closed)
    else:
        d = int(raw_closed) - int(raw)
    if d < 0:
        d = 0
    if d > span:
        d = span
    return offset + (d * travel) // span


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    a = ap.parse_args()
    u = a.unit

    with M2kMaster() as m:
        as_found = m.read_holding(u, 0x0000, 7)
        print(f"  as-found holdings: {as_found}\n")
        try:
            # ---- FR-S24: one response must be self-consistent -------------
            i = m.read_input(u, 0x0000, 15)
            raw, opening, pct = i[4], i[0], i[14]
            off, trav = as_found[0], as_found[3]
            rc, ro = as_found[4], as_found[5]
            want = expect_opening(raw, off, trav, rc, ro)
            record("FR-S24", "FR-S24", opening == want,
                   f"30001={opening} is the FR-E04 scaling of the SAME "
                   f"response's 30005={raw} (computed {want})")

            # ---- FR-E20: percentage of the instantaneous opening ----------
            want_pct = ((opening - off) * 1000) // trav if trav else 0
            if want_pct > 1000:
                want_pct = 1000
            record("FR-E20", "FR-E20", abs(pct - want_pct) <= 1,
                   f"30015={pct} matches (30001-offset)*1000/travel={want_pct}")

            # ---- FR-E04 / FR-E05: drive the calibration ------------------
            # A fixed wiper with a swept calibration exercises the whole
            # scaling path. Each case names what it is actually probing.
            cases = [
                (0,    10000, 0,    1023, "nominal, wiper mid-travel"),
                (500,  10000, 0,    1023, "offset applied at the closed point"),
                (0,    20000, 0,    1023, "travel doubles the opening"),
                (0,    10000, 1023, 1,    "REVERSED mounting — sense inverts"),
                (0,    10000, 600,  700,  "narrow span around the wiper"),
                (0,    10000, 900,  1000, "wiper BELOW the closed point — clamps to offset"),
                (0,    10000, 100,  200,  "wiper ABOVE the open point — clamps to full travel"),
            ]
            for off_v, trav_v, rc_v, ro_v, what in cases:
                m.write_multiple(u, 0x0000, [off_v, as_found[1], as_found[2],
                                             trav_v, rc_v, ro_v])
                wait_for_new_window(m, u)
                j = m.read_input(u, 0x0000, 15)
                got_raw, got_open = j[4], j[0]
                want = expect_opening(got_raw, off_v, trav_v, rc_v, ro_v)
                ok = want is not None and abs(int(got_open) - int(want)) <= 20
                record("FR-E04", "FR-E04", ok,
                       f"{what}: raw={got_raw} -> 30001={got_open} "
                       f"(expected {want})")

            # ---- FR-E09: 30005 is PRE-scaling ----------------------------
            m.write_multiple(u, 0x0000, [0, as_found[1], as_found[2],
                                         10000, 0, 1023])
            wait_for_new_window(m, u)
            raw_a = m.read_input(u, 0x0004, 1)[0]
            m.write_multiple(u, 0x0000, [0, as_found[1], as_found[2],
                                         50000, 0, 1023])
            wait_for_new_window(m, u)
            raw_b = m.read_input(u, 0x0004, 1)[0]
            record("FR-E09", "FR-E09", abs(raw_a - raw_b) <= 3,
                   f"30005 unmoved by a 5x travel change: {raw_a} -> {raw_b} "
                   f"(it reports the code BEFORE scaling)")

            # ---- FR-E05: a rejected calibration must not take effect ------
            before = m.read_holding(u, 0x0000, 7)
            try:
                m.write_multiple(u, 0x0004, [500, 520])   # span 20 < CAL_MIN_SPAN
                record("FR-E05", "FR-E05", False,
                       "a sub-CAL_MIN_SPAN calibration was ACCEPTED")
            except codec.Exception_ as e:
                after = m.read_holding(u, 0x0000, 7)
                record("FR-E05", "FR-E05", after == before,
                       f"a calibration violating FR-E06 is rejected "
                       f"(exception {e.code}) and changes nothing")
        finally:
            print("\n  restoring holdings ...")
            m.write_multiple(u, 0x0000, as_found[:6])
            print(f"  {m.read_holding(u, 0x0000, 7)[:6]}")

    n_fail = sum(1 for _, _, v, _ in results if v == "FAIL")
    print(f"\n{len(results) - n_fail} pass, {n_fail} fail")
    print("""
NOT COVERED — these need the window to move, which this bench cannot do:
  FR-E01  absolute after reset, no homing move   (needs a power cycle)
  FR-E03  end-to-end accuracy vs a reference     (needs the window emulator)
  FR-E10  signed movement rate                   (needs movement)
  FR-E17  maximum age of a read value            (needs a changing value)
  FR-E18/E19  teach handshake                    (needs both stops reached)
  FR-E15  20 ms debounce                         (needs an injected bounce)""")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
