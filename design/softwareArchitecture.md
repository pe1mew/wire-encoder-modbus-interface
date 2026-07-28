# Software Architecture — Wire Encoder Modbus Interface

| Field | Value |
|---|---|
| Document | Software architecture (design rationale) |
| Project | `wire-encoder-modbus-interface` firmware |
| Date | 2026-07-28 |
| Status | **Inherited baseline, adopted as-is for the Modbus/platform half; the measurement half is a plan.** The zero-ISR super-loop, the module split and the sizing method come from the sibling `windmeters-modbus-interface` project, where they are implemented and HIL-verified on the same MCU. Everything below marked *planned* has not been built here. |
| Related docs | `design/TDS.md` v0.2 (requirements this design satisfies), `design/driverDevelopment.md` (the encoder driver is written against this architecture), `design/integrationPlan.md`, `design/scratchBook.md`; sibling project's `design/softwareArchitecture.md` (the source of §1, §3, §4) |

## 1. Scope and constraints

Target: CH32V003J4M6 — RV32EC, one core, 48 MHz HSI, 16 KB flash, 2 KB SRAM.
The device measures window opening from a draw-wire encoder's 10 kΩ
potentiometer on PA2 (TDS §1.1).

**One build.** Unlike the sibling project, which compiles three sensor
variants from one tree, there is one sensor read one way — so there is no
build selector and no capability macro for the measurement path. Two
compile-time options remain, both off by default and neither a product
variant: `HAVE_END_SWITCH` (the optional PC1 input, §3) and `TEST_HOOKS`
(bench-only).

Given these constraints and the TDS requirements, the architecture is
**zero-interrupt: a cooperative super-loop polls everything.** No RTOS —
it would cost more RAM than the application uses and buys nothing here.

> **Inherited amendment (sibling project, 2026-07-03 phase-3 bench):** the
> original design used a USART RX ISR + SysTick ISR. On the bench, the RXNE
> ISR corrupted ~1/3 of received frames (missing/scrambled leading bytes,
> no USART error flags, wire verified pristine) — symptoms consistent with
> interrupt prologue/state corruption on this RV32EC toolchain path. Polled
> RX fixed it completely (26/26 matrix + 40/40 endurance). Since the main
> loop cycles in ~1 µs versus 1042 µs per byte at 9600 baud, polling is
> provably lossless and interrupts buy nothing. **Do not introduce ISRs in
> this project without first root-causing that failure** (suspect
> `__attribute__((interrupt))` code generation with ch32v003fun). This
> applies here unchanged — same core, same toolchain, same driver binary.

## 2. Structure

```
┌─ main loop (everything, run-to-completion, no ISRs) ────────┐
│ for(;;) {                                                   │
│   modbus_service();      // poll RXNE/errors, stamp ticks,  │
│                          // gap detect, parse, respond      │
│   opening_service();     // PLANNED: 16-conversion ADC      │
│                          // burst, scale, publish on        │
│                          // window close                    │
│   diagnostics_service(); // uptime, counters, switch        │
│   IWDG_refresh();        // only here (FR-S20)              │
│ }                                                           │
└─────────────────────────────────────────────────────────────┘
   No hardware counter needed: the potentiometer is ABSOLUTE, so
   there is nothing to accumulate between samples.
   Timing: raw SysTick->CNT arithmetic (HCLK; FUNCONF_SYSTICK_USE_HCLK 1)
```

Initialization before the loop follows the FR-S18 order strictly:
PC2/DE low first → PC4 address latch (and the optional PC1 switch input) →
sensor front-end ready (ADC self-calibration) → IWDG on → USART1 receiver
enabled last.

**Current state:** `main.c`, `board.c`, `regs.c`, `persist.c` and the `mb`
driver are in the tree and build. `opening_service()` does not exist yet —
the measurement registers hold their FR-S23 pre-first-window value.

*See §7 for the component, super-loop sequence, and Modbus state-machine
diagrams.*

