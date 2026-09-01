"""TP-B35 — FR-S16 (internal RC oscillator) and FR-MB23 (discard RX while TX).

FR-S16: the CH32V003 runs from its internal 48 MHz HSI with no crystal fitted.
The verification clause is a soak -- 10,000 request/response cycles at 9600 baud
with **zero** framing or CRC errors. An oscillator too far off tolerance fails
gradually and statistically, so a handful of transactions cannot find it; that
is the whole point of the number.

FR-MB23 rides along. The DUT's RO and DI are tied on the shared PD6 node, so if
it ever evaluated its own transmission as an incoming frame it would log CRC
errors. A zero count across 10,000 exchanges is the standing evidence that it
does not.

Pass: 30009 unchanged, and 30010 advanced by exactly the number of requests
sent. Both are read from the device, not inferred from what this script thinks
it sent.

Run:  .venv-m2k/Scripts/python software/hil/tp_b35.py --unit 40 --cycles 10000
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import m2k_master
import modbus_rtu_codec as codec
from m2k_master import M2kMaster


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--cycles", type=int, default=10000)
    ap.add_argument("--window", type=float, default=0.04,
                    help="capture window in seconds per exchange")
    a = ap.parse_args()
    u = a.unit

    # A 7-byte reply lands ~4 ms after our 8.3 ms frame and takes 7.3 ms, so
    # ~20 ms of capture suffices. The 120 ms default is sized for a 35-byte
    # reply and would make a 10,000-cycle soak take three times as long for no
    # extra information.
    m2k_master.RESPONSE_WINDOW_S = a.window

    req = codec.read_input_registers(u, 0x0006, 1)
    bad = errors = 0
    misses: list[tuple[int, int, str]] = []
    latencies: list[float] = []
    t0 = time.monotonic()

    with M2kMaster() as m:
        c_before, s_before = m.read_input(u, 0x0008, 2)
        _, s_probe = m.read_input(u, 0x0008, 2)
        per_read = s_probe - s_before
        print(f"  before: 30009 = {c_before}, 30010 = {s_before} "
              f"(a counter read advances it by {per_read})")
        print(f"  running {a.cycles} cycles ...", flush=True)

        for i in range(a.cycles):
            try:
                raw = m._exchange(req)
                reply = m._extract(raw, u)
                codec.parse_response(reply, u, codec.FC_READ_INPUT)
                got = m.response_latency_s(len(req))
                if got:
                    latencies.append(got["latency_s"] * 1e3)
            except codec.ModbusError as e:
                bad += 1
                # Distinguish the two causes rather than assume. A miss with NO
                # edges in the capture means the reply fell outside our window
                # -- a rig timing artefact. A miss WITH a full frame's worth of
                # edges that still would not decode points at the DUT's
                # transmit clock, which is exactly what FR-S16 is about.
                line = m.last_capture or []
                edges = [k for k in range(1, len(line)) if line[k] != line[k-1]]
                # "Edges present" is NOT the same as "the DUT's clock is bad".
                # A TRUNCATED capture also has edges and also will not decode.
                # Classify by where the last edge sits: a reply that ran into
                # the end of the window was clipped by the rig, not mangled by
                # the DUT. Anything else -- edges present, comfortably inside
                # the window, still undecodable -- is the only class that can
                # implicate the transmit clock.
                tail_s = ((len(line) - edges[-1]) / m2k_master.SAMPLE_RATE
                          if edges else None)
                clipped = tail_s is not None and tail_s < 2 * 11 / 9600
                if not edges:
                    kind, why = "empty", "no edges — reply outside the window"
                elif clipped:
                    kind, why = "clipped", (f"last edge only {tail_s*1e3:.1f} ms "
                                            f"from the window end — truncated")
                else:
                    kind, why = "suspect", (f"{len(edges)} edges, {tail_s*1e3:.1f} ms "
                                            f"of idle after — genuinely undecodable")
                misses.append((i, kind, str(e)[:40]))
                if bad <= 5:
                    print(f"    cycle {i}: {e}  [{why}]", flush=True)
            except codec.Exception_ as e:
                errors += 1
                if errors <= 5:
                    print(f"    cycle {i}: exception {e.code}", flush=True)
            if (i + 1) % 500 == 0:
                el = time.monotonic() - t0
                print(f"    {i+1}/{a.cycles}  {el:6.0f} s elapsed, "
                      f"{bad} bad, {errors} exceptions", flush=True)

        c_after, s_after = m.read_input(u, 0x0008, 2)

    elapsed = time.monotonic() - t0
    d_crc = c_after - c_before
    # requests served = the soak's cycles + the two counter reads that fall
    # between the before-reading and the after-reading
    d_served = s_after - s_before - 2 * per_read
    print(f"\n  after:  30009 = {c_after}, 30010 = {s_after}")
    print(f"  {a.cycles} cycles in {elapsed:.0f} s "
          f"({elapsed / a.cycles * 1e3:.1f} ms each)")
    print(f"  master saw {bad} unusable replies, {errors} exception responses")
    if latencies:
        print(f"  latency median {statistics.median(latencies):.2f} ms, "
              f"max {max(latencies):.2f} ms over {len(latencies)} samples")

    empty = sum(1 for _, k, _ in misses if k == "empty")
    clipped = sum(1 for _, k, _ in misses if k == "clipped")
    suspect = sum(1 for _, k, _ in misses if k == "suspect")
    if misses:
        print()
        print(f"  master-side misses: {len(misses)} of {a.cycles} "
              f"({len(misses)/a.cycles*100:.2f} %)")
        print(f"    {empty:4d} empty   — reply fell outside the capture window (rig)")
        print(f"    {clipped:4d} clipped — reply ran into the window end (rig)")
        print(f"    {suspect:4d} suspect — edges well inside the window, still "
              f"undecodable (would implicate the DUT's TX clock)")

    ok_crc = d_crc == 0
    ok_served = d_served == a.cycles
    # A miss whose capture held no edges is our window, not the DUT's clock.
    tx_suspect = suspect
    ok_master = tx_suspect == 0 and errors == 0
    print(f"\n  {'PASS' if ok_crc else 'FAIL'} 30009 moved by {d_crc} "
          f"(FR-S16 requires zero framing/CRC errors)")
    print(f"  {'PASS' if ok_served else 'FAIL'} 30010 moved by {d_served}, "
          f"expected exactly {a.cycles}")
    print(f"  {'PASS' if ok_master else 'FAIL'} no miss implicates the DUT's "
          f"transmit clock ({tx_suspect} captures had edges but would not decode)")
    good = ok_crc and ok_served and ok_master
    print(f"\n{'PASS' if good else 'FAIL'} TP-B35 (FR-S16, FR-MB23)"
          + ("" if a.cycles >= 10000 else
             f"  — PARTIAL: {a.cycles} cycles, the requirement says 10 000"))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
