"""TP-B21 / TP-B22 — FR-S20 watchdog recovery and FR-S21 post-reset state.

REQUIRES THE `encoder_test` BUILD. It carries the TEST_HOOKS trigger: writing
magic 0xDEAD to holding 0x00FF makes the main loop stop refreshing the IWDG.
The release build has no such register and answers exception 02.

FR-S20: the device must resume answering a valid FC04 within 3 s, WITHOUT a
power cycle. FR-S21: after that reset the state must be defined -- holdings
restored from flash, measurement accumulators cleared, status bits 0 and 1 set.

Run:  .venv-m2k/Scripts/python software/hil/tp_b21_b22.py --unit 40
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import modbus_rtu_codec as codec
from m2k_master import M2kMaster

HANG_REG, HANG_MAGIC = 0x00FF, 0xDEAD
RECOVER_BUDGET_S = 3.0
STATUS_FIRST_WINDOW_INCOMPLETE = 0x0001
STATUS_AVG_NOT_FILLED = 0x0002


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    a = ap.parse_args()
    u = a.unit
    fails = []

    with M2kMaster() as m:
        # ---- baseline -----------------------------------------------------
        holdings = m.read_holding(u, 0x0000, 7)
        uptime_before, = m.read_input(u, 0x0007, 1)
        ident, = m.read_input(u, 0x0006, 1)
        print(f"  before: 30007 = 0x{ident:04x}, uptime {uptime_before} s, "
              f"holdings {holdings}")

        # Prove the test hook EXISTS before relying on it. On a release build
        # 0x00FF is not in the map and this returns exception 02 -- which would
        # otherwise look like a watchdog that never fired.
        try:
            m.read_holding(u, HANG_REG, 1)
            print("  test hook present: holding 0x00FF is readable "
                  "(this is the encoder_test build)")
        except codec.Exception_ as e:
            print(f"  *** holding 0x00FF returns exception {e.code} — this is "
                  f"NOT the encoder_test build. Flash it first.")
            return 1

        # ---- TP-B21: stall the loop ---------------------------------------
        print(f"\n  writing 0x{HANG_MAGIC:04X} to holding 0x{HANG_REG:04X} ...")
        t_hang = None
        try:
            m.write_single(u, HANG_REG, HANG_MAGIC)
            t_hang = time.monotonic()
            print("  the write was answered; the loop stalls after replying")
        except codec.ModbusError:
            # Equally valid: it may hang before the response leaves.
            t_hang = time.monotonic()
            print("  no reply to the write — it stalled before responding")

        # It must go quiet, or nothing was proven.
        time.sleep(0.05)
        went_quiet = False
        for _ in range(4):
            try:
                m.read_input(u, 0x0006, 1, )
            except (codec.ModbusError, codec.Exception_):
                went_quiet = True
                break
        if not went_quiet:
            print("  *** the device never stopped answering — the hang hook "
                  "did not take effect; TP-B21 proves nothing")
            fails.append("TP-B21: device never hung")

        # ---- wait for the watchdog ----------------------------------------
        print("  waiting for the IWDG ...")
        recovered_at = None
        while time.monotonic() - t_hang < RECOVER_BUDGET_S + 2.0:
            try:
                m.read_input(u, 0x0006, 1)
                recovered_at = time.monotonic()
                break
            except (codec.ModbusError, codec.Exception_):
                continue

        if recovered_at is None:
            print(f"  FAIL TP-B21 — no valid response within "
                  f"{RECOVER_BUDGET_S + 2.0:.0f} s of the stall")
            fails.append("TP-B21: never recovered")
            return report(fails)

        recovery_s = recovered_at - t_hang
        ok = recovery_s <= RECOVER_BUDGET_S
        print(f"  {'PASS' if ok else 'FAIL'} TP-B21 (FR-S20) — answered again "
              f"{recovery_s:.2f} s after the stall (budget {RECOVER_BUDGET_S:.0f} s, "
              f"no power cycle)")
        if not ok:
            fails.append(f"TP-B21: recovery {recovery_s:.2f} s")

        # ---- TP-B22: the state after that reset ---------------------------
        time.sleep(0.3)
        ireg = m.read_input(u, 0x0000, 15)
        after = m.read_holding(u, 0x0000, 7)
        uptime_after = ireg[7]
        status = ireg[5]

        checks = [
            ("uptime restarted (proves a real reset, not a stall that cleared)",
             uptime_after < uptime_before),
            ("holdings restored to their persisted values",
             after[:6] == holdings[:6]),
            ("40007 (teach) reads 0 — deliberately not persisted", after[6] == 0),
            ("measurement registers 30001-30005 cleared",
             all(v == 0 for v in ireg[0:5])),
            ("status bit 0 set (first window incomplete)",
             bool(status & STATUS_FIRST_WINDOW_INCOMPLETE)),
            ("status bit 1 set (average not filled)",
             bool(status & STATUS_AVG_NOT_FILLED)),
        ]
        print(f"\n  after:  uptime {uptime_after} s (was {uptime_before}), "
              f"status 0x{status:04x}, holdings {after}")
        for what, good in checks:
            print(f"  {'PASS' if good else 'FAIL'} TP-B22 — {what}")
            if not good:
                fails.append(f"TP-B22: {what}")

        # ---- leave the hook disarmed --------------------------------------
        try:
            m.write_single(u, HANG_REG, 0)
            print("\n  hang trigger cleared (0x00FF = 0)")
        except Exception as e:                              # noqa: BLE001
            print(f"\n  could not clear the hang trigger: {e}")

    return report(fails)


def report(fails) -> int:
    print()
    if fails:
        print(f"{len(fails)} FAILED")
        for f in fails:
            print("   ", f)
        return 1
    print("TP-B21 and TP-B22 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
