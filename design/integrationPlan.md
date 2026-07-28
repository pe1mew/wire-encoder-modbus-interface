# Integration Plan — Product Firmware

| Field | Value |
|---|---|
| Document | Product-firmware integration plan and results |
| Project | `wire-encoder-modbus-interface` |
| Date | 2026-07-28 |
| Status | **Stages A–C complete** (skeleton, board bring-up, register image + persistence — all carried over and building). **Stage D onward not started** — blocked on the phase-1 encoder driver. |
| Related docs | `design/TDS.md` v0.1, `design/softwareArchitecture.md`, `design/driverDevelopment.md`, `software/hil/README.md` |

## 1. Purpose

The drivers prove that each mechanism works in isolation. This document is
how they become one product: the stage sequence, what each stage must
demonstrate before the next begins, and the hardware-gated test set that
cannot run until a board exists.

## 2. Inputs — what is already proven

| Input | Provenance | Confidence |
|---|---|---|
| Modbus RTU driver (`mb.c`) | Sibling project phase 3 — 26/26 matrix, 40/40 endurance, latency histogram | High |
| Board bring-up (`board.c`) — FR-S18 init order, PC4 latch, IWDG, PVD | Sibling project, silicon-verified | High |
| Flash persistence (`persist.c`) — FR-S39 ping-pong store | Sibling project, verified across watchdog reset and real power cycle | High |
| Debug UART | Sibling project | High |
| Encoder driver (`we.c`) | **Does not exist** | — |

## 3. Project decisions

1. **Reference driver libraries in place.** `lib_extra_dirs` points at
   `software/drivers/*/lib`; no source is copied into the firmware tree. A
   fix to a driver is a fix everywhere, and the HIL evidence keeps
   pointing at the code that was actually tested.
2. **One release build** (FR-S01/FR-S02): `encoder`, build byte 0x01,
   address 40/45. Two non-product environments exist beside it —
   `encoder_endswitch` (the optional PC1 input, §3.5) and `encoder_test`
   (`TEST_HOOKS`). **Never release a test binary.** There is deliberately no
   variant machinery: one sensor, read one way.
3. **Resource ceilings are build gates, not guidelines** —
   `board_upload.maximum_size` 14336 / `maximum_ram_size` 1792 (NFR-RES01).
   A build that outgrows the budget fails rather than shipping.
4. **The register image is table-driven.** One `{addr, min, max, *value}`
   table makes FR-MB19 (no clamping), FR-MB22 (atomicity) and FR-MB28
   (quantity validation) a single code path, with the FR-S31 and FR-E06
   cross-register constraints in one `cross_validate` hook.
5. **Requirements-first.** A behaviour change starts in `TDS.md`, not in
   `regs.c`.

## 4. Work stages

### Stage A — skeleton — **DONE**

PlatformIO project, both envs building, `sensors.h` capability mapping,
`version.h`. *Demonstrated:* `pio run` succeeds inside the NFR-RES01
ceilings — 3 572 B flash / 616 B RAM for the release build, 3 720 B / 624 B
with the end-switch option.

### Stage B — board bring-up — **DONE (inherited)**

`board.c`: FR-S18 init order with PC2/DE low as the first GPIO action, PC4
address latch (FR-S03), IWDG (FR-S20) and PVD (FR-S22).
*Demonstrated in the sibling project on the same silicon;* **owed here:**
re-confirm the address latch reads 40/45 on this project's first board. The
optional PC1 end-switch input is configured here too, when compiled in.

### Stage C — register image + persistence — **DONE**

`regs.c` implements the complete TDS §2.7/§2.8 map: 12 input registers, 6
holding registers with per-register ranges, the FR-S31 + FR-E06
cross-validate hook, and FR-S39 flash persistence via `persist.c`.
Measurement registers hold their FR-S23 pre-first-window value (0) and
status bits 0/1 are set, which is exactly correct for a device with no
measurement service.

*Demonstrated:* builds and links; a flashed device should answer FC03/FC04
across the whole map and persist holding writes across a reset. **Not yet
executed on hardware** — no board.

