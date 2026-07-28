# Driver Development Plan

| Field | Value |
|---|---|
| Document | Driver development plan and results |
| Project | `wire-encoder-modbus-interface` |
| Date | 2026-07-28 |
| Status | **Plan only — no driver written yet.** Phase 0 (foundations) and phase 2 (Modbus RTU) are satisfied by carried-over, already-verified code. Phase 1 (the encoder driver) is ready to start: the sensor and its front-end are settled. |
| Related docs | `design/TDS.md` §3.3/§3.4 (the requirements each matrix verifies), `design/softwareArchitecture.md` (the contract drivers integrate into), `design/integrationPlan.md` (what happens after), `software/hil/README.md` (the bench) |

## 1. Approach

Same method as the sibling project, and it is the reason that project's
integration went as smoothly as it did: **each driver is developed as a
standalone PlatformIO project with its own HIL test matrix, and is not
integrated until every row of that matrix passes on real silicon.** A
driver that has only ever run inside the product firmware has never been
tested — it has been observed.

The loop per phase is: flash (`pio`) → stimulate (ADALM2000 / libm2k) →
observe (Saleae Logic 2 via its MCP server) → assert (Python). See
[`software/hil/README.md`](../software/hil/README.md).

Each driver lives in `software/drivers/<name>/` with its deliverable
library under `lib/<prefix>/`, and the product firmware references it
**in place** via `lib_extra_dirs` — no copies, ever.

## 2. Phase 0 — common foundations — **DONE (inherited)**

Carried over from the sibling project, where each item was verified on the
same MCU:

| Deliverable | Location | Status |
|---|---|---|
| Project conventions (PlatformIO + ch32v003fun, `funconfig.h` with `FUNCONF_SYSTICK_USE_HCLK 1`, WCH-LinkE on PD1) | `software/drivers/*/platformio.ini` | inherited |
| Bare-MCU bring-up project | `software/drivers/blinky_template/` | inherited, PASS in source project |
| Debug UART on PD6 (TX-only, idle mark driven — HDSEL floats the line) | `software/drivers/common/debug_uart/` | inherited, PASS in source project |
| HIL harness (Saleae MCP + M2K stimulus + assertion scripts) | `software/hil/` | scaffolding inherited; encoder check scripts to be written |

**Nothing to do here** beyond re-confirming the bench comes up on this
project's DUT: run `smoke_test.py`, then `blinky_check.py` and
`uart_check.py` against a flashed board. That is the ten-minute proof that
the rig is wired correctly before any real work starts.

## 3. Phase 1 — wire encoder driver (`wire_encoder`) — **NOT STARTED**

The sensor is a draw-wire encoder whose drum turns a **10 kΩ
potentiometer**, read ratiometrically on PA2 (TDS §3.4). This is
electrically the same front-end as the sibling project's wind vane (11 kΩ
pot, same pin, same ADC settings, same float-detection trick), and **that
driver is the reference implementation** — it is HIL-verified on silicon at
±1.0° against a precision divider with ≤3 counts of span over 100 reads.
Start from it. What differs is only what happens above the driver: a linear
opening instead of a circular heading.

### 3.1 Deliverable API (`we.h`)

The driver's job is narrow on purpose: **produce a raw code and say whether
it is trustworthy.** Scaling, offset, windowing, averaging and the fault
*timer* all live above it, in `meas_open.c` and `regs.c`, so the driver has
no knowledge of Modbus, of windows, or of millimetres.

```c
void     we_init(void);            /* front-end bring-up per FR-S18 step 3 */
bool     we_sample(uint16_t *raw); /* one acquisition; false = invalid     */
uint16_t we_raw_max(void);         /* 1023 — 10-bit ADC full scale         */
```

`we_sample()` returning false is the single input to the FR-E07 fault
machine — the driver reports *this sample is bad*, and the layer above
decides when that becomes a fault (2 s) and what the registers say.

### 3.2 Rig

- DUT on the WCH-LinkE (3.3 V + flash + SWIO on PD1).
- Stimulus is a **resistor divider from DUT VDD** with a DMM-measured ratio
  — *not* the M2K AWG. The sibling project learned this the hard way: the
  M2K's absolute accuracy (AWG +25 mV, scope ~1 %/−30 mV low) is nowhere
  near good enough to judge a ratiometric ADC, while a divider from the
  DUT's own rail cancels out entirely. It matters even more here, where
  FR-E03's budget is ±0.1 % of full travel. The M2K stays useful for
  dynamics and end stops.
