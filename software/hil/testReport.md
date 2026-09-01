# HIL Test Report

Consolidated record of every hardware-in-the-loop test executed against
this project's device under test: setup, expected result, pass criteria,
and verdict.

| Field | Value |
|---|---|
| Project | `wire-encoder-modbus-interface` |
| Last updated | 2026-08-08 |
| DUT | **Breadboard build.** CH32V003J4M6, MAX3485, 3RG4023-3AB00 ×2, draw-wire front-end. No PCB. |
| Plan | [`design/testPlan.md`](../../design/testPlan.md) v0.1 |

---

## Status: Group A opened, 2 rows executed, Modbus link up

Hardware exists and has been exercised. What follows is what was actually
run — everything else in the plan is still untouched.

### Executed

| Row | Date | Result |
|---|---|---|
| — | 2026-08-08 | **Debug link verified.** WCH-LinkE `mode:RV version 2.15`; target examined, `XLEN=32`, `misa=0x40800014` (RV32EC + vendor) — the expected silicon. Reached via OpenOCD, not minichlink: the `WCHLink_A64` driver blocks libusb (`LIBUSB_ERROR_ACCESS`), and `upload_protocol = wch-link` routes through OpenOCD anyway, so no Zadig/WinUSB step is needed. |
| — | 2026-08-08 | **Firmware flashed.** `encoder` build byte `0x01`, 3 704 B flash / 620 B RAM. `** Verified OK **`. |
| **TP-A00** | 2026-08-08 | **PASS, on the fourth attempt.** −20 mV with both sensor outputs disconnected. It failed three times first, and each failure was a real fault it was written to catch: **R10 still fitted**, **R5 floating**, a third wiring error, and finally **the MCU's internal pull-up on PC4** (~47 kΩ to 3V3, sourcing ~63 µA into the summing node) left enabled by the image previously in flash. |
| **TP-A02** | 2026-08-08 | **PASS.** Bands at `Von` = 23.09 V: **−0.019 V / 1.291 V / 2.210 V** = **0 / 401 / 686 counts**. `Von` confirmed by three independent routes agreeing to **0.2 %** — each switch alone, and both together (which carries no leakage term). Rail 24.1 V. |
| **TP-A01** | 2026-08-08 | **WITHDRAWN.** Written to characterise a 33 µA sensor leakage that turned out not to exist — it was the PC4 pull-up. Connecting or disconnecting both sensors moves PC4 by 0.9 mV. |
| — | 2026-08-08 | **First Modbus transaction.** DUT answered at unit 40, 9600 8N1. `30007 = 0x0101` (build `0x01`, firmware 1) and a full 15-register FC04 read. See below. |

### Modbus link brought up

Three faults stood between a correctly flashed DUT and a first reply. Only the
first was on the DUT's side of the wire, and none of them was the DUT.

1. **No fail-safe bias — the receiver had no defined idle state.** The DUT's
   `served`, `crc_errors` and `rx_len` counters all read 0 after ten frames,
   and `GPIOD_IDR = 0xB2` put **PD6 low** — the RX line sitting at space, not
   idle mark. Idle differential measured **−0.011 V** against the ≥200 mV a
   receiver needs to resolve. Forcing DE high proved the DUT's transceiver
   drove the bus correctly, so the fault was the bias network, not the part.
   Arithmetic located it: `3.3 × RL/(40 000 + RL) = 0.011` gives RL ≈ 133 Ω,
   i.e. a ~120 Ω termination the 20 kΩ bias pair could not pull against.
   **Fix (bench):** termination removed, bias changed to 680 Ω. Idle
   differential is now **+258 mV** and the master selftest passes all three
   checks.
2. **A leading null on every reply.** With DE and R̄Ē tied on the raw master,
   RO floats while we transmit and its enable transient decodes as one spurious
   byte. Cured in software: the master now hunts for the span that starts with
   the expected unit address *and* carries a valid CRC, rather than assuming
   the first byte received is the first byte of the response.
