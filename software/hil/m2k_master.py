"""Raw RS-485 Modbus master, bit-banged from an ADALM2000.

Drives a second MAX3485 as the master so the DUT sees a real bus. This is
better than a USB adapter for this project, not a substitute: FR-MB20/21/23
are *timing* requirements, and a USB adapter hides inter-frame timing behind
its own driver's buffering. Here every bit is placed deliberately.

WIRING
    M2K DIO0 (out) ──► DI          on the raw-master MAX3485
    M2K DIO1 (out) ──► DE + R̄Ē
    M2K DIO2 (in)  ◄── RO
    M2K V+         ──► VCC (3.3 V)
    A / B          ──► the DUT bus, and M2K scope 1+/2+ for the wire view
    all grounds common — M2K, Saleae, LinkE, DUT

    NOTE on RO: with DE and R̄Ē tied, the receiver is disabled while we
    transmit, so RO floats during our own frame. That is harmless here — the
    decoder hunts for start bits and the response arrives after DE drops — but
    if you see phantom bytes, fit a pull-up on RO or drive R̄Ē separately.

SETUP (one-time, from software/hil/README.md)
    1. PlutoSDR-M2k-USB-Drivers.exe      (admin)
    2. libm2k-0.9.0-Windows-setup.exe    (admin)
    3. py -3.11 -m venv software/hil/.venv-m2k
       .venv-m2k\\Scripts\\pip install libm2k-0.9.0-cp311-cp311-win_amd64.whl
    Run with that venv's python — libm2k wheels top out at cp311.

The protocol itself lives in `modbus_rtu_codec.py` and is host-tested by
`test_modbus_rtu_codec.py`. Nothing in this file re-implements framing.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import modbus_rtu_codec as codec

try:
    import libm2k
except ImportError:  # pragma: no cover - depends on the venv
    print(__doc__.split("SETUP")[1].split("The protocol")[0])
    raise

# ── Bench constants ─────────────────────────────────────────────────────────
BAUD = 9600
DIO_TX, DIO_DE, DIO_RX = 0, 1, 2

#: Sample rate for both directions. 960 kHz gives exactly 100 samples per bit
#: at 9600 baud, which keeps the codec's mid-bit sampling well clear of edges.
SAMPLE_RATE = 960_000
SAMPLES_PER_BIT = SAMPLE_RATE // BAUD

#: FR-MB23: t3.5 at 9600 8N1 is 4.01 ms. The house gap is 5 ms — a 2.5 ms gap
#: once made the DUT correctly coalesce two frames into one discarded frame,
#: which is a genuinely confusing failure to debug.
T35_S = 3.5 * 11 / BAUD
HOUSE_GAP_S = 0.005

#: How long to listen after releasing the bus. Generous: a 15-register FC04
#: response is 35 bytes ≈ 40 ms at 9600, plus turnaround.
RESPONSE_WINDOW_S = 0.25


class M2kMaster:
    """Half-duplex Modbus RTU master on M2K digital I/O.

    Use as a context manager — the M2K keeps driving its outputs after a
    process exits, and leaving DE asserted holds the bus hostage.
    """

    def __init__(self, uri: str | None = None, verbose: bool = False):
        self.verbose = verbose
        contexts = libm2k.getAllContexts()
        if not contexts:
            raise RuntimeError(
                "no ADALM2000 found. Drivers installed? Device plugged in? "
                "Try m2k_smoke.py first.")
        self.ctx = libm2k.m2kOpen(uri or contexts[0])
        if self.ctx is None:
            raise RuntimeError(f"m2kOpen failed for {uri or contexts[0]}")
        self.dig = self.ctx.getDigital()
        self.ps = self.ctx.getPowerSupply()

    # ── lifecycle ──────────────────────────────────────────────────────────
    def __enter__(self) -> "M2kMaster":
        self.setup()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def setup(self) -> None:
        """Bring up V+ and the DIO lines. Idle state: TX high, DE low."""
        # THE classic failure: an unpowered MAX3485 sits inert and looks
        # exactly like a wiring fault. Every script must do this itself.
        self.ps.enableChannel(0, True)
        self.ps.pushChannel(0, 3.3)

        for ch in (DIO_TX, DIO_DE):
            self.dig.setDirection(ch, libm2k.DIO_OUTPUT)
            self.dig.setOutputMode(ch, libm2k.DIO_PUSHPULL)
            self.dig.enableChannel(ch, True)
        self.dig.setDirection(DIO_RX, libm2k.DIO_INPUT)
        self.dig.enableChannel(DIO_RX, True)

        self.dig.setSampleRateOut(SAMPLE_RATE)
        self.dig.setSampleRateIn(SAMPLE_RATE)
        self.dig.setCyclic(False)

        self.dig.setValueRaw(DIO_TX, libm2k.HIGH)   # idle mark
        self.dig.setValueRaw(DIO_DE, libm2k.LOW)    # receiver, not driver
        time.sleep(0.01)

    def close(self) -> None:
        try:
            self.dig.setValueRaw(DIO_DE, libm2k.LOW)   # always release the bus
            self.dig.setValueRaw(DIO_TX, libm2k.HIGH)
            self.ps.enableChannel(0, False)
        finally:
            libm2k.contextClose(self.ctx, True)

    # ── the ten-second proof the rig is alive ──────────────────────────────
    def selftest(self) -> None:
        """Static DE/DI exercise: drive space, drive mark, release.

        Watch A/B on the scope. Space and mark should differ by ~2 V
        differential; released should collapse to the bias level. If nothing
        moves, V+ is not reaching the transceiver — check that before
        suspecting anything else.
        """
        for label, de, tx in (("drive space", libm2k.HIGH, libm2k.LOW),
                              ("drive mark ", libm2k.HIGH, libm2k.HIGH),
                              ("released   ", libm2k.LOW, libm2k.HIGH)):
            self.dig.setValueRaw(DIO_DE, de)
            self.dig.setValueRaw(DIO_TX, tx)
            print(f"  {label}  DE={'H' if de == libm2k.HIGH else 'L'} "
                  f"DI={'H' if tx == libm2k.HIGH else 'L'}")
            time.sleep(1.0)
        self.dig.setValueRaw(DIO_DE, libm2k.LOW)
        self.dig.setValueRaw(DIO_TX, libm2k.HIGH)

    # ── transport ──────────────────────────────────────────────────────────
    def _word(self, tx: int, de: int) -> int:
        return (tx << DIO_TX) | (de << DIO_DE)

    def _transmit(self, frame: bytes) -> None:
        """Push one frame with DE asserted, then release and hold the gap."""
        lead = int(0.0005 * SAMPLE_RATE)          # DE settle before the start bit
        bits = codec.encode_uart(frame, SAMPLES_PER_BIT)
        buf = [self._word(1, 1)] * lead
        buf += [self._word(b, 1) for b in bits]
        buf += [self._word(1, 1)] * lead          # hold the stop bit, still driving
        buf += [self._word(1, 0)] * int(HOUSE_GAP_S * SAMPLE_RATE)  # release + t3.5
        self.dig.push(buf)

    def _receive(self) -> bytes:
        n = int(RESPONSE_WINDOW_S * SAMPLE_RATE)
        raw = self.dig.getSamples(n)
        line = [(w >> DIO_RX) & 1 for w in raw]
        return codec.decode_uart(line, SAMPLES_PER_BIT)

    def transact(self, request: bytes, unit: int, function: int,
                 retry_on_crc: bool = True) -> list[int]:
        """Send a request, return the decoded registers.

        Retries once on a CRC error by default. That is not superstition: a
        listening master accumulates every byte another node puts on the shared
        bus and then parses the stale backlog. One throwaway read IS the flush.
        """
        attempts = 2 if retry_on_crc else 1
        last: Exception | None = None
        for attempt in range(attempts):
            self._transmit(request)
            reply = self._receive()
            if self.verbose:
                print(f"    -> {request.hex(' ')}")
                print(f"    <- {reply.hex(' ') or '(silence)'}")
            try:
                return codec.parse_response(reply, unit, function)
            except codec.ModbusError as e:
                last = e
                if attempt + 1 < attempts:
                    time.sleep(HOUSE_GAP_S)
                    continue
                raise
        raise last  # pragma: no cover

    # ── the four function codes this device implements ─────────────────────
    def read_input(self, unit: int, start: int, count: int) -> list[int]:
        return self.transact(codec.read_input_registers(unit, start, count),
                             unit, codec.FC_READ_INPUT)

    def read_holding(self, unit: int, start: int, count: int) -> list[int]:
        return self.transact(codec.read_holding_registers(unit, start, count),
                             unit, codec.FC_READ_HOLDING)

    def write_single(self, unit: int, reg: int, value: int) -> None:
        self.transact(codec.write_single_register(unit, reg, value),
                      unit, codec.FC_WRITE_SINGLE)

    def write_multiple(self, unit: int, start: int, values: list[int]) -> None:
        self.transact(codec.write_multiple_registers(unit, start, values),
                      unit, codec.FC_WRITE_MULTIPLE)

    def send_raw(self, frame: bytes) -> bytes:
        """Put arbitrary bytes on the wire and return whatever comes back.

        For the negative rows: deliberately bad CRC (TP-B12), unknown register
        (TP-B13), frames for another unit (TP-B11).
        """
        self._transmit(frame)
        return self._receive()


def main() -> int:
    """Bring-up check: open, configure, exercise DE/DI, poll the DUT."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--unit", type=int, default=40,
                    help="Modbus address: 40 jumper open, 45 bridged")
    ap.add_argument("--selftest", action="store_true",
                    help="static DE/DI exercise only — no bus traffic")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    with M2kMaster(verbose=args.verbose) as m:
        print(f"M2K up. {SAMPLE_RATE} Sa/s, {SAMPLES_PER_BIT} samples/bit at "
              f"{BAUD} baud, t3.5 = {T35_S * 1000:.2f} ms, "
              f"gap = {HOUSE_GAP_S * 1000:.0f} ms")
        if args.selftest:
            print("static DE/DI exercise — watch A/B on the scope:")
            m.selftest()
            return 0

        print(f"\npolling unit {args.unit} ...")
        try:
            ident = m.read_input(args.unit, 0x0006, 1)[0]
            print(f"  30007 identification = {ident:#06x} "
                  f"(build {ident >> 8:#04x}, fw {ident & 0xFF})")
            regs = m.read_input(args.unit, 0x0000, 15)
            for i, v in enumerate(regs):
                print(f"  {30001 + i}  {v:>5}  {v:#06x}")
        except codec.Exception_ as e:
            print(f"  DUT answered with an exception: {e}")
        except codec.ModbusError as e:
            print(f"  no usable reply: {e}")
            print("  If this is silence: run --selftest first. An unpowered")
            print("  MAX3485 is inert and looks identical to a wiring fault.")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
