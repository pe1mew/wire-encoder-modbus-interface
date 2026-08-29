# Changelog

All notable changes to the Wire Encoder Modbus Interface are documented in
this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and
this project adheres to [Semantic Versioning](https://semver.org/). No
firmware release has been tagged yet — the version-byte registry lives in
[`software/firmware/RELEASES.md`](software/firmware/RELEASES.md); firmware
version 1 will be tagged `fw-v1` at the first release.

---

## [Unreleased]

### The device

Measures **how far a window is open** — a greenhouse vent, a roof light, a
louvre — and publishes it on Modbus RTU over RS-485. A draw-wire encoder
attached to the moving frame turns a **10 kΩ potentiometer**; the wiper
voltage is an absolute measure of the opening, valid the instant power
returns, with no homing move. Two end-of-travel switches report that the
window has reached a mechanical stop, read as a supervised resistor ladder
that also monitors its own cable.

### Added — project set-up

- Repository bootstrapped from the sibling
  [`windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface)
  project: same MCU (CH32V003J4M6), same RS-485 front-end, same zero-ISR
  architecture, same document structure — and, as it turns out, the same
  potentiometer-on-PA2 sensor topology, which makes that project's vane
  driver the reference implementation for this one's.
- **No wind-sensor content was carried over.** The anemometer and vane
  drivers, the circular-mean and gust machinery, the pulse-counting path and
  the wind-specific HIL scripts are all absent by design. What remains from
  the sibling project is the protocol, platform and bench infrastructure,
  plus factual provenance notes where code was inherited.

### Added — design & requirements

- Design document chain seeded: `design/README.md` (index),
  **`description.md`** (functional description in prose),
  **`requirementsCompliance.md`** (check against the greenhouse-Controller
  M3 requirements study), **`TDS.md` v0.5**, `softwareArchitecture.md`, `driverDevelopment.md`,
  `integrationPlan.md`, `scratchBook.md`.
- **`TDS.md` v0.5 — auto-calibration, and two registers that pay for
  themselves twice.**

  *Auto-calibration from the end switches* (the question asked in
  `scratchBook.md` Q1) is now specified as two cooperating halves rather than
  a single automatic behaviour, because letting a stop silently overwrite a
  calibration point would let one bad reading move every value the device has
  ever reported. **FR-E18** does the observing: whenever the switch loop
  reports a stop, the raw ADC code at that moment is captured and published in
  new input registers 30013 (closed end) and 30014 (open end). It is inert —
  the device reports what it saw and changes nothing. **FR-E19** does the
  committing, and only when told to: writing 1 to new holding register 40007
  sets status bit 5, and the bit clears only when **both** ends have been
  reached *and* both captured values have been read back over the bus. The
  read-back is the interesting part of the handshake — it makes the master's
  own confirmation a precondition, so a teach cannot complete on values nobody
  ever looked at. 40007 is deliberately **not persisted**: a teach in progress
  must not survive a power cut. The commit re-checks the 64-count minimum span,
  because an internal write bypasses the FR-MB19 range check that a Modbus
  write would have hit.

  FR-E18 raises a question the device cannot answer from the loop alone —
  *which* stop was reached, given that the §4.4 ladder resolves "a stop" and
  not "which stop", and that an uncalibrated device cannot infer it from
  position either. The **signed movement rate** settles it. Register 30012
  becomes a **signed int16** (positive = opening, negative = closing), which
  was worth doing on its own — a master can now distinguish a window opening
  from one closing without differencing successive polls — and its sign is
  also what FR-E18 uses to attribute a capture, falling back to proximity only
  when the device was stationary.

  New **FR-E20** adds **percentage of full travel** in input register 30015,
  0.1 % resolution, sharing 30001's 65535 fault sentinel. Trivially derivable
  by the master, but a window is a thing people think about in percentages,
  and putting the conversion here means one definition of "fully open" rather
  than one per client. `scale_percent()` lives in the host-tested `scale.c`
  alongside the opening arithmetic; the host suite is now **38 cases**.

- **`TDS.md` v0.5 — NFR-ENV03 narrowed from IP67 to IP65**, with the selected
  **Kopp 99966478** box named as what sets the figure — the same treatment the
  temperature ceiling got from the LJ18A3 end switch. The principle is that a
  requirement should state what the bill of materials actually delivers, and
  name the part that limits it, rather than assert a number nothing in the
  design meets. IP65 is the greenhouse study's stated *minimum*; its
  preference for IP67 was written for hardware at the aperture, which may be
  rain-wetted with the vent open, and this box holds only the electronics.
  With that settled, `requirementsCompliance.md` §4 was rewritten: both gaps
  it originally raised — potentiometer life and mechanism accuracy — are
  **closed** by the draw-wire supplier specification (>100 000 cycles, 0.2 %
  comprehensive error). Three gaps replace them, two of which arrived with
  the parts chosen since, which is what happens when a compliance analysis
  against a design becomes one against a bill of materials. Only one is a
  requirement *missed* rather than narrowed with its cause named: the
  **draw-wire unit is IP50 and sits outside the enclosure**, so the box that
  now satisfies NF-WP05 protects the electronics and does nothing for the
  sensor hanging on the window frame.
- **`TDS.md` v0.4** — the opening scaling became **direction-agnostic**
  (FR-E04): the two calibration points may be given in either order, so a
  draw-wire mounted such that the wiper code *falls* as the window opens
  calibrates exactly like a normal one, with no invert register and no extra
  installer step. FR-E06 now constrains the *distance* between the points
  rather than their ordering, and adds a **minimum span of 64 counts** —
  applied to values loaded from flash as well as to Modbus writes, so a
  degenerate stored pair can never reach the divisor. The arithmetic moved
  into a hardware-free `scale.c` and is **host-tested at its corners in both
  mounting senses** (`software/firmware/test/test_scale.c`), which is how a
  documented overflow figure was found to be wrong by ~393 000 — the margin
  is 196 605 (0.0046 %), not the threefold-larger value first written down.
  v0.4 also adds **FR-E17, a maximum-age contract**: the value in 30001 is
  never older than the configured measurement window, so a master bounds
  staleness by setting one register rather than by any freshness protocol.
  (Sampling on demand was considered and dropped — unnecessary once the age is
  bounded, and it would have left the averaging, envelope and rate registers
  without the regular cadence they need.)

  And it closes the environmental questions: §4.5 records the IP65 enclosure
  with all connectors inside it, glanded field cables, terminal blocks for the
  sensor and switch loop, and a **pressure-equalisation vent plug** — which
  matters more than it looks, because a fully sealed box uses its own seals as
  a valve every night as it cools, drawing water in. NFR-ENV02…05 make
  condensing operation, ingress, UV and vibration testable. New §4.6 gives the
  reason conformal coating is *specified* rather than merely advisable: the
  wiper is a 2.5 kΩ node, greenhouse condensate is ionic, and surface leakage
  of 100 kΩ costs 1.2 % of full scale — so coating is part of the accuracy
  budget, not a longevity nicety, and a damp uncoated board would fail FR-E03
  silently.
- **`TDS.md` v0.3** — end-of-travel switches became **mandatory** and moved
  from a single digital input to a **supervised resistor ladder on PC4**
  (ADC channel 2, §4.4), with the address jumper moving to PC1. The swap is
  the point: PC4 carries an ADC channel and PC1 does not, so the analog pin
  goes to the thing at the far end of a cable and the boot-time jumper takes
  the digital pin. The ladder resolves five states — cable open, normal, one
  switch closed, both closed, cable shorted — so a cut or shorted switch
  cable is distinguishable from a switch operating. Status register 30006
  gained bit 4 (switch-loop fault) alongside bit 3 (end of travel reached);
  bit 2 was renamed *wiper* fault, since there are now two independent
  front-ends that fault separately (FR-E14/E15/E16). The `HAVE_END_SWITCH`
  build option and the `encoder_endswitch` environment are gone with it.
  Derivation, including why the ladder cannot resolve *which* switch and
  supervise the cable at the same time, is in `design/scratchBook.md`.
- **`TDS.md` v0.2** — §2 (Modbus RTU contract, FR-MB01…FR-MB30) carried over
  unchanged from the windmeters TDS v0.9, where every row is HIL-verified
  against the same driver binary. §2.7/§2.8 replaced with the window-opening
  register map: 12 input registers (opening instantaneous / averaged /
  window min / window max, raw ADC code, status, identification, uptime, CRC
  and served counters, seconds-since-valid-reading, movement rate) and 6
  persisted holding registers (zero offset, measurement window, averaging
  window, full travel, two-point raw calibration). §3 keeps the proven
  lifecycle requirements (FR-S01…FR-S03, FR-S18…FR-S24, FR-S30…FR-S36,
  FR-S39) and adds a new **FR-E** series for the measurement path. §4
  hardware is open.
- **§4.2 documents the real pin budget.** The J4M6 SOP-8 bonds several GPIO
  onto shared pins (pin 1 is PD6 *and* PA1; pin 8 is PD1, PD4 *and* PD5), so
  there are six physical I/O pins, not the seven a port-name list implies.
  **Every one is now committed**; any front-end idea needing another pin
  does not fit.
- UML: `design/diagrams/modbus_state.puml` carried over (protocol behaviour
  is unchanged, title retargeted); component and super-loop diagrams redrawn
  for the encoder module split.

### Added — software (carried over, HIL-verified in the source project)

- `software/drivers/modbus_rtu/` — Modbus RTU slave driver (`mb.c`/`mb.h`):
  framing/CRC, t3.5 gap detection, address filtering, FC03/04/06/16,
  standard exceptions, no-clamp range rejection, atomic FC16,
  remap-switching line discipline (no HDSEL), polled RX (zero ISRs). Its
  test shell was retargeted to this project's register map and address.
- `software/drivers/common/debug_uart/` — bench trace UART.
- `software/drivers/blinky_template/` — bare-MCU bring-up project.
- `software/firmware/src/board.{c,h}` — RS-485 quiescing, jumper address
  latch, IWDG and PVD (FR-S18/S20/S22), with the address retargeted to
  40/45 and the jumper moved to PC1.
- `software/firmware/src/persist.{c,h}` — power-loss-safe ping-pong flash
  store for the six holding registers (FR-S39), fields retargeted to this
  holding set and the store magic changed to `'WE'` so a windmeters record
  left in a re-flashed chip can never be read as valid.
- `software/hil/` — Saleae/M2K instrument scaffolding and the acceptance
  suite shell, plus the bench-quirk catalogue in its README — the hard-won
  part.

### Added — software (new)

- `software/firmware/` — product-firmware skeleton. **One release build**
  (`encoder`, build byte 0x01, address 40/45), with `encoder_test`
  (bench-only) beside it. `regs.{c,h}` implements the full §2.7/§2.8
  register image with the FR-S31 + FR-E06 cross-validate hook, the §4.4
  ladder band decode and the FR-E15 debounce. Measurement registers read
  their FR-S23 pre-first-window value until the encoder driver lands.
  The FR-E04 scaling lives in a hardware-free `scale.{c,h}` with a host test
  in `software/firmware/test/`. As-built: 3 604 B flash / 616 B RAM
  (25 % / 34 % of the NFR-RES01 ceilings).
- `software/drivers/wire_encoder/` — driver-project shell with the drafted
  `we.h` API contract; **no implementation yet**, deliberately, so the
  firmware cannot link against a stub that looks like a driver.

### Hardware decisions

- **End switches: LJ18A3-8-Z/BX inductive proximity sensors** (2026-07-29).
  NPN normally-open, 6–30 V, 8 mm range against a 30 × 30 × 1 mm iron target,
  M18×1, unshielded, with an actuation LED. The supply range spans the board's
  own 24 V PoE rail, so they run off it directly — no extra regulator and no
  load on the 3.3 V. Being non-contact, they retire the 25 000-cycle wear
  concern for the switches; only the potentiometer still carries it.
  Datasheet in `documentation/Proximity-Switch-LJ18A3-8-Z-BX.pdf`. Confirmed
  specs: <13 mA each, <300 mA output, ≈0.8 mm hysteresis, 500 Hz, reverse-
  connection/surge/short-circuit protection, 1.1 m flying lead.
- **§4.4 end-switch interface redesigned as an attenuating divider.** The
  sensors are not open-collector — each has an internal 10 kΩ pull-up to +V
  (`LJ_en.pdf` p. 2), so an inactive one *sources* 24 V rather than floating.
  The previous pull-up-to-3.3 V topology would have sat at **10.4 V with one
  sensor inactive and 14.0 V with both**, against an ADC pin whose maximum is
  a diode drop above 3.3 V — a destroy-the-part error, caught before any board
  existed. The sensor already provides a clean 0 ↔ 24 V signal, so the board
  now **attenuates and clamps** instead of exciting: 100 k per output and a
  470 k end-of-line summed in the field junction, 10 k + 4k7 and a clamp at
  the board. Bands invert — healthy is now the highest reading (547) and a
  dead cable is zero. Three things improved in the process:
  **fail-safe by construction** (the board-side pull-down holds a
  disconnected input at 0, which is the fault band, so nothing reads healthy
  by accident); **saturation voltage almost stops mattering** (the 100 k
  summing resistors reduce its effect from 296 counts to 17, so the unknown
  `Vsat` is no longer make-or-break); and **±15 % supply tolerance is
  absorbed** with ≥45 counts to spare at the tightest point. Given up: the
  measurement is no longer ratiometric, and both-active vs cable-fault are
  only just distinguishable — both are bit-4 faults, so treat them as one.
  `regs.c`'s classifier and thresholds updated to match.
- **End switch changed to the 3RG4023-3AB00, and it inverts the whole
  interface** (2026-08-08, `documentation/6561.pdf`). The LJ18A3-8-Z/BX was
  **NPN** with an internal 10 kΩ pull-up, so an inactive sensor sat *high*.
  This one is **PNP**: inactive is *open*, operated drives *high*. Every level
  in §4.4 inverts, and so do the firmware thresholds — **normal is now the
  lowest reading and a fault the highest.**

  Circuit: **R10 (470 k pull-up) is deleted** — it held *both active* off the
  floor when the NPN outputs pulled down, and against a PNP source it only
  injects an offset into a network that now needs a pull-down. The existing
  10 k + 4k7 attenuator *is* that pull-down, so no part replaces it. **R8/R9
  100 k → 68 k**, sized so *both active* does not clip at +15 % supply while
  keeping the 10 µA off-state leakage clear of the *one active* band. Bands at
  24 V: **29 / 423 / 719 counts**, thresholds 230 and 510.

  **The fault band is gone, and that is inherent rather than an oversight.** A
  PNP normally-open output sources nothing when inactive, when its cable is
  open, and when its signal is shorted to 0 V — all three read ~0 counts.
  Status bit 4 and FR-E16 now cover *both active* and nothing else. Note this
  inverts the *direction* of the undetected failure rather than removing it:
  under the NPN part an open cable read 337 counts and reported a **false**
  stop; now it reads ~0 and reports a **missed** one. `regs.c` loses
  `SW_CABLE_FAULT` entirely and classifies three states, not four.

  **What it buys is bigger than what it costs.** The LJ18A3's +65 °C ceiling
  was NFR-ENV01's limit and **the one requirement this design knowingly failed**
  against the greenhouse study — NF-WP03 asks +70 °C. At **−25…+85 °C** the new
  sensor stops being the constraint, NFR-ENV01 goes to **+70 °C**, and NF-WP03
  moves into the met column. The old §6 entry predicted the fix would be "a
  wider-range end switch"; it arrived as a change of part rather than as a
  survey. Also gained: reverse-voltage, wire-breakage, inductive-overvoltage,
  short-circuit and overload protection all built in, switch-on pulse
  suppression, and an **M12 connector** in place of a 1.1 m flying lead — which
  turns the field joint from a workmanship item into a cordset.

  Two things to watch, both now in §6. The **≤2.5 V output drop is specified at
  the rated 300 mA** and this network draws **290 µA**; the real drop should be
  a fraction of a volt, but nothing guarantees it, and the difference is 23
  counts of margin against 63 — so measuring `Von` at the divider's actual load
  replaces the LJ18A3 bench item as the blocker. And **hysteresis is as low as
  0.04 mm**, twenty times tighter than before, which makes FR-E15's 20 ms
  debounce load-bearing rather than precautionary.

- **D3 selected: PESD5V0S1BA**, 5 V standoff, bidirectional, SOD-323. The
  standoff is deliberately *not* 3.3 V: the wiper swings to 3.3 V, so a
  3.3 V-standoff part would sit at 100 % of its rated working voltage at full
  scale, where leakage is largest and most temperature-dependent. Every
  component on the schematic now carries a footprint. What remains is evidence
  — datasheets quote reverse current at `V_RWM` and 25 °C, which says little
  about 3.3 V at +70 °C, so FR-E21's fit/unfit measurement still has to be made.

- **The wiper had no protection at all, and now does** (2026-08-07,
  FR-E21). PA2 ran bare from the terminal block to the MCU — no series
  element, no clamp — while the switch input two pins away had a 10 k series,
  a divider and a zener. The asymmetry was inherited from the sibling board,
  whose `ANALOG_IN` also went straight from the RJ14 to the pin, and it had
  been sitting in §6 as "wiper ESD protection" since the first draft.

  Fitted: **R11 10 kΩ** in series, **C6 1 nF** as a reservoir and **D3**, a
  TVS. Three things about that set are not the obvious choices.

  **The resistor is the current limiter, not the TVS.** A TVS is a transient
  device and cannot hold a low-impedance 24 V short; a miswired terminal is
  not a transient. 10 kΩ holds a 27.6 V fault (24 V passive PoE at +15 %) to
  **2.4 mA** against the CH32V003's **±4 mA** injected-pin absolute maximum —
  the same ≈2 mA design point §4.4.2 had already chosen for the switch input.

  **The capacitor is what makes a 10 kΩ series resistor affordable.** The
  ADC's sample capacitor charges from the reservoir instead of through the
  resistor, which only has to recharge 1 nF between conversions: 12.5 µs
  against a ≥100 ms window. It is deliberately *small* — FR-E07 detects an
  open wiper by toggling the internal pull resistor between conversions, and
  at tens of kΩ that pull settles through 1 nF in ~40 µs where 100 nF would
  take 4 ms and start eating the measurement cadence. FR-E12's sample time
  goes to ≥241 cycles anyway, which costs ~42 µs per conversion and removes
  any need to lean on the reservoir argument.

  **The clamp is a specification, not a preference** (new §4.6.1). §4.6's
  ≥10 MΩ wiper-node rule has always been read as being about moisture; it is
  really about any current path off that node, which makes it a component
  rule too. It disqualifies both obvious candidates: the **BZX84-C3V3**
  already used on PC4 leaks microamps well below breakdown and *non-linearly*,
  ≈12 mV or 4 counts that calibration cannot remove; and **BAT54S**, the
  reflex ADC clamp, leaks ~2 µA at 25 °C and roughly doubles per 10 °C, so at
  NFR-ENV01's +65 °C ceiling it is ≈32 µA — **80 mV, 25 counts, 2.4 % of full
  scale** against a sensor specified at 0.2 %. The trap is that PC4 and PA2
  sit at comparable impedance so the PC4 clamp looks transferable; the
  difference is not impedance but that PC4 resolves four bands with 45 counts
  of margin while PA2 is the measurement the product exists to make. D3 is
  therefore specified at **≤100 nA at 3.3 V across the full NFR-ENV01 range**
  and left with a blank footprint so it cannot be laid out unselected.

- **The installation is a star, and it costs the cable supervision**
  (2026-08-07). The PCB is the hub; the draw-wire and **each** end switch run
  their own cable to it. There is no field junction, so the 100 k summing
  resistors and the 470 k have nowhere to live except the PCB — and an
  end-of-line resistor at the near end of the line is not an end-of-line
  resistor. The four band levels are unchanged; what changed is what a fault
  looks like. An open sensor cable removes that branch's pull-up, and
  *removed* lands between *inactive* and *active*: **337 counts, 38 from a
  genuine stop at 299, inside the same band**. So a cut does not report a
  fault, it reports **a stop that did not happen** — worse than a detected
  fault, because the controller acts on it instead of alarming. It cannot be
  tuned out: the bands need 45 counts of margin for supply tolerance alone,
  and a fifth state does not fit between four on one 10-bit pin. FR-E16 and
  status bit 4 are narrowed to cover a short to 0 V and both-switches-active
  only; FR-E14's verification gains a negative test that confirms the limit
  rather than contradicting it. The 470 k stays on the board with a new job —
  it is what holds *both active* at 56 counts instead of collapsing it onto
  *shorted* at 0.

  The trade is not one-way. Field-mounted 100 k and 470 k would have sat
  uncoated in the dampest part of the installation, where §4.6's own figures
  say contaminated films reach 100 kΩ–10 MΩ without difficulty — and against
  this network a **182 kΩ** leak from signal to +V *masks a real stop*, five
  times easier to reach than the 37 kΩ that would invent a false one, sitting
  between two adjacent terminals, failing in the direction where the window
  keeps driving. On the PCB, inside IP65 and coated, neither number matters.
  The star moves one hidden failure out of the harness and turns one
  detectable failure into a hidden one. A firmware mitigation is available
  and deliberately not yet specified: after FR-E19 has taught the endpoints, a
  stop claimed while the wiper sits far from either calibrated end is
  implausible, and the two independent front-ends can cross-check. Recorded in
  TDS §6 with the two questions it still needs answered.

  Knock-on: the enclosure now uses **all six** entries — bus in, bus out,
  draw-wire, switch A, switch B, vent — with none spare.

- **⛔ Superseded — the original open-collector assumption.**
  The manufacturer's manual (`LJ_en.pdf` p. 2) shows the NPN output carries an
  **internal 10 kΩ pull-up to +V** — it is not a bare open collector and does
  not float when inactive. The §4.4 network, which assumes it floats and pulls
  it up to 3.3 V, would sit at **10.4 V with one sensor inactive and 14.0 V
  with both**, against an ADC pin whose maximum is a diode drop above 3.3 V.
  That is a destroy-the-part error, not a calibration one. The interface has to
  become an attenuating divider referenced to the sensor supply; the
  supervision concept survives, the topology and values do not. Verify on the
  bench first: brown-to-black with the sensor unpowered should read ~10 kΩ.
- **⚠ /BX is NPN; /BY is PNP — and one of the supplied datasheets is the /BY.**
  The board pulls PC4 up to 3.3 V and relies on the sensor *sinking* it, which
  is safe only for an open-collector output. A PNP part sources its own supply
  rail and would put 24 V on an ADC pin. Check the marking on the sensor, not
  the paperwork that came with it.
- **NFR-ENV01 narrowed to −25…+65 °C**, and it now names what sets the limit:
  the LJ18A3-8-Z/BX end switch (−30…+65 °C) is the narrowest part in the chain;
  the electronics would have carried +70 °C. Stating the real figure beats
  leaving a requirement the BOM cannot meet. The acceptance criterion also
  gained a row — the §4.4 switch bands must decode correctly at both extremes,
  because an NPN saturation voltage drifts with temperature. Consequence: this
  is 5 °C below the greenhouse study's NF-WP03, and is now the one requirement
  the design knowingly does not meet in full; the resolution is a survey of the
  mounting position and, if needed, a wider-range switch.
- **⚠ The §4.4 ladder band values are now provisional.** They were derived for
  dry contacts closing to 0 Ω. An NPN output closes to its saturation voltage
  instead, which shifts every active band upward — enough that at 0.5 V a
  wiring fault decodes as a normal end-stop, and at 1.5 V an actively
  signalling sensor decodes as *no sensor active*. Both are silent
  mis-decodes. `Vsat` is not stated in either supplied document and must be
  measured, then the resistors and thresholds re-derived, before the schematic
  is committed (TDS §6). Recommended at the same time: merge "both active" and
  "cable shorted" into one fault band — they are both impossible states, both
  set the same status bit, and merging them recovers most of the lost margin.
- **New failure mode to design out:** with powered sensors, a break in the +V
  conductor alone kills both while the EOL resistor keeps the loop reading
  healthy. Dry contacts did not have this. Fixable by deriving part of the
  pull-up from the sensors' +V at the far end.

### Notes

- `documentation/` contains a Mann Hwa / Zhongyang ZY-series encoder
  catalogue PDF. It describes **incremental** rotary encoders and **does not
  describe the sensor this project uses** — see `documentation/readme.md`.
  Do not design against it.

---

*Nothing released yet.*
