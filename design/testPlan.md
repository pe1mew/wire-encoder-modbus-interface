# Test Plan — Hardware Verification

| | |
|---|---|
| Document | Test plan for the wire-encoder Modbus interface |
| Version | 0.1 (first issue — written when hardware was first wired, 2026-08-08) |
| Traces to | [`TDS.md`](TDS.md) v0.6 — every row below cites the requirement whose verification clause it executes |
| Records to | [`../software/hil/testReport.md`](../software/hil/testReport.md) |
| Supersedes | [`integrationPlan.md`](integrationPlan.md) §7, which was a placeholder awaiting hardware |

---

## 1. How to use this

Every row traces to a requirement in [`TDS.md`](TDS.md). The requirement owns
the pass criterion; this document owns the *procedure* — what to connect, what
to do, and in what order. Where the two disagree, **the TDS wins** and this
plan is wrong.

Do not tick a row off without writing the observed value into
`software/hil/testReport.md`. A row recorded as "pass" with no number is worth
very little six months later, and this project has already had two occasions
where a computed figure turned out to be wrong by a factor of three.

**Run the groups in order.** Group A needs no firmware and includes the one
measurement currently blocking the PCB. Group B needs a flashed device and is
the largest body of work that the *current* image can actually satisfy.

---

## 2. What this plan cannot cover yet, and why

`regs_publish_switches()` and `regs_publish_opening()` exist and compile, but
**`main.c` never calls them** — they sit behind stage-D comments. In the image
you can flash today, the measurement path and the end-switch classification are
dead code.

That is not a wiring problem and no amount of bench work fixes it. It means:

| | Rows | Status |
|---|---|---|
| **Group A** — electrical, no firmware | 9 | **Runnable now** |
| **Group B** — protocol and lifecycle | 32 | **Runnable now**, on a flashed device |
| **Group C** — measurement, switches, teach | 26 | **Blocked** until integration stage D |
| **Group D** — environmental | 5 | Needs a climate chamber |
| **Group E** — build-time | 3 | Already automated in `software/hil/acceptance/` |

Group C is not deferred by choice. Attempting those rows against the current
image will produce failures that mean nothing.

---

## 3. Equipment and setup

| Item | Purpose | Status |
|---|---|---|
| WCH-LinkE | Flash and debug over SWIO | **Verified working** 2026-08-08 — `mode:RV version 2.15`, target examined, `misa=0x40800014` |
| Bench PSU, 24 V, adjustable ±15 % | Sensor supply and PoE feed; Group A and the tolerance rows | Required |
| DMM, 4½ digit | Node voltages; 1 mV resolution matters for the §4.4 bands | Required |
| **ADALM2000 (M2K)** | Stimulus *and* the raw RS-485 master — see §3.2. Also a 16-channel logic analyser, so it covers the timing rows until the Saleae arrives | **Available.** `libm2k` in a Python 3.11 venv; `m2k_smoke.py` proves the link |
| Saleae Logic16 | Preferred observer for the FR-MB timing rows | **Connected and verified** 2026-08-08 — device `94BAD48182A91BFD` visible over the Logic 2 MCP bridge. Probe map in §3.5 |
| Hot-air source or hair dryer | TP-A01, the blocking leakage test | Required |
| Precision resistance box or 10 k pot | Stands in for the draw-wire in Group C | For stage D |

### 3.1 DUT configuration

**The DUT is a breadboard build — there is no PCB.** That is not a caveat to
apologise for; it is the correct order, because TP-A01 gates the layout. But
it changes what some rows mean:

- **Every node is accessible.** No test points needed, no clip-to-SOIC-pin.
- **The rig is now a suspect.** A breadboard has its own leakage and its own
  intermittent contacts, and both can masquerade as device behaviour. TP-A00
  exists because of this.
- **The wiper node is the vulnerable one.** §4.6 requires >10 MΩ from that
  node to any rail, and a used breadboard with flux or finger grease across a
  few rows can be far below that. Long jumpers on a 2.5 kΩ node also pick up
  noise that a ground-planed PCB would not. Expect the wiper to look worse
  here than it will on a board — and do not tune anything to compensate.
