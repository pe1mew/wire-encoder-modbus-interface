# Design documentation

This directory holds the design record for the Wire Encoder Modbus
Interface firmware — the chain from first idea to a validated,
requirement-traced implementation. The documents build on each other in
this order:

```
scratchBook  →  description  →  TDS  →  softwareArchitecture  →  driverDevelopment  →  integrationPlan
(brainstorm)   (what it does)  (what   (how + diagrams)         (drivers + results)   (product fw + results)
                in prose)      must
                               be true)
```

## What the device does

Measures **how far a window is open** — a greenhouse vent, a roof light, a
louvre — and publishes it on Modbus RTU over RS-485. A draw-wire encoder
attached to the moving frame turns a **10 kΩ potentiometer**; the wiper
voltage is an absolute measure of the opening, valid the instant power
returns, with no homing move.

## Where this project stands

Read this before trusting a status line anywhere else: **the Modbus and
platform half of this project is inherited and proven; the measurement half
is a plan.** The documents below are honest about which is which, and the
distinction matters when you pick up the work.

| Document | Purpose | Status |
|---|---|---|
| [`description.md`](description.md) | **Functional description** — what the device does, in prose, for an integrator or installer: the sensing principle, what it reports, commissioning, fault behaviour, and what it deliberately does *not* do. Start here. | Current. The measurement path is implemented and verified; §3.1 documents the health bits and §8.1 the end-sensor and draw-wire installation rules |
| [`TDS.md`](TDS.md) | **Technical Design Specification** — the requirements contract (FR-MB…, FR-S…, FR-E…, NFR-…) with measurable pass/fail criteria. The single source of truth for behaviour. | **v0.7 draft.** §2 Modbus and §3.1/§3.2 lifecycle inherited from the sibling project's v0.9 and verified there; §2.7/§2.8 register map and the FR-E series are new and expected to move; §4 hardware open |
| [`softwareArchitecture.md`](softwareArchitecture.md) | **How** the requirements are met: the zero-ISR cooperative super-loop, the module split, the sizing rationale. §7 embeds the UML diagrams. | Current. All modules are in the tree and verified; §5 carries the as-built sizes and the **1.146 ms blocking budget** |
| [`driverDevelopment.md`](driverDevelopment.md) | Plan + results per standalone driver, each HIL-verified before integration. | All phases satisfied. Phase 1 (the encoder driver) is written, HIL-verified and integrated; its acceptance rows close through integration stages D–E |
| [`testPlan.md`](testPlan.md) | **Hardware test plan** — every row traced to a TDS verification clause, grouped by what the current image can actually exercise: electrical (no firmware), protocol and lifecycle, and what stays blocked until integration stage D. | **v0.3.** Groups B and C executed and passing; Group A partly blocked on an adjustable PSU and a PCB. Every requirement is gate-checked for a test row by `test_traceability.py` |
| [`integrationPlan.md`](integrationPlan.md) | The product-firmware plan: stages A–F, each with an exit criterion, plus the hardware-gated test set. | **Stages A–F all complete.** Remaining work is blocked on instruments, not code |
| [`scratchBook.md`](scratchBook.md) | The brainstorm and working notes seeding the TDS — the sensor, the pin budget, scaling derivation, resolution/range decision, hardware questions. | Working notes |
| [`windowEmulator.md`](windowEmulator.md) | **Window and window-controller emulator** — a bench rig standing in for a window and its actuator controller: the control logic and its truth table, plus the mechanical and safety requirements. Scoped to the rig alone; it specifies nothing about what is mounted on it. | **v0.4 — built and in bench service.** Closed seven FR-E/EM rows. §1.1 records two as-built traits that change how results read |
| [`requirementsCompliance.md`](requirementsCompliance.md) | Compliance check against the `greenhouse-Controller` M3 window-position-sensor requirements study — a matrix of that document's FR-WP/NF-WP requirements against this design, with the gaps. | Analysis only; the source study is itself marked *not adopted*. **FR-WP07 is flagged conditional** — bit 3 reports the sensor, not the window |
| [`diagrams/`](diagrams/) | UML diagrams as PlantUML sources + rendered PNGs, plus the window-emulator controller schematic (see below). | — |
| [`../docs/modbusInterfaceContractSpecification.md`](../docs/modbusInterfaceContractSpecification.md) | **Interface contract for the client** — the greenhouse controller's view: where each value lives, what it means and does *not* mean, how to teach, which bits are alarms and which are health. Organised by purpose, every statement traced to a TDS requirement. §8 sizes the configuration to the target window (1.5 m in 171 s, the M3 travel time) and gives the study's FR-WP20 threshold — which turns out to be that window's nominal speed — the margin it needs. | **v1.1.** Derived from TDS v0.7; the TDS stays normative. Not a design input — a design *output* for the other side of the bus |

