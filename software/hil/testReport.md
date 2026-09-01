# HIL Test Report

Consolidated record of every hardware-in-the-loop test executed against
this project's device under test: setup, expected result, pass criteria,
and verdict.

| Field | Value |
|---|---|
| Project | `wire-encoder-modbus-interface` |
| Last updated | 2026-09-01 |
| DUT | **Breadboard build.** CH32V003J4M6, MAX3485, 3RG4023-3AB00 ×2, draw-wire front-end. No PCB. |
| Plan | [`design/testPlan.md`](../../design/testPlan.md) v0.2 |

---

## Status: Group A opened, Group B largely executed, Modbus link up

Hardware exists and has been exercised. What follows is what was actually
run — everything else in the plan is still untouched.

### Executed

| Row | Date | Result |
|---|---|---|
| — | 2026-08-31 | **Debug link verified.** WCH-LinkE `mode:RV version 2.15`; target examined, `XLEN=32`, `misa=0x40800014` (RV32EC + vendor) — the expected silicon. Reached via OpenOCD, not minichlink: the `WCHLink_A64` driver blocks libusb (`LIBUSB_ERROR_ACCESS`), and `upload_protocol = wch-link` routes through OpenOCD anyway, so no Zadig/WinUSB step is needed. |
| — | 2026-08-31 | **Firmware flashed.** `encoder` build byte `0x01`, 3 704 B flash / 620 B RAM. `** Verified OK **`. |
| **TP-A00** | 2026-08-31 | **PASS, on the fourth attempt.** −20 mV with both sensor outputs disconnected. It failed three times first, and each failure was a real fault it was written to catch: **R10 still fitted**, **R5 floating**, a third wiring error, and finally **the MCU's internal pull-up on PC4** (~47 kΩ to 3V3, sourcing ~63 µA into the summing node) left enabled by the image previously in flash. |
| **TP-A02** | 2026-08-31 | **PASS.** Bands at `Von` = 23.09 V: **−0.019 V / 1.291 V / 2.210 V** = **0 / 401 / 686 counts**. `Von` confirmed by three independent routes agreeing to **0.2 %** — each switch alone, and both together (which carries no leakage term). Rail 24.1 V. |
| **TP-A01** | 2026-08-31 | **WITHDRAWN.** Written to characterise a 33 µA sensor leakage that turned out not to exist — it was the PC4 pull-up. Connecting or disconnecting both sensors moves PC4 by 0.9 mV. |
| — | 2026-09-01 | **First Modbus transaction.** DUT answered at unit 40, 9600 8N1. `30007 = 0x0101` (build `0x01`, firmware 1) and a full 15-register FC04 read. See below. |

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
960 kSa/s capture) — evidence for FR-MB01's 9600 8N1, well inside the ±5 %
a UART receiver tolerates.

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

### Group B — 34 checks pass, 0 fail

Driven by [`group_b.py`](group_b.py) against the `encoder` build at unit 40.
Holding registers are read as-found and restored with a single atomic FC16 in a
`finally` block, so the run leaves no state behind; the restore is verified and
reported.