- Saleae on the debug-UART trace line; the driver traces raw code +
  validity per sample and the assertions run off that.
- For the FR-E01 and FR-E07 rows, the **real draw-wire unit** eventually
  has to be on the bench — a divider proves the firmware, not the
  installation.

### 3.3 Test matrix (HIL, Saleae-asserted)

To be executed as `software/hil/we_check.py`.

| # | Row | Verifies | Method |
|---|---|---|---|
| 1 | End stops read the extreme codes | FR-E11 | Wire fully retracted and fully extended; raw code ≤5 and ≥1018 |
| 2 | Five-point linearity across travel | FR-E03 | Precision divider at 5 ratios spanning the range; each within ±0.1 % of full travel |
| 3 | Stability at a fixed point | FR-E03, FR-E12 | 100 reads over 60 s span ≤3 LSB |
| 4 | Oversampling actually happens | FR-E13 | Code review + row 3; 32 consecutive reads span ≤3 counts |
| 5 | Sample time ≥71 cycles | FR-E12 | Code review; confirmed by row 3 with the real 10 kΩ source impedance |
| 6 | Absolute-after-reset | FR-E01 | Power-cycle with the wire held at a fixed extension; first sample matches the pre-reset sample, with no movement |
| 7 | Invalid sample on disconnect | FR-E07 | Physically lift the wiper wire (a "disabled" M2K AWG channel is ~50 Ω, **not** high-Z — it cannot emulate a disconnection) |
| 8 | Invalid sample on short | FR-E07 | Wiper shorted to rail and to GND in turn |
| 9 | No false fault over a full sweep | FR-E07 | 10-minute continuous open/close cycle; zero invalid samples |
| 10 | Acquisition burst ≪ 1 ms | FR-E13, FR-MB20 | Trace-line timing across the 16-conversion burst |

**Exit criterion:** every row PASS, results recorded in
`software/hil/testReport.md`, before the driver is referenced by the
product firmware.

## 4. Phase 2 — Modbus RTU driver (`modbus_rtu`) — **DONE (inherited)**

`software/drivers/modbus_rtu/` is the sibling project's phase-3 driver,
carried over unchanged. In that project it passed:

- **26/26 matrix vectors** covering FR-MB02/05/06/08–15/19/22/25/28/30 and
  the cross-register constraint hook,
- **40/40 endurance transactions**, zero loss,
- response latency median 5.2 ms on the TTL rig; 1000/1000 through a
  MAX3485 at 4.07/4.12/4.17/4.44 ms (min/med/p99/max).

Two decisions inside it are bench-forced and must not be "cleaned up":
**no HDSEL** (it intermittently swallowed the first byte after bus idle —
the driver switches the USART remap instead), and **polled RX, zero
interrupts** (an RXNE ISR corrupted ~1/3 of frames with no error flags).
See `software/drivers/modbus_rtu/README.md`.

**What is still owed here:** the matrix has never been run *on this
project's DUT*. Re-run `mb_check.py` (to be retargeted to this register
map) once a board exists — the driver is proven, the wiring is not.

## 5. Phase 3 — integration

Hand-off to [`integrationPlan.md`](integrationPlan.md): the product
firmware references the verified libraries in place and adds the register
image, the measurement service, the averaging engine and persistence.

## 6. Risks and open items

- **The mechanism is the other half of the accuracy budget.** FR-E03 splits
  the error into a firmware part (±0.1 % of full travel, provable with a
  divider) and the draw-wire unit's own linearity, backlash and wire
  stretch, which only the real sensor on the real window can show. Plan
  both; a green §3.3 matrix is necessary, not sufficient.
- **The bench has never been stood up for this project.** Every quirk in
  `software/hil/README.md` is inherited knowledge; re-confirm the wiring
  and channel mapping before trusting any capture. Saleae lead labels are
  not channel indices.
- **Actuator noise.** A window actuator is a motor sitting next to the
  sensor cable. None of the sibling project's bench work exercised that,
  and it is the most likely source of a surprise once installed.
- **`we_raw_max()` (1023) must match `WE_RAW_MAX_DEFAULT` in the firmware's
  `sensors.h`**, which seeds holding register 40006's default. Keep those
  two in sync or a fresh device calibrates itself to nonsense on first
  boot, and nothing in the FR-E04 scaling can detect it.
