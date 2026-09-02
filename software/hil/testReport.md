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

## Status: stages A–F complete; acceptance suite green

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
| **TP-A09** | 2026-09-01 | **PASS — visual, confirmed by the operator.** Both end sensors wired **star**, one cable each to the PCB hub, summing on the board; R10 absent. Not an instrument measurement: a field junction is invisible electrically, which is why the row exists and why it gates the Group C switch rows. |
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

### Group B — 74 checks pass, 0 fail

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
| TP-B02 | FR-S03, FR-MB05, FR-MB07 | **PASS** — bridged: answers at 45, silent at 40. Moved back to open while running: **no effect until reset**. |
| TP-B04 | FR-S32 | **PASS** — 30007 identical across a real power cycle. |
| TP-B19 | FR-S39 | **PASS** — all six persisted holdings survived exactly; 40007 correctly did not. |
| TP-B21 | FR-S20 | **PASS** — watchdog recovered the stalled loop in **1.20 s**, no power cycle (budget 3 s). |
| TP-B22 | FR-S21 | **PASS** — six post-reset state checks; see below. |
| TP-B01b | FR-S01, FR-S32 | **PASS** — `encoder` reports `0x0101`, `encoder_test` reports `0x8101`. The bench image is now identifiable over the bus. |
| TP-B20 | FR-S39 | **ACCEPTED at 13 of 20 cycles**, no corruption. See below. |
| TP-B35 | FR-S16, FR-MB23 | **PASS** — 10 000 cycles, 30009 unchanged, 30010 advanced by exactly 10 000. See below. |
| TP-B24 | FR-S19 | **PASS** (partial scope) — bus never left the fail-safe bias across a real power cycle; peak 0.296 V. See below. |
| TP-B33 | FR-MB28 | **PASS** — FC03/FC04 quantity 0 and 126, FC16 quantity 0 and byte-count mismatch: exception 03 each, nothing modified. |
| TP-B34 | FR-MB24 | **PASS** — a 514-byte burst and a corrupt frame both discarded, and the device still answered the next valid request. |
| TP-B32 | FR-MB04 | **PASS** — DE asserted 3–82 µs before the first start bit, released 3–6 µs after the last stop bit, against a 1 146 µs budget. See below. |

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

### TP-B21 / TP-B22 — watchdog recovery and the state after it

Flashed `encoder_test` (`Verified OK`), ran the row, reflashed `encoder`
(`Verified OK`) and confirmed the hook was gone before continuing.

**TP-B21 (FR-S20) — PASS.** Writing magic `0xDEAD` to holding `0x00FF` stopped
the main loop refreshing the IWDG. The write itself was answered; the device
then went silent and **answered a valid FC04 again 1.20 s later, with no power
cycle**, against FR-S20's 3 s budget. The 1.20 s includes this script's ~0.15 s
poll granularity, so the true IWDG period is at or under that and inside
FR-S20's 100 ms–2 s window.

The row first proves the device actually *stopped* answering. Without that, a
watchdog that never fired and a device that never hung are indistinguishable,
and the row would pass while testing nothing.

**TP-B22 (FR-S21) — PASS**, six checks after that reset:

| Check | Result |
|---|---|
| Uptime restarted (32 s → **0 s**) — a real reset, not a stall that cleared | PASS |
| Holdings restored to persisted values `[0, 1000, 10, 10000, 0, 1023]` | PASS |
| 40007 (teach) reads 0 — deliberately not persisted | PASS |
| Measurement registers 30001–30005 cleared | PASS |
| Status bit 0 set (first window incomplete) | PASS |
| Status bit 1 set (average not filled) | PASS |

### TP-B04 / TP-B19 — across a real power cycle

Driven by [`power_cycle.py`](power_cycle.py): it writes probe values, the
operator removes power, and it judges the read-back against what it actually
wrote rather than against what anyone remembers.

The probe values `[1234, 2500, 30, 8888, 200, 900]` differ from the §2.8
defaults in **every** register. That is deliberate: with any register left at
its default, "the value survived" and "the value was lost and came back as a
default" are the same reading.

| Check | Result |
|---|---|
| All six persisted holdings survived | **PASS** — exact match |
| 40007 (teach) reads 0 — not persisted | **PASS** |
| 30007 identical across the cycle (FR-S32) | **PASS** — `0x0101` both sides |
| Uptime 80 s → **15 s** | power really was removed; this is a cold boot, not another watchdog reset |
| 30001–30005 clear, status `0x0013` with bits 0 and 1 set (FR-S21) | **PASS** |

FR-S21 is now demonstrated after **both** reset causes that the bench can
produce — the watchdog (TP-B21) and a true power-on. The two are not the same
path through the firmware, and passing one does not imply the other.

**TP-B20 is NOT covered by this.** It asks for 20 cycles, some interrupted
mid-write, which is a different question: not "does the store survive a clean
cycle" but "can the ping-pong store be caught in a torn write". One clean cycle
says nothing about that.

### TP-B02 — the address jumper

With **JP6 bridged** and a power cycle:

| Check | Result |
|---|---|
| Answers at **45** — `30007 = 0x0101` | **PASS** (FR-S03) |
| **Silent at 40**, the old address | **PASS** (FR-MB05) |

The second row carries the weight. A device that answered at both addresses
would sail through a test that only checked the new one.

**Persistence survived a second cycle, at the new address:** holdings still
`[1234, 2500, 30, 8888, 200, 900]`, 40007 still 0. FR-S39 now holds across two
independent power cycles rather than one.

**FR-S35's power-on reset is confirmed — and only a power cycle could show it.**
After the boot, `30009 = 0` and `30010 = 2` (our own two reads). The requirement
says both counters reset to 0 at power-on; TP-B16 verified they *count*
correctly but could not verify they *start* at zero.

**FR-MB07's latch clause — PASS.** With the device still powered, JP6 was moved
back to **open** (which selects address 40). It kept answering at **45** and
stayed silent at **40**. Uptime read 72 s against 25 s before the move,
confirming continuity: no reset intervened, so the address really is latched at
startup and there is no live re-read.

That is the clause that would catch out an installer who moved the jumper on a
live bus and assumed it had taken effect. Testing only the bridged case would
have missed it entirely.