| Row | Traces to | Result |
|---|---|---|
| TP-B01 | FR-S01 | **PASS** — `0x0101`, build `0x01`, firmware 1. |
| TP-B06 | FR-MB01, 08–11 | **PASS** — FC03, FC04, FC06, FC16 all accepted. |
| TP-B07 | FR-MB25 | **PASS** — request data big-endian, CRC little-endian, response data big-endian (verified on 30008, whose two bytes differ; 30007 is `0x0101` and would have proven nothing). |
| TP-B08 | FR-MB19 | **PASS** — 40002 = 65000 and = 50 both exception 03, register unchanged at 1000. **Not clamped.** |
| TP-B09 | FR-MB22 | **PASS** — FC16 with one valid and one invalid value rejected whole, neither register moved. |
| TP-B10 | FR-E06 | **PASS** — 40005/40006 at span 63 rejected with exception 03, both unchanged. |
| TP-B11 | FR-MB05 | **PASS** — FC04 to address 247: silent. |
| TP-B11 | FR-MB06 | **PASS** — broadcast FC06 silent **and not executed**; 40001 unmoved. |
| TP-B12 | FR-MB02, FR-S35 | **PASS** — corrupted CRC: silent, 30009 +1, 30010 +0. |
| TP-B13 | FR-MB13 | **PASS** — input 0x0020: exception 02. |
| TP-B15 | FR-MB03 | **PASS** — both halves; see below. |
| TP-B17 | FR-MB08 | **PASS** — 30001–30015 all readable. |
| TP-B18 | FR-MB09 | **PARTIAL** — 40001–40007 all readable. They equal the §2.8 defaults, but see the caveat below: that does **not** verify them. |
| TP-B25 | FR-MB12 | **PASS** — FC01, FC02, FC05 each exception 01. |
| TP-B26 | FR-MB14 | **PASS** — 12 registers from 0x000A spans the map edge: exception 02, no partial data. |
| TP-B27 | FR-MB15 | **PASS** — FC06 to holding 0x0020: exception 02. |
| TP-B28 | FR-MB30 | **PASS** — FC06 response byte-identical to the request; FC16 response PDU is `00 01 00 02`, address and quantity, not data. |
| TP-B30 | FR-MB18 | **PASS** — only codes 01, 02, 03 observed across the whole group. |
| TP-B31 | FR-MB17 | **PASS** — never silent on a valid addressed request. |
| TP-B16 | FR-S35 | **PASS** — 20 good + 10 corrupted frames: 30010 +20, 30009 +10. Exact, both counters. |
| TP-B14 | FR-MB20 | **PASS** — n=1000, median **4.08 ms**, max **4.14 ms** against a 100 ms limit. See below. |
| TP-B29 | FR-MB21 | **PASS** — **100 %** within 15 ms, where 95 % is required. |
| TP-B05 | FR-S34 | **PASS** — monotonic over 10 min, 605 s counted in 606 s (0.18 %). |

**TP-B18 is PARTIAL, and the reason is easy to miss.** The registers read
exactly the §2.8 defaults — but only because they were *written* back to those
values by hand after an earlier run was killed mid-suite. No factory reset
happened. Finding the defaults present therefore says nothing about what a
factory reset produces, which is what the row actually asks. §7 of the plan
already notes that no factory-reset procedure is defined; until one exists this
row cannot be closed, and the run reports the precondition rather than claiming
a pass it has not earned.

**FR-MB06 is a deliberate deviation and it holds.** Broadcast writes are
ignored rather than executed, against Modbus-over-Serial-Line V1.02 §2.2. The
test plan's original pass criterion said "action without response", which is the
specification's behaviour and not this device's; the row was corrected to match
FR-MB06 before it was run, and both halves — no reply *and* no side effect —
were checked.

**FR-S31 admits only one invalid ordering.** TP-B09 asks for a register pair
that is valid while the intermediate states are not. Since the constraint is
(40003 × 1000) ≥ 40002, making *both* orderings invalid would require 40003 to
be simultaneously larger and smaller than its previous value. The row therefore
exercises the one direction that is genuinely unreachable register-by-register:
40002 = 60000 with 40003 = 60, accepted as a pair, where writing 40002 first
would violate FR-S31.

### Response latency — measured against DE, and a retracted number

**TP-B14 (FR-MB20) and TP-B29 (FR-MB21) — PASS**, n = 1000 at the plan's 50 ms
spacing:

| | |
|---|---|
| Median | **4.08 ms** |
| p95 | 4.13 ms |
| Maximum | **4.14 ms** (FR-MB20 limit: 100 ms) |
| Within 15 ms | **100 %** (FR-MB21 requires 95 %) |
| Unanswered | 0 |
| DE pulse-width error, worst of 1000 | **0.000 ms** |

The spread across 1000 polls is 60 µs, and the figure is physically coherent:
**t3.5 at 9600 is 4.01 ms**, so the DUT waits exactly the frame-boundary silence
Modbus requires and then answers within about 20 µs of it. FR-MB20 measures from
the last request byte, so that mandatory silence is inside the number — the
firmware's own contribution is the 20 µs, and the requirement is met with a
factor of ~24 in hand.

