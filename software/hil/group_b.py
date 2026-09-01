"""Group B — protocol and lifecycle rows that need no bench intervention.

Run:  .venv-m2k/Scripts/python software/hil/group_b.py --unit 40

Covers the design/testPlan.md §5 rows that the M2K raw master can drive on its
own. Rows needing a power cycle, a jumper change, the `encoder_test` build or an
adjustable supply are listed at the end as NOT RUN, with what they need — they
are not silently omitted.

STATE SAFETY. This writes holding registers, which the DUT persists to flash.
The as-found values are read first and restored with a single atomic FC16 at
the end, including after a failure or a Ctrl-C. Nothing here writes 40007
(teach), which would arm a calibration capture.

COUNTER ARITHMETIC. Reading 30009/30010 is itself a served request, so every
counter read moves the counter. The per-read increment is measured at the start
rather than assumed, and subtracted from every delta.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import modbus_rtu_codec as codec
from m2k_master import (M2kMaster, SAMPLE_RATE, SAMPLES_PER_BIT, T35_S,
                        HOUSE_GAP_S, DIO_RX, RESPONSE_WINDOW_S)

IREG_CRC_ERRS, IREG_SERVED = 0x0008, 0x0009
HOLDING_DEFAULTS = [0, 1000, 10, 10000, 0, 1023, 0]
CAL_MIN_SPAN = 64

#: Where the as-found holdings are stashed so a killed run is recoverable.
STASH = Path(__file__).with_name(".holdings-as-found.json")

results: list[tuple[str, str, str, str]] = []
exception_codes_seen: set[int] = set()
silent_on_valid: list[str] = []


def record(row: str, req: str, ok: bool | None, detail: str) -> None:
    verdict = "PASS" if ok else ("FAIL" if ok is False else "INFO")
    results.append((row, req, verdict, detail))
    print(f"  {verdict:<4} {row:<8} {detail}")


# ── expectation helpers ─────────────────────────────────────────────────────
def expect_exception(m, row, req_id, request, unit, fc, code, what):
    """A well-formed exception response with the expected code."""
    try:
        m.transact(request, unit, fc, retry_on_crc=False)
        record(row, req_id, False, f"{what}: accepted, expected exception {code}")
    except codec.Exception_ as e:
        exception_codes_seen.add(e.code)
        record(row, req_id, e.code == code,
               f"{what}: exception {e.code}" +
               ("" if e.code == code else f", expected {code}"))
    except codec.ModbusError as e:
        silent_on_valid.append(f"{row}: {what}")
        record(row, req_id, False, f"{what}: no usable response ({e})")


def expect_silence(m, row, req_id, request, unit, what):
    """No frame addressed to `unit` comes back at all."""
    raw = m.send_raw(request)
    reply = m._extract(raw, unit)
    quiet = not (codec.crc_ok(reply) and len(reply) >= 4 and reply[0] == unit)
    record(row, req_id, quiet,
           f"{what}: " + ("silent" if quiet else f"replied {reply.hex(' ')}"))


def counters(m, unit) -> tuple[int, int]:
    crc, served = m.read_input(unit, IREG_CRC_ERRS, 2)
    return crc, served


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--polls", type=int, default=200,
                    help="FR-MB21 sample size; the plan specifies 1000")
    ap.add_argument("--uptime-minutes", type=float, default=0.0,
                    help="TP-B05 duration; the plan specifies 10. 0 skips it.")
    ap.add_argument("--restore-stashed", action="store_true",
                    help="write the stashed as-found holdings back and exit; "
                         "for recovering from a run that was killed")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    u = a.unit

    if a.restore_stashed:
        return restore_stashed(u, a.verbose)

    with M2kMaster(verbose=a.verbose) as m:
        print(f"\nGroup B against unit {u}\n")

        # ── as-found state, restored in the finally block ───────────────────
        # Written to disk BEFORE anything is modified. A finally block does not
        # run when the process is killed, and on 2026-09-01 a kill left the DUT
        # holding TP-B09's test values (40002=60000, 40003=60) with no record of
        # what they had been. The stash is the record; it is removed only after
        # a verified restore.
        if STASH.exists():
            stale = json.loads(STASH.read_text())
            now = m.read_holding(u, 0x0000, 7)
            print("\n  *** A previous run did not restore the DUT. ***")
            print(f"  It recorded 40001-40007 as {stale['as_found']} "
                  f"at {stale['when']}.")
            print(f"  The device now reads {now}.")
            print("  Restore by hand, or pass --restore-stashed, before "
                  "trusting anything below.\n")

        as_found = m.read_holding(u, 0x0000, 7)
        print(f"  as-found holdings 40001-40007: {as_found}")
        if not STASH.exists():
            STASH.write_text(json.dumps(
                {"as_found": as_found, "when": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "unit": u}, indent=2))
        try:
            run_rows(m, u, as_found, a)
        finally:
            print("\n  restoring holdings ...")
            try:
                # One atomic FC16 over 40001-40006. Restoring register by
                # register would pass through intermediate states that
                # FR-S31 and FR-E06 reject. 40007 is not persisted and is
                # never written here.
                m.write_multiple(u, 0x0000, as_found[:6])
                back = m.read_holding(u, 0x0000, 7)
                same = back[:6] == as_found[:6]
                print(f"  restored: {back[:6]}  " +
                      ("(matches as-found)" if same else "*** MISMATCH ***"))
                if same:
                    STASH.unlink(missing_ok=True)   # only now is it safe to forget
                else:
                    record("restore", "-", False,
                           f"holdings not restored: {back[:6]} vs {as_found[:6]}")
            except Exception as e:                      # noqa: BLE001
                print(f"  *** RESTORE FAILED: {e} — check 40001-40006 by hand")

    summarise()
    return 1 if any(v == "FAIL" for _, _, v, _ in results) else 0


def restore_stashed(unit: int, verbose: bool) -> int:
    """Put the stashed as-found holdings back, for a run that was killed.

    Restores 40001-40006 in one atomic FC16 — register by register would pass
    through states FR-S31 and FR-E06 reject. 40007 is not persisted and is not
    written. The stash is removed only once a read-back confirms the values.
    """
    if not STASH.exists():
        print(f"nothing stashed at {STASH} — nothing to restore")
        return 0
    stale = json.loads(STASH.read_text())
    want = stale["as_found"][:6]
    print(f"stashed {stale['as_found']} at {stale['when']} (unit {stale['unit']})")
    if stale["unit"] != unit:
        print(f"*** stash is for unit {stale['unit']}, not {unit} — refusing")
        return 1
    with M2kMaster(verbose=verbose) as m:
        print(f"  device reads {m.read_holding(unit, 0x0000, 7)}")
        m.write_multiple(unit, 0x0000, want)
        back = m.read_holding(unit, 0x0000, 7)
        if back[:6] == want:
            STASH.unlink()
            print(f"  restored {back[:6]}; stash cleared")
            return 0
        print(f"  *** restore failed: {back[:6]} != {want}")
        return 1


def run_rows(m, u, as_found, a) -> None:
    # ── TP-B01 identity ─────────────────────────────────────────────────────
    ident, = m.read_input(u, 0x0006, 1)
    record("TP-B01", "FR-S01", (ident >> 8) == 0x01,
           f"identification 0x{ident:04x} = build 0x{ident >> 8:02x}, "
           f"firmware {ident & 0xFF}")

    # ── TP-B17 every input register ─────────────────────────────────────────
    ireg = m.read_input(u, 0x0000, 15)
    record("TP-B17", "FR-MB08", len(ireg) == 15,
           f"30001-30015 all readable: {ireg}")

    # ── TP-B18 every holding register ───────────────────────────────────────
    at_default = as_found == HOLDING_DEFAULTS
    record("TP-B18", "FR-MB09", len(as_found) == 7,
           f"40001-40007 all readable: {as_found}" +
           ("  (= §2.8 defaults)" if at_default else
            f"  NOTE: differs from §2.8 defaults {HOLDING_DEFAULTS}; the row's "
            "'after a factory reset' precondition was not met, so defaults are "
            "not verified here"))

    # ── counter arithmetic: measure the per-read increment ──────────────────
    _, s0 = counters(m, u)
    _, s1 = counters(m, u)
    per_read = s1 - s0
    record("counters", "FR-S35", per_read >= 1,
           f"each counter read advances 30010 by {per_read}")

    # ── TP-B06 all four function codes ──────────────────────────────────────
    ok = True
    try:
        m.read_holding(u, 0x0000, 7)                      # FC03 / FR-MB09
        m.read_input(u, 0x0000, 15)                       # FC04 / FR-MB08
        m.write_single(u, 0x0000, as_found[0])            # FC06 / FR-MB10
        m.write_multiple(u, 0x0000, as_found[:2])         # FC16 / FR-MB11
    except Exception as e:                                # noqa: BLE001
        ok = False
        record("TP-B06", "FR-MB08..11", False, f"function code set: {e}")
    if ok:
        record("TP-B06", "FR-MB01,08,09,10,11", True,
               "FC03, FC04, FC06 and FC16 all accepted with correct framing")

    # ── TP-B07 byte order on the wire (FR-MB25) ─────────────────────────────
    req = codec.read_input_registers(u, 0x000E, 1)
    body_be = req[2:6].hex(" ") == "00 0e 00 01"
    crc = codec.crc16(req[:-2])
    crc_le = (req[-2], req[-1]) == (crc & 0xFF, crc >> 8)
    raw = m.send_raw(codec.read_input_registers(u, 0x0006, 1))
    rep = m._extract(raw, u)
    # 30007 is 0x0101, which is a palindrome — read 30008 (uptime) instead,
    # whose two bytes differ, so big-endian data is actually observable.
    raw2 = m.send_raw(codec.read_input_registers(u, 0x0007, 1))
    rep2 = m._extract(raw2, u)
    data_be = None
    if codec.crc_ok(rep2) and len(rep2) == 7:
        on_wire = rep2[3] << 8 | rep2[4]
        again, = m.read_input(u, 0x0007, 1)
        data_be = abs(on_wire - again) <= 3      # uptime ticks between reads
    record("TP-B07", "FR-MB25", bool(body_be and crc_le and data_be),
           f"request data big-endian: {body_be}; CRC little-endian: {crc_le}; "
           f"response data big-endian: {data_be} "
           f"(30008 on the wire {rep2[3:5].hex(' ') if len(rep2) >= 5 else '?'})")

    # ── TP-B13 / TP-B26 / TP-B27 illegal data address (FR-MB13/14/15) ───────
    expect_exception(m, "TP-B13", "FR-MB13",
                     codec.read_input_registers(u, 0x0020, 1),
                     u, codec.FC_READ_INPUT, 2, "read input 0x0020")
    expect_exception(m, "TP-B26", "FR-MB14",
                     codec.read_input_registers(u, 0x000A, 12),
                     u, codec.FC_READ_INPUT, 2,
                     "read 12 inputs from 0x000A, spanning the map edge")
    expect_exception(m, "TP-B27", "FR-MB15",
                     codec.write_single_register(u, 0x0020, 1),
                     u, codec.FC_WRITE_SINGLE, 2, "write holding 0x0020")

    # ── TP-B25 illegal function (FR-MB12) ───────────────────────────────────
    for fc in (0x01, 0x02, 0x05):
        bad_fc = codec.append_crc(bytes((u, fc, 0x00, 0x00, 0x00, 0x01)))
        raw = m.send_raw(bad_fc)
        rep = m._extract(raw, u)
        got = None
        if codec.crc_ok(rep) and len(rep) >= 5 and rep[1] == (fc | 0x80):
            got = rep[2]
            exception_codes_seen.add(got)
        elif not rep:
            silent_on_valid.append(f"TP-B25: FC{fc:02x}")
        record("TP-B25", "FR-MB12", got == 1,
               f"FC{fc:02X}: " + (f"exception {got}" if got is not None
                                  else f"no exception response ({rep.hex(' ') or 'silence'})"))

    # ── TP-B08 out-of-range value (FR-MB19) ─────────────────────────────────
    before, = m.read_holding(u, 0x0001, 1)
    for bad, why in ((65000, "above the 60000 maximum"), (50, "below the 100 minimum")):
        expect_exception(m, "TP-B08", "FR-MB19",
                         codec.write_single_register(u, 0x0001, bad),
                         u, codec.FC_WRITE_SINGLE, 3, f"40002 = {bad} ({why})")
    after, = m.read_holding(u, 0x0001, 1)
    record("TP-B08", "FR-MB19", after == before,
           f"40002 unchanged after both rejections: {before} -> {after}"
           + ("" if after == before else "  *** CLAMPED OR WRITTEN ***"))

    # ── TP-B09 FC16 atomicity (FR-MB22) ─────────────────────────────────────
    b1, b2 = m.read_holding(u, 0x0000, 2)
    expect_exception(m, "TP-B09", "FR-MB22",
                     codec.write_multiple_registers(u, 0x0000, [100, 65000]),
                     u, codec.FC_WRITE_MULTIPLE, 3,
                     "FC16 40001=100 (valid) + 40002=65000 (invalid)")
    a1, a2 = m.read_holding(u, 0x0000, 2)
    record("TP-B09", "FR-MB22", (a1, a2) == (b1, b2),
           f"neither register moved: 40001 {b1}->{a1}, 40002 {b2}->{a2}"
           + ("" if (a1, a2) == (b1, b2) else "  *** PARTIAL WRITE ***"))

    # The plan asks for a pair that is valid while an intermediate state is not.
    # FR-S31 is (40003 x 1000) >= 40002, so only ONE of the two orderings can be
    # invalid: making both invalid would need 40003 to be simultaneously larger
    # and smaller than its old value. The row is exercised in the direction that
    # is genuinely unreachable register-by-register.
    try:
        m.write_multiple(u, 0x0001, [60000, 60])          # 60x1000 >= 60000 ok
        got = m.read_holding(u, 0x0001, 2)
        record("TP-B09", "FR-MB22", got == [60000, 60],
               f"FC16 40002=60000 + 40003=60 accepted as a pair -> {got}; "
               "writing 40002 first would violate FR-S31 (10x1000 < 60000)")
    except codec.Exception_ as e:
        exception_codes_seen.add(e.code)
        record("TP-B09", "FR-MB22", False,
               f"valid pair rejected with exception {e.code} — atomicity not honoured")

    # ── TP-B10 calibration span (FR-E06) ────────────────────────────────────
    c1, c2 = m.read_holding(u, 0x0004, 2)
    expect_exception(m, "TP-B10", "FR-E06",
                     codec.write_multiple_registers(u, 0x0004, [100, 100 + CAL_MIN_SPAN - 1]),
                     u, codec.FC_WRITE_MULTIPLE, 3,
                     f"40005/40006 span {CAL_MIN_SPAN - 1} < CAL_MIN_SPAN {CAL_MIN_SPAN}")
    d1, d2 = m.read_holding(u, 0x0004, 2)
    record("TP-B10", "FR-E06", (d1, d2) == (c1, c2),
           f"both unchanged: 40005 {c1}->{d1}, 40006 {c2}->{d2}")

    # ── TP-B28 response shape (FR-MB30) ─────────────────────────────────────
    cur, = m.read_holding(u, 0x0000, 1)
    fc06 = codec.write_single_register(u, 0x0000, cur)
    echo = m._extract(m.send_raw(fc06), u)
    record("TP-B28", "FR-MB30", echo == fc06,
           f"FC06 response byte-identical to request: {echo == fc06} "
           f"({echo.hex(' ')})")
    vals = m.read_holding(u, 0x0001, 2)
    fc16 = codec.write_multiple_registers(u, 0x0001, vals)
    rep = m._extract(m.send_raw(fc16), u)
    shape = len(rep) == 8 and rep[2:6].hex(" ") == "00 01 00 02"
    record("TP-B28", "FR-MB30", shape,
           f"FC16 response PDU is address+quantity, not data: {rep.hex(' ')}")

    # ── TP-B11 wrong address and broadcast (FR-MB05 / FR-MB06) ──────────────
    expect_silence(m, "TP-B11", "FR-MB05",
                   codec.read_input_registers(247, 0x0000, 1), u,
                   "FC04 to address 247")
    # FR-MB06 is a deliberate deviation from Modbus V1.02 §2.2: broadcast is
    # ignored, NOT executed. Prove both halves — no reply, and no side effect.
    base, = m.read_holding(u, 0x0000, 1)
    probe = (base + 7) & 0xFFFF
    expect_silence(m, "TP-B11", "FR-MB06",
                   codec.write_single_register(0, 0x0000, probe), u,
                   f"broadcast FC06 40001 = {probe}")
    now, = m.read_holding(u, 0x0000, 1)
    record("TP-B11", "FR-MB06", now == base,
           f"broadcast write NOT executed: 40001 stayed {base}"
           + ("" if now == base else f" — but it changed to {now}, which is the "
              "Modbus V1.02 behaviour and a FR-MB06 violation"))

    # ── TP-B12 bad CRC (FR-MB02 + FR-S35) ───────────────────────────────────
    c_before, s_before = counters(m, u)
    corrupt = bytearray(codec.read_input_registers(u, 0x0000, 1))
    corrupt[-1] ^= 0xFF
    expect_silence(m, "TP-B12", "FR-MB02", bytes(corrupt), u,
                   "frame with a corrupted CRC")
    c_after, s_after = counters(m, u)
    d_crc = c_after - c_before
    # Exactly ONE served request falls between two consecutive counter reads —
    # the earlier read itself, whose own increment lands after it has sampled
    # the value it returns. `per_read` measured that; subtracting it twice was
    # an arithmetic error that reported a healthy device as failing.
    d_served = s_after - s_before - per_read
    record("TP-B12", "FR-S35", d_crc == 1 and d_served == 0,
           f"30009 +{d_crc} (expected +1), 30010 +{d_served} beyond the "
           f"counter read itself (expected +0)")

    # ── TP-B16 counters against a known mix of frames (FR-S35) ──────────────
    tp_b16(m, u, per_read)

    # ── TP-B15 inter-frame gap (FR-MB03) ────────────────────────────────────
    tp_b15(m, u, per_read)

    # ── TP-B14 / TP-B29 response latency (FR-MB20 / FR-MB21) ────────────────
    latency(m, u, a.polls)

    # ── TP-B05 uptime (FR-S34) ──────────────────────────────────────────────
    if a.uptime_minutes > 0:
        uptime_row(m, u, a.uptime_minutes)
    else:
        record("TP-B05", "FR-S34", None,
               "NOT RUN — pass --uptime-minutes 10 (the plan's duration)")

    # ── TP-B30 / TP-B31, judged over everything above ───────────────────────
    record("TP-B30", "FR-MB18", exception_codes_seen <= {1, 2, 3},
           f"exception codes observed across Group B: "
           f"{sorted(exception_codes_seen) or 'none'} (only 01/02/03 permitted)")
    record("TP-B31", "FR-MB17", not silent_on_valid,
           "the DUT answered every valid addressed request"
           if not silent_on_valid else f"silent on: {silent_on_valid}")


def tp_b16(m, u, per_read, good: int = 20, bad: int = 10) -> None:
    """FR-S35: 30009 and 30010 must match the frames sent, exactly.

    A known mix, counted independently of every other row. The good frames are
    sent through send_raw rather than transact so that a retry cannot quietly
    inflate the count being verified.
    """
    req = codec.read_input_registers(u, 0x0006, 1)
    corrupt = bytearray(codec.read_input_registers(u, 0x0000, 1))
    corrupt[-1] ^= 0xFF

    c0, s0 = counters(m, u)
    for _ in range(good):
        m.send_raw(req)
    for _ in range(bad):
        m.send_raw(bytes(corrupt))
    c1, s1 = counters(m, u)

    d_crc = c1 - c0
    d_served = s1 - s0 - per_read
    record("TP-B16", "FR-S35", d_crc == bad and d_served == good,
           f"{good} good + {bad} corrupted frames: 30010 +{d_served} "
           f"(expected +{good}), 30009 +{d_crc} (expected +{bad})")


def tp_b15(m, u, per_read) -> None:
    """Two frames in one burst, separated by a controlled mark gap (FR-MB03).

    Below t3.5 the DUT must merge them into a single frame, whose CRC then
    fails. Above t3.5 it must see two frames and serve the second.

    The FIRST frame is addressed to unit 247, which FR-MB05 requires the DUT to
    ignore. That is deliberate: the measured response latency is ~12 ms, so two
    frames to the DUT's own address 6 ms apart would have it replying to the
    first while we are still transmitting the second. That is bus contention,
    not a frame-boundary test, and an earlier version of this row measured it
    and called it a failure. Addressing the first frame elsewhere removes the
    reply entirely and leaves only boundary detection under test.
    """
    other = codec.read_input_registers(247, 0x0006, 1)   # ignored, never answered
    mine = codec.read_input_registers(u, 0x0006, 1)
    lead = int(0.0005 * SAMPLE_RATE)

    def burst(gap_s: float) -> None:
        bits = (codec.encode_uart(other, SAMPLES_PER_BIT)
                + [1] * int(gap_s * SAMPLE_RATE)
                + codec.encode_uart(mine, SAMPLES_PER_BIT))
        buf = ([m._word(1, 1)] * lead
               + [m._word(b, 1) for b in bits]
               + [m._word(1, 1)] * lead
               + [m._word(1, 0)] * int(HOUSE_GAP_S * SAMPLE_RATE))
        m.dig.push(buf)
        time.sleep(RESPONSE_WINDOW_S)

    for gap_s, exp_crc, exp_served, label in (
            (T35_S * 0.5, 1, 0,
             f"{T35_S * 0.5 * 1000:.2f} ms (below t3.5) -> must merge into one "
             "frame with a failing CRC"),
            (T35_S * 1.5, 0, 1,
             f"{T35_S * 1.5 * 1000:.2f} ms (above t3.5) -> must split; the 247 "
             "frame ignored, ours served")):
        c0, s0 = counters(m, u)
        burst(gap_s)
        c1, s1 = counters(m, u)
        d_crc, d_served = c1 - c0, s1 - s0 - per_read
        ok = d_crc == exp_crc and d_served == exp_served
        record("TP-B15", "FR-MB03", ok,
               f"two frames {label}: 30009 +{d_crc} (expected +{exp_crc}), "
               f"30010 +{d_served} (expected +{exp_served})")


def latency(m, u, polls: int) -> None:
    """FR-MB20 (<=100 ms, must) and FR-MB21 (95 % <=15 ms, should).

    Timed against DE, which we drive, rather than against our own frame on RX,
    which the DUT's receiver suppresses. If the DE readback is unusable the row
    reports BLOCKED, not FAIL: an unmeasurable timing says nothing about whether
    the device met it.
    """
    req = codec.read_input_registers(u, 0x0006, 1)
    samples: list[float] = []
    unmeasurable: list[str] = []
    worst_width_err = 0.0
    print(f"  measuring response latency over {polls} polls ...")
    for _ in range(polls):
        m._exchange(req)
        got = m.response_latency_s(len(req))
        if got is None:
            unmeasurable.append(m.last_latency_note)
            continue
        worst_width_err = max(worst_width_err, got["de_width_error_s"] * 1000.0)
        samples.append(got["latency_s"] * 1000.0)
        time.sleep(0.05)                       # FR-MB21's 50 ms spacing
    if not samples:
        why = unmeasurable[0] if unmeasurable else "no samples"
        record("TP-B14", "FR-MB20", None, f"BLOCKED — {why}")
        record("TP-B29", "FR-MB21", None, "BLOCKED — no usable latency samples")
        return
    samples.sort()
    p95 = samples[int(0.95 * (len(samples) - 1))]
    worst = samples[-1]
    lost = len(unmeasurable)
    record("TP-B14", "FR-MB20", worst <= 100.0 and lost == 0,
           f"n={len(samples)}" + (f", {lost} unmeasurable" if lost else "") +
           f"; median {statistics.median(samples):.2f} ms, p95 {p95:.2f} ms, "
           f"max {worst:.2f} ms (limit 100 ms). DE pulse-width error at worst "
           f"{worst_width_err:.3f} ms, which is the check that the DE readback "
           f"is our own driven line")
    within15 = sum(1 for s in samples if s <= 15.0) / len(samples)
    partial = "" if polls >= 1000 else         f"  PARTIAL: n={polls}, the plan specifies 1000 — rerun with --polls 1000"
    record("TP-B29", "FR-MB21", within15 >= 0.95 and worst <= 100.0,
           f"{within15 * 100:.1f} % within 15 ms (need 95 %), "
           f"100 % within 100 ms: {worst <= 100.0}{partial}")


def uptime_row(m, u, minutes: float) -> None:
    """FR-S34: 30008 monotonic, whole seconds, tracking real time."""
    print(f"  sampling uptime for {minutes:.1f} min ...")
    t0 = time.monotonic()
    first, = m.read_input(u, 0x0007, 1)
    seen = [(0.0, first)]
    while time.monotonic() - t0 < minutes * 60:
        time.sleep(15)
        v, = m.read_input(u, 0x0007, 1)
        seen.append((time.monotonic() - t0, v))
    mono = all(b[1] >= a[1] for a, b in zip(seen, seen[1:]))
    elapsed, drift = seen[-1][0], (seen[-1][1] - seen[0][1]) - seen[-1][0]
    record("TP-B05", "FR-S34", mono and abs(drift) <= max(2.0, 0.01 * elapsed),
           f"monotonic: {mono}; counted {seen[-1][1] - seen[0][1]} s over "
           f"{elapsed:.0f} s of wall clock (drift {drift:+.1f} s). "
           "Reset-to-zero is TP-B04's power cycle, not covered here.")


def summarise() -> None:
    print("\n" + "=" * 72)
    for row, req, verdict, detail in results:
        print(f"{verdict:<4} {row:<9} {req:<22} {detail}")
    n_fail = sum(1 for _, _, v, _ in results if v == "FAIL")
    n_pass = sum(1 for _, _, v, _ in results if v == "PASS")
    print("=" * 72)
    print(f"{n_pass} pass, {n_fail} fail, "
          f"{sum(1 for _, _, v, _ in results if v == 'INFO')} informational")
    print("""
NOT RUN — these need the bench, not the master:
  TP-B02  FR-S03/MB07   jumper JP6 open then bridged, power cycle between
  TP-B03  FR-S02        power-on to first valid response
  TP-B04  FR-S32        30007 across a power cycle
  TP-B19  FR-S39        holdings survive a power cycle
  TP-B20  FR-S39        20 power cycles, some mid-write
  TP-B21  FR-S20        `encoder_test` build, magic 0xDEAD to holding 0x00FF
  TP-B22  FR-S21        register state after that watchdog reset
  TP-B23  FR-S22        BLOCKED — needs an adjustable supply (as TP-A03)
  TP-B24  FR-S18/S19    bus capture from power-on
  TP-B32  FR-MB04       DE timing against the bus, on the scope""")


if __name__ == "__main__":
    sys.exit(main())