**And the change did take at the next reset — PASS.** After a power cycle with
JP6 open the device answers at **40** and is silent at **45**. The full cycle is
therefore closed in both directions: bridged→45, open→40, and neither takes
effect until reset.

**FR-S39 across three independent power cycles.** The probe values survived all
three, and `30009`/`30010` came back 0 and 2 (our own reads) after each boot, so
FR-S35's reset-to-zero is confirmed repeatedly rather than once. Defaults were
restored afterwards and the restore verified by read-back.

### TP-B24 / FR-S19 — no boot banner, across a real power cycle

**PASS**, on the third attempt. The first two were reported **INCONCLUSIVE**
rather than passed, because no power cycle fell inside the listening window:

| Attempt | Uptime before → after | Verdict |
|---|---|---|
| 45 s window | 491 → 538 s | no reset in the window — nothing tested |
| 120 s window | 562 → 683 s | no reset in the window — nothing tested |
| 120 s window | **29 136 → 106 s** | **reset confirmed** |

The row refuses to return a verdict until uptime has gone **backwards**. Without
that guard, a DUT that was quietly disconnected — or simply never cycled —
passes perfectly. It fired twice here, which is the only reason two empty runs
were not written up as evidence.

**Result:** with the master held released and sending nothing for 120 s spanning
a full power cycle, the peak bus differential was **0.296 V** against a 0.26 V
fail-safe bias and a ~1.4 V driven level. The DUT never drove the bus. No boot
banner, no test bytes, nothing unprompted.

**Measured without the analyser.** TP-B24 was written for the Saleae, but the
MCP bridge cannot set a Logic16's input voltage range (see below) and the server
later disconnected outright. It is not needed: the DUT drives the bus only when
its DE is asserted, so "did it ever transmit?" is answerable from the bus alone.
No rail probe either — the reset is proved after the fact from uptime rather
than observed at the instant it happens.

**Scope of this pass, and what it does not cover:**

- FR-S19's second clause — *received bytes discarded until ≥3.5 character times
  of bus idle* — needs a partial frame delivered at the instant of boot, which
  needs a rail probe to trigger from. Not tested.
- The TDS asks for **20** cycles with another master/slave pair actively
  exchanging frames. This is **one** cycle on an otherwise quiet bus. The
  no-boot-banner claim is well supported; "never transmits while another pair is
  talking" is not.
- **FR-S18** is co-cited on this row and is only partially covered. A bus
  capture can show DE low from the first instant (clause 1); it cannot show the
  PC1 latch order, ADC self-calibration before the first conversion, or USART
  enabled last (clauses 2–4).

### TP-B35 — the 10 000-cycle soak, and a classifier that accused the DUT

**PASS.** FR-S16 (internal 48 MHz HSI, no crystal) and FR-MB23 (RX discarded
while transmitting), over the full 10 000 request/response cycles the
requirement specifies:

| | Result |
|---|---|
| 30009 — framing/CRC errors | **0** |
| 30010 — served | advanced by **exactly 10 000** |
| Latency | median **4.08 ms**, max **4.14 ms** over 9 998 samples |
| Master-side misses | 2 of 10 000 (0.02 %), both attributable to the rig |

The verdict rests on the **DUT's own counters**, not on what the script believes
it sent. FR-MB23 rides along: the DUT's RO and DI are tied on the shared PD6
node, so a device that ever evaluated its own transmission as an incoming frame
could not hold a zero CRC-error count across 10 000 exchanges.

**A first run reported FAIL. That was my classifier, not the device.**

It counted any missed reply whose capture contained *edges* as implicating the
DUT's transmit clock — 4 of them, at a 40 ms capture window. But a **truncated**
capture also contains edges and also fails to decode, so clipped frames were
being filed under "the DUT's fault". Re-run at 80 ms, where the ~21 ms of
content cannot run off the end:

| | 40 ms window | 80 ms window |
|---|---|---|
| Total misses | 8 (0.08 %) | 2 (0.02 %) |
| empty — reply outside the window | 4 | 1 |
| clipped — ran into the window end | — | 1 |
| **suspect — would implicate the DUT** | **4** | **0** |

Doubling the window took the suspect class to zero and the overall miss rate
down fourfold. The four were truncation.

The classifier now separates *empty*, *clipped* and *suspect* by where the last
edge sits relative to the window end, and only *suspect* counts against the
verdict. Two independent arguments also stood against a genuine clock fault
before the re-run, though neither would have settled it: the DUT's measured
**0.8 % fast** is consistent and far inside the ±5 % a per-character resyncing
decoder tolerates, and a tolerance problem degrades steadily rather than
producing four isolated failures among 9 992 clean ones.

**This is the third time in this session a FAIL was published against the DUT
for an analysis error** — after TP-B32's drive-window fragmentation and the
retracted 11.85 ms latency. The common shape: a measurement was believed before
its own sanity check was applied. The rule earned here is narrower and worth
keeping: **a verdict that blames the device must first rule out the instrument,
and "my capture contains something" is not evidence that the something is
correct.**

### TP-B20 — the persistence store under torn writes (PARTIAL, 13 of 20)

**No corruption in 13 power cycles**, each preceded by ~200 writes driven at
roughly 22 % flash duty. Every cycle returned a valid record:

    40001 = 111 or 222        one of the two values actually written
    40002-40006 = 1100, 11, 11000, 100, 900

Several cycles came back with uptime at **0 s**, so the cut landed during or
immediately after a burst — real mid-write interruptions, not merely clean
cycles. The store never fell back to the §2.8 defaults, which is the signature
this row hunts: FR-S21 restores defaults when the persistent record is judged
blank or corrupt, so seeing defaults after writing non-defaults *is* the
corruption.

Every value is deliberately non-default for that reason. Had the settings been
left at their defaults, "survived" and "was lost and restored from defaults"
would read identically.

**Why the timing had to be forced.** A flash save is ~6 ms, once per changed
holding set, immediately after the Modbus response. Hitting it by hand is
impossible — human reaction is ~50x too slow. The cut can only land mid-write by
chance, and that chance *is* the flash duty cycle. Hence the burst: FC06 writes
sent fire-and-forget, spaced 27 ms so our next frame does not collide with the
DUT's reply, giving ~22 % duty and an expected ~3 genuine mid-write hits across
13 cycles.

