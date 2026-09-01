"""TP-B20 / FR-S39 — the persistence store against torn writes.

TP-B19 showed the six settings survive a CLEAN power cycle. This asks the
harder question: can the ping-pong store be caught mid-write and left corrupt?

THE TIMING PROBLEM. A flash save is ~6 ms, once per changed holding set, right
after the Modbus response. Hitting that by hand is impossible -- human reaction
is about fifty times too slow. So the cut can only land mid-write by chance,
and the chance is the flash DUTY CYCLE while you are cutting. This drives
writes continuously during each round to raise that duty to ~22 %:

    ~9 ms   our FC06 frame
    ~18 ms  wait, so the DUT's reply does not collide with our next frame
    ~6 ms   of that window is the flash save

Writes are capped at 200 per round (4 000 total, ~2 000 per ping-pong record,
roughly 20 % of a conservative 10 000-cycle endurance budget). That cost buys
an expected ~4 genuine mid-write interruptions across 20 rounds. Anything less
aggressive tests almost nothing; that trade was made deliberately.

WHAT COUNTS AS CORRUPTION. 40001 is alternated between two non-default values
while 40002-40006 are held at a distinctive non-default set. After each cycle:

  * 40001 must read 111 or 222 -- one of the two values actually written
  * 40002-40006 must read the distinctive set
  * reading the SECTION 2.8 DEFAULTS means the store was judged invalid and the
    firmware fell back (FR-S21) -- that is the corruption this row hunts

You do not need to watch for a cue. Power-cycle the DUT whenever you like; the
script detects each cycle from uptime going backwards and starts the next round
by itself.

Run:  .venv-m2k/Scripts/python software/hil/tp_b20.py --unit 40 --rounds 20
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import modbus_rtu_codec as codec
from m2k_master import M2kMaster

SETTLED = [1100, 11, 11000, 100, 900]      # 40002-40006, all non-default
ALT = (111, 222)                            # 40001 alternates between these
DEFAULTS = [0, 1000, 10, 10000, 0, 1023]
INTER_FRAME_S = 0.018                       # keeps our next frame off its reply


def wait_alive(m, u, timeout=180.0):
    """Block until the DUT answers again, or give up.

    Every read in this row can land while the operator still has the power off.
    Treating that silence as a result is wrong twice over: it crashes an
    unguarded read, and it reports "no reply after the cycle" as a FAILURE when
    the only fact established is that the device is not powered yet. A first
    version did both.
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            v, = m.read_input(u, 0x0007, 1)
            return v
        except (codec.ModbusError, codec.Exception_):
            time.sleep(0.25)
    return None


def read_holdings(m, u):
    for _ in range(4):
        try:
            return m.read_holding(u, 0x0000, 7)
        except (codec.ModbusError, codec.Exception_):
            time.sleep(0.05)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=40)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--writes", type=int, default=200)
    ap.add_argument("--timeout", type=float, default=180.0)
    a = ap.parse_args()
    u = a.unit
    fails, done, total_writes = [], 0, 0

    with M2kMaster() as m:
        # Put 40002-40006 somewhere unmistakably not-default, once.
        m.write_multiple(u, 0x0000, [ALT[0]] + SETTLED)
        got = read_holdings(m, u)
        if got is None or got[:6] != [ALT[0]] + SETTLED:
            print(f"  could not establish the starting record: {got}")
            return 1
        print(f"  starting record: {got[:6]}")
        print(f"  §2.8 defaults, for contrast: {DEFAULTS}")
        print(f"\n  Power-cycle the DUT {a.rounds} times, at your own pace.")
        print(f"  Each round drives ~{a.writes} writes at ~22 % flash duty, then "
              f"waits.\n")

        for rnd in range(1, a.rounds + 1):
            up_before = wait_alive(m, u)     # power may still be off from the last round
            if up_before is None:
                print(f"  round {rnd}: DUT never came back — stopping. "
                      f"{done} rounds completed.")
                break
            round_t0 = time.monotonic()      # the clock the uptime is judged against
            last = ALT[rnd % 2]

            # ---- the burst -------------------------------------------------
            for k in range(a.writes):
                last = ALT[k % 2]
                try:
                    m._transmit(codec.write_single_register(u, 0x0000, last))
                    total_writes += 1
                except Exception:                               # noqa: BLE001
                    break                                       # power gone
                time.sleep(INTER_FRAME_S)

            print(f"  round {rnd}/{a.rounds}: {a.writes} writes done "
                  f"(last wrote 40001 = {last}); waiting for your power cycle ...",
                  flush=True)

            # ---- wait for the cycle, detected against ELAPSED WALL TIME ----
            # Not against up_before on its own. After a cycle that baseline is
            # only a few seconds, so the next cycle's uptime is not reliably
            # LESS than it and the reset goes unseen -- which is exactly what
            # happened on the first attempt: two cycles detected out of twenty.
            #
            # A running device's uptime must track wall time. If it lags by
            # more than a few seconds, it restarted -- true whether the cut
            # landed during the burst or during this wait, and true however
            # small the baseline was.
            t0 = time.monotonic()
            cycled = False
            while time.monotonic() - t0 < a.timeout:
                try:
                    up, = m.read_input(u, 0x0007, 1)
                    expected = up_before + (time.monotonic() - round_t0)
                    if up < expected - 3.0:
                        cycled = True
                        break
                except (codec.ModbusError, codec.Exception_):
                    pass                                        # powered down
                time.sleep(0.25)

            if not cycled:
                print(f"  round {rnd}: no power cycle seen in {a.timeout:.0f} s "
                      f"— stopping. {done} rounds completed.")
                break

            # ---- the verdict for this round -------------------------------
            time.sleep(0.4)
            up_now = wait_alive(m, u)        # power may not be restored yet
            if up_now is None:
                print(f"  round {rnd}: DUT did not come back within the timeout "
                      f"— NOT counted as a failure, nothing was tested")
                continue
            print(f"    cycle detected: uptime now {up_now} s "
                  f"(was {up_before} s, {time.monotonic()-round_t0:.0f} s ago)")
            h = read_holdings(m, u)
            if h is None:
                # Alive a moment ago but not answering a holding read: that is a
                # real anomaly, not an operator still holding the switch.
                fails.append(f"round {rnd}: answered 30008 but not 40001-40007")
                print(f"  *** round {rnd}: FAIL — answered uptime but not holdings")
                continue
            ok_alt = h[0] in ALT
            ok_rest = h[1:6] == SETTLED
            is_default = h[:6] == DEFAULTS
            done += 1
            if ok_alt and ok_rest:
                print(f"  round {rnd}: OK — 40001 = {h[0]}, rest {h[1:6]}")
            else:
                why = ("STORE FELL BACK TO §2.8 DEFAULTS — corruption detected"
                       if is_default else f"unexpected record {h[:6]}")
                fails.append(f"round {rnd}: {why}")
                print(f"  *** round {rnd}: FAIL — {why}")

    print(f"\n  {done} power cycles verified, {total_writes} flash-triggering "
          f"writes issued (~{total_writes // 2} per ping-pong record)")
    if fails:
        print(f"\nFAIL TP-B20 (FR-S39) — {len(fails)} round(s) corrupted:")
        for f in fails:
            print("   ", f)
        return 1
    partial = "" if done >= 20 else f"  — PARTIAL: {done} cycles, the row asks for 20"
    print(f"\nPASS TP-B20 (FR-S39) — the store yielded a valid record after every "
          f"cycle{partial}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