## The constraint that shapes everything

The CH32V003**J4M6** is the SOP-8 package, and several GPIO share one
physical pin (pin 1 is PD6 *and* PA1; pin 8 is PD1, PD4 *and* PD5). There
are **six physical I/O pins and every one is committed**: Modbus data, the
potentiometer wiper (ADC ch0), RS-485 DE/RE, the address jumper, the
end-switch ladder (ADC ch2), and SWIO. Check any front-end proposal against
TDS §4.2 before assuming a pin exists.

Note the PC1/PC4 assignment is the reverse of the obvious one: **PC4 has an
ADC channel and PC1 does not**, so the analog pin goes to the switch loop
(which has more than one bit to say) and the boot-time address jumper takes
the digital pin.

## Diagrams

Three UML views live in [`diagrams/`](diagrams/) and are embedded in
[`softwareArchitecture.md`](softwareArchitecture.md) §7:

- **[`component.puml`](diagrams/component.puml)** — module structure & data
  flow (potentiometer → `we` → `meas_open` → `regs` hub → Modbus). Planned
  modules are shaded.
- **[`superloop_sequence.puml`](diagrams/superloop_sequence.puml)** — one
  zero-ISR super-loop iteration.
- **[`windowEmulatorController.py`](diagrams/windowEmulatorController.py)** —
  not UML: the window-emulator controller schematic, rendered to
  `windowEmulatorController.png` by running the script. Embedded in
  [`windowEmulator.md`](windowEmulator.md) §3.
- **[`modbus_state.puml`](diagrams/modbus_state.puml)** — the Modbus RTU
  line-discipline state machine, carried over unchanged from the sibling
  project (the protocol behaviour is identical).

Regenerate the PNGs with the local PlantUML:

```sh
"C:/apps/plantuml/plantuml.exe" -tpng -o . design/diagrams/*.puml
```

## Build configuration

**One release build** (FR-S01) — there is one sensor read one way, so there
is no variant machinery. It is addressed by a **PC1** solder jumper:

| Jumper | Address |
|---|---|
| open | **40** |
| bridged | 45 |

Deliberately clear of the sibling windmeters family (30–37) so both can
share one RS-485 segment. One non-product environment sits beside the
release build: `encoder_test` (bench-only hooks — never released).

## How this connects to the rest of the repo

- The **API reference** ([`Doxyfile`](../Doxyfile) at the repo root) folds
  these design documents in as pages alongside the header/source
  documentation — run `doxygen Doxyfile` for a single browsable site with
  the project [`README.md`](../README.md) as its landing page.
- The requirements here are verified by the scripted bench in
  [`software/hil/`](../software/hil/); every executed test with its
  setup/expected/verdict belongs in
  [`software/hil/testReport.md`](../software/hil/testReport.md).
- Contribution workflow (requirements-first, build, run the acceptance
  suite) is in [`contributing.md`](../contributing.md).
- **The sibling project is part of the design record.** Where this chain
  says "inherited", the reasoning and the bench evidence live in
  [`windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface)'s
  `design/` directory. Don't re-derive what is already written down there —
  in particular, its vane driver is the reference implementation for
  reading a potentiometer on PA2.