## 3. Key decisions and why

The first three are inherited verbatim and are not up for renegotiation
without bench evidence; the last two are specific to this device.

**Everything stateful lives in the main loop.** Modbus registers are written
by the measurement service and read by the Modbus service — both in the same
sequential loop, so FR-S24's snapshot coherence is *structural*: no masking,
no double-buffering, no races, because there is no preemption between
producer and consumer. This is the single biggest simplification available.

**Frame boundary by polling, not a timer.** The main loop checks
`ms_tick - last_rx_tick ≥ 5` to detect the 3.5-character gap (FR-MB03). A
dedicated t3.5 timer interrupt is the textbook approach, but the loop
iterates thousands of times per millisecond and the detection jitter this
adds is microseconds against a 100 ms budget (FR-MB20).

**Blocking TX from the main loop.** The longest response (~29 bytes) takes
~33 ms of wire time at 9600 baud. Sending it byte-by-byte with a poll on
TXE, then polling TC to drop DE within one character time (FR-MB04), is
simple and deterministic. Self-echo cannot occur: the remap-switching line
discipline (RX native on PD6; TX remapped onto PD6 only for the response,
RO tri-stated while DE is high — HDSEL was abandoned per the §1 amendment)
leaves nothing looped back, and the receiver re-arms only after DE drops
plus a t3.5 idle (FR-MB23).

**An absolute sensor removes the accumulator — and the timer.** The sibling
project's speed path needed TIM2 counting continuously in hardware because
pulses arrive whether or not firmware is looking. A potentiometer carries
the window's position in the sensor: a sample taken now is complete in
itself. Consequences — no timer peripheral is claimed, the measurement
window is purely a *publishing* cadence rather than an accumulation
interval, and FR-E01's "correct immediately after reset, no homing" falls
out for free. The window still matters (it paces averaging and bounds the
FR-E10 rate estimate), but a missed window costs one sample, not a
reference.

**Nothing in this firmware blocks for long.** The ADC burst — 16
conversions at the ≥71-cycle sample time — totals well under 1 ms, and the
optional end-switch debounce (FR-E15) is a comparison against a SysTick
stamp, not a delay: a candidate level simply has to survive 20 ms of
main-loop passes. The only meaningful blocking operations are the ~33 ms
response TX and the ~6 ms flash commit, both inherited, both deliberately
outside the FR-MB20/21 latency path or well inside it. This is worth stating
because it is what a future feature must not break.

## 4. Shared state — the complete list

With zero interrupts there is **no concurrency surface at all**: every
variable has exactly one execution context. The RX buffer, tick stamps,
register image, debounce state, and averaging blocks are all plain
main-loop state. FR-S24's snapshot coherence is absolute by construction.

## 5. Sizing sanity check

**RAM:** 256 B RX + 64 B TX + ~32 B register image + ~384 B averaging blocks
(64 entries × u16 for the mean, plus the FR-E08 min/max blocks) + ~512 B
stack ≈ **1.25 KB**, inside NFR-RES01's 1792 B ceiling.

**Flash:** Modbus core ~2–3 KB, bitwise CRC-16 (~100 B — speed is
irrelevant at 9600 baud), measurement + scaling logic ~1 KB, persistence
~600 B. Comfortably inside NFR-RES01's 14 336 B ceiling, and materially
cheaper than the sibling project's largest build, which spent ~1 KB on a
sin/cos table and CORDIC `atan2` for a circular mean — **the opening is a
scalar, so none of that is needed here.** (Note: RV32EC has no hardware
multiply/divide; libgcc soft routines are pulled in by the FR-E04 math.)

**Latency:** response starts ~5 ms after the frame gap in the sibling
project's measured typical case, and this firmware's loop is strictly
lighter. Meets FR-MB21's 95%-within-15 ms with margin, and FR-MB20's 100 ms
hard limit trivially.

