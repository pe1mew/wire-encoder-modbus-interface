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
  M3 requirements study), **`TDS.md` v0.4**, `softwareArchitecture.md`, `driverDevelopment.md`,
  `integrationPlan.md`, `scratchBook.md`.
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

  And it closes the environmental questions: §4.5 records the IP67 enclosure
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

### Notes

- `documentation/` contains a Mann Hwa / Zhongyang ZY-series encoder
  catalogue PDF. It describes **incremental** rotary encoders and **does not
  describe the sensor this project uses** — see `documentation/readme.md`.
  Do not design against it.

---

*Nothing released yet.*
