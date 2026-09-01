"""Modbus RTU framing and 8N1 UART bit codec — pure Python, no instrument.

Split out from the M2K transport deliberately, the same way `scale.c` is split
from the firmware: everything here can be tested on the host, and the parts
most likely to be subtly wrong (CRC byte order, LSB-first bit order, exception
decoding) are proven before any hardware is connected.

The transport lives in `m2k_master.py` and imports this.

Reference: TDS §2 (FR-MB01…FR-MB30). Note FR-MB25 in particular — **data is
big-endian, the CRC is little-endian**. Getting that backwards produces frames
a DUT silently discards, which looks exactly like a wiring fault.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Modbus RTU constants ────────────────────────────────────────────────────
FC_READ_HOLDING = 0x03
FC_READ_INPUT = 0x04
FC_WRITE_SINGLE = 0x06
FC_WRITE_MULTIPLE = 0x10

EXCEPTION_TEXT = {
    1: "ILLEGAL FUNCTION",
    2: "ILLEGAL DATA ADDRESS",
    3: "ILLEGAL DATA VALUE",
    4: "SLAVE DEVICE FAILURE",
}


class ModbusError(Exception):
    """Protocol-level failure: exception response, bad CRC, short frame."""


@dataclass
class Exception_(Exception):
    """A well-formed exception response — not a transport failure."""

    function: int
    code: int

    def __str__(self) -> str:
        return (f"exception {self.code} "
                f"({EXCEPTION_TEXT.get(self.code, 'unknown')}) "
                f"to function {self.function:#04x}")


# ── CRC-16 (Modbus): poly 0xA001 reflected, init 0xFFFF ─────────────────────
def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def append_crc(pdu: bytes) -> bytes:
    """Append the CRC **little-endian** — low byte first (FR-MB25)."""
    crc = crc16(pdu)
    return pdu + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def crc_ok(frame: bytes) -> bool:
    return len(frame) >= 3 and crc16(frame[:-2]) == (frame[-1] << 8 | frame[-2])


# ── Request builders ────────────────────────────────────────────────────────
def _u16(v: int) -> bytes:
    """Big-endian, per FR-MB25."""
    return bytes(((v >> 8) & 0xFF, v & 0xFF))


def read_input_registers(unit: int, start: int, count: int) -> bytes:
    return append_crc(bytes((unit, FC_READ_INPUT)) + _u16(start) + _u16(count))


def read_holding_registers(unit: int, start: int, count: int) -> bytes:
    return append_crc(bytes((unit, FC_READ_HOLDING)) + _u16(start) + _u16(count))


def write_single_register(unit: int, reg: int, value: int) -> bytes:
    return append_crc(bytes((unit, FC_WRITE_SINGLE)) + _u16(reg) + _u16(value))


def write_multiple_registers(unit: int, start: int, values: list[int]) -> bytes:
    body = _u16(start) + _u16(len(values)) + bytes((len(values) * 2,))
    for v in values:
        body += _u16(v)
    return append_crc(bytes((unit, FC_WRITE_MULTIPLE)) + body)


# ── Response parsing ────────────────────────────────────────────────────────
def parse_response(frame: bytes, unit: int, function: int) -> list[int]:
    """Return the register values, or raise.

    Raises Exception_ for a well-formed exception response and ModbusError for
    anything malformed. The distinction matters: an exception is the DUT
    working correctly (TP-B08, TP-B13 depend on getting one), a ModbusError is
    the link failing.
    """
    if len(frame) < 4:
        raise ModbusError(f"short frame ({len(frame)} bytes): {frame.hex(' ')}")
    if not crc_ok(frame):
        raise ModbusError(f"bad CRC: {frame.hex(' ')}")
    if frame[0] != unit:
        raise ModbusError(f"wrong unit {frame[0]}, expected {unit}")

    fc = frame[1]
    if fc == (function | 0x80):
        raise Exception_(function, frame[2])
    if fc != function:
        raise ModbusError(f"wrong function {fc:#04x}, expected {function:#04x}")

    if function in (FC_READ_INPUT, FC_READ_HOLDING):
        n = frame[2]
        if len(frame) != 3 + n + 2:
            raise ModbusError(f"byte count {n} disagrees with frame length "
                              f"{len(frame)}")
        data = frame[3:3 + n]
        return [data[i] << 8 | data[i + 1] for i in range(0, n, 2)]
    # FC06 echoes the request; FC16 echoes address and count. Neither carries
    # register data, so an empty list is the honest return.
    return []


# ── 8N1 UART, as a sample stream ────────────────────────────────────────────
def encode_uart(data: bytes, samples_per_bit: int,
                idle_before: int = 0, idle_after: int = 0) -> list[int]:
    """One byte -> start(0), 8 data bits LSB-FIRST, stop(1). Idle line is 1."""
    out: list[int] = [1] * idle_before
    for byte in data:
        out += [0] * samples_per_bit                       # start
        for bit in range(8):                               # LSB first
            out += [(byte >> bit) & 1] * samples_per_bit
        out += [1] * samples_per_bit                       # stop
    return out + [1] * idle_after


def decode_uart(samples: list[int], samples_per_bit: int) -> bytes:
    """Recover bytes from a sample stream, sampling each bit at its midpoint.

    Resynchronises on the falling edge of **every** start bit, as a real UART
    receiver does. Advancing a fixed ten bit times per character instead looks
    correct and works on short frames, but lets any baud difference accumulate:
    the CH32V003 transmits 0.8 % fast (measured 9.92 bit times per character on
    2026-09-01), which is nothing across a 7-byte reply and a whole bit time
    across a 35-byte one. The long frames then lost characters to framing
    errors while the short ones decoded perfectly — a failure that reads like a
    truncated response and is not one.

    Tolerates a capture that begins part-way through a frame; that character is
    lost and the next start edge recovers alignment.
    """
    out = bytearray()
    i, n, half = 0, len(samples), samples_per_bit // 2
    while i < n:
        # A start bit is a FALLING edge, not merely a low sample. Requiring the
        # edge stops the hunt from locking onto the middle of a long low run.
        if samples[i] != 0 or (i and samples[i - 1] != 1):
            i += 1
            continue
        # Bound by the last sample actually read — the stop-bit midpoint at 9.5
        # bit times, not a full 10. Demanding 10 discards the final character of
        # any frame from a fast transmitter that is not followed by idle.
        if i + 9 * samples_per_bit + half >= n:
            break
        if samples[i + half] != 0:          # glitch, not a start bit
            i += 1
            continue
        byte = 0
        for bit in range(8):
            centre = i + (bit + 1) * samples_per_bit + half
            byte |= (samples[centre] & 1) << bit
        if samples[i + 9 * samples_per_bit + half] != 1:   # framing error
            i += 1
            continue
        out.append(byte)
        # Land in the middle of the stop bit and hunt forward for the next
        # falling edge. Nominal mid-stop is 9.5 bit times in, and the real stop
        # bit spans 9r..10r for a baud ratio r, so this holds alignment for
        # r in 0.95..1.055 — the usual +/-5 % UART tolerance, per character
        # rather than per frame.
        i += 9 * samples_per_bit + half
    return bytes(out)


def split_frames(data: bytes, gaps: list[int], t35_bits: float = 3.5) -> list[bytes]:
    """Split a byte stream into frames on gaps of >= t3.5 bit times.

    `gaps[i]` is the idle bit-times *before* byte i. Modbus RTU has no framing
    other than silence, which is why FR-MB23 exists and why the raw master must
    respect the 5 ms house gap (see m2k_master).
    """
    if not data:
        return []
    frames, current = [], bytearray([data[0]])
    for i in range(1, len(data)):
        if gaps[i] >= t35_bits:
            frames.append(bytes(current))
            current = bytearray()
        current.append(data[i])
    frames.append(bytes(current))
    return frames