- **Contact intermittency looks exactly like a sensor fault.** Before
  believing any FR-E07 or switch-band anomaly, reseat and re-measure.

- **Build:** `encoder` (build byte `0x01`) for everything except TP-B21/B22,
  which need `encoder_test` for the FR-S20 hang hook.
- **Address:** 40 with the PC1 jumper open, 45 bridged. 9600 8N1.
- **Never ship `encoder_test`** — `platformio.ini` says so and it carries the
  watchdog hang trigger at holding `0x00FF`.

### 3.2 The M2K raw master — how Group B gets driven

There is no USB Modbus adapter in this plan and none is needed. The sibling
project's rig, documented in [`../software/hil/README.md`](../software/hil/README.md),
drives a **second MAX3485 as a raw master** from the M2K:

```
M2K DIO0 ──► DI          second MAX3485        A/B ──► DUT bus
M2K DIO1 ──► DE + R̄Ē     (the raw master)      A/B ──► M2K scope 1+/2+
M2K V+   ──► VCC (3.3 V)
```

Bit-banging the master this way is *better* than a USB adapter for this plan,
not a workaround: it gives exact control of inter-frame timing, which is what
FR-MB20/21/23 actually test. A USB adapter hides precisely the thing under
test behind its own driver's buffering.

Four inherited lessons, each of which cost someone an afternoon:

- **Enable V+ in every script.** `ps.enableChannel(0, True)` then
  `pushChannel(0, 3.3)`. An unpowered MAX3485 sits inert and looks exactly
  like a wiring fault. The static DE/DI test — drive space, drive mark,
  release — is the ten-second proof the rig is alive.
- **A listening master never stops buffering.** It accumulates every byte
  another node puts on the shared bus, then parses the stale backlog and
  reports CRC_ERR. One throwaway read *is* the flush; retry once on
  `crc_error` before trusting a read that follows raw-master traffic.
- **Inter-frame marks must exceed t3.5 = 4.01 ms** at 9600 baud. A 2.5 ms gap
  once made the DUT correctly coalesce two frames into one discarded frame.
  The house gap is **5 ms** (48 bit times).
- **Keep M2K AWG outputs 0–3.3 V** near the DUT. The hardware can swing ±5 V,
  which is beyond CH32V003 absolute maximums.

All grounds common — M2K, Saleae, LinkE and DUT.

### 3.3 Two M2K limits that bite this plan specifically

- **Scope inputs are ±25 V.** The +15 % supply case is **27.6 V and exceeds
  them.** TP-A03 and TP-A08 must be measured with the DMM, not the M2K scope.
- **The M2K supplies are ±5 V at ~50 mA** and cannot feed the 24 V rail at
  all — two sensors alone draw 20 mA at 24 V. The bench PSU owns that rail.

### 3.4 Programming power rule — read before connecting

The SOP-8 package has **no NRST**, so power-cycling is the only recovery path
from a wedged debug interface. J2 pin 3 carries 3V3, and so does the board.

> **Either** remove the 24 V feed and let the LinkE supply 3V3 through J2,
> **or** keep the 24 V feed and leave the LinkE's 3V3 disconnected.
> Never both, and never neither.

Getting this wrong parallels two supplies *and* removes the LinkE's ability to
power-cycle the target — precisely when you would need it.

### 3.5 Probe map

Four digital channels tell the whole Modbus story: what the master sent, when
it released the bus, what the DUT saw, and when the DUT drove. Ground common
throughout; Saleae threshold set for **3.3 V logic**.

| Ch | Signal | Connect to | Gives you |
|---|---|---|---|
| **0** | `MB-TX/RX` | **U2 pin 1 or 4** (= U1 pin 1) | Both directions of the conversation — RO and DI are tied for half-duplex. Decode as **UART 9600 8N1**. |
| **1** | `MB-RE/DE` | **U2 pin 2 or 3** (= U1 pin 6) | When the DUT takes and releases the bus — TP-B14 and TP-B24. |
| **2** | raw-master `DI` | **M2K DIO0** | What the master actually put on the wire. |
| **3** | raw-master `DE/RE` | **M2K DIO1** | When the master released. Paired with ch 1 this measures t3.5 directly. |
| GND | — | **U2 pin 5** or **J2 pin 1** | J2 is a 2.54 mm header and is the tidiest ground tap. |

