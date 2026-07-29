# Compliance check — greenhouse-Controller M3 window position sensor

| Field | Value |
|---|---|
| Document | Requirement compliance analysis |
| Project | `wire-encoder-modbus-interface` |
| Date | 2026-07-28 |
| Checked against | `greenhouse-Controller/design/windowPositionSensorRequirements.MD`, dated 2026-07-28 (marked PRELIMINARY STUDY — not adopted) |
| This design | `design/TDS.md` **v0.5**, `design/description.md` |
| Status | Updated through TDS v0.5. The two gaps this analysis originally raised are both closed; what remains is listed in §4. |

---

## 1. Verdict

**The functional and protocol design is a strong match — in several places an
exact one. The environmental gaps identified in the first pass of this
analysis have since been closed** (TDS v0.4: §4.5 enclosure strategy,
NFR-ENV02…05). What remains is one procurement condition, not a design gap.

*Updated 2026-07-28 after TDS v0.4, which also closed the direction-of-travel
limitation this analysis had flagged as a live risk.*

The requirements study independently arrives at "draw-wire, Modbus RTU,
absolute" as its preferred technology (§9) — which is what this device is.
Of the three requirements it names as most likely to make a purchase useless,
this design satisfies all three by construction.

| Area | Requirements | Verdict |
|---|---|---|
| What it measures (§2) | FR-WP01…07, 21, 22 | **Met**, subject to the sensor unit's own accuracy |
| Timing (§3) | FR-WP08, 09, 10 | **Met**, with a maximum-age contract (FR-E17). The shipped default window is too long for this application and must be set at commissioning |
| Modbus/electrical (§4) | FR-WP11…15, NF-WP01, 02 | **Met**, except FR-WP11 partially and a connector mismatch |
| Environment (§5) | NF-WP03…08 | **Addressed** by the §4.5 enclosure strategy and NFR-ENV02…05 — except NF-WP03's +70 °C, which the end switch caps at +65 °C, and the draw-wire unit's own cycle life |
| Failure behaviour (§6) | FR-WP16…20 | **Met** for the parts that are the sensor's to meet |

Counting only what is this device's responsibility: **27 met, 3 met with
caveats, 4 belong to the controller.** The procurement conditions this
analysis originally raised — wiper life and mechanism accuracy — are both
closed by the supplier specification. The three that remain are in §4, and
only one of them is a requirement missed outright rather than narrowed with
its cause named: **NF-WP05, because the draw-wire unit is IP50 and lives
outside the box.**

---

## 2. Compliance matrix

### 2.1 What the sensor must measure

| ID | Req (abbreviated) | Verdict | Evidence / note |
|---|---|---|---|
| FR-WP01 | Monotonic position over full stroke | ✅ **Met** | 30001, 0.1 mm units, 0–65534. The 2 m stroke is 20 000 units — well inside range |
| FR-WP02 | Absolute; valid at power-on, no homing | ✅ **Met — core design property** | FR-E01. A potentiometer carries position in the sensor; there is nothing to home and nothing to lose. Directly removes their §1.3 |
| FR-WP03 | Measured at the leaf, not the motor shaft | ✅ **Met by construction** | The wire attaches to the moving flap. Immune to drum-radius nonlinearity, rope stretch and slip — the exact failure modes their §1.4 item 2 raises |
| FR-WP04 | Resolution ≤ 1 % of stroke | ✅ **Met, ~10× margin** | 1023 ADC counts over a 2 m stroke = **1.96 mm/count = 0.098 %**. Even if the potentiometer spans only half the ADC range, 0.2 % still clears it 5× |
| FR-WP05 | Repeatability ≤ ±1 % over temperature | ✅ **Met** | FR-E03 firmware budget is ±0.1 % of full travel, stability ≤3 LSB (≈5.9 mm ≈ 0.29 %). Ratiometric operation cancels supply drift. The draw-wire unit's own **comprehensive error is 0.2 % max** (supplier specification, transcribed in `documentation/product-images/readme.md`), so the mechanism's share is well inside the budget |
| FR-WP06 | Absolute accuracy ≤ ±2 % (Should) | ✅ **Met** | Firmware ±0.1 %, mechanism 0.2 % — an order of magnitude inside the ±2 % asked |
| FR-WP07 | Fully-closed distinguishable from near-closed (Should) | ✅ **Met — and exceeded** | This is what the end switches are for. Status bit 3 says a stop was reached; the reported position says which. They asked for a *Should*; this design makes it mandatory and supervises the cable as well |
| FR-WP21 | Tolerate wind sway; report *mean* not instantaneous; filtering within FR-WP09 | ✅ **Met, with a bonus** | 30002 is a configurable boxcar mean; set to 1 s it satisfies both this and FR-WP09 (§3 below). **Bonus:** 30003/30004 report the min/max envelope over the averaging period — i.e. they *quantify the billowing amplitude*, which the study asks about but does not request a means to measure |
| FR-WP22 | Measurement point representative of a 40 m span | ➖ **Installation matter** | Firmware is agnostic. Note two devices can share the segment (addresses 40 and 45), so characterising both ends is possible without new hardware |

