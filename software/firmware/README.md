# Firmware — Wire Encoder Modbus interface

PlatformIO project for the **CH32V003J4M6** (RISC-V, SOIC-8, 16 KB flash /
2 KB RAM). Measures window opening from a draw-wire encoder's 10 kΩ
potentiometer, read ratiometrically on PA2, and publishes it over Modbus
RTU (TDS §1.1, §3.4).

> **Status: complete and HIL-verified.** Integration stages **A–F are done**
> ([`design/integrationPlan.md`](../../design/integrationPlan.md)): board
> bring-up, the register image, flash persistence, the ADC driver, the
> measurement service, averaging, and the FR-E23/FR-E24 sensing-health checks.
> A flashed device measures, publishes, and reports status **`0x0000`** when
> healthy. Executed evidence is in
> [`software/hil/testReport.md`](../hil/testReport.md).
>
> What is **not** closed is blocked on instruments, not on code: FR-E03 needs a
> precision resistance box at five ratios, FR-E15 a 5 ms bounce injector, and
> TP-A03/TP-B23 an adjustable PSU — that last one covers the ±15 % supply
> margin, the tightest unmeasured number in the design.

## Modules

| File | Responsibility |
|---|---|
| `main.c` | The zero-ISR super-loop. **Nothing here may block for more than ~1 ms** — see the budget below |
| `board.c` | Clocks, GPIO, the FR-S18 bring-up order |
| `regs.c` | The register image, FC dispatch, status-bit assembly |
| `persist.c` | Flash-backed holdings (FR-S39), 20-byte `rec_t` |
| `meas_open.c` | Measurement pacing at 40 Hz; wiper and switch ladder on **alternate ticks** |
| `scale.c` | FR-E04 two-point opening scale, sign-aware, clamped |
| `avg.c` | FR-S31 two-stage boxcar (mean/min/max), ~384 B |
| `health.c` | FR-E23 position-not-following, FR-E24 plausible band |
| `version.h` | `FW_VERSION` — the single source for register 30007 |

The ADC driver itself lives outside this project, in
[`software/drivers/wire_encoder/`](../drivers/wire_encoder/), and is referenced
in place.

## ⚠ The blocking budget

No requirement states this, and it has bitten the project once:

> `mb_rx_service` polls a single-byte USART register. Any main-loop pass longer
> than **one character time (1.146 ms at 9600 baud)** loses a byte to overrun,
> and FR-MB24 discards the frame — **without** incrementing 30009, because an
> overrun is not a CRC error. Requests vanish with no diagnostic anywhere.

Integration stage D dropped **9.7 %** of requests before this was understood.
If you add work to the loop, measure the **pass time**, not just the
measurement-window budget.

Authoritative references: the register map and behaviour contract live in
[`design/TDS.md`](../../design/TDS.md) (§2.7 input / §2.8 holding registers,
§4.2 pin map); the zero-ISR super-loop design and module split in
[`design/softwareArchitecture.md`](../../design/softwareArchitecture.md).

## Build environments

**One release build.** There is one sensor read one way, so there is no
variant machinery and no `SENSOR_*` selector.

| Environment | Extra define | Purpose | Release? |
|---|---|---|---|
| `encoder` | — | **The product.** Build byte 0x01, address 40 (PC1 jumper open) / 45 (bridged) | ✅ |
| `encoder_test` | `TEST_HOOKS` | FR-S20 watchdog hang trigger (holding `0x00FF`, magic `0xDEAD`) for the HIL reset checks | ❌ **never** |

The end-of-travel switches are **not** an option: they are read as a
supervised resistor ladder on PC4 (TDS §4.4) and are part of the product.

## Prerequisites

