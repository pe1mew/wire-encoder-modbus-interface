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
returns, with no homing move.

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

- Design document chain seeded: `design/README.md` (index), **`TDS.md`
  v0.2**, `softwareArchitecture.md`, `driverDevelopment.md`,
  `integrationPlan.md`, `scratchBook.md`.
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
  Five are committed; **PC1 is the only spare**, and it carries the optional
  end-switch input.
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
  40/45 and the optional PC1 end-switch input added.
- `software/firmware/src/persist.{c,h}` — power-loss-safe ping-pong flash
  store for the six holding registers (FR-S39), fields retargeted to this
  holding set and the store magic changed to `'WE'` so a windmeters record
  left in a re-flashed chip can never be read as valid.
- `software/hil/` — Saleae/M2K instrument scaffolding and the acceptance
  suite shell, plus the bench-quirk catalogue in its README — the hard-won
  part.

### Added — software (new)

- `software/firmware/` — product-firmware skeleton. **One release build**
  (`encoder`, build byte 0x01, address 40/45); beside it `encoder_endswitch`
  (optional PC1 end-switch input, FR-E14/E15) and `encoder_test`
  (bench-only). `regs.{c,h}` implements the full §2.7/§2.8 register image
  with the FR-S31 + FR-E06 cross-validate hook and the FR-E15 switch
  debounce. Measurement registers read their FR-S23 pre-first-window value
  until the encoder driver lands.
  As-built: 3 572 B flash / 616 B RAM (25 % / 34 % of the NFR-RES01
  ceilings); 3 720 B / 624 B with the end-switch option.
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
