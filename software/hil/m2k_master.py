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
RESPONSE_WINDOW_S = 0.12

#: DE is asserted this long before the first start bit and held this long after
#: the last stop bit. Shared by _transmit and response_latency_s — the latency
#: measurement subtracts it to recover the instant our last stop bit ended, so
#: the two must not drift apart.
LEAD_SAMPLES = int(0.0005 * SAMPLE_RATE)


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
    def selftest(self) -> bool:
        """Drive space, drive mark, release — and **measure** A/B each time.

        Requires the bus on M2K scope 1+/2+. Returns True on pass.

        Three checks. The third is the one that matters and the one an earlier
        version of this file did not make:

        1. **The driver drives.** |differential| >= MIN_DIFF_V when asserted.
           If this fails, V+ is not reaching the transceiver — an unpowered
           MAX3485 is inert and looks exactly like a wiring fault.
        2. **The polarity inverts.** Mark and space must have *opposite* signs.
        3. **The driver releases.** On DE low the differential must collapse to
           well under the driven level. A transceiver whose DE is stuck high
           passes checks 1 and 2 perfectly while driving the bus continuously —
           contending with every reply and, since R̄Ē is tied to DE, never
           receiving one. That fault cost a full session on 2026-09-01: the
           released differential sat 44 mV from the driven one and the test,
           which only compared mark against space, reported success.

        Polarity is derived, not assumed: **A is whichever line is high during
        mark** (RS-485 idle/mark is A > B). So a swapped probe pair is reported
        rather than failed, and a genuinely crossed bus shows up as an idle
        bias that disagrees with mark.
        """
        MIN_DIFF_V = 1.0        # a 3.3 V MAX3485 into a loaded bus
        RELEASE_RATIO = 0.5     # released must be at most half the driven level

        ain = self.ctx.getAnalogIn()
        self.ctx.calibrateADC()
        for ch in (0, 1):
            ain.enableChannel(ch, True)
            ain.setRange(ch, libm2k.PLUS_MINUS_25V)
        ain.setSampleRate(100_000)

        def measure(de: int, tx: int) -> tuple[float, float]:
            self.dig.setValueRaw(DIO_DE, de)
            self.dig.setValueRaw(DIO_TX, tx)
            time.sleep(0.3)
            # DISCARD THE FIRST BUFFER. libm2k's analog input is buffered, and
            # the first getSamples() after a state change can hand back the
            # buffer that was in flight before it — so a single read reports
            # the PREVIOUS state. That is not academic: with one read per
            # state, `released` came back bit-identical to `drive mark`
            # (0.817 V / 2.138 V, to three decimals) on 2026-09-01 and the
            # test spent an hour accusing the rig of a fault it did not have.
            # Identical values to three decimals are a repeated buffer, not a
            # measurement.
            ain.getSamples(4000)
            s = ain.getSamples(4000)
            mid = lambda v: sorted(v)[len(v) // 2]
            return mid(s[0]), mid(s[1])

        states = {}
        print(f"  {'state':<14}{'ch0':>9}{'ch1':>9}{'ch0-ch1':>10}")
        for label, de, tx in (("drive space", libm2k.HIGH, libm2k.LOW),
                              ("drive mark", libm2k.HIGH, libm2k.HIGH),
                              ("released", libm2k.LOW, libm2k.HIGH)):
            c0, c1 = measure(de, tx)
            states[label] = c0 - c1
            print(f"  {label:<14}{c0:>8.3f}V{c1:>8.3f}V{c0 - c1:>9.3f}V")
        self.dig.setValueRaw(DIO_DE, libm2k.LOW)
        self.dig.setValueRaw(DIO_TX, libm2k.HIGH)

        space, mark, idle = (states["drive space"], states["drive mark"],
                             states["released"])
        driven = max(abs(space), abs(mark))
        a_is = "ch1" if mark < 0 else "ch0"      # A is high during mark

        checks = [
            ("driver drives", driven >= MIN_DIFF_V,
             f"{driven:.3f} V >= {MIN_DIFF_V} V"),
            ("polarity inverts between mark and space",
             (space > 0) != (mark > 0),
             f"space {space:+.3f} V, mark {mark:+.3f} V"),
            ("driver RELEASES on DE low", abs(idle) <= RELEASE_RATIO * driven,
             f"idle {abs(idle):.3f} V <= {RELEASE_RATIO:.0%} of {driven:.3f} V"),
        ]
        print()
        for name, ok, detail in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name:<42} {detail}")

        print(f"\n  A is {a_is} (the line high during mark); "
              f"idle bias is {'mark' if (idle < 0) == (mark < 0) else 'SPACE'} "
              f"polarity at {abs(idle) * 1000:.0f} mV")
        if abs(idle) > 0.001 and (idle < 0) != (mark < 0):
            print("  ^ idle bias opposes mark: the bias network is backwards, "
                  "or A/B are crossed between master and DUT.")
        return all(ok for _, ok, _ in checks)

    # ── transport ──────────────────────────────────────────────────────────
    def _word(self, tx: int, de: int) -> int:
        return (tx << DIO_TX) | (de << DIO_DE)

    def _transmit(self, frame: bytes) -> None:
        """Push one frame with DE asserted, then release and hold the gap."""
        lead = LEAD_SAMPLES                       # DE settle before the start bit
        bits = codec.encode_uart(frame, SAMPLES_PER_BIT)
        buf = [self._word(1, 1)] * lead
        buf += [self._word(b, 1) for b in bits]
        buf += [self._word(1, 1)] * lead          # hold the stop bit, still driving
        buf += [self._word(1, 0)] * int(HOUSE_GAP_S * SAMPLE_RATE)  # release + t3.5
        self.dig.push(buf)

    def _exchange(self, frame: bytes) -> bytes:
        """Transmit and capture the reply, as one operation.

        The capture is armed BEFORE the push. Capturing afterwards loses the
        head or the tail of the reply depending on how long push() blocks:
        with a capture started after the fact, a 15-register response came back
        truncated four bytes early while a 1-register one survived, which reads
        like a protocol fault and is not one.
        """
        n = int(RESPONSE_WINDOW_S * SAMPLE_RATE)
        self.dig.startAcquisition(n)
        try:
            self._transmit(frame)
            raw = self.dig.getSamples(n)
        finally:
            self.dig.stopAcquisition()
        line = [(w >> DIO_RX) & 1 for w in raw]
        # Keep the sample stream. Response latency (FR-MB20/21) has to be
        # measured from edges, not inferred from when Python got the bytes —
        # and when a frame does not decode, the raw line is the only honest
        # evidence of what was on the wire. The full words are kept too: DE is
        # captured on the same timebase as RX, which is the only exact way to
        # know when our own transmission ended.
        self.last_capture = line
        self.last_capture_raw = raw
        return codec.decode_uart(line, SAMPLES_PER_BIT)

    def response_latency_s(self, frame_len: int) -> dict | None:
        """Seconds from the end of our last stop bit to the reply's first edge.

        Returns a dict with `latency_s` and `de_width_error_s`, or None with
        `self.last_latency_note` explaining why it could not be measured.
        `frame_len` is the length in bytes of the frame we sent.

        **Measured against DE, not against our own frame on RX.** R̄Ē is tied to
        DE, so the DUT's receiver is disabled while we transmit and our frame
        does not appear on RO at all. An earlier version tried to locate our
        last stop bit from the RX line and was wrong on every one of 1000
        samples, because the first edge in the capture is RO's enable transient
        rather than our first start bit. DE is captured on the same timebase in
        the same acquisition and we drive it ourselves, so

            our last stop bit ends at (DE falling edge) - LEAD_SAMPLES

        with nothing inferred. The DE **pulse width** is then the check that the
        readback means what it is assumed to mean: it must equal
        2*LEAD_SAMPLES + ten bit times per byte sent, or the capture is not
        showing our driven DE and no number is returned.

        The reply is the first RX falling edge after that instant which is still
        low half a bit later — a real start bit. RO's enable transient sits at
        the DE edge and is far too short to qualify.
        """
        self.last_latency_note = ""
        raw = getattr(self, "last_capture_raw", None)
        if raw is None or not len(raw):
            self.last_latency_note = "no capture"
            return None
        rx = [(w >> DIO_RX) & 1 for w in raw]
        de = [(w >> DIO_DE) & 1 for w in raw]

        rises = [i for i in range(1, len(de)) if not de[i - 1] and de[i]]
        falls = [i for i in range(1, len(de)) if de[i - 1] and not de[i]]
        de_fall = next((f for f in falls if rises and f > rises[0]), None)
        if not rises or de_fall is None:
            self.last_latency_note = (
                "DE does not toggle in the capture — the M2K is not reading back "
                "its own output pin, so FR-MB20 cannot be measured this way")
            return None

        expected = 2 * LEAD_SAMPLES + 10 * SAMPLES_PER_BIT * frame_len
        width_err = abs((de_fall - rises[0]) - expected)
        if width_err > SAMPLES_PER_BIT:
            self.last_latency_note = (
                f"DE pulse {de_fall - rises[0]} samples, expected {expected} for "
                f"{frame_len} bytes — the readback is not our driven DE")
            return None

        our_end = de_fall - LEAD_SAMPLES
        half = SAMPLES_PER_BIT // 2
        reply = next((i for i in range(our_end + 1, len(rx) - half)
                      if rx[i - 1] and not rx[i] and not rx[i + half]), None)
        if reply is None:
            self.last_latency_note = "no start bit after we released the bus"
            return None
        return {"latency_s": (reply - our_end) / SAMPLE_RATE,
                "de_width_error_s": width_err / SAMPLE_RATE}

    @staticmethod
    def _extract(data: bytes, unit: int) -> bytes:
        """Pick a well-formed frame out of a decoded byte stream.

        Needed because the receiver is enabled by the same signal that stops
        the driver, so RO's enable transient regularly decodes as a leading
        null. Rather than blindly stripping a byte, find the span that starts
        with our unit address and carries a valid CRC — that also survives
        trailing noise and another node's traffic on a shared bus.
        """
        for start in range(len(data)):
            if data[start] != unit:
                continue
            for end in range(start + 4, len(data) + 1):
                if codec.crc_ok(data[start:end]):
                    return data[start:end]
        return data          # nothing valid — hand it all back for the error

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
            raw = self._exchange(request)
            reply = self._extract(raw, unit)
            if self.verbose:
                print(f"    -> {request.hex(' ')}")
                print(f"    <- {reply.hex(' ') or '(silence)'}"
                      + (f"   [from {raw.hex(' ')}]" if raw != reply else ""))
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
        return self._exchange(frame)


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
            print("measured DE/DI exercise (bus on scope 1+/2+):")
            if not m.selftest():
                print("\nSELFTEST FAILED — fix the rig before trusting any "
                      "Group B result. Nothing downstream is meaningful until "
                      "this passes.")
                return 1
            print("\nSELFTEST PASSED — transceiver powered, driving, and "
                  "releasing.")
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