**As-built (skeleton, 2026-07-28):** release build 3 572 B flash / 616 B
RAM; with the end-switch option 3 720 B / 624 B. Both a quarter of the flash
ceiling and a third of the RAM ceiling, so the measurement service and the
averaging engine have ample room. Record the release numbers here when they
land.

## 6. Module split

| Module | Contents | State |
|---|---|---|
| `main.c` | The super-loop and window pacing | **in tree** (no measurement call yet) |
| `board.c` | Clocks, GPIO, FR-S18 init order, PC4 address latch, IWDG + PVD, optional PC1 switch input | **in tree**, inherited |
| `sensors.h` | Build-type byte and the raw full-scale default; no variant selector | **in tree** |
| `mb.c` | Framing, CRC, FC dispatch, exceptions, DE control + remap-switching line discipline — referenced in place from `software/drivers/modbus_rtu` | **in tree**, inherited, HIL-verified in the sibling project |
| `regs.c` | Register image + table-driven `{addr, min, max}` validator — FR-MB19/22/28 become one code path; the FR-S31 + FR-E06 cross-validate hook; persist load/save wiring; the FR-E15 switch debounce | **in tree** |
| `persist.c` | FR-S39 holding-register persistence — two-page flash ping-pong, power-loss atomic | **in tree**, inherited |
| `meas_open.c` | Window pacing, FR-E04 scaling, FR-E07 fault machine, FR-E10 movement rate | **planned** (integration stage D) |
| `we.c` | Raw-code acquisition: 16-conversion ratiometric ADC burst with float detection — to be referenced in place from `software/drivers/wire_encoder` | **planned** (driver phase 1) |
| `avg.c` | Boxcar/two-stage averaging + FR-E08 min/max tracking (FR-S31) | **planned** (integration stage E) |
| `debug_uart.c` | PD6 TX-only tracing (driver phases only; absent from release builds) | **in tree**, inherited |

Driver development happens standalone per `design/driverDevelopment.md`;
this document is the contract the driver integrates back into.

## 7. Diagrams (UML)

The Modbus state machine (§7.3) reflects the **shipped, verified**
implementation carried over from the sibling project. The component and
super-loop diagrams show the **target** design, with planned modules
marked. Sources live in [`design/diagrams/`](diagrams/) as PlantUML;
regenerate the PNGs with:

```sh
"C:/apps/plantuml/plantuml.exe" -tpng -o . design/diagrams/*.puml
```

### 7.1 Component diagram — module structure & data flow

![Firmware component diagram](diagrams/component.png)

Source: [`diagrams/component.puml`](diagrams/component.puml). The
potentiometer → `we` → `meas_open` → **`regs` hub** → Modbus pipeline, with
the cross-cutting `main` super-loop and `board` safety services, and the
`avg` / `persist` satellites off the hub. Solid = runtime data/calls,
dotted = control; orange = planned, not yet implemented.

### 7.2 Super-loop sequence — one cooperative iteration (see §2, §3)

![Super-loop sequence diagram](diagrams/superloop_sequence.png)

Source: [`diagrams/superloop_sequence.puml`](diagrams/superloop_sequence.puml).
One pass of the zero-ISR loop: `mb_poll` (polled RX with the request/response
handled in-line) → `regs_service` → `regs_persist_service` (flash only on a
change, and only after the response) → the measurement service → the
PVD-gated watchdog feed. No interrupts, so there is no concurrency surface.

### 7.3 Modbus RTU line discipline — state machine (see §3)

![Modbus RTU line-discipline state machine](diagrams/modbus_state.png)

Source: [`diagrams/modbus_state.puml`](diagrams/modbus_state.puml), carried
over unchanged. The remap-switching RX/TX discipline: unsynced → idle →
receiving → evaluate → `Responding` (Tx-phase / Rx-phase composite) → idle.
HDSEL was abandoned per the amendment in §1; DE timing and t3.5 gaps carry
their FR IDs on the transitions.