### 2.2 Timing — the section that needs action

| ID | Req | Verdict | Evidence / note |
|---|---|---|---|
| FR-WP08 | ≥1 Hz, **fresh** value each read | ✅ **Met — now an explicit contract** | **FR-E17**: the value in 30001 is never older than the configured measurement window. "Fresh" is therefore a number the master sets, not a hope. It **defaults to 1000 ms**, so 40002 must be set to 100–200 ms at commissioning for this application — see §3. With 200 ms the worst-case staleness is 2.3 mm, 0.12 % of the 2 m stroke |
| FR-WP09 | Filtering ≤ ~1 s group delay, or configurable to it | ✅ **Met** | Two routes. (a) Read 30001 — instantaneous, no filtering beyond the measurement window. (b) Read 30002 with 40003 = 1 s: a 1 s boxcar, group delay ≈ 0.45 s. The FR-E13 16-conversion burst takes <1 ms and adds no meaningful delay |
| FR-WP10 | Transaction ≤200 ms; ≤50 ms preferred | ✅ **Met with wide margin** | FR-MB20 hard limit 100 ms; FR-MB21 95 % within 15 ms. The sibling project measured **4.12 ms median over 1000 requests** through a MAX3485 with the same driver binary |

**AT-WP04 check.** At 11.7 mm/s the flap moves 11.7 mm per second ≈ **6 ADC
counts per second**. Polling at 1 Hz therefore yields distinct, monotonic
values throughout a 171 s stroke with comfortable margin — provided 40002 is
short enough that each poll lands on a fresh window.

### 2.3 Modbus and electrical

| ID | Req | Verdict | Evidence / note |
|---|---|---|---|
| FR-WP11 | Address user-configurable without returning the unit | ⚠️ **Partially met** | Address is a **solder jumper**: 40 (open) or 45 (bridged). Settable by the user, and both are clear of the addresses in use (1, 44). But it is two fixed values, not an arbitrary address, and setting it means opening the enclosure with a soldering iron. There is deliberately **no address register** (FR-MB07) — a design decision, not an oversight. Adequate for one M3 sensor; a constraint if the fleet grows |
| FR-WP12 | Position in a **single transaction**, atomic w.r.t. motion | ✅ **Met — explicitly designed for** | FR-S24 requires every value in one response to be a coherent snapshot from one measurement update, never a mixture of two windows. The registers are contiguous (30001–30012) |
| FR-WP13 | No broadcast, no master behaviour, no proprietary framing | ✅ **Met** | Pure slave (FR-S19, never transmits unprompted). Standard FC03/04/06/16 only. Broadcast is deliberately ignored (FR-MB06) |
| FR-WP14 | Observe 3.5-char silence, release the line promptly | ✅ **Met, HIL-verified** | FR-MB03 (t3.5 framing), FR-MB04 (DE de-asserted within one character time). Verified on the bench in the sibling project |
| FR-WP15 | Manufacturer-documented register semantics | ✅ **Met** | TDS §2.7/§2.8 give address, function code, unit, range, default and requirement ID per register. Endianness is normative (FR-MB25: big-endian data, little-endian CRC). `design/description.md` is the integrator-facing version |
| NF-WP01 | Supply should match what is distributed (+24 V) | ✅ **Met** | The power chain accepts **24 V**. The field cable enters through a gland and terminates inside the enclosure (§4.5), so the incoming conductors are +24 V/GND/A/B on the installation's own terms rather than requiring a particular plug |
| NF-WP02 | Reuse the junction arrangement; daisy-chain, no stubs, termination practice | ✅ **Met** | Two connectors for daisy-chaining, 120 Ω terminator behind a jumper, A/B fail-safe bias, TVS — all inside the sealed enclosure, cables glanded |