`U2` is the MAX3485 in SOIC-8, easier to reach than the MCU's SOP-8 — though
on the breadboard either is a jumper away.

**Do not put the Saleae on RS-485 A/B.** They are differential and, with the
20 k bias pair and the 120 Ω termination, idle near mid-rail; a digital
threshold there yields frame boundaries at best. **A/B → M2K scope 1+/2+** for
the analog wire view. The split is deliberate: Saleae observes logic, M2K
observes the line.

For the programming interface rather than the bus, probe `SWIO` on **J2 pin 2**
(or U1 pin 8) with ground on **J2 pin 1**.

#### Reference pinouts

| U2 — MAX3485 | | U1 — CH32V003J4M6 | | J2 |
|---|---|---|---|---|
| 1 `RO` → MB-TX/RX | 5 `GND` | 1 `PD6/PA1` MB-TX/RX | 5 `PC1` ADDRESS | 1 `GND` |
| 2 `R̄Ē` → MB-RE/DE | 6 `A` | 2 `VSS` | 6 `PC2` MB-RE/DE | 2 `SWIO` |
| 3 `DE` → MB-RE/DE | 7 `B` | 3 `PA2` WIPER | 7 `PC4` ENDSW | 3 `3V3` |
| 4 `DI` → MB-TX/RX | 8 `VCC` | 4 `VDD` | 8 `PD1` SWIO | |

---

## 4. Group A — electrical, no firmware required

Run these first. TP-A01 is the item gating the PCB.

| ID | Traces to | Procedure | Pass criterion |
|---|---|---|---|
| **TP-A00** | §4.4.4 | **Run this before TP-A01.** Verify the rig before trusting any reading from it: R5 continuity to 0 V, R6 to the summing node, R10 **absent**. Then unplug both sensor outputs from R8/R9 and measure PC4. | **≤ 5 counts (≈0.016 V).** *(Executed 2026-08-08 — **FOUND TWO FAULTS**: R10 still fitted and R5 floating. Every measurement taken before the fix was of a circuit that was neither the schematic nor a divider, and all of it was discarded. This row earned its place on first use — and again afterwards, when its own criterion caught the MCU pull-up on PC4 that had survived every rig fix. Passed on the fourth attempt at −20 mV.)* |
| ~~**TP-A01**~~ | TDS §6, §4.4.4 | **WITHDRAWN 2026-08-08 — there is no leakage to heat.** The 33 µA it was written to characterise was the MCU's pull-up on PC4, not the sensors, which move PC4 by 0.9 mV between connected and disconnected. Retained here only so the withdrawal is visible. Original procedure: Disconnect sensor B. With sensor A powered and inactive, record PC4 at room temperature. Warm the sensor body by ~20 °C (hot air, low; measure the case). Record PC4 every 5 °C. | PC4 rises by **less than 30 %** over the sweep → the 35 µA is an internal bleeder, §4.4 stands. A steep climb → junction leakage, and §4.4.2's values need re-deriving with a smaller `Rs` and a lighter load. **Record the curve, not just the verdict.** |
| **TP-A02** | §4.4.3 | With both sensors connected and powered, measure PC4 in all three states: neither active, each one active separately, both active. | Within **±5 %** of −0.019 / 1.291 / 2.210 V. *(Executed 2026-08-08, final set: −0.019 / 1.291 / 1.292 / 2.210. `Von` = 23.09 V from three independent routes agreeing to 0.2 %.)* |
| **TP-A03** | §4.4.4 | Sweep the sensor supply 20.4 → 27.6 V. Record PC4 for one-active and both-active at each end. | One active ≤ 462 counts and both active ≥ 582 counts, i.e. the 522 threshold is not crossed from either side. **BLOCKED 2026-08-08 — no adjustable PSU available.** This matters more than a skipped row usually would: the ±15 % supply margin is the *tightest number in the design* (≈60 counts at `SW_TH_BOTH`) and it is currently **calculated, not measured**. It also leaves open whether the 1.01 V output drop is constant or scales with the rail, which is what the sweep would have settled. Needs a bench supply, or a series element to drop the rail for the low end. |
| **TP-A04** | FR-E21 | Apply **+27.6 V** to each J4 pin in turn for 60 s. Measure the current into PA2. | ≤ **4 mA** (CH32V003 absolute maximum, datasheet §3.2). Device undamaged; the wiper reads correctly after removal. |
| **TP-A05** | FR-E21, §4.6.1 | Measure the mid-scale wiper code with D3 fitted and unfitted, at room temperature and at +70 °C. | Difference ≤ **1 count**. This is the PESD5V0S1BA leakage figure no datasheet answers at 3.3 V and +70 °C. |
| **TP-A06** | §4.3, FR-E11 | With the draw-wire at mid-travel, verify the wiper is fed from 3V3 and that PA2 tracks it ratiometrically: vary 3V3 by ±5 % and observe the *ratio*. | The wiper/3V3 ratio changes by < 0.2 %. Confirms nothing has broken ratiometric operation. |
| **TP-A07** | §4.6 | Measure insulation from the wiper node to each rail, board clean and dry. | > **10 MΩ** — the §4.6 rule. Below that, conformal coating is not optional and the board is already out of budget. |
| **TP-A08** | §4.1 | Measure the 3V3 rail and total board current at 20.4 / 24 / 27.6 V input. | 3V3 within 3.1–3.4 V at all three. Record the current for the PoE budget. |
| **TP-A09** | §4.4 | Confirm both sensors are wired **star** — one cable each to the hub, summing on the PCB — and that R10 is absent. | Visual against the §4.4.2 schematic. A field junction here would invalidate every Group C switch row. |