### Stage D — measurement service — **NOT STARTED**

Blocked on the phase-1 driver. Adds `meas_open.c`: window pacing from
40002, `we_sample()` per window, FR-E04 scaling with clamping, the FR-E07
fault machine (2 s hold → 65535 + status bit 2), FR-E09 raw diagnostic and
FR-E10 movement rate.

*Exit:* at a fixed reference opening, 30001 tracks FR-E03 accuracy;
changing 40002 changes the publish cadence per FR-E02; disconnecting the
wiper walks the fault machine per FR-E07.

### Stage E — averaging engine — **NOT STARTED**

Adds `avg.c`: the FR-S31 boxcar (exact ≤64 windows, two-stage above) for
30002, plus the FR-E08 min/max tracking for 30003/30004.

**Design note carried forward:** the sibling project's `avg.c` handled both
a scalar and a circular quantity. The opening is a scalar, so the circular
half — a Q15 sin/cos table and CORDIC `atan2`, about 1 KB of flash — is
**not** needed. The new work is the min/max block aggregation, which has no
sibling precedent: a two-stage boxcar's blocks must carry the block minimum
and maximum, not a mean, or the envelope is wrong whenever N > 64.

**Worth challenging before building it:** a window moves slowly and then
stops, and the instantaneous reading is already stable to ≤3 LSB. The
averaging engine is inherited from a sensor measuring a genuinely noisy
quantity. The envelope registers (30003/30004) clearly earn their place —
they tell a master the window moved between polls — but the mean may be
solving a problem this device does not have, at ~384 B of RAM and a stage of
work. Decide deliberately rather than by inheritance.

*Exit:* FR-S23's partial-window rule (no zero-padding), FR-S30's
accumulator clear on a 40002/40003 write, FR-E05's clear on a calibration
write, and FR-E08's envelope test.

### Stage F — acceptance — **NOT STARTED**

The `software/hil/acceptance/` pytest suite run against the flashed
release build, covering every §2 row executable over the link (NFR-TST01)
plus the measurement rows. Populates `software/hil/testReport.md`.

## 5. Budgets

| Quantity | Ceiling | Current | Note |
|---|---|---|---|
| Flash | 14 336 B (NFR-RES01) | 3 572 B *(skeleton)* | Record per release in `softwareArchitecture.md` §5 |
| RAM | 1 792 B (NFR-RES01) | 616 B *(skeleton)* | Averaging blocks are the largest planned addition (~384 B) |
| Response latency | 100 ms hard / 15 ms typical (FR-MB20/21) | not measured here | Sibling project: 4.12 ms median through a MAX3485 |
| ADC burst per window | ≪ 1 ms | not measured | 16 conversions at ≥71 cycles; nothing else in this loop blocks |

## 6. Risks & watch items

- **Stage D and E are the whole product and neither has started.** What is
  in the tree is scaffolding plus proven infrastructure; do not let the
  green build suggest otherwise.
- **The register map may still move.** TDS §6 flags the resolution (0.1 mm
  caps travel at 6.5 m), the movement-rate sign, and a possible
  percentage-open register as open. All three are register-map changes.
  Settle them before any master integrates.
- **`encoder_endswitch` is an unexercised build.** An optional environment
  that nobody flashes rots. Either the mechanism gets switches and this
  becomes the shipped build, or it should be dropped rather than carried
  indefinitely.
- **Two devices per RS-485 segment.** One address jumper, one address pair.
  A site with three instrumented windows on one bus needs a second jumper —
  a PCB change. Decide before layout.
- **Inherited code is verified elsewhere, not here.** `mb.c`, `board.c` and
  `persist.c` have never run on this project's hardware. Stage B/C's
  hardware re-confirmation is not a formality.

## 7. Hardware-gated test set

Everything below needs a board and cannot start until one exists. The
sibling project's `integrationPlan.md` §9 is the template — it splits into
a breadboard MAX3485 rig (before the PCB) and a real-PCB set (RS-485
electrical rows, power chain, connector pinout, enclosure fit). Reproduce
that split here once the hardware design begins, and record every executed
row in `software/hil/testReport.md`.