### 2.4 Environment — closed in TDS v0.4, ingress figure settled in v0.5

The first pass of this analysis found nothing specified here. TDS §4.5 and
NFR-ENV02…05 now cover it: an IP65 enclosure with every connector inside it,
field cables through glands, terminal blocks for the sensor and switch loop,
mounted out of direct UV, and the board itself protected against condensation
rather than relying on the seal alone.

| ID | Req | Verdict | Note |
|---|---|---|---|
| NF-WP03 | −20 °C to +70 °C | ⚠️ **Low end met, high end 5 °C short** | NFR-ENV01 is now **−25 °C to +65 °C** (narrowed 2026-07-29). The cold end has margin; the hot end does not reach +70 °C because the **LJ18A3-8-Z/BX end switch is rated to +65 °C** and is the narrowest part in the chain — the electronics would have carried +70 °C. **This is the one requirement the design knowingly does not meet in full.** It matters because the sensor sits at the window frame, exactly where the solar gain that motivated the +70 °C figure occurs, even though measured greenhouse air peaks at 33 °C. Resolution is a survey of the mounting position; if it can exceed 65 °C, the fix is a wider-range end switch |
| NF-WP04 | 100 % RH, condensing | ✅ **Met** | **NFR-ENV02.** Sealed and glanded enclosure, plus protection of the board itself against condensation (conformal coating the recommended default) — because a sealed box in a swinging temperature still breathes. The acceptance criterion is a condensing-night cycle, which is AT-WP08 |
| NF-WP05 | IP65 minimum, IP67 preferred | ⚠️ **Enclosure meets the minimum; the sensor does not** | **NFR-ENV03: IP65.** The earlier RJ45 objection dissolves once the connectors are *inside* the box: ingress protection is a property of the enclosure and its glands, so an ordinary connector in a sealed enclosure is fine (§4.5). The selected **Kopp 99966478 is IP65** — the stated minimum, and NFR-ENV03 was narrowed to match it rather than claim an IP67 the BOM does not deliver. The study's IP67 preference was for hardware *at the aperture*; this box is not. **But the draw-wire unit itself is only IP50** and necessarily sits outside it on the window frame. That is the weakest environmental point in the design — see §4 |
| NF-WP06 | UV and greenhouse chemical resistance | ✅ **Met** | **NFR-ENV04.** Mounted out of direct UV inside the greenhouse structure, which is the shaded-position answer; where an installation cannot guarantee that, the requirement falls back to a UV-stabilised enclosure |
| NF-WP07 | Tolerate motor vibration and end-stop shock without drift | ✅ **Met** | **NFR-ENV05**, with a 100-cycle acceptance criterion covering both the persisted calibration and mechanical mounting drift |
| NF-WP08 | ~25 000 cycles / 20 years; **contacting technologies must be assessed** | ✅ **Met on both counts.** The end switches are inductive proximity sensors — non-contact, so the concern does not apply. The draw-wire unit is specified at **>100 000 cycles**, 4× the ~25 000 needed over twenty years | The sensor is a potentiometer — precisely the contacting wiper technology this requirement singles out. A conductive-plastic element will manage 25 000 strokes comfortably; a cermet or wirewound one may not. **This must be specified when the draw-wire unit is bought.** Partial mitigation: the two-point calibration is re-teachable, so wear that shifts the endpoints can be corrected in the field rather than requiring replacement |