---

## 5. Group B — protocol and lifecycle, on a flashed device

Everything here works against the **current** image. This is the largest body
of verification available before stage D, and none of it needs the measurement
path.

### 5.1 Boot and identity

| ID | Traces to | Procedure | Pass criterion |
|---|---|---|---|
| TP-B01 | FR-S01 | Power on. Poll 30007 (identification). | Reports build byte `0x01` and the firmware version. One release build only. |
| TP-B02 | FR-S03, FR-MB07 | Read the device at address 40 with JP6 open. Power down, bridge JP6, power up, read at 45. | Responds only at the expected address in each case. Changing the jumper while running has **no** effect until reset. |
| TP-B03 | FR-S02 | Time from power-on to first valid response. | Within the FR-S02 budget. |
| TP-B04 | FR-S32 | Read 30007 across a power cycle. | Identical both times. |
| TP-B05 | FR-S34 | Read 30008 (uptime) at intervals over 10 min. | Monotonic, whole seconds, starts at 0 after reset. |

### 5.2 Modbus contract — FR-MB01…FR-MB30

The full protocol row set is inherited from the sibling project's TDS v0.9,
where every row is HIL-verified against the same driver binary. Re-run rather
than assume: the address, the register map and the build differ.

| ID | Traces to | Procedure | Pass criterion |
|---|---|---|---|
| TP-B06 | FR-MB01, FR-MB08, FR-MB09, FR-MB10, FR-MB11 | FC03, FC04, FC06, FC16 against valid addresses. | Correct data, correct byte count, correct CRC. |
| TP-B07 | FR-MB25 | Inspect data byte order and CRC byte order on the wire. | **Big-endian data, little-endian CRC.** |
| TP-B08 | FR-MB19 | Write out-of-range values to each holding register (below min, above max). | Exception code 3; the stored value is unchanged. |
| TP-B09 | FR-MB22 | FC16 spanning 40002 and 40003 such that the pair is valid but each intermediate state is not. | Accepted — atomicity judged on the result, not the intermediate. |
| TP-B10 | FR-E06 | FC16 writing 40005/40006 closer than `CAL_MIN_SPAN` (64 counts). | Rejected, both values unchanged. |
| TP-B11 | FR-MB05, FR-MB06 | Frame addressed to another device (247); broadcast frame (address 0) carrying a write whose effect is observable. | Silence for both. The broadcast must **not be executed** — a follow-up unicast read shows the register unchanged. This is a deliberate deviation from Modbus-over-Serial-Line V1.02 §2.2, stated in FR-MB06; the pass criterion is *not* the specification's. |
| TP-B12 | FR-MB02, FR-S35 | Frame with a deliberately bad CRC. | No response within 200 ms; **30009 increments by exactly one** and 30010 does not move. |
| TP-B13 | FR-MB13 | Read a non-existent register address. | Exception code 2. |
| TP-B14 | FR-MB20/21 | Logic-analyser capture of turnaround and response latency across 1000 polls. | Within the FR-MB20/21 budgets; histogram recorded. |
| TP-B15 | FR-MB03 | Inter-frame idle (t3.5) at 9600 baud. | Frames separated correctly; no merged frames under back-to-back polling. |
| TP-B16 | FR-S35 | Read 30009 and 30010 after a known mix of good and bad frames. | Counts match the frames sent exactly. |
| TP-B17 | §2.7, FR-MB08 | Read every input register 30001–30015. | All present; measurement registers return their FR-S23 pre-first-window value (see §6 — this is expected, not a fault). |
| TP-B18 | §2.8, FR-MB09 | Read every holding register 40001–40007 after a factory reset. | Defaults match §2.8: 0 / 1000 / 10 / 10000 / 0 / 1023 / 0. |
| TP-B25 | FR-MB12 | Send FC01, FC02, FC05 to the DUT's address. | Exception **01** for each. |
| TP-B26 | FR-MB14 | FC04 read whose range spans the map edge (e.g. 12 registers from 30010). | Exception **02** for the whole request; **no partial data**. |
| TP-B27 | FR-MB15 | FC06 write to an unimplemented holding address (raw 0x0020). | Exception **02**; no register changes. |
| TP-B28 | FR-MB30 | Capture the FC06 and FC16 success responses. | FC06 response is **byte-identical** to the request. FC16 response PDU after the function code is exactly starting-address then quantity — **not** the register data. |
| TP-B29 | FR-MB21 | 1 000 FC04 requests at 50 ms spacing, default configuration. | ≥95 % of responses start within **15 ms** of the last request byte; 100 % within the FR-MB20 100 ms limit. Histogram recorded. |
| TP-B30 | FR-MB18 | Collect every exception response produced across Group B. | Only codes **01, 02, 03** ever appear. No vendor-specific codes. |
| TP-B31 | FR-MB17 | Every valid addressed request issued in Group B. | The DUT is never silent on one — a normal or exception response always arrives. |
| TP-B32 | FR-MB04 | Scope PC2 (DE) against the bus during a response. | DE asserted before the first transmitted byte and released after the last, each within one character time (≈1.15 ms). |