- [PlatformIO Core](https://platformio.org/install/cli) (`pip install platformio`)
  or the PlatformIO VS Code extension.
- A **WCH-LinkE** programmer on SWIO (PD1).

The community WCH platform (`platform = ch32v`) and the `ch32v003fun`
framework are pulled automatically on first build. The verified driver
libraries (`mb_*`, `dbg_*`) are referenced **in place** from
[`software/drivers/`](../drivers/) — no copies.
`software/drivers/wire_encoder/lib` is on `lib_extra_dirs` as of stage D; the
linker pulls `we.c` in because `meas_open.c` includes `we.h`.

## Usage

```sh
pio run                            # the release build
pio run -t upload                  # flash via WCH-LinkE
```

There is no serial console: the release firmware never transmits
unsolicited (FR-S19) — PD6 is the Modbus data line. Talk to a flashed
device over RS-485/Modbus RTU (9600 8N1).

## Resource ceilings (NFR-RES01)

The 87.5 % ceilings — **14 336 B flash / 1 792 B RAM** — are hard build
gates (`board_upload.maximum_size` / `maximum_ram_size`); a build that
exceeds them fails. As-built:

| Environment | Flash | RAM |
|---|---|---|
| `encoder` | 6 364 B (44.4 %) | 1 108 B (61.8 %) |
| `encoder_test` | 6 396 B (44.6 %) | 1 112 B (62.1 %) |

**As-built with stages A–F complete** (measured 2026-09-05), so these are a
planning basis. RAM is the tighter of the two: `avg.c`'s ring accounts for
~384 B of the 1 108 B, and the remaining headroom is ~684 B.

## Configuration and calibration

All six holding registers (40001–40006) are runtime-writable and **persist
in flash across reset/power-loss** (FR-S39). Opening scaling is a two-point
runtime calibration (FR-E05), so one binary serves any window with no
rebuild. **Calibration is a field procedure over Modbus:**

1. Close the window fully. Read 30005 (raw ADC) and write that value to
   **40005**.
2. Open it fully. Read 30005 and write that value to **40006**.
3. Measure the actual travel and write it, in 0.1 mm, to **40004**.

The order does not matter and neither does the direction: if the raw value
*falls* as the window opens, write the readings to the same registers anyway
— 40005 is whatever you read with the window closed, 40006 whatever you read
with it open. The firmware handles both senses (FR-E04). The two must differ
by at least 64 counts (FR-E06).

**Size the draw-wire so neither end sits at an electrical extreme.** Leave
≥10 % of ADC range beyond each end of travel (`design/description.md` §8.1).
This is not tidiness: if fully-closed reads near 0, a conductor shorted to
ground is *indistinguishable* from a correctly closed window, and no firmware
can separate them. The headroom is also what makes FR-E24's plausible band
meaningful — on a rig that traverses the full 0–1023 the band covers every
reachable code and the check is inert by design.

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
in [`RELEASES.md`](RELEASES.md). The old bar for `fw-v1` — "not until the
measurement service exists" — **has been met**; the remaining question is
whether to release with FR-E03 and FR-E15 still open on instrument
availability. That is a release decision, not a code one.

## Testing

- **Host tests** (no hardware). Three suites, each compiling the **shipped**
  source rather than a copy. MinGW ships with Code::Blocks on this bench:

  ```sh
  cd test
  gcc -O2 -Wall -Wextra -I../src -o test_scale  test_scale.c  ../src/scale.c  && ./test_scale
  gcc -O2 -Wall -Wextra -I../src -o test_avg    test_avg.c    ../src/avg.c    && ./test_avg
  gcc -O2 -Wall -Wextra -I../src -o test_health test_health.c ../src/health.c && ./test_health
  ```

  `test_avg` (26 checks) pins FR-S31's block **min/max** — a block *mean* makes
  the envelope wrong in a way that still looks plausible. `test_health`
  (25 checks) pins the two properties easiest to break silently: FR-E24 must be
  **self-disabling** on a full-range calibration, and FR-E23 must not count a
  window **rocking on its stop** as a departure.

  The FR-E04 opening scaling is pure integer
  arithmetic with a sign-aware map, clamping at both ends and 0.0046 % of
  overflow headroom — so it lives in `src/scale.c` with no hardware
  dependency, and the test compiles the shipped code:

  ```sh
  cd test
  gcc -O2 -Wall -Wextra -I../src -o test_scale test_scale.c ../src/scale.c && ./test_scale
  ```

  Covers both mounting senses, the offset behaviour at and beyond each
  calibration point, the overflow corners, the minimum legal calibration
  span, the unreachability of the fault sentinel, and monotonicity swept
  across the whole ADC range. Run it after touching anything in `scale.c`.

- **Acceptance suite** (bench):

  ```sh
  cd ../hil/acceptance
  ..\.venv-m2k\Scripts\python.exe -m pytest .
  ```

  **11 tests**, of which 7 need no hardware; the other 4 skip cleanly without
  an ADALM2000. Build gates, protocol checks, and the traceability gates that
  fail if any requirement gains no test row, if a row cites an id that does not
  exist, or if an id is abbreviated. Instrument setup, wiring
  and the bench-quirk catalogue are in
  [`software/hil/README.md`](../hil/README.md); executed HIL tests belong
  in [`software/hil/testReport.md`](../hil/testReport.md).