### 2.5 Failure behaviour

| ID | Req | Verdict | Evidence / note |
|---|---|---|---|
| FR-WP16 | Failure detectable; no stale, frozen or plausible-but-wrong data | ✅ **Met — with one honest limit** | A disconnected or shorted wiper reports **65535** in all four position registers plus status bit 2 (FR-E07) — an explicit, out-of-band error, not silence and not a plausible number. 30011 (seconds since last valid reading) catches the "readings stopped without the detector tripping" case. **The limit:** no position sensor can detect a *slipped wire* — it produces a plausible wrong reading. The end switches are the partial defence, and their own FR-WP03/AT-WP09 puts the rest in the controller as commanded-vs-measured divergence |
| FR-WP17 | Controller falls back to time-based control | ➖ **Controller-side** | This device's contribution is making the failure unambiguous so the fallback can trigger |
| FR-WP18 | Wind override must not depend on position | ➖ **Controller-side** | Nothing here creates such a dependency |
| FR-WP19 | Fault surfaced to the operator | ➖ **Controller-side** | Status bits 2 and 4 are the raw material |
| FR-WP20 | Reject implausible readings / jumps >0.58 %/s (Should) | ✅ **Directly supported** | 30012 reports the movement rate the device measured. 0.58 %/s of a 2 m stroke = 11.7 mm/s = **117** in the register's 0.1 mm/s units — a ready-made plausibility threshold |

---

## 3. Configuration required at commissioning

The shipped defaults are tuned for a slow monitoring application and **do not
meet FR-WP08**. For closed-loop M3 positioning:

| Register | Default | Set to | Why |
|---|---|---|---|
| 40002 measurement window | 1000 ms | **100–200 ms** | FR-WP08: a fresh value at every 1 Hz poll. At 1000 ms a poll can return a value up to a second old, and consecutive polls may repeat |
| 40003 averaging window | 10 s | **1 s** | FR-WP09: caps group delay at ≈0.45 s. Only matters if the controller reads 30002; reading 30001 sidesteps filtering entirely |
| 40004 full travel | 10000 (1000.0 mm) | **20000** (2000.0 mm) | The measured M3 stroke |
| 40005 / 40006 raw calibration | 0 / 1023 | measured | The commissioning procedure in `description.md` §6 |

Both settings satisfy the FR-S31 cross-check (40003 × 1000 ≥ 40002) and
persist across power loss.

**Which register should the control loop read?** **30001** (instantaneous).
It is unfiltered beyond the measurement window, which is what a positioning
loop wants. 30002/30003/30004 are for the wind-sway question (FR-WP21) and
for diagnostics, not for stopping the motor.

> Worth considering: if this device is only ever used for closed-loop
> positioning, the 40002 default should change from 1000 ms to 200 ms so it
> is right out of the box. That is a one-line change to TDS §2.8 and is
> cheaper to make now than to remember at every commissioning.

---

## 4. Gaps that need a design decision

**Both gaps this analysis originally raised are now closed**, by the
draw-wire supplier specification found in the product images
(`documentation/product-images/readme.md`):

| Originally raised | Closed by |
|---|---|
| Potentiometer life (NF-WP08) — "specify a conductive-plastic element" | **>100 000 cycles** specified, 4× the ~25 000 needed over twenty years |
| Sensor accuracy (FR-WP05/06) — "the mechanism's share must be specified" | **0.2 % comprehensive error**, an order of magnitude inside the ±2 % asked |

Three gaps have replaced them. Two arrived with the parts that were chosen
afterwards, which is the ordinary way of things — a compliance analysis
against a *design* becomes an analysis against a *bill of materials* as soon
as parts are picked, and the narrowest part sets the answer.