### 5.3 Persistence, watchdog and supply

| ID | Traces to | Procedure | Pass criterion |
|---|---|---|---|
| TP-B19 | FR-S39 | Write non-default values to all six persisted holdings. Power-cycle. Read back. | All six survive. 40007 (teach) reads **0** — deliberately not persisted. |
| TP-B20 | FR-S39 | Repeat 20 power cycles, cutting power at random points including mid-write. | No corruption; the ping-pong store always yields a valid record. |
| TP-B21 | FR-S20 | **`encoder_test` build.** Write magic `0xDEAD` to holding `0x00FF` to stall the loop. | IWDG resets the device within the FR-S20 timeout. |
| TP-B22 | FR-S21 | After the TP-B21 reset, read all registers. | Defined state: holdings restored from flash, measurement registers at their pre-first-window values, status bits 0 and 1 set. |
| TP-B23 | FR-S22 | Ramp the supply down slowly until PVD trips. | Device resets cleanly rather than executing at an undefined rail. |
| TP-B24 | FR-S18/S19 | Capture the RS-485 bus from power-on with the analyser. | DE/RE is low (receiver enabled, driver off) from the first instant; no bus disturbance during boot. |

---

## 6. Group C — blocked until integration stage D

**Do not run these against the current image.** `main.c` never calls
`regs_publish_opening()` or `regs_publish_switches()`, so every row here would
fail for a reason that has nothing to do with what it tests.

Blocked rows, by what unblocks them:

| Unblocked by | Requirements |
|---|---|
| Stage D — encoder driver + measurement service | FR-E01, E02, E03, E04, E05, E07, E09, E11, E12, E13, E17, FR-S17, FR-S23, FR-S24, FR-S30, FR-S36 |
| Stage D — switch sampling wired to `regs_publish_switches()` | FR-E14, E15, E16, FR-S33 |
| Stage D + a calibrated rig | FR-E18, E19 (teach handshake — needs both ends actually reached) |
| Stage E — averaging engine | FR-E06, E08, E10, E20, FR-S31 |

