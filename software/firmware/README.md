# Firmware — Wire Encoder Modbus interface

PlatformIO project for the **CH32V003J4M6** (RISC-V, SOIC-8, 16 KB flash /
2 KB RAM). Measures window opening from a draw-wire encoder's 10 kΩ
potentiometer, read ratiometrically on PA2, and publishes it over Modbus
RTU (TDS §1.1, §3.4).

> **Status: skeleton.** Board bring-up, the complete register image and
> flash persistence build and run. **There is no measurement service** — the
> encoder driver is unwritten — so measurement registers read their FR-S23
> pre-first-window value (0) and status bits 0/1 stay set. A flashed device
> answers the whole map correctly and reports, truthfully, that it has never
> completed a measurement. See
> [`design/integrationPlan.md`](../../design/integrationPlan.md) stages D–F
> for what is missing.

Authoritative references: the register map and behaviour contract live in
[`design/TDS.md`](../../design/TDS.md) (§2.7 input / §2.8 holding registers,
§4.2 pin map); the zero-ISR super-loop design and module split in
[`design/softwareArchitecture.md`](../../design/softwareArchitecture.md).

## Build environments

**One release build.** There is one sensor read one way, so there is no
variant machinery and no `SENSOR_*` selector.

| Environment | Extra define | Purpose | Release? |
|---|---|---|---|
| `encoder` | — | **The product.** Build byte 0x01, address 40 (jumper open) / 45 (bridged) | ✅ |
| `encoder_endswitch` | `HAVE_END_SWITCH` | Adds the optional end-of-travel switch input on PC1 (TDS §3.5), published as status bit 3 | only if the mechanism has switches |
| `encoder_test` | `TEST_HOOKS` | FR-S20 watchdog hang trigger (holding `0x00FF`, magic `0xDEAD`) for the HIL reset checks | ❌ **never** |

## Prerequisites

- [PlatformIO Core](https://platformio.org/install/cli) (`pip install platformio`)
  or the PlatformIO VS Code extension.
- A **WCH-LinkE** programmer on SWIO (PD1).

The community WCH platform (`platform = ch32v`) and the `ch32v003fun`
framework are pulled automatically on first build. The verified driver
libraries (`mb_*`, `dbg_*`) are referenced **in place** from
[`software/drivers/`](../drivers/) — no copies.
`software/drivers/wire_encoder/lib` is deliberately **not** on
`lib_extra_dirs`: it holds an API contract with no implementation, and
adding it before the driver exists buys nothing but a link error. Add it in
integration stage D.

## Usage

```sh
pio run                            # the release build
pio run -t upload                  # flash via WCH-LinkE
pio run -e encoder_endswitch       # with the optional switch input
```

There is no serial console: the release firmware never transmits
unsolicited (FR-S19) — PD6 is the Modbus data line. Talk to a flashed
device over RS-485/Modbus RTU (9600 8N1).

## Resource ceilings (NFR-RES01)

The 87.5 % ceilings — **14 336 B flash / 1 792 B RAM** — are hard build
gates (`board_upload.maximum_size` / `maximum_ram_size`); a build that
exceeds them fails. As-built for the skeleton:

| Environment | Flash | RAM |
|---|---|---|
| `encoder` | 3 572 B (25 %) | 616 B (34 %) |
| `encoder_endswitch` | 3 720 B (26 %) | 624 B (35 %) |
| `encoder_test` | 3 600 B (25 %) | 616 B (34 %) |

Those are skeleton numbers and are not a planning basis — the measurement
service and the averaging engine are still to come (the latter adds ~384 B
of RAM). Record the release numbers here when they land.

## Configuration and calibration

All six holding registers (40001–40006) are runtime-writable and **persist
in flash across reset/power-loss** (FR-S39). Opening scaling is a two-point
runtime calibration (FR-E05), so one binary serves any window with no
rebuild. **Calibration is a field procedure over Modbus:**

1. Close the window fully. Read 30005 (raw ADC) and write that value to
   **40005**.
2. Open it fully. Read 30005 and write that value to **40006**.
3. Measure the actual travel and write it, in 0.1 mm, to **40004**.

That's it — the values survive power loss. The compile-time defaults that
seed those registers on first boot can be overridden per build:

```ini
build_flags = ... -D RAW_CLOSED_DEFAULT=0 -D RAW_OPEN_DEFAULT=1023
```

`RAW_OPEN_DEFAULT` otherwise follows `WE_RAW_MAX_DEFAULT` in `sensors.h`
(1023, the 10-bit ADC full scale). **Keep it equal to the driver's
`we_raw_max()`** — a mismatch calibrates a fresh device to nonsense on first
boot and nothing in the FR-E04 scaling can detect it.

## Versioning and releases

The firmware version byte (reported in input register 30007, low byte) has
a single source: [`src/version.h`](src/version.h). Releases are registered
in [`RELEASES.md`](RELEASES.md). **Do not tag `fw-v1` until the measurement
service exists** — a release that returns 0 for every measurement is not a
product.

## Testing

- **Acceptance suite** (bench):

  ```sh
  cd ../hil/acceptance
  ..\.venv-m2k\Scripts\python.exe -m pytest .
  ```

  Only the build-gate rows are populated so far. Instrument setup, wiring
  and the bench-quirk catalogue are in
  [`software/hil/README.md`](../hil/README.md); executed HIL tests belong
  in [`software/hil/testReport.md`](../hil/testReport.md).