**A previous figure of 11.85 ms is retracted.** It was wrong, not merely
imprecise, and it was wrong for an instructive reason.

FR-MB20 is a wire timing, so it needs the instant our own last stop bit ended.
The first method took that from the RX line — first edge in the capture, plus
the known frame length. That assumes our transmission appears on RO. **It does
not:** R̄Ē is tied to DE on the raw master, so the DUT's receiver is disabled
while we transmit, and the first edge in the capture is RO's enable transient.
Every sample was measured from an origin roughly 70 bit times off.

The measurement now uses **DE**, which we drive ourselves and which is captured
on the same timebase in the same acquisition:

    our last stop bit ends at (DE falling edge) − LEAD_SAMPLES

Nothing is inferred. The **DE pulse width** is the check that the readback is
really our driven line: it must equal `2·LEAD + 10 bit times per byte sent`, and
across all 1000 polls the error was **zero samples**. The reply is then the first
RX falling edge still low half a bit later — a real start bit, which RO's
transient is far too short to imitate.

**What caught it was a cross-check, not a review.** The first version of the
row was recorded as provisional precisely because its derivation rested on one
route; adding a second route made all 1000 samples disagree and the row reported
`1000 suspect` rather than a plausible number. Had it not cross-checked, 11.85 ms
would have gone into this report as evidence and looked entirely reasonable —
comfortably inside both limits, tightly distributed, and wrong.

The row also reported **FAIL** on that run, which was the wrong verdict: an
unmeasurable timing says nothing about whether the device met it. It now reports
**BLOCKED** when the DE readback is unusable, so a limitation of the rig can
never be read as a defect in the DUT.

### One row of mine was measuring the wrong thing

TP-B15's second half originally sent two requests to the DUT's own address 6 ms
apart in a single burst, expecting both to be served. It failed. The DUT was
correct: **response latency is ~11.9 ms**, so it began replying to the first
frame while the master was still transmitting the second. That is bus
contention, and no frame-boundary requirement is under test in it.

Rebuilt so the two halves are isolated: the **first** frame is addressed to unit
247, which FR-MB05 obliges the DUT to ignore, so nothing contends and only
boundary detection is exercised.

- **2.01 ms gap (below t3.5)** → merged into one frame, CRC fails: 30009 +1,
  30010 +0. Correct.
- **6.02 ms gap (above t3.5)** → split into two frames, the 247 one ignored and
  ours served: 30009 +0, 30010 +1. Correct.

Two further failures in the first run were an arithmetic error of mine, not the
DUT: exactly **one** served request falls between two consecutive counter reads,
and the code subtracted that increment twice.

### Not yet run

Group A rows TP-A03…A09; all of Group C (blocked on integration stage D).

Group B rows that need the bench rather than the master — none of them are
blocked on software:

| Row | Traces to | Needs |
|---|---|---|
| TP-B02 | FR-S03, FR-MB07 | JP6 open then bridged, power cycle between |
| TP-B03 | FR-S02 | power-on to first valid response |
| TP-B04 | FR-S32 | 30007 across a power cycle |
| TP-B19 | FR-S39 | holdings survive a power cycle |
| TP-B20 | FR-S39 | 20 power cycles, some interrupted mid-write |
| TP-B21 | FR-S20 | the `encoder_test` build, magic `0xDEAD` to holding 0x00FF |
| TP-B22 | FR-S21 | register state after that watchdog reset |
| TP-B24 | FR-S18/S19 | bus capture from the instant of power-on — **the Saleae is now connected, so this is runnable** |
| TP-B32 | FR-MB04 | DUT DE (PC2) timing against the bus — likewise runnable now the analyser is on the bench |
| TP-B18 | §2.8, FR-MB09 | **PARTIAL** until a factory-reset procedure exists (plan §7) |

**BLOCKED, both for the same reason:** TP-A03 and **TP-B23** (FR-S22, PVD)
need an adjustable supply, and this bench has a fixed one. The ±15 % supply
margin — 60 counts, the tightest number in the design — therefore remains
calculated, not measured.

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