When stage D lands, the highest-value rows are:

- **FR-E16 negative tests.** Disconnect one sensor cable; short the switch
  input to 0 V. Both must leave bit 4 **clear** and report no stop. These
  confirm documented limits rather than contradicting them, and they are the
  only evidence that the limits are understood.
- **FR-E14** against the TP-A02 band voltages, at both NFR-ENV01 extremes.
- **FR-E19** teach handshake: bit 5 clears only when both ends have been
  reached *and* both captured values read back.
- **FR-E03** end-to-end accuracy against an independently measured opening —
  which needs the window emulator ([`windowEmulator.md`](windowEmulator.md)).

---

## 7. Groups D and E — environmental and build-time

| ID | Traces to | Note |
|---|---|---|
| TP-D01…D05 | NFR-ENV01…05 | Climate chamber. NFR-ENV01 is now **−25…+70 °C**; the +70 °C figure is inherited from the sibling project's part set and is an assertion until this row runs. |
| TP-E01 | NFR-RES01 | Automated — `software/hil/acceptance/test_builds.py`. Currently 3 704 B flash / 620 B RAM against 14 336 / 1 792 ceilings. |
| TP-E02 | NFR-BLD01 | Automated, opt-in: `pytest -m reproducible`. |
| TP-E03 | NFR-TST01 | Host suite: 38 cases in `software/firmware/test/test_scale.c`, all passing. |

---

## 8. What is deliberately not tested, because it cannot be detected

Writing a test for these would produce a permanent failure that is not a
defect. They are documented limits, and the *negative* tests in §6 are how we
show we know about them.

- **An open sensor cable.** With a PNP normally-open output, *inactive*,
  *cable open* and *shorted to 0 V* are one electrical condition (§4.4.6). The
  device reports "between the stops" and cannot know better.
- **A broken +V conductor to a sensor.** Same signature.
- **Which end switch operated.** Both sum through identical 68 kΩ resistors;
  the states differ by 2 counts of resistor tolerance (§4.4.5). The position
  registers answer this instead.
- **A slipped draw-wire.** No position sensor can detect it — it produces a
  plausible wrong reading. The defence is controller-side
  commanded-versus-measured divergence (`requirementsCompliance.md` FR-WP16).

---

## 9. Known gaps in this plan

- ~~The raw-master scripts do not exist yet.~~ **Written 2026-08-08.**
  `software/hil/modbus_rtu_codec.py` (framing, CRC, 8N1 codec) is pure Python
  and passes 20/20 host tests; `software/hil/m2k_master.py` drives it from M2K
  DIO. The transport is smoke-tested against a real M2K — open, configure,
  push, capture, and the transmitted buffer decodes back to the exact frame.
  **What remains is physical**: the second MAX3485 has to be wired per §3.2,
  and `m2k_master.py --selftest` is the ten-second proof it is alive before
  any Group B row is attempted.
- ~~The Saleae is not connected yet.~~ **Resolved 2026-08-08** — the Logic16
  is visible over the MCP bridge (`94BAD48182A91BFD`). TP-B14, TP-B15 and
  TP-B24 can use it directly, with the M2K driving as raw master.
- **No factory-reset procedure is defined**, which TP-B18 assumes. Erasing
  flash via the LinkE is the obvious route; write it down once it is used.
- **Every Group A result carries a breadboard caveat** until it is repeated on
  a PCB. TP-A00 separates rig leakage from sensor leakage; nothing separates
  breadboard noise on the wiper from real noise except repeating TP-A06 and
  TP-A07 on a board. Record which rows were taken on which hardware.
- **TP-A05 needs +70 °C**, so it belongs with Group D rather than the bench —
  unless a hot-air source with a thermocouple is judged adequate.

---

*End of test plan v0.1 (2026-08-08). Group A is runnable today and TP-A01 gates
the PCB. Group B is runnable as soon as a Modbus master exists. Group C is
blocked on integration stage D, and saying so is the point of this document.*
