"""TP-B02 / TP-B04 / TP-B19 / TP-B20 — the rows that need a power cycle.

Two steps per cycle, with you doing the middle bit:

    python software/hil/power_cycle.py arm      # writes non-default holdings
    ... you power the DUT off and on ...
    python software/hil/power_cycle.py check    # reads back and judges

`arm` records the expected state to a file, so `check` compares against what was
actually written rather than against what anyone remembers.

    python software/hil/power_cycle.py address --unit 45
        TP-B02 after moving JP6. Confirms the device answers at the new address
        and is silent at the old one.

    python software/hil/power_cycle.py restore
        Puts the §2.8 defaults back when you are done.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import modbus_rtu_codec as codec
from m2k_master import M2kMaster

STATE = Path(__file__).with_name(".power-cycle-state.json")
DEFAULTS = [0, 1000, 10, 10000, 0, 1023]
# Deliberately unlike the defaults in every register, so "survived" cannot be
# confused with "was never written" or "came back as a default".
PROBE = [1234, 2500, 30, 8888, 200, 900]


def arm(u, m):
    before = m.read_holding(u, 0x0000, 7)
    ident, = m.read_input(u, 0x0006, 1)
    uptime, = m.read_input(u, 0x0007, 1)
    m.write_multiple(u, 0x0000, PROBE)          # atomic; 30x1000 >= 2500
    back = m.read_holding(u, 0x0000, 7)
    if back[:6] != PROBE:
        print(f"  *** the probe values did not take: {back[:6]} != {PROBE}")
        return 1
    STATE.write_text(json.dumps(
        {"unit": u, "probe": PROBE, "as_found": before, "ident": ident,
         "uptime": uptime, "when": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=2))
    print(f"  holdings before this run : {before}")
    print(f"  holdings now written     : {back[:6]}")
    print(f"  30007 = 0x{ident:04x}, uptime {uptime} s")
    print(f"\n  ARMED. Now power the DUT off, wait a couple of seconds, and "
          f"power it back on.\n  Then run:  power_cycle.py check")
    return 0


def check(u, m):
    if not STATE.exists():
        print(f"  nothing armed — run `arm` first ({STATE} missing)")
        return 1
    s = json.loads(STATE.read_text())
    if s["unit"] != u:
        print(f"  *** armed for unit {s['unit']}, not {u}")
        return 1
    holdings = m.read_holding(u, 0x0000, 7)
    ident, = m.read_input(u, 0x0006, 1)
    ireg = m.read_input(u, 0x0000, 15)
    uptime, status = ireg[7], ireg[5]
    fails = []

    def row(name, req, good, detail):
        print(f"  {'PASS' if good else 'FAIL'} {name:<7} ({req}) — {detail}")
        if not good:
            fails.append(name)

    row("TP-B19", "FR-S39", holdings[:6] == s["probe"],
        f"holdings survived the power cycle: {holdings[:6]} "
        f"(wrote {s['probe']})")
    row("TP-B19", "FR-S39", holdings[6] == 0,
        f"40007 (teach) reads {holdings[6]} — must be 0, not persisted")
    row("TP-B04", "FR-S32", ident == s["ident"],
        f"30007 identical across the cycle: 0x{ident:04x} "
        f"(was 0x{s['ident']:04x})")
    row("cycle", "—", uptime < s["uptime"] or uptime < 30,
        f"uptime {uptime} s (was {s['uptime']} s) — confirms power really "
        f"was removed")
    row("TP-B22", "FR-S21", all(v == 0 for v in ireg[0:5]) and (status & 0x3) == 0x3,
        f"defined state after reset: 30001-30005 clear, status 0x{status:04x} "
        f"with bits 0 and 1 set")

    print()
    if fails:
        print(f"{len(set(fails))} row(s) FAILED")
        return 1
    print("all power-cycle rows PASS.  Run `restore` when you are finished.")
    return 0


def address(u, m, old):
    """TP-B02 — after moving JP6 and power-cycling."""
    ok_new = ok_old = False
    try:
        i, = m.read_input(u, 0x0006, 1)
        ok_new = True
        print(f"  PASS TP-B02 (FR-S03) — answers at {u}: 30007 = 0x{i:04x}")
    except (codec.ModbusError, codec.Exception_) as e:
        print(f"  FAIL TP-B02 — no answer at {u}: {e}")
    try:
        m.read_input(old, 0x0006, 1)
        print(f"  FAIL TP-B02 (FR-MB05) — STILL answers at the old address {old}")
    except (codec.ModbusError, codec.Exception_):
        ok_old = True
        print(f"  PASS TP-B02 (FR-MB05) — silent at the old address {old}")
    return 0 if (ok_new and ok_old) else 1


def restore(u, m):
    m.write_multiple(u, 0x0000, DEFAULTS)
    back = m.read_holding(u, 0x0000, 7)
    ok = back[:6] == DEFAULTS
    print(f"  holdings now {back[:6]} — "
          + ("matches the §2.8 defaults" if ok else "*** MISMATCH ***"))
    if ok:
        STATE.unlink(missing_ok=True)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step", choices=["arm", "check", "address", "restore"])
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--old-unit", type=int, default=40,
                    help="for `address`: the address it used to answer at")
    a = ap.parse_args()
    with M2kMaster() as m:
        print()
        if a.step == "arm":
            return arm(a.unit, m)
        if a.step == "check":
            return check(a.unit, m)
        if a.step == "address":
            return address(a.unit, m, a.old_unit)
        return restore(a.unit, m)


if __name__ == "__main__":
    sys.exit(main())
