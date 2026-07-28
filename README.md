# Wire Encoder Modbus Interface

A CH32V003-based interface board that measures **how far a window is open**
and publishes it on **Modbus RTU over RS-485**, powered by 24 V passive PoE
and designed for daisy-chained field buses.

The measurement comes from a **draw-wire encoder**: a spring-loaded drum
pays out a steel wire attached to the moving window frame, and the drum
turns a **10 kΩ potentiometer**. The wiper voltage is therefore an absolute
measure of the opening — valid the instant power returns, with no homing
move and no count to lose.

One firmware build, addressed by a solder jumper:

| Jumper open | Jumper bridged |
|---|---|
| **40** | 45 |

The 40/45 pair is deliberately clear of the sibling
[`windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface)
family (30–37), so both can share one RS-485 segment.

## Project status (2026-07)

| Area | State |
|---|---|
| Requirements | [`design/TDS.md`](design/TDS.md) **v0.2** — §2 Modbus contract inherited and proven; §3 measurement requirements drafted; §4 hardware open |
| Drivers | Modbus RTU + debug UART carried over HIL-verified; the encoder driver (`software/drivers/wire_encoder/`) is **not yet written** — its API contract is drafted in [`design/driverDevelopment.md`](design/driverDevelopment.md) |
| Product firmware | Skeleton only: board bring-up, register image, flash persistence and the Modbus service build and run; **no measurement service yet** ([`design/integrationPlan.md`](design/integrationPlan.md) stage C) |
| Hardware/HIL | No schematic yet — `hardware/KiCad/` holds the symbol libraries only. HIL harness scaffolding in place, check scripts to be written |
| Release | No firmware version tagged ([`software/firmware/RELEASES.md`](software/firmware/RELEASES.md)) |

## Hardware

The board reuses the sibling project's design wholesale apart from the
sensor front-end:

- **MCU**: WCH CH32V003J4M6 (RISC-V, SOP-8, 16 KB flash / 2 KB RAM). The
  8-pin package drives the whole design: single-wire UART discipline, remap
  tricks, and a zero-interrupt firmware architecture
  ([`design/softwareArchitecture.md`](design/softwareArchitecture.md)).
- **RS-485**: MAX3485; DI+RO tied to PD6, DE+R̄Ē tied to PC2 with a 10 k
  pull-down (keeps the bus safe during reset/flashing); 120 Ω terminator
  behind a solder jumper; A/B fail-safe bias; SM712 TVS.
- **Power**: 24 V passive PoE on the spare pairs (4/5 = +, 7/8 = −) →
  DB207 bridge (polarity protection only) → HLK-K7803 buck → 3.3 V.
- **Sensor front-end**: the potentiometer wiper on PA2, read ratiometrically
  against VDD — no external reference, so supply ripple cancels.

**The pin budget is the binding constraint.** The SOP-8 package bonds
several GPIO onto shared pins (pin 1 is PD6 *and* PA1; pin 8 is PD1, PD4
*and* PD5), leaving **six physical I/O pins**. Five are committed — Modbus
data, the wiper, DE/RE, the address jumper and SWIO — so **PC1 is the only
spare**, and it carries the optional end-of-travel switch input. Any
front-end idea that needs a second spare pin does not fit. See
[`design/TDS.md`](design/TDS.md) §4.2.

## Modbus register map (summary)

12 input registers (FC04) and 6 holding registers (FC03/06/16). Inputs:
instantaneous and averaged opening, the minimum/maximum of the current
averaging window, the raw ADC code, status bits, identification (build +
firmware version), uptime, CRC/served counters,
seconds-since-last-valid-reading, and movement rate. Holdings: zero offset,
measurement window, averaging window, full travel, and the two-point raw
calibration (raw code closed / raw code fully open) — so one image serves
any window, calibrated in the field over Modbus. All persisted in flash
across reset/power-loss; the defaults apply only on first boot / erased
store. The authoritative map with ranges, defaults and requirement IDs is
[`design/TDS.md`](design/TDS.md) §2.7/§2.8.

## Repository layout

| Path | Contents |
|---|---|
| [`design/`](design/README.md) | The design-document chain (index in [`design/README.md`](design/README.md)): scratchBook → TDS → softwareArchitecture (+ UML diagrams in `design/diagrams/`) → driverDevelopment → integrationPlan |
| `hardware/KiCad/` | Schematic + PCB (KiCad); symbol libraries as git submodules |
| `hardware/Documentation/` | Component datasheets (HLK-K78xx, DB20x, MAX3483/85, Kradex enclosure) |
| `software/firmware/` | Product firmware (PlatformIO + ch32v003fun): one release build, plus an end-switch option and a bench-only test build |
| `software/drivers/` | Standalone driver projects with HIL test shells (the verified libraries the product references in place) |
| `software/hil/` | Scripted hardware-in-the-loop harness: Saleae Logic 2 (MCP) + ADALM2000 (libm2k) + `acceptance/` pytest suite |
| `Doxyfile` | Doxygen config — builds a single site (design docs + API reference) with this README as the landing page |
| `documentation/` | Chip pinout, programmer manual, and sensor reference material |

Clone with submodules:

```sh
git clone --recurse-submodules https://github.com/pe1mew/wire-encoder-modbus-interface.git
```

## Building and flashing

Requires [PlatformIO](https://platformio.org/) and a WCH-LinkE on SWIO.

```sh
cd software/firmware
pio run                            # the release build
pio run -t upload                  # flash via WCH-LinkE
```

`encoder_endswitch` adds the optional PC1 end-switch input; `encoder_test`
adds bench-only hooks — never release that binary. Resource ceilings
(14 336 B flash / 1 792 B RAM, NFR-RES01) are enforced as hard build gates.
The firmware version byte lives in `src/version.h`; the release process is
documented in `RELEASES.md`.

## Testing

- **Acceptance suite** (bench: Saleae Logic 2 with its MCP server, ADALM2000,
  WCH-LinkE, TTL Modbus rig):

  ```sh
  cd software/hil/acceptance
  ..\.venv-m2k\Scripts\python.exe -m pytest .
  ```

  Only the build-gate rows are populated so far; the protocol and
  measurement rows arrive with the driver work. See
  [`software/hil/README.md`](software/hil/README.md) for instrument setup,
  wiring, and the bench-quirk catalogue.

## Documentation

- **Design record** — [`design/README.md`](design/README.md) indexes the
  document chain (requirements → architecture → drivers → integration) and
  the UML diagrams.
- **API + design site** — the firmware headers/sources carry full Doxygen,
  and [`Doxyfile`](Doxyfile) folds the design docs in as pages with this
  README as the landing page. Build the browsable HTML with:

  ```sh
  doxygen Doxyfile        # output in documentation/doxygen/html/index.html
  ```

## Related repositories

- [`pe1mew/windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface) —
  the sibling project this repository is derived from: same MCU, same
  RS-485 front-end, same zero-ISR architecture, and the same potentiometer
  reading topology. Its Modbus RTU driver, board/persistence modules and
  HIL harness are carried over here, and its `design/` chain is the
  reference for anything not yet written down.
- [`pe1mew/windmeters-modbus-interface-tester`](https://github.com/pe1mew/windmeters-modbus-interface-tester) —
  the Modbus RTU master bench tool (M5Stack AtomS3 + RS-485) used to
  exercise devices in this family.

## License

Software is provided under a Source-Available Non-Commercial License;
documentation and images under CC BY-NC-ND 4.0. See [LICENSE](LICENSE) and
[license.md](license.md). Third-party datasheets and KiCad library
submodules remain under their owners' terms.

## Author

Remko Welling (PE1MEW)