3. **Long replies lost characters; short ones did not.** A 7-byte
   identification reply decoded perfectly while a 35-byte register read came
   back four bytes short — which reads as a truncated response and is not one.
   The capture held **61.8 ms of idle after the last edge**, so nothing was
   truncated. Run-length measurement on the RX line showed **9.92 bit times per
   character**: the DUT transmits **0.8 % fast**, well inside UART tolerance.
   The decoder was at fault — it advanced a fixed ten bit times per character
   instead of resynchronising on each start edge, so the error accumulated to a
   whole bit time across a long frame. Now resyncs per character; regression
   tests cover a 35-byte frame at ±1 % baud, including the all-zeros case where
   the stop bit is the only edge to lock to.

**Measured:** DUT UART **0.8 % fast** at 9600 (9.92 bit times per character,
960 kSa/s capture). Evidence for FR-MB20 when TP-B15 runs.

**First full read**, unit 40, FC04, 15 registers:

| Register | Value | Reading |
|---|---|---|
| 30006 status | `0x0013` | bits 0+1 (no window published yet) and bit 4 (switch fail-safe until the first ladder sample) — all three correct for integration stage D being absent |
| 30007 identification | `0x0101` | build `0x01`, firmware 1 — matches `platformio.ini` and FR-S32 |
| 30008 uptime | 42 588 s | 11 h 49 m, powered since the flash |
| **30009 CRC errors** | **0** | **every frame the DUT received was well-formed** |
| 30010 served | 10 | our transactions, all answered |
| 30011 reading age | 42 588 s | nothing ever published — stage D, as expected |
| 30001–30005, 30012 | 0 | no measurement path yet |

The zero CRC-error count is the load-bearing number: it says the DUT's receive
path was correct throughout, and every symptom above was on the master's side.

### What TP-A02 established

- **Output drop is 1.01 V at 290 µA**, not zero. The datasheet's ≤2.5 V is a
  300 mA figure and does not scale to nothing at microamps.
- **Sensor off-state leakage is below the noise floor** — far inside the 10 µA
  allowed, and 20× better than the figure twice recorded before the rig was
  clean.
- **Thresholds 170 / 522**, margins 170 and 60 counts across ±15 % supply.
- A constant **−19 mV** sits at PC4 with sensors disconnected (~4 µA sunk
  board-side). Unexplained; 6 counts; invariant with state.

### The lesson this bench day cost

Three complete measurement sets were taken, fitted, documented and committed
before the fourth revealed all three were of a circuit that did not match the
schematic. **The tell was visible in the first set and missed:** *one active*
to *both active* stepped 50 mV where the topology requires it to roughly
double. A model needing a new free parameter for every measurement is
describing the wrong circuit — check the rig before refitting.

### Not yet run

Group A rows TP-A03…A09; all of Group C (blocked on integration stage D).
Group B is now **unblocked** — the raw master exists and the DUT answers it.
TP-A03 stays **BLOCKED**: no adjustable supply on this bench, so the ±15 %
margin (60 counts, the tightest number in the design) remains calculated.

---

## Inherited evidence, and what it does not cover

## What goes here first

In order, once a board exists:

1. **Bench bring-up** — `smoke_test.py`, `blinky_check.py`, `uart_check.py`.
   Proves the rig before anything rests on a capture.
2. **Board bring-up (integration stage B)** — the FR-S03 address latch
   reads 40 with the jumper open and 45 bridged; FR-S18 init order leaves
   the transceiver quiescent through reset.
3. **Register map (stage C)** — the full TDS §2.7/§2.8 read/write matrix
   plus FR-S39 persistence across a watchdog reset.
4. **Modbus protocol matrix** — the §2 rows re-run on this DUT.
5. **Encoder driver (phase 1)** — the `driverDevelopment.md` §3.3 matrix.
6. **Measurement and averaging (stages D/E)**, then the full acceptance
   suite (stage F, NFR-TST01).

## Report format

One section per test, so a reader can reproduce it without reading the
script:

```
### <ID> — <short name>

| Field | Value |
|---|---|
| Requirement(s) | FR-… |
| Script | software/hil/<script>.py |
| Setup | instruments, wiring, DUT build flashed |
| Stimulus | what was applied |
| Expected | the measurable outcome |
| Pass criterion | the threshold that decides it |
| Result | measured numbers |
| Verdict | PASS / FAIL / BLOCKED, with the date |
```

Regenerate or extend this report whenever a check script or a design
document changes — a stale test report is worse than none, because it
reads as evidence.
