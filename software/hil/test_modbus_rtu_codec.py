"""Host tests for modbus_rtu_codec — no instrument, no DUT.

Run: python software/hil/test_modbus_rtu_codec.py

These cover the parts most likely to be subtly wrong and least likely to
announce it: CRC byte order, big-endian register data, LSB-first UART bits,
and exception decoding. A frame with the CRC bytes swapped is silently
discarded by the DUT and looks exactly like a wiring fault, which is an
expensive thing to debug on a bench.
"""
import random
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])

import modbus_rtu_codec as m

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name:<52} {got!r}")
    if not ok:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


# ── CRC, cross-checked against an independently written implementation ──────
def crc16_table_driven(data: bytes) -> int:
    """Deliberately a different algorithm from the one under test: build a
    nibble table and walk it. If both agree over random data, neither is
    carrying a loop-order or shift-direction mistake."""
    tbl = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
        tbl.append(c)
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ tbl[(crc ^ b) & 0xFF]
    return crc


random.seed(20260808)
mismatch = next((d for d in
                 (bytes(random.randrange(256) for _ in range(random.randrange(1, 40)))
                  for _ in range(2000))
                 if m.crc16(d) != crc16_table_driven(d)), None)
check("CRC agrees with an independent implementation (2000 vectors)",
      mismatch, None)

# A published vector, to catch both implementations being wrong together.
# "01 03 00 00 00 0A" is the classic Modbus example; the frame goes out as
# 01 03 00 00 00 0A C5 CD, i.e. CRC 0xCDC5 sent low byte first.
VECTOR = bytes.fromhex("01030000000A")
check("published vector: CRC of 01 03 00 00 00 0A is 0xCDC5",
      f"{m.crc16(VECTOR):#06x}", "0xcdc5")
check("published vector: transmitted as ... C5 CD",
      m.append_crc(VECTOR)[-2:].hex(" "), "c5 cd")

# ── byte order: FR-MB25 ─────────────────────────────────────────────────────
frame = m.read_input_registers(unit=40, start=0x000E, count=1)
check("request is unit,fc,start_hi,start_lo,count_hi,count_lo",
      frame[:6].hex(" "), "28 04 00 0e 00 01")
crc = m.crc16(frame[:-2])
check("CRC appended LITTLE-endian (low byte first)",
      (frame[-2], frame[-1]), (crc & 0xFF, crc >> 8))
check("register data is BIG-endian in the request",
      m.write_single_register(40, 0x0001, 0x0BB8)[2:6].hex(" "), "00 01 0b b8")

# ── round trips ─────────────────────────────────────────────────────────────
for name, req in (("FC04 read input", m.read_input_registers(40, 0, 15)),
                  ("FC03 read holding", m.read_holding_registers(45, 0, 7)),
                  ("FC06 write single", m.write_single_register(40, 3, 10000)),
                  ("FC16 write multiple",
                   m.write_multiple_registers(40, 4, [0, 1023]))):
    check(f"{name}: own CRC verifies", m.crc_ok(req), True)

# A synthetic FC04 response carrying three registers
body = bytes((40, 0x04, 6)) + bytes((0x00, 0x60, 0x01, 0x91, 0x02, 0xAE))
check("FC04 response decodes to registers",
      m.parse_response(m.append_crc(body), 40, m.FC_READ_INPUT),
      [0x0060, 0x0191, 0x02AE])

# ── failure modes ───────────────────────────────────────────────────────────
bad = bytearray(m.append_crc(body)); bad[-1] ^= 0xFF
try:
    m.parse_response(bytes(bad), 40, m.FC_READ_INPUT); got = "no error"
except m.ModbusError: got = "ModbusError"
except m.Exception_: got = "Exception_"
check("corrupted CRC raises ModbusError", got, "ModbusError")

exc = m.append_crc(bytes((40, 0x04 | 0x80, 0x02)))
try:
    m.parse_response(exc, 40, m.FC_READ_INPUT); got = "no error"
except m.Exception_ as e: got = e.code
except m.ModbusError: got = "ModbusError"
check("exception response raises Exception_ with the code (not ModbusError)",
      got, 2)

try:
    m.parse_response(m.append_crc(bytes((41, 0x04, 0))), 40, m.FC_READ_INPUT)
    got = "no error"
except m.ModbusError: got = "ModbusError"
check("response from the wrong unit raises ModbusError", got, "ModbusError")

# ── UART 8N1 codec ──────────────────────────────────────────────────────────
SPB = 8
wave = m.encode_uart(b"\x55", SPB)
check("one byte is 10 bit times (start + 8 + stop)", len(wave), 10 * SPB)
check("line starts with a start bit (low)", wave[0], 0)
check("line ends with a stop bit (high)", wave[-1], 1)
check("0x55 goes out LSB-first: 1,0,1,0,1,0,1,0",
      [wave[(b + 1) * SPB] for b in range(8)], [1, 0, 1, 0, 1, 0, 1, 0])

payload = m.read_input_registers(40, 0, 15)
check("UART round-trip of a whole frame",
      m.decode_uart(m.encode_uart(payload, SPB, idle_before=20, idle_after=20), SPB),
      payload)

random.seed(7)
blob = bytes(random.randrange(256) for _ in range(64))
check("UART round-trip, 64 random bytes",
      m.decode_uart(m.encode_uart(blob, 16, idle_before=5), 16), blob)
# A capture that begins part-way through a character mis-frames once and then
# resyncs — exactly what a real UART receiver does. Expecting perfect recovery
# would be expecting something no receiver can deliver.
mid = m.decode_uart(m.encode_uart(b"\xAA\xBB\xCC", SPB)[3 * SPB:], SPB)
check("capture starting mid-character resyncs by the end", mid[-1:], b"\xcc")
check("...and a capture starting in idle is exact",
      m.decode_uart(m.encode_uart(b"\xAA\xBB\xCC", SPB, idle_before=13), SPB),
      b"\xaa\xbb\xcc")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    for f in FAILS:
        print("   ", f)
    sys.exit(1)
print("all codec tests pass")