**Cost:** ~4 600 flash writes, ~2 300 per ping-pong record — roughly 23 % of a
conservative 10 000-cycle endurance budget on this board. Approved deliberately;
a gentler test would have exercised almost nothing.

**Status: ACCEPTED at 13 of 20, by decision on 2026-09-01.** The remaining
seven cycles were dropped deliberately, not overlooked: each costs ~200 flash
writes and the run had already spent ~23 % of a conservative endurance budget on
this prototype. The row should be re-run in full on the PCB, where the flash is
not a hand-built board's. 30009 also picked up 1 CRC error across the run,
consistent with power removed part-way through a frame — expected, not a fault.

Bench left at the §2.8 defaults `[0, 1000, 10, 10000, 0, 1023]`, verified by
read-back, with the release build running at address 40.

**Three instrumentation bugs were found and fixed while running this row**, and
none of them were the DUT:

1. The cycle detector compared uptime against a baseline read at round start.
   After a cycle that baseline is 0–2 s, so the next cycle's uptime was not
   reliably *less* than it and resets went unseen — 2 of 20 detected on the
   first attempt. Now judged against **elapsed wall time**: a running device's
   uptime must track the clock, and lagging by >3 s means it restarted.
2. An unguarded uptime read at round start crashed when the operator still had
   power off.
3. "No reply after the cycle" was recorded as a **FAILURE** when the only fact
   established was that power had not been restored yet. One round was reported
   corrupt on that basis; the result was discarded, not counted against the
   device.

### End-to-end travel: 999.0 mm measured against a 1000 mm rig scale

The rig's own scale (EM-M06) reads **1000 mm** across the traverse; the device
reported **999.0 mm**. Agreement to **0.1 %**.

The 1.0 mm is not mechanism error — it is **one ADC count**. With travel = 1000.0
mm mapped across raw 0–1023, one count is 0.977 mm, and the carriage reached raw
**1022** at the open limit rather than 1023. The whole discrepancy is that single
count of calibration span.

**This does NOT close FR-E03, and an earlier note in this report said it would.**
That was a mis-reading of the requirement's scope, corrected here:

> "Reported opening accuracy — **with the potentiometer replaced by a precision
> divider of ≤0.1 % ratio accuracy** — shall be within ±0.1 % of the configured
> full travel (40004), covering quantization and INL. **End-to-end accuracy
> including the draw-wire mechanism's linearity and the potentiometer's own
> conformity is a separate hardware/calibration item (§6).**"

FR-E03 is scoped to the **electronics** — quantisation and INL — measured with a
precision divider in place of the pot, at five ratios spanning the range, plus
100 reads over 60 s at a fixed ratio spanning ≤3 LSB. The draw-wire mechanism is
explicitly excluded. It needs the precision resistance box from the plan's
equipment list, not the emulator and not the rig's scale.

**What the 999.0 mm figure is genuinely evidence for** is the §6
hardware/calibration item — the mechanism and the pot's conformity — and on that
it is a strong result: 0.1 % end to end, with the residual accounted for by a
single ADC count rather than unexplained.

**Related, already measured:** the ≤3 LSB stability half of FR-E03's
verification clause passes — 30005 spanned **0 LSB over 60 reads** (Group C) and
**2 counts over 32 reads** after the FR-E12 change. Only the five-ratio divider
sweep is outstanding.

### FR-E01 — the opening is absolute across a reset

**PASS.** Power-cycled with the carriage parked at mid-travel and untouched:

| | Before | First window after reset |
|---|---|---|
| 30001 | 2619 | **2609** |
| 30005 | 268 | **267** |
| uptime | 38 786 s | 1 s |

The 1.0 mm difference is **one ADC count** — the quantisation floor, not an
error. The first published window arrived **0.98 s** after the device answered
again: one measurement window, so the value was right at the first opportunity.

That is what "absolute" buys, and it is the property that separates a
potentiometric draw-wire from an incremental encoder — the latter reads zero or
nonsense until it finds a reference.

**The test refuses to run near a zero opening, and that guard matters.** FR-S23
initialises 30001–30004 to 0 and holds them there until the first window
completes. The carriage had been parked at the closed limit minutes earlier;
had the row been run there, "correct immediately after reset" and "still showing
the uninitialised value" would have been *the same number* — and it would have
passed against a device that measured nothing at all.

**It also catches the FIRST published window rather than a settled value**,
polling until status bit 0 clears. A device needing a homing move would produce
a wrong first value and then converge, which any later poll would hide.

### FR-E18 / FR-E19 — the teach handshake, 7 pass 0 fail

Newly runnable once both stops became reachable. Every clause of FR-E19, in
order:

| Clause | Result |
|---|---|
| (a) arm | **PASS** — 40007 = 1 sets status bit 5 |
| (a) stale captures discarded | **PASS** — reading pre-existing 30013/30014 (22, 910) after arming committed **nothing** |
| (b) capture at each stop | **PASS** — 2 entries, closed at rate −919, open at +890 |
| (c) commit **waits** for the master | **PASS** — bit 5 still set after both captures, before they were read |
| (c) commit | **PASS** — 40005 = 56, 40006 = 834, bit 5 clear, 40007 reset to 0 |
| FR-E18 direction | **PASS** — the closed end took the lower code (56 < 834) |
| (d) abort | **PASS** — 40007 = 0 clears bit 5, calibration untouched |

**The poll is deliberately narrowed to 30001–30012.** `regs.c` sets the
"master has read it" flag *inside* the register read, so a routine 15-register
block poll satisfies clause (c) continuously and the commit fires the moment
both endpoints are captured. The waiting half of the handshake would never be
observed and the row would pass while testing nothing.

**The stale-capture guard is asserted, not assumed.** 30013/30014 keep their
values across arming by design — they are diagnostics, and it is the internal
capture flags that arming clears. The firmware comment says *"a stale capture
from an earlier session can never be committed"*; reading two plausible stale
numbers after arming and observing no commit is what turns that into evidence.

**NOT covered:** FR-E19's refusal to commit a pair violating FR-E06's 64-count
minimum span. The rig traverses the full ADC range and cannot present two stops
that close together.

