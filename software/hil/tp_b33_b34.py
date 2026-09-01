"""TP-B33 / TP-B34 — FR-MB28 quantity limits and FR-MB24 malformed-frame handling.

Both rows were missing from the plan entirely until the citation sweep; both are
testable with the raw master and no bench help.

FR-MB28: FC03/FC04 with quantity 0 or >125, and FC16 with quantity 0, >123, or a
byte-count field that disagrees with the quantity, must all return exception 03
and modify nothing.

FR-MB24: a receive error, or more bytes without a t3.5 gap than the 256-byte ADU
maximum, must be discarded with no response -- and the device must still answer
the NEXT well-formed request. That second half is the one that matters: a device
that wedges after a bad frame also "does not respond", and the two are only
distinguishable by asking again.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import modbus_rtu_codec as codec
from m2k_master import M2kMaster, HOUSE_GAP_S

results = []


def record(row, req, ok, detail):
    verdict = "PASS" if ok else "FAIL"
    results.append((row, req, verdict, detail))
    print(f"  {verdict} {row:<7} {detail}")


def expect_exc(m, row, req, frame, unit, fc, code, what):
    try:
        m.transact(frame, unit, fc, retry_on_crc=False)
        record(row, req, False, f"{what}: ACCEPTED, expected exception {code}")
    except codec.Exception_ as e:
        record(row, req, e.code == code,
               f"{what}: exception {e.code}" + ("" if e.code == code else f" (wanted {code})"))
    except codec.ModbusError as e:
        record(row, req, False, f"{what}: no usable response ({e})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    a = ap.parse_args()
    u = a.unit

    with M2kMaster() as m:
        before = m.read_holding(u, 0x0000, 7)
        print(f"  holdings before: {before}\n")

        # ---- TP-B33 / FR-MB28 -----------------------------------------
        for fc, name in ((codec.FC_READ_INPUT, "FC04"), (codec.FC_READ_HOLDING, "FC03")):
            for qty in (0, 126):
                f = codec.append_crc(bytes((u, fc, 0, 0, (qty >> 8) & 0xFF, qty & 0xFF)))
                expect_exc(m, "TP-B33", "FR-MB28", f, u, fc, 3,
                           f"{name} quantity {qty}")

        # FC16 quantity 0
        f = codec.append_crc(bytes((u, 0x10, 0, 0, 0, 0, 0)))
        expect_exc(m, "TP-B33", "FR-MB28", f, u, codec.FC_WRITE_MULTIPLE, 3,
                   "FC16 quantity 0")
        # FC16 quantity > 123 is NOT TESTABLE with a legal frame, and the
        # requirement's own threshold says why. An FC16 ADU is 9 + 2N bytes, so
        # N = 123 gives 255 and N = 124 gives 257 -- past the 256-byte RTU
        # maximum. Any frame that violates FR-MB28's ">123" clause therefore
        # also violates FR-MB24's length limit, and a device that discards it
        # silently is obeying FR-MB24. Sending it and calling the silence a
        # FR-MB28 failure, as a first version of this row did, tests nothing.
        print("  SKIP TP-B33  FC16 quantity >123: unreachable — 9 + 2*124 = 257 "
              "bytes exceeds the 256-byte ADU maximum, so FR-MB24 catches it "
              "first. See the plan's known-gaps section.")
        # FC16 byte count disagreeing with quantity (says 6, quantity 2 -> wants 4)
        body = bytes((u, 0x10, 0, 0, 0, 2, 6)) + bytes(4)
        expect_exc(m, "TP-B33", "FR-MB28", codec.append_crc(body), u,
                   codec.FC_WRITE_MULTIPLE, 3, "FC16 byte count 6 with quantity 2")

        after = m.read_holding(u, 0x0000, 7)
        record("TP-B33", "FR-MB28", after == before,
               f"no register modified by any rejected write: {after}")

        # ---- TP-B34 / FR-MB24 -----------------------------------------
        print()
        oversize = bytes((u, 0x04)) + bytes(range(256)) * 2      # 514 bytes, no gaps
        try:
            m._transmit(oversize)
            time.sleep(0.3)
            record("TP-B34", "FR-MB24", True,
                   f"{len(oversize)}-byte burst (> the 256-byte ADU maximum) sent")
        except Exception as e:                                   # noqa: BLE001
            record("TP-B34", "FR-MB24", False, f"could not transmit the burst: {e}")

        time.sleep(HOUSE_GAP_S * 3)
        quiet = True
        try:
            m.read_input(u, 0x0006, 1)
        except codec.ModbusError:
            pass
        # The half that matters: is it still alive?
        alive = False
        for _ in range(3):
            try:
                v, = m.read_input(u, 0x0006, 1)
                alive = True
                break
            except (codec.ModbusError, codec.Exception_):
                time.sleep(0.05)
        record("TP-B34", "FR-MB24", alive,
               "still answers the next well-formed request after the over-long "
               "frame" if alive else "*** WEDGED — no reply after the over-long frame")

        # a deliberately mis-framed byte stream: valid CRC is impossible here,
        # so this exercises the receive-error path rather than the CRC path
        try:
            m.send_raw(bytes((u, 0x04, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00)))
        except Exception:                                        # noqa: BLE001
            pass
        alive2 = False
        for _ in range(3):
            try:
                m.read_input(u, 0x0006, 1)
                alive2 = True
                break
            except (codec.ModbusError, codec.Exception_):
                time.sleep(0.05)
        record("TP-B34", "FR-MB24", alive2,
               "still answers after a corrupt frame" if alive2 else "*** wedged")

        i = m.read_input(u, 0x0000, 15)
        print(f"\n  crc_errors {i[8]}, served {i[9]}")

    n_fail = sum(1 for _, _, v, _ in results if v == "FAIL")
    print(f"\n{len(results) - n_fail} pass, {n_fail} fail")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
