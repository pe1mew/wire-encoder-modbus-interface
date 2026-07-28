# HIL Test Report

Consolidated record of every hardware-in-the-loop test executed against
this project's device under test: setup, expected result, pass criteria,
and verdict.

| Field | Value |
|---|---|
| Project | `wire-encoder-modbus-interface` |
| Last updated | 2026-07-28 |
| DUT | *none — no hardware exists yet* |

---

## Status: no tests executed

**Nothing in this repository has been run on hardware.** There is no board,
no flashed device, and no bench standing for this project.

What that means when reading the rest of the repository:

- The verification claims in `software/drivers/modbus_rtu/README.md` and in
  `design/driverDevelopment.md` §4 are **inherited** from the sibling
  [`windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface)
  project. They were earned on the same MCU, the same framework and the
  same driver source — but on that project's hardware. Its evidence lives
  in that repository's `software/hil/testReport.md`.
- Carrying code across a repository boundary carries the code, not the
  evidence. `mb.c`, `board.c` and `persist.c` are proven; *this device*
  running them is not.

## What goes here first

In order, once a board exists:

1. **Bench bring-up** — `smoke_test.py`, `blinky_check.py`, `uart_check.py`.
   Proves the rig before anything rests on a capture.
2. **Board bring-up (integration stage B)** — the FR-S03 address latch
   reads 40 with the jumper open and 45 bridged; FR-S18 init order leaves
   the transceiver quiescent through reset.
3. **Register map (stage C)** — the full TDS §2.7/§2.8 read/write matrix
   plus FR-S39 persistence across a watchdog reset.
4. **Modbus protocol matrix** — the §2 rows re-run on this DUT.
5. **Encoder driver (phase 1)** — the `driverDevelopment.md` §3.3 matrix.
6. **Measurement and averaging (stages D/E)**, then the full acceptance
   suite (stage F, NFR-TST01).

## Report format

One section per test, so a reader can reproduce it without reading the
script:

```
### <ID> — <short name>

| Field | Value |
|---|---|
| Requirement(s) | FR-… |
| Script | software/hil/<script>.py |
| Setup | instruments, wiring, DUT build flashed |
| Stimulus | what was applied |
| Expected | the measurable outcome |
| Pass criterion | the threshold that decides it |
| Result | measured numbers |
| Verdict | PASS / FAIL / BLOCKED, with the date |
```

Regenerate or extend this report whenever a check script or a design
document changes — a stale test report is worse than none, because it
reads as evidence.