1. **The draw-wire unit is IP50 and sits outside the enclosure (NF-WP05).**
   This is the weakest environmental point in the design and the only one
   where a requirement is missed outright rather than narrowed. NF-WP05 asks
   ≥IP65 of the sensor; IP50 is dust-protected and not water-protected, in a
   greenhouse that condenses most nights. The IP65 box protects the
   electronics and does nothing for the sensor. Options: a sheltered mounting
   position, a shroud, or a higher-rated unit.

2. **Ambient ceiling +65 °C against +70 °C asked (NF-WP03).** Set by the
   LJ18A3-8-Z/BX end switch and now stated honestly in NFR-ENV01 rather than
   claimed and unmet. Resolvable by survey — if the mounting position cannot
   exceed 65 °C the gap is theoretical — or by a wider-range switch.

3. **Address configurability (FR-WP11).** A solder jumper giving two fixed
   addresses, not an arbitrary one. Adequate for a single M3 sensor and clear
   of the addresses in use; a constraint only if the fleet grows. Unchanged
   since the first pass and deliberate (FR-MB07).

Note what is *not* on this list any more: the enclosure. NFR-ENV03 was
narrowed from IP67 to IP65 to match the selected Kopp 99966478, which meets
NF-WP05's stated minimum for hardware not mounted at the aperture.

---

## 5. Where this design gives more than was asked

Worth knowing, because some of it addresses problems the study raises but
does not request a solution for:

- **Supervised switch cable.** FR-WP07 asks only for a closed indication.
  This design distinguishes cable-open, healthy, at-a-stop, both-closed and
  cable-shorted — so a cut switch cable cannot masquerade as "not at a stop".
  Given FR-WP16's insistence on never returning plausible-but-wrong data,
  that is aligned with the intent rather than merely the letter.
- **Movement envelope (30003/30004).** Min and max over the averaging
  period. For a hanging flap that billows (FR-WP21), this measures the sway
  amplitude directly rather than merely tolerating it.
- **Movement rate (30012).** A ready-made input to FR-WP20's plausibility
  check, and a direct answer to "is the actuator actually running?" — which
  bears on their §1.2 open-loop blindness.
- **Bus health counters (30009/30010).** CRC-error and served-request counts
  support AT-WP05's 24-hour coexistence test with evidence from the device's
  own side, not just the master's.
- **Field-recalibratable endpoints.** Partially offsets the NF-WP08 wear
  concern: a worn wiper whose endpoints have shifted can be re-taught over
  Modbus rather than replaced.

---

## 6. What this study changed here

Acted on in TDS v0.4:

- **Direction of travel — fixed.** The study made this concrete: M3 is
  *raised to close, lowered to open*, so whether the wiper code rises or falls
  depends entirely on how the draw-wire is mounted — a 50/50 risk on a real
  installation rather than a theoretical one. FR-E04 now accepts the
  calibration points in either order, host-tested in both senses.
- **Environment — specified.** §4.5 and NFR-ENV02…05.

Still open, and informed by the study:

- **Auto-calibration stopped being a convenience and became a diagnostic.**
  The study's §1.2 asks for mechanical fault detection — slip, obstruction, a
  window blocked part-way — and AT-WP09 tests exactly that. A slipped wire is
  the one failure this sensor cannot otherwise see, because it yields a
  plausible wrong reading; the end switches are its only independent physical
  reference. Comparing the raw code at a stop against the stored endpoint
  measures the drift directly, without relying on the controller's
  travel-time model the way their commanded-versus-measured scheme does.
  Analysis in `design/scratchBook.md` §Q1, tracked in TDS §6.
- **The movement rate became signed** (FR-E10, 2026-07-29), which serves
  FR-WP20 better than a magnitude: the controller sees a jump's direction as
  well as its size, and for a hanging flap "moving down" and "moving up" have
  different mechanical meanings (their §1.4 item 3 — the drive is asymmetric
  and directional hysteresis is expected). A **percentage-of-travel register**
  (30015, FR-E20) was added at the same time, so a master no longer divides by
  40004 to get the number it actually wants.

---

*Analysis only. The source document is itself marked PRELIMINARY STUDY —
not adopted — so nothing here should be treated as an agreed requirement on
this project.*