### A rig finding I withdrew — and then disproved by measurement

**RETRACTED 2026-09-01.** This section previously claimed the closed-end sensor
violated EM-M05 by releasing at the mechanical limit, and recommended moving
both sensors. Both claims were wrong.

**Actuating before the mechanical limit is the design.** EM-M03 requires *"a
hard mechanical limit beyond each switch's actuation point, so that over-travel
is bounded even with every switch defeated."* The switch firing at raw 56 with
the hard stop at raw 0 is that arrangement working. In service the drive is
*inhibited* at the switch, so **the switch point is the operational end of
travel** and the mechanical limit is a backstop nobody reaches. The carriage
only ran past it here because manual movement bypasses the inhibit.

**So the taught calibration is right, not narrow.** Teaching 40005 = 56 and
40006 = 834 captures the endpoints that matter. The earlier concern — that it
should span the full 0–1022 mechanical travel — had the product backwards.

**And the EM-M05 evidence does not say what was claimed.** From the movement
log:

    t = 0.22 s   30001 = 0, raw = 0, status 0x0008   AT STOP
    t = 19.95 s  30001 = 0, raw = 0, status 0x0000   still

Bit 3 held for **20 seconds** at raw 0 — the sensor *was* continuously active at
the limit, which argues **for** EM-M05, not against it. It cleared at 19.95 s,
about 1.3 s before the position visibly changed at 21.22 s. The simple reading
is the operator starting to move away, with 30001 not yet updated within its
window.

**What went wrong in the analysis**: "bit 3 cleared while the position had not
changed yet" was read as "the switch released on its own", when a switch
releasing as you move off it — one window ahead of the position register —
explains it without any defect. A rig fault was constructed from a one-sample
ambiguity, and a hardware change was recommended on the strength of it.

**EM-M05 has since been tested properly — and PASSES.** Parked at the closed
limit, hands off, 122 samples over 30 s ([`em_m05.py`](em_m05.py)):

| | |
|---|---|
| 30005 span | **0..0** — zero counts of wander, so the carriage was demonstrably stationary |
| Bit 3 dropouts | **0** |

The stationary requirement is what makes it a test rather than an anecdote:
with the raw code provably fixed, "the switch held" and "the operator kept it on
the switch" stop being the same observation. That is precisely the ambiguity the
withdrawn finding was built on.

**The switch stays continuously active at the mechanical limit.** The rig meets
EM-M05, the geometry meets EM-M03, and the taught endpoints are correct. There
was never a defect here.

### The window emulator arrived — four movement rows closed

The rig from [`design/windowEmulator.md`](../../design/windowEmulator.md) is
built. Driven by hand through a full traverse, it closed four requirements that
had been blocked since integration stage D.

**The traverse itself is the headline.** From the closed stop to the open stop:

| | Closed | Open |
|---|---|---|
| 30005 raw | **0** | **1022** |
| 30001 opening | **0** | **9990** (999.0 mm) |
| Status | bit 3 set (at stop) | bit 3 set (at stop) |

The wiper spans essentially the entire 10-bit range against the default
calibration of 40005 = 0 / 40006 = 1023 — a 1-count shortfall at the top. The
draw-wire front-end and the register defaults agree without adjustment.

| Row | Result |
|---|---|
| **FR-E10** | **PASS** — 30012 went both signs (+1095 opening, −1378 closing, 0.1 mm/s) and the sign agreed with the direction of change in **604 of 604** steps |
| **FR-E14** | **PASS** — bit 3 set at each stop and cleared on leaving it, under real carriage motion rather than a target waved at a sensor |
| **FR-E08** | **PASS** — the envelope spanned the full 999.0 mm traverse |
| **FR-E17** | **PASS** — 30001 refreshed every **250–1000 ms** while moving, against a 1000 ms window |

**FR-E17 first reported FAIL, and the metric was wrong.** It measured the gap
between 30001 **changes** across the whole log and found 41 s — but the carriage
sat still for 98 s of the run, and a stationary window republishes the *same
value* every window. That is a refresh, not a stall. FR-E17 bounds how **old** a
value is, not how long since it last differed, and the metric could not tell the
two apart. Restricted to spans where the carriage was genuinely moving, the
worst refresh interval is 1000 ms — exactly one window.

This is the same family as the FR-E16 isolation error earlier: **the wrong
statistic produces a number, and the number is wrong.** Three of these now, all
in tests I wrote, all reporting a defect that was not there.

**End-to-end travel agrees with the rig to 0.1 %** — but that is NOT FR-E03;
see the correction below.

**Still outstanding after this:** FR-E01 (needs a power cycle at a known
opening), FR-E18/E19 (teach handshake — both stops are now reachable, so this is
newly runnable), FR-E15 (needs an injected 5 ms bounce).

### Group C — the measurement rows, 11 pass 0 fail

Unblocked by stages D and E. Most of Group C needs the window to **move**, which
this bench cannot do on demand — but FR-E04 is a pure function of the raw code
and the three calibration registers, so driving the **calibration** against a
fixed wiper exercises the whole path end to end with a prediction computed
independently in the test.

| Case | raw | 30001 | expected |
|---|---|---|---|
| Nominal, wiper mid-travel | 673 | 6578 | 6578 |
| Offset applied at the closed point | 673 | 7078 | 7078 |
| Travel doubled | 673 | 13157 | 13157 |
| **Reversed mounting** (40006 < 40005) | 673 | **3424** | 3424 |
| Narrow span around the wiper | 673 | 7300 | 7300 |
| Wiper below the closed point | 673 | **0** | clamps to the offset |
| Wiper above the open point | 673 | **10000** | clamps to full travel |

