# Drivers for CH32V003J4M6

Standalone driver projects, each with its own HIL test shell. The product
firmware in [`../firmware/`](../firmware/) references these libraries **in
place** through `lib_extra_dirs` — nothing is copied, so the code that ships
is the code that was tested.

The development method (build standalone → verify every matrix row on
silicon → only then integrate) is in
[`design/driverDevelopment.md`](../../design/driverDevelopment.md).

| Project | Deliverable | Status |
|---|---|---|
| [`blinky_template/`](blinky_template/) | Bare-MCU bring-up: board, framework and WCH-LinkE upload settings. The starting point when cloning a new driver project. | Inherited, verified |
| [`common/debug_uart/`](common/debug_uart/) | `dbg_*` — TX-only trace UART on PD6, 115200 8N1. Driver-phase tool only; never linked into a release binary. | Inherited, verified |
| [`modbus_rtu/`](modbus_rtu/) | `mb_*` — the Modbus RTU slave driver: framing, CRC, t3.5 gap detection, FC03/04/06/16, exceptions, DE control. | Inherited, verified (26/26 matrix + 40/40 endurance in the source project) |
| [`wire_encoder/`](wire_encoder/) | `we_*` — absolute window-opening readout: 10 kΩ potentiometer on PA2, ratiometric 10-bit ADC, plus the end-switch ladder on PC4. | **Written and HIL-verified** (2026-09-01), integrated at stage D. Note its ADC sample time is **≥241 cycles**, not the sibling project's ≥71 — FR-E21's series resistor changes the source impedance. See the project README |

**"Inherited" means carried over from the sibling
[`windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface)
project**, where each was HIL-verified on this same MCU. The evidence lives
in that repository's `software/hil/testReport.md`. It has not been re-run on
this project's hardware — there is no hardware yet.