Plus **FR-S24** (30001 is the scaling of the *same response's* 30005),
**FR-E20** (30015 is the percentage of the instantaneous opening), **FR-E09**
(30005 unmoved by a 5× travel change — it really is pre-scaling), and **FR-E05**
(a calibration violating FR-E06's minimum span is rejected and changes nothing).

**The reversed-mounting case earns its place.** FR-E04's calibration points
define *direction*, so a sensor mounted backwards must calibrate as naturally as
one mounted forwards. Same raw code, inverted opening, exact match.

**Two failures first, both mine, and one of them was the device being right:**

- **A race in the test.** After writing a calibration it polled for status bit 0
  to *clear* — but bit 0 had not been *set* yet, so the loop exited on the first
  poll and read the pre-write value. It reported an FR-E04 failure against
  correct firmware. The fix waits for the bit to be set **and then** cleared.
- **An invalid test case.** The reversed-mounting case first used `40006 = 0`,
  but §2.8 gives 40006 the range **1–65535**. Exception 03 was the correct
  answer to a bad request of mine.

**Still not covered, and none of it is a software gap:**

| Requirement | Needs |
|---|---|
| FR-E01 absolute after reset | a power cycle with the window held at a known opening |
| FR-E03 electronics accuracy | a **precision divider** substituted for the pot, at 5 ratios — not the emulator |
| FR-E10 signed movement rate | the window actually moving |
| FR-E17 maximum age of a read | a changing value, to have staleness to bound |
| FR-E18/E19 teach handshake | both stops physically reached |
| FR-E15 20 ms debounce | a 5 ms bounce injected electrically |

### FR-E12 was violated by the driver I wrote, and the header is why

`we.c` configured the ADC sample time to **73 cycles**. **FR-E12 requires ≥241.**

The driver was written to `we.h`'s front-end note, which said "≥71-cycle sample
time" — the value FR-E12 explicitly supersedes and names as superseded: FR-E21's
R11 puts 10 kΩ in series, so the DC source is 12.5 kΩ, above what 71 was chosen
for. **The same header also carried a stale five-state ladder description, which
was caught on sight. This one was not**, because it looked like a considered
number rather than an obvious contradiction.

Fixed to 241 cycles — and that forced a second change. At the HCLK/8 ADC clock
the requirement's own cost note (~42 µs per conversion) would make `we_sample`
1056 µs, inside the 1.146 ms per-pass blocking budget by **8 %**, which is not
margin. The ADC clock went to **HCLK/4 = 12 MHz** (the part's ceiling is 14 MHz),
giving ~21 µs per conversion and `we_sample` ~678 µs. FR-E12 specifies a *cycle
count*, which 241 at 12 MHz satisfies exactly as at 6 MHz; 20 µs of acquisition
against a 12.5 kΩ source into a ~10 pF sample capacitor is ~160 time constants.

FR-E12's own cost note weighs the conversion against the **measurement window**
(≥100 ms) — the right comparison for throughput, and the wrong one for a polled
UART receiver. That budget exists nowhere in the requirements.

**Verified after the change:** FR-E12's own criterion — 32 consecutive reads at
a fixed position spanning **2 counts** against a ≤3 limit — plus 400/400
requests served with latency unchanged at 4.09 ms median.

### Integration stage F — the acceptance suite (NFR-TST01)

`software/hil/acceptance/` run against the flashed release build:
**8 passed, 0 failed, 2 min 7 s.**

    test_build_within_ceilings[encoder]           PASSED
    test_build_within_ceilings[encoder_test]      PASSED
    test_nfr_tst01_every_frmb_id_accounted_for    PASSED
    test_nfr_tst01_report                         PASSED
    test_group_b_protocol_matrix                  PASSED
    test_quantity_limits_and_malformed_frames     PASSED
    test_oscillator_soak_and_latency              PASSED
    test_measurement_service                      PASSED

**The traceability gate is a test, not a document.** NFR-TST01's criterion is
not "the tests pass" — it is that the report *lists every non-excepted, active
FR-MB ID with result PASS*, and **a missing ID blocks a release exactly as a
failing one does**. So the gate re-reads the TDS at run time, enumerates the
FR-MB IDs that exist, and fails if any is unaccounted for. Adding a requirement
now breaks the suite until it is covered or excepted. It fails in the other
direction too: a map entry naming a requirement the TDS no longer defines is a
coverage claim for something withdrawn.

That gate runs **without hardware**, deliberately — a coverage claim that only
holds when the bench is plugged in is not a coverage claim. The DUT rows skip
rather than fail when no ADALM2000 is present, so a checkout without the bench
still runs green and still says what it covered.

| Disposition | Count |
|---|---|
| Automated by the suite | **24** |
| Bench-only, not automated | **1** — FR-MB07 |
| Excepted by NFR-TST01 | **3** — FR-MB01, FR-MB04, FR-MB23 |
| Defined in the TDS | 28 |

**FR-MB07 needs a decision, and was initially miscategorised by me.** I first
listed it as covered, which overstated things. NFR-TST01 scopes itself to
criteria *"executable over the serial link"*; FR-MB07's substance is that the
address is **latched at startup**. Reading the address is executable over the
link — proving it does not change until reset is not, since it needs a power
cycle. Either NFR-TST01's exception list should name FR-MB07 alongside the other
three, or FR-MB07 should be split into a link-testable clause and a bench
clause. Until then it reports as BENCH rather than claiming an automated PASS
that never happened.

**The three excepted requirements are not unverified.** Evidence gathered this
session: **FR-MB01** by Logic 2's Async Serial decode of 13 frames, byte-exact;
**FR-MB04** by TP-B32's drive-envelope measurement (DE asserted 3–82 µs before
the first start bit, released 3–6 µs after the last stop bit, against a 1 146 µs
budget); **FR-MB23** by the zero-CRC-error soak across 10 000 exchanges. They
remain excepted because the requirement says so, not because nothing is known.

**One deliberate deviation in the suite:** the soak runs 500 cycles here, not
FR-S16's 10 000. This gate runs on every release and 10 000 takes 25 minutes.
The full soak is a release-day step (`tp_b35.py --cycles 10000`), already run
and recorded above, and the docstring says which was used.

### Integration stage E — averaging engine live, status reads 0x0000

`avg.c` implements the FR-S31 boxcar and the FR-E08 envelope; `regs.c` calls it
at the three points already marked for it. **30002, 30003 and 30004 now update
and status bit 1 clears.** 5 880 B flash, 1 092 B RAM — 41 % and 61 % of the
NFR-RES01 ceilings.

**Status `0x0000` — every bit clear — for the first time in this project.**
Window complete, average filled, no wiper fault, no end stop, no switch fault.

| Observation | |
|---|---|
| Bit 1 cleared after 10 windows | N = 10 s / 1 s, exactly as FR-S31 computes |
| 30002 between 30003 and 30004 throughout | a real envelope, not placeholders |
| 30003 rose 6549 → 6559 mid-run | the old minimum **rolled out** of the window — the boxcar rolls, it does not merely accumulate |

**FR-S23's no-zero-padding rule, verified on hardware.** After writing 40003 to
clear the accumulator, 30002 read **6559** from the first completed window — the
true opening. A zero-padded accumulator would have read ~328, then ~656,
climbing toward the real value across 20 s. Status also showed `0x0003` at the
instant of the write (window aborted *and* average cleared, FR-S30/FR-E05), then
`0x0002` until the first new window closed.

**One buffer serves all three registers.** The mean, minimum and maximum are all
taken over the same set of published openings, so the ring is 64 entries of
(mean, min, max) rather than three separate structures — 384 B, which is what
takes RAM from 688 B to 1 092 B.

### The block that hides an excursion — 26 host tests

`test_avg.c` compiles the **shipped** `avg.c`, not a copy, and covers the three
properties that are easy to get wrong, invisible on a bench where the opening
barely moves, and each of which produces a plausible-looking number:

- **FR-S23 partial mean.** 3 of 10 windows at 5000 reads **5000**, not the 1500
  a zero-padded accumulator gives — the exact case the TDS states.
- **FR-S31 block weighting.** Half a 200-window span at 2000 and half at 4000
  averages to 3000, so each block weighs as `block_size` windows rather than as
  one.
- **FR-E08 through blocking.** With N = 200 and block size 4, a single 9000
  excursion reports `max = 9000` — **not** the 4500 block mean. This is the
  failure the integration plan predicted: a block storing only its mean would
  report an envelope *narrower than the movement that happened*, hiding exactly
  what the register exists to expose.

Also covered: the boxcar displacing old values, N clamped to 1 when the
averaging period is shorter than the window, the N = 64 exact/blocked boundary,
N = 6000 at full scale for overflow, and a reconfigure forgetting everything.

**Worth flagging: the mean may not earn its place.** The integration plan asked
for this to be decided deliberately rather than by inheritance, and there is now
evidence. 30005 measured a span of **0 LSB over 60 reads** — the instantaneous
reading is already stable, and the averaging engine is inherited from a sibling
project measuring a genuinely noisy quantity. The envelope registers clearly
earn their place; they tell a master the window moved between polls. The mean
costs 384 B of RAM to smooth a signal that does not appear to need smoothing.
FR-S31 is a **Must**, so it was built as specified — but the register map, not
the implementation, is where that question belongs.

### Integration stage D — measurement service live

`we.c` (ADC driver) and `meas_open.c` (window pacing, scaling, publication) are
written and wired into `main.c`'s two FR-S18 slots. **30001, 30005, 30012 and
30015 now update**; status bit 0 clears when a window completes. Flash 5 292 B,
RAM 688 B, both inside the NFR-RES01 ceilings.

| Check | Requirement | Result |
|---|---|---|
| Wiper stability | FR-E03/E13 | 30005 span **0 LSB** over 60 reads (criterion ≤3), median 679 |
| Wiper integrity | FR-E07 | status bit 2 clear — the pull-toggle test trusts the front-end on real hardware |
| Window abort | FR-S30 | writing 40002 re-asserts status bit 0, both cases |
| Publish cadence | FR-E02 | 40002 = 3000 ms → window closed at **3203 ms**; 700 ms → **797 ms** (poll granularity ~110 ms) |

The 0-LSB span is the 16-conversion mean with min/max rejection doing its job;
FR-E03's criterion allows 3.

### FR-E14 / FR-E16 — end-switch classification, all three states

**PASS.** All three §4.4.3 states reached on hardware by actuating the PNP
proximity switches, and each drove the status bits FR-S33 specifies:

| Actuation | Status | Classification |
|---|---|---|
| Neither sensor | `0x0002` | bits 3 and 4 clear |
| Sensor A alone | `0x000a` | **bit 3** — one active |
| Sensor B alone | `0x000a` | **bit 3** — same band |
| Both together | `0x0012` | **bit 4** — switch fault |

**A and B produce the identical band.** The §4.4.3 measurements assumed the two
68 kΩ summing arms are matched; nothing had checked it on this device. They are.

**Bit 4 had never been exercised before.** "Both active" is physically
impossible on a working window — the frame cannot be at both stops — so it only
arises from a wiring or mounting fault, which is exactly what the bit is for.
This is the first evidence the path works at all.

**FR-E16 isolation — the opening path is untouched by switching.** Across all
seven switch transitions, 30001 was *identical* in the polls either side:

    0.16 - 17.98 s   30001 = 6637, 30005 = 679   (across the ONE transition)
    20.22 - 35.56 s  30001 = 6578, 30005 = 673   (across FIVE transitions)
    40.02 - 45.39 s  30001 = 6549, 30005 = 670   (across the neither transition)

30001 changed exactly twice, both times mid-state, and both times tracking
30005: raw −6 then −3 counts gives opening −59 then −29, matching the ~9.8
units-per-count scaling. That is the wiper drifting, not switch coupling.

**Three versions of this check were wrong before one was right**, and the
progression is worth keeping because the mistake is subtle:

1. **Range.** Compared the whole run's min/max span of 30001 (88) against an
   arbitrary threshold, and failed. But FR-E16 permits the opening to change —
   it forbids it changing *because* a switch changed. Span cannot express that.
2. **Edge-to-edge.** Compared 30001 at consecutive transitions, up to 6.7 s
   apart, so ordinary drift accumulated into the delta and it failed again.
3. **Adjacent polls.** Compare the poll immediately before and after each
   transition, ~0.1 s apart. Drift is negligible over that span, and every
   transition shows zero movement.

**Correlation questions need a correlation statistic.** Two of those three
attempts reported a FAIL against a device that was behaving correctly.

**NOT verified: FR-E15's 20 ms debounce.** It requires a 5 ms bounce injected
electrically; a hand-actuated proximity sensor cannot produce one. The
transitions observed here were clean, which is consistent with a working
debounce but does not test it.

### FR-E07 — the wiper fault machine, both directions

**PASS**, measured across real transitions with the wiper physically
disconnected and reconnected:

| | Observed |
|---|---|
| Reconnect | bit 2 **clears**, 30001 returns to 6647, 30011 resets to 0 |
| Disconnect | 30001–30004 → **65535**, bit 2 **set**, 30011 = **3 s** |
| Budget | 3.4 s = 2 s timer + two 200 ms windows + 1 s of 30011 granularity |
| 30005 through the fault | holds **679/681**, the last code the front-end produced |

**It recovers.** A fault machine that latched permanently would be
indistinguishable from this one in steady state, and only the reconnect
distinguishes them.

**The number is coherent, not merely inside a limit.** At a 1000 ms window the
same measurement read 4 s; at 200 ms it reads 3 s. The ~1 s difference is
exactly the window granularity, so the figure decomposes as the specified 2 s
timer, plus the windows that must close around it, plus 30011's whole-second
reporting. A figure that could not be accounted for that way would not have been
accepted.

**The hold is invisible by design, and that broke two of my tests first.**
FR-E07 sets bit 2 only *after* the 2 s expires, so while the last opening is
being held the registers look exactly like healthy operation. The first version
of this row hunted for "bit 2 set but 30001 not yet the sentinel" — a state the
requirement forbids — and reported INCONCLUSIVE. The second treated its own
first poll as a transition, so a device that was already faulted when polling
began had its settled state timed as a hold and produced a meaningless "18 s
FAIL". The instrument that actually works is **30011**, whose whole job is
counting time since the last valid reading.

**Not covered:** FR-E07 also claims a *shorted* wiper is detectable. It is not —
a field short sits on the far side of R11, so PA2 sees 10 kΩ to the rail, which
is electrically identical to the wiper at an end stop. Only opens are
detectable, and only opens were tested. See the driver commit.

### Stage D broke the Modbus link, and the DUT's own counters said how

The first stage D build **silently dropped 9.7 % of requests** — 271 served of
300 — with **30009 unmoved**. That combination is diagnostic: frames were not
being mis-received, they were not being *seen*.

`mb_rx_service` polls a **single-byte USART register** from the main loop, and
FR-MB24 discards a frame on overrun. So **any main-loop pass longer than one
character time (11 bits / 9600 = 1.146 ms) loses a byte** — and an overrun is
not a CRC error, so the counter that would normally shout stays silent.

Measured costs at 6 MHz ADC clock, 73-cycle sample: a conversion is ~14 µs, so
`we_switch_sample` is ~224 µs and `we_sample` ~552 µs. The broken build had two
500 µs FR-E07 pull settles (~1.25 ms for `we_sample` alone) **and** ran both
samples in the same pass — ~1.48 ms, comfortably over budget.

Two fixes, both derived rather than guessed:

- **Settle 500 µs → 150 µs.** The worst case is an open wiper, where C6 (1 nF)
  charges through the ~40 kΩ pull alone: τ = 40 µs, so 150 µs is 3.75 τ, 97.6 %
  settled — ample to tell a ~1023-count swing from a ~242-count one.
- **The wiper and the divider now sample on alternate ticks** at 40 Hz, giving
  each 20 Hz (twice FR-E14's floor) while no pass ever pays for both.

| | Before stage D | Stage D (broken) | Stage D (fixed) |
|---|---|---|---|
| Requests served | 10 000 / 10 000 | **271 / 300** | **500 / 500** |
| Latency median | 4.08 ms | 4.08 ms | 4.08 ms |
| Latency max | 4.14 ms | 5.89 ms | 4.74 ms |

**The blocking budget was nowhere in the design documents.** It is a hard
consequence of a polled receiver on a one-byte register, it is invisible until
something exceeds it, and exceeding it produces silent frame loss rather than an
error count. It is now stated in both `we.c` and `meas_open.c`, with the
arithmetic, so the next person to add work to that loop has to redo the sum
rather than guess.

### The Saleae independently confirmed the transport

Logic 2's own Async Serial analyzer, on the same bus, over 13 transactions:

- **13 of 13 DUT responses verified by an independent CRC check**, byte-exact
  `28 04 02 01 01 24 a6` → register `0x0101`. A different tool and a different
  decoder agree with `modbus_rtu_codec.py` completely.
- **Every transaction carried exactly one spurious `0x00`, flagged by the
  analyzer as a FRAMING ERROR.** That is independent confirmation of the RO
  enable-transient diagnosed from the M2K alone, and the reason `_extract` hunts
  for a valid frame instead of trusting the first byte received.

**Caveat: the capture holds only the DUT's responses, not the master's
requests.** The `0x00` sits 13 ms before each response — exactly where the
master's frame starts — so the analyzer sees the beginning of our transmission
and cannot decode the rest. Consistent with the threshold problem below. The
DUT-side result stands on its own; the master-side capture does not.

**The Logic16 voltage range still cannot be set through the MCP bridge**, after
a full Logic 2 and Claude Code restart: `digitalThresholdVolts` accepts only
1.2/1.8/3.3 at the schema and the backend rejects all three, wanting a range
(`1.8V to 3.6V` / `3.6V to 5.0V`). Omitting it starts a capture that works for
the strongly-driven DUT signal and not for ours.

### The test build now identifies itself (fixed 2026-09-01)

`platformio.ini` says of `encoder_test`: *"NEVER release this binary."* Until
now the only thing enforcing that was discipline — **`BUILD_TYPE` was `0x01` in
both builds**, so 30007 read `0x0101` either way and a device carrying the
FR-S20 hang hook (holding `0x00FF`, magic `0xDEAD`, which stops the main loop
refreshing the watchdog) was indistinguishable over the bus from a correct one.

Fixed by decision on 2026-09-01: `sensors.h` guards `BUILD_TYPE` with `#ifndef`
and `[env:encoder_test]` defines it as **`0x81`** — high bit meaning *not for
release*. FR-S32 amended to make that normative.

**Verified on the bench, both directions:**

| Image | 30007 | Holding `0x00FF` |
|---|---|---|
| `encoder_test` | **`0x8101`** | readable — hang hook present |
| `encoder` | **`0x0101`** | exception 02 — hook absent |

Release build size is unchanged at 3 704 B; the test build is 3 736 B.

This also makes **TP-B01b verifiable by its own stated method**. Its criterion is
FR-S01's "one release build only", and it previously checked that by reading
30007 — which could not distinguish the images at all. The holding-`0x00FF`
probe is kept as a cross-check but is no longer the primary means: inferring
which firmware is running from a side effect is weaker than asking it.

### TP-B32 — DE timing, measured without the analyser

**PASS**, n = 10. FR-MB04 allows one character time (11 bits = **1 146 µs**) on
each side:

| | Measured | Budget | Margin |
|---|---|---|---|
| DE asserted **before** the first start bit | 3–82 µs (median 42) | 1 146 µs | ~14x |
| DE released **after** the last stop bit | 3–6 µs (median 5) | 1 146 µs | ~200x |
| Drive window | 7.30–7.38 ms | a 7-byte frame at 9600 is **7.29 ms** | — |

That last row is the check that the measurement is real, not the result.

**Measured from the bus, not from PC2.** The DUT drives the bus only while its
DE is asserted, so the drive envelope sits on the M2K's analog inputs on the
same timebase as the data — driven is ±1.4 V, released is the 0.26 V fail-safe
bias. A magnitude threshold finds the drive window and a sign change finds each
data bit, with no second probe and no second instrument's clock to reconcile.

**A first FAIL on this row is retracted — it was my analysis, not the DUT.**
The differential swings ±1.4 V and passes through zero at *every bit
transition*, so |A−B| dips below the threshold for a few microseconds on each
edge. Requiring long runs above the threshold chopped one drive window into one
fragment per bit; the code then measured the last fragment and reported a
7.29 ms frame as a **1.04 ms drive window**, with a nonsensical −6.5 ms release
lag. The fix is to threshold first and then *close* gaps shorter than two bit
times — no real release is that brief, since t3.5 alone is 35 bit times.

**The tell was in the output the whole time**: a 7-byte frame cannot occupy a
1.04 ms drive window. Checking the measured frame duration against the frame
length it must have would have caught it before the verdict was written, and
that check is now printed on every run.

### The Saleae could not be driven programmatically

TP-B32 was written for the Logic16, and the probe map already routes ch1 to the
DUT's DE. It could not be used: **the MCP bridge cannot set a Logic16's input
voltage range.** `start_capture` requires `logicDeviceConfiguration`, its schema
accepts only the scalars 1.2, 1.8 and 3.3, and the backend rejects all three —
it wants a range (`1.8V to 3.6V` or `3.6V to 5.0V`). Omitting the threshold is
the only way a capture starts, and the default applied then does not match 3.3 V
logic: a 20-second capture across four channels returned **zero transitions**,
including on the master's own DI, which was certainly switching.

The analyser itself is fine — the Logic 2 UI shows correct traffic on the same
probes. Any Saleae row (TP-B24, and TP-B32 if it is ever re-run there) has to be
captured from the UI and the `.sal` loaded afterwards, not driven end-to-end
from here.

### Outstanding — what is left, and what each needs

Nothing below is blocked on software. Stages A–F are complete and every
requirement reachable with the present equipment has been exercised.

**Blocked on equipment this bench does not have:**

| Row / requirement | Needs | Consequence of leaving it |
|---|---|---|
| **TP-A03**, **TP-B23** (FR-S22) | an adjustable supply | The ±15 % supply margin — **60 counts**, the tightest number in the design — stays calculated, never measured. This is the most valuable of the four. |
| **FR-E03** | a precision resistance box, 5 ratios spanning the range | Electronics accuracy (quantisation + INL) unverified. The **≤3 LSB stability half already passes**; only the ratio sweep is missing. |
| **FR-E15** | a 5 ms bounce injected electrically | The 20 ms debounce is unverified. Every transition observed on the rig was clean, which is consistent with it working but does not test it. |
| **FR-E19** (part) | two stops <64 counts apart | The refusal to commit a calibration violating FR-E06 is untested. The rig traverses the full ADC range and cannot present them. |
| **TP-B36** (FR-S02) | a PCB | The release binary on unmodified hardware. Everything to date carries a breadboard caveat. |

**Not blocked, just not done:**

| Row | Note |
|---|---|
| TP-A04–A08 | TP-A04 and TP-A08 also want the adjustable supply; TP-A05 needs +70 °C (really Group D); TP-A07 needs a megohmmeter |
| TP-B18 | **PARTIAL** until a factory-reset procedure exists (plan §7) — the defaults were observed, not verified |
| TP-B20 | **ACCEPTED at 13/20 cycles** by decision, to bound flash wear on a prototype |
| TP-B24 | **PASS** (partial scope) — one cycle on a quiet bus, where the TDS asks for 20 with another master/slave pair active |

**Three decisions taken 2026-09-01**, each recorded in the TDS:

1. **The mean (30002) is KEPT.** The measured 0 LSB of spread over 60 reads is a
   *clean-bench* figure — short cable, still carriage, no wind loading on the
   window — and the engine costs 384 B of a 1 792 B budget currently at 61 %.
   FR-S31 now carries that measurement and the instruction to revisit with
   **field** noise data rather than bench data.
2. **FR-E07 narrowed to open circuits only.** It previously claimed an open *or
   shorted* wiper was detectable. A short is not: R11 sits between the field
   wiring and PA2, so a short to either rail presents 10 kΩ to that rail —
   electrically identical to the wiper resting at the corresponding end stop.
   The requirement now says so, and states the consequence plainly: **a wiper
   shorted to 0 V reports the window as fully closed.** A cross-check against
   the end switches would catch it; that is noted as the route, not required.
3. **FR-MB07 added to NFR-TST01's exception list**, beside FR-MB01, FR-MB04 and
   FR-MB23. Its *no-address-register* half is link-testable and already covered
   by TP-B13/B27; only *latched at startup* needs a power cycle, which is
   exactly what the exception list is for.

**NFR-TST01's criterion is now met in full**: 24 automated, 4 excepted, **0
unaccounted**. The suite's `BENCH_ONLY` category is empty and the report says so
rather than warning about a row that no longer exists.

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
