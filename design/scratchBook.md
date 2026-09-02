# Scratch book — working notes

Working notes for the wire-encoder interface: what the registers mean, how
the hardware might be wired, how the scaling is derived. Superseded by
[`TDS.md`](TDS.md) wherever the two overlap — the TDS wins.

Started 2026-07-28 from the sibling
[`windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface)
project.

---

# The job

Measure **how far a window is open** and put the number on Modbus.

The window — a greenhouse vent, a roof light, a louvre — is driven by an
actuator. Something needs to know the current opening: to hold a setpoint, to
verify the actuator actually moved, to close everything before a storm.

## The sensor

A **draw-wire encoder**: spring-loaded drum, steel wire to the moving frame,
drum geared to a **10 kΩ potentiometer**. Pull the wire out, the pot turns.
The wiper is a plain voltage divider from the supply rail, so:

- It is **absolute**. Power returns, the wiper is where it always was, the
  reading is correct with no homing move and no count to recover. This is the
  single most important property and it makes the firmware much simpler than
  an incremental encoder would.
- It is **ratiometric**. The pot is fed from the same 3.3 V that references
  the ADC, so rail ripple and rail drift cancel exactly. No external
  reference — adding one would *break* that cancellation, which is
  counter-intuitive enough to be worth writing down.
- It is **electrically identical to the sibling project's wind vane** (11 kΩ
  pot on PA2, 10-bit ADC, ≥71-cycle sample time, float detection by pull-
  resistor toggle). That driver is HIL-verified on silicon and is the
  reference implementation. What differs is only what happens *above* the
  driver: a linear opening instead of a circular heading, so none of the
  circular-mean machinery carries over.

---

# Pin budget — the binding constraint

Read this before proposing any front-end change.

The CH32V003**J4M6** is the SOP-8 package: eight pins, two of them power.
And several GPIO **share one physical pin** — pin 1 carries PD6 *and* PA1;
pin 8 carries PD1, PD4 *and* PD5. A list of port names ("PA1 PA2 PC1 PC2 PC4
PD4 PD6 are usable") therefore badly overstates what is available. There are
**six physical I/O pins.**

| Pin | Port(s) | Capability | Committed to |
|---|---|---|---|
| 1 | PD6 (= PA1) | USART | Modbus data |
| 3 | PA2 | **ADC A0** | Pot wiper |
| 5 | PC1 | digital, 5 V tolerant | **Address jumper** |
| 6 | PC2 | digital, 5 V tolerant | RS-485 DE/RE |
| 7 | PC4 | **ADC A2** | **End-switch loop** |
| 8 | PD1 (= PD4/PD5) | SWIO | Programming |

**Everything is committed. There is no spare pin.**

## The PC1 ↔ PC4 swap (decision, 2026-07-28)

The obvious assignment — address jumper on PC4, switches on PC1 — wastes the
better pin. **PC4 has an ADC channel (A2); PC1 does not.**

- The **address jumper** is a board-local solder blob read once at boot. It
  is a pure digital question and does not care which pin it sits on.
- The **end switches** are at the far end of a cable, on a moving window,
  and there are two of them. Everything you might want beyond "a switch is
  closed" — which switch, whether the cable is intact — needs more than one
  bit.

So swap them: **address jumper → PC1, end-switch loop → PC4.** It costs
nothing, changes no requirement, and turns a one-bit input into a
multi-state one. Do it before the PCB is laid out; afterwards it is a cut
track.

The only thing given up is PC1's 5 V tolerance on the switch loop — the
supervised loop below is fed from the board's own 3.3 V pull-up, so it never
needed 5 V anyway.

---

# Software

## Scaling

Opening is a straight two-point linear map from the raw ADC code:

```
opening[0.1 mm] = offset + ((raw − raw_closed) × travel) / (raw_open − raw_closed)
                   40001              40005      40004     40006      40005
```

All four constants are holding registers, all persisted (FR-E04/FR-E05). The
point of doing it this way rather than with compile-time constants: one
firmware image serves any window, and **calibration is a field operation over
Modbus** — close the window, read 30005, write it to 40005; open it fully,
read 30005, write it to 40006; write the measured travel to 40004. Done, no
rebuild, survives power loss.

Overflow check: `65535 × 65534 = 4,294,770,690` fits `uint32_t`
(max 4,294,967,295) with **196,605 to spare — 0.0046 %**. Verified by
exhaustive corner testing, not by inspection; an earlier hand calculation of
this product was wrong by 393,000 and overstated the margin threefold, which
is itself the argument for testing it rather than reasoning about it. It holds
only because both operands are 16-bit. If the opening ever becomes 32-bit (see
below), redo this.

Note what this is *not*: a constant derived from theory with an uncertainty
attached. Calibration here is **measurement** — the two end points are things
you can physically go and observe, so the only error is the one you make
observing them.

## Resolution and range — decide before publishing the map

0.1 mm in a 16-bit register caps travel at **6553.4 mm**. Ample for a window
vent. Options if that ever binds:

| Resolution | Max travel | Cost |
|---|---|---|
| 0.1 mm | 6.5 m | Current draft |
| 1 mm | 65 m | Coarse for a small vent |
| 0.1 mm, 32-bit (two registers) | 429 km | Register-map change; masters must read the pair in one FC04 (they can — quantity 2) |

The real limit is the sensor's wire length, not the register. Match them.

## Percentage open

A master asking "how far open, in percent" currently has to divide 30001 by
40004 itself. A dedicated register (0–1000 = 0.0–100.0 %) would be one
addition to §2.7 and would make the common case trivial — for a window, the
percentage is arguably the *natural* unit and millimetres are the
implementation detail. Not added yet only because the map edge is a
compatibility commitment once a master integrates. Worth revisiting early.

## Averaging

Same boxcar as the sibling project (FR-S31): N = floor(40003 × 1000 / 40002)
completed windows, exact up to 64, two-stage beyond. The opening is a scalar,
so the circular-mean machinery (Q15 sin/cos table + CORDIC atan2, ~1 KB of
flash) is **not** needed — the one place this firmware is structurally
cheaper than its sibling.

New problem with no sibling precedent: the FR-E08 min/max envelope. In the
two-stage case each block must carry its own minimum and maximum, not a mean,
or the reported envelope is wrong whenever N > 64. Cheap to do right, easy to
get wrong by pattern-matching on the mean path.

Worth questioning at some point: **how much averaging does a window actually
need?** A window moves slowly and then stops. The instantaneous reading is
already stable to ≤3 LSB. The averaging engine is inherited from a sensor
measuring a genuinely noisy, fast-changing quantity; here it may be solving a
problem that does not exist. It costs ~384 B of RAM and a stage of integration work.
Left in for now because the envelope registers (30003/30004) do earn their
place — they tell a master the window moved between polls.

## Movement rate

30012 reports the opening delta between consecutive windows, scaled to
0.1 mm/s. Cheap (one subtraction and a divide by the window). Useful for
"is the actuator actually running?".

Open: signed or magnitude? Signed distinguishes opening from closing at no
register cost but halves the range to ±3276.7 mm/s. For a window actuator the
*direction* is arguably worth more than the range — nothing on a window moves
at 3 m/s.

## Fault detection

Toggle the internal pull resistor on PA2 between conversions and compare: a
floating wiper follows the pull, a driven one does not. Straight from the
sibling project's FR-S38.

Policy lives above the driver: hold the last valid value for 2 s, then report
65535 and set status bit 2. The driver only ever says "this sample is bad".

A cut wire to a window on a roof is a realistic failure, and 65535 in
30001–30004 is unmistakable — no plausible opening is 6553.5 mm.

## End switches — **mandatory**

> **Superseded 2026-07-29.** The sensor is an LJ18A3-8-Z/BX inductive
> proximity switch, and its output has an **internal 10 kΩ pull-up to +V** —
> it is not a dry contact and it does not float. Everything below was written
> for dry contacts; the pull-up topology it describes would have put 10–14 V
> on the ADC pin. **The shipped design is the attenuating divider in TDS
> §4.4.** This section is kept for the reasoning that still holds — why the
> switches are mandatory, why the loop is supervised, and why the ladder does
> not try to say *which* switch — but no number in it is current.


**Decision: the end switches are part of the product, not an option.** They
are how the device knows the window has physically reached a stop, which the
measured opening can only ever *infer* — and the inference is only as good as
the calibration, which is exactly what you cannot trust after someone
re-strings the wire or the drum slips. A window actuator driving into a
closed stop is a real way to break things.

That kills the `-D HAVE_END_SWITCH` build option. One build, switches
present, PC4.

### Two ways to wire them

**Option 1 — one digital pin, normally-closed series loop.** Both switches
NC, in series. Loop intact = window is between the ends. Either switch opens
= an end reached. A cut cable also reads "end reached", which fails safe.
Which end follows from the reported opening.

Simple, two conductors, no analog. Loses: which switch, and any distinction
between "at an end" and "cable cut". It was the plan while PC1 was the only
pin available.

**Option 2 — resistor ladder on the ADC (PC4).** One pin, several states.
This is what the swap buys, and it is worth taking.

### What a 2-switch ladder can and cannot do

Board-side pull-up `R_pu` to 3V3; each switch shorts a resistor to GND. ADC
count = `1023 × R_low / (R_pu + R_low)`, and because the ladder is fed from
the same rail the ADC references, the thresholds are **ratiometric** — rail
drift cancels, exactly as it does for the wiper.

The trap: with two switches to GND, "both closed" is the parallel
combination, and `R_A ∥ R_B` is always **below** the smaller of the two — and
it approaches that smaller value as the two resistors diverge. So:

| Goal | Choose | Result |
|---|---|---|
| Tell A from B | Very different resistors (22k / 6.8k) | A = 703, B = 414 — clear. But "both" = 350, only 64 counts under B |
| Tell "both" from "one" | Equal resistors (10k / 10k) | one = 512, both = 341 — 171 counts apart. But A and B are now identical |

**You can resolve *which* switch, or you can resolve *both-closed*, but not
both well.** That is a property of the topology, not of the resistor values,
and it is worth knowing before spending an afternoon on it.

Given the opening is already measured to ±0.1 % of travel, *which* switch is
the redundant one. So spend the resolution elsewhere.

> ⚠️ **Corrected 2026-08-31 — the "not both" claim above is NPN-only.**
>
> Everything above assumes the NPN topology: switches *shorting* resistors to
> GND, where `R_A ∥ R_B` collapses toward the smaller resistor as the two
> diverge. That is what makes the two goals fight.
>
> The 3RG4023-3AB00 is **PNP** and *sources* through its summing resistor, so
> the arithmetic is different, and four states **can** be separated with
> asymmetric resistors. Scanning the E24 range against the measured bands
> finds 202 workable pairs at ±15 % supply. The best, 75 k / 110 k, gives
> 102 / 326 / 434 / 591 counts — all four states, including which switch.
>
> **It is still the wrong choice, but now for a measurable reason rather than
> an impossibility.** That arrangement leaves **7 counts** at its tightest
> point where the symmetric 68 k / 68 k pair leaves **38**. Seven is inside
> the noise: FR-E12 allows ±3 counts of ADC spread at a fixed input, and 1 %
> resistors alone eat about 6 of the 7 — a 750 Ω error on 75 k moves that band
> by ~3.6 counts, with the second resistor contributing as much again. Nothing
> would be left for temperature, and nothing at all for the leakage question
> in §4.4.4 that is still open.
>
> So the conclusion is unchanged and the reasoning is not. The honest form is:
> *the position registers resolve which end far more robustly than the switch
> path could, so the switch path spends its resolution on the one thing
> position cannot report — both switches active at once.* FR-E18 already
> attributes an end-stop capture that way, by direction of travel and
> proximity to the calibrated endpoints.
>
> Worth noting how this was nearly missed: the claim was true when written,
> the sensor changed underneath it, and the proof kept reading as if it were a
> law. A margin argument that has quietly become an impossibility claim is
> exactly the kind of thing to re-derive after a part change.

### Recommended: supervised loop

Take the equal-resistor arrangement and add an **end-of-line resistor**
permanently across the loop at the sensor end. Now the cable itself is
monitored:

```
   3V3
    │
   10k  R_pu (board)
    │
  PC4 ●────────── cable ──────┬──────────┬─────────┐
    │                         │          │         │
   ADC                      4.7k       4.7k      47k   R_eol (field,
                              │          │         │    at the far end)
                            SW_A       SW_B        │
                              │          │         │
                             GND        GND       GND
```

| State | Nominal count | Decision band |
|---|---|---|
| Cable open / R_eol missing | 1023 | ≥ 930 |
| Normal — between the ends | 843 | 550 – 930 |
| One end switch closed | 306 | 245 – 550 |
| Both closed (wiring fault) | 187 | 100 – 245 |
| Cable shorted to GND | 0 | < 100 |

Nearest nominal-to-threshold margin is ~58 counts (≈ 0.19 V) — comfortable
against 1 % resistors and the ±2 counts of ADC noise the sibling project
measured. Use 1 % parts; 5 % will eat that margin.

What this buys over a bare digital pin: **a cut or shorted cable is
distinguishable from a switch operating.** For a sensor on a roof window
that is the difference between "the window is closed" and "we have no idea
where the window is", and it costs one resistor in the field.

### What the LJ18A3-8-Z/BX changes (2026-07-29)

**The good news first.** 6–30 V spans the board's 24 V PoE rail, so the
sensors run straight off it — no extra regulator, no load on the 3.3 V rail.
And being non-contact, they retire the 25 000-cycle wear worry for the
switches entirely; only the potentiometer still carries it.

**The problem.** Every band value in the table above assumes a contact that
closes to 0 Ω. An NPN open-collector output closes to `Vsat`, not to zero,
and that offset lands directly on the "active" levels:

| `Vsat` | open | normal | one active | both active |
|---|---|---|---|---|
| 0 V *(as tabulated)* | 1023 | 844 | 306 | 187 |
| 0.5 V | 1023 | 844 | 405 | **308** |
| 1.5 V | 1023 | 844 | **602** | 549 |

Against the thresholds as written (normal ≥550, one ≥245):

- **at 0.5 V**, "both active" (308) climbs above the 245 threshold and decodes
  as *one active* — a wiring fault reported as a normal end-stop;
- **at 1.5 V**, "one active" (602) climbs above the 550 threshold and decodes
  as *normal* — the device would say the window is clear of its stops while a
  sensor is actively signalling.

Both are **silent** mis-decodes. Nothing flags them; the number simply means
something other than what the table says. That is the worst shape a bug can
take in this device, and it arrived through a hardware substitution that looks
like a straight swap.

Neither document in `documentation/` states `Vsat`. It has to be measured on
the actual part at the actual pull-up current (a few hundred µA, far below the
sensor's rated load, so the low end of its range is likely) — and then the
resistors and thresholds re-derived. That is now a blocking item in TDS §6.

**Take the four-band simplification while re-deriving.** "Both active" and
"cable shorted" are both impossible-state faults, both set bit 4, and neither
is separately actionable — the answer to either is *go and look*. Merging them
into one fault band below "one active" frees the bottom of the range and
recovers most of the margin `Vsat` eats. Five states become four and nobody
loses anything they were using.

**And a new failure mode.** With dry contacts, any cable break disconnected
the EOL resistor and read as *cable open*. With powered sensors, a break in
the **+V conductor alone** kills both sensors while the 0 V and output
conductors keep the EOL resistor connected — so the loop reads a healthy
*normal* for ever, including at an end stop. That is exactly the
plausible-but-wrong state the supervision existed to prevent, reintroduced by
the move to active devices. Fixable at the schematic by deriving part of the
pull-up from the sensors' +V at the far end, so losing it shifts the level.

Two smaller consequences:

- **Four conductors, not two** (+V, 0 V, out A, out B). The gland and terminal
  block sizing in §4.5 assumed two.
- **Power-on delay.** These sensors need tens of milliseconds before their
  output is valid, which FR-S18's "first published state must match reality"
  has to accommodate.

### Firmware consequences

- The ADC now multiplexes two channels: A0 (wiper, ≥16 conversions) and A2
  (ladder, a couple of conversions). Same ≥71-cycle sample time serves both
  — the ladder's source impedance with a switch closed is ≤ 5 kΩ, well under
  the 10 kΩ the sample time was chosen for.
- Debounce stays in firmware, 20 ms, as a SysTick comparison — never a
  delay. Nothing in this loop is allowed to block.
- The status register needs more than one bit now: at minimum *end reached*
  and *switch-loop fault*. Both should go in the §2.7 status word rather
  than a new register.
- The fault states are diagnostics, not alarms — report them, do not let
  them suppress the opening reading.

### Where this decision landed — **propagated in full (TDS v0.3)**

This section was the decision; the TDS and the firmware have since caught up.
Recorded here so a reviewer can check the loop closed rather than take it on
trust — and so that anyone reopening the decision knows every place it
touches.

**Requirements** (`design/TDS.md`)

| Where | What changed |
|---|---|
| §1.1, §1.2 | End switches described as a supervised ladder; "mandatory" and the PC1↔PC4 rationale added to the fixed decisions |
| §2.7 | Status word: bit 3 *end of travel reached*, **new** bit 4 *switch-loop fault*; bit 2 renamed *wiper* fault now that two independent front-ends can fault |
| §3.1 | FR-S01 no longer permits an optional product feature; FR-S03 and FR-S18 read the jumper on **PC1**; FR-S18 gained criterion (c) — the first published switch state must match reality with no spurious transition |
| §3.5 | Rewritten and mandatory: **FR-E14** (sample ≥10 Hz, classify into five bands, unbanded → "cable open" as the safe default), **FR-E15** (20 ms debounce, never blocking), **FR-E16** (fault bit for the three impossible states, *report only*) |
| §3.7 | FR-S33 bitfield redefined, with the note that bits 2 and 4 are independent and may combine |
| §4.2 | Pin table rebuilt with a capability column; every pin committed; the swap justified in place |
| §4.4 | **New section** — the ladder schematic, band table with nominals and thresholds, the ~58-count worst margin, the 1 % resistor requirement, and the warning that the EOL resistor must be *in the field* |
| §6 | "One input for two switches" dropped as an open item; switch polarity added in its place |
| FR-MB27 | Lost its "where not fitted, the bit reads 0" clause — there is no *not fitted* |

**Firmware**

| File | What changed |
|---|---|
| `sensors.h` | `HAVE_END_SWITCH` gone; the switches are part of the product |
| `board.c/h` | Address jumper moved to PC1. `board_end_switch_active()` **removed** — the ladder is an ADC read, and the ADC has one owner (the driver), so a digital accessor on the board layer would have been the wrong home |
| `regs.c/h` | `regs_publish_switches(raw)` added: the §4.4 band thresholds, the classifier, a SysTick debounce that measures elapsed time rather than call count. `STATUS_END_REACHED` + `STATUS_SWITCH_FAULT`; `STATUS_SENSOR_FAULT` → `STATUS_WIPER_FAULT` |
| `we.h` | `we_switch_sample()` added to the driver contract |
| `platformio.ini` | `encoder_endswitch` environment deleted |

**Everything else:** `Doxyfile` (`PREDEFINED`), `test_builds.py` (env list),
`conftest.py` (`--endswitch` option), `hil/README.md` (check-script table),
`component.puml`, `softwareArchitecture.md`, the three READMEs,
`integrationPlan.md`, `RELEASES.md`, `changelog.md`.

### What is genuinely still owed

Documentation is complete. What remains is implementation and evidence:

1. **`we_switch_sample()` does not exist.** The whole encoder driver is
   unwritten (driver phase 1), so nothing produces a ladder reading yet.
2. **`regs_publish_switches()` is never called.** It compiles and its logic is
   settled, but wiring it to the measurement service is integration stage D.
   Until then it has been exercised by the compiler and nothing else.
3. **The five bands have never been measured.** They are arithmetic — resistor
   values, a ~58-count worst margin, and the assumption that 1 % parts hold
   it. That wants a breadboard *before* the PCB is laid out, not after. It is
   the item most likely to need the numbers moved.
4. **Switch polarity is still open** (TDS §6). §4.4 assumes normally-open
   contacts closing to GND; normally-closed inverts the whole table and
   changes which state means "cable cut". Decide before the resistor values
   go on a schematic.
5. ~~**The end-of-line resistor is an installation instruction**, not a BOM
   line on the board.~~ **Overtaken by the star decision below** — it is now a
   BOM line on the board, and the degradation this warned about is what the
   design has, deliberately.

### The sensor changed to PNP — 2026-08-29

The LJ18A3-8-Z/BX is out; **3RG4023-3AB00** is in, because there are units on
the bench. It is **PNP** where the old one was NPN, and that single fact
rewrites §4.4 from top to bottom: an NPN sits high when inactive and pulls
low; a PNP is open when inactive and drives high. Normal becomes the *lowest*
reading instead of the highest.

Worth recording what this did to the two things the star decision below was
agonised over.

**The fault band did not survive, and could not have.** With a PNP
normally-open output, *inactive*, *cable open* and *shorted to 0 V* are the
same electrical condition — nothing sourcing. There is no clever value choice
that separates them, because there is no current to measure. So the ladder
went from four states to three, and bit 4 now means *both active* and nothing
else.

But note what actually changed about the failure, because it is easy to
over-read as a regression. Both before and after, **an open sensor cable is
undetected** — that was already true from the moment the star put the summing
resistors on the board. What flipped is the *direction*: the NPN reported a
**false stop** (337 counts, inside the one-active band), the PNP reports a
**missed stop** (~0, inside normal). Which is worse depends on the controller.
A false stop makes a master believe the window reached its limit; a missed
stop makes it believe the window never did. Neither is flagged. The honest
summary is that the undetected failure moved, it did not appear.

**The temperature ceiling closed, and that is the real prize.** +65 °C was the
LJ18A3's, it was NFR-ENV01's limit, and it was *the one requirement this
design knowingly failed* against the greenhouse study. The new part runs to
+85 °C. The old §6 entry said the answer would be "a wider-range end switch";
it arrived as a change of part rather than as the temperature survey we
expected to have to do. Worth noticing how cheaply a documented gap closed
once the constraint was named and attached to a specific part — the entry
existed precisely so that anyone touching the BOM would see it.

**One number is now doing all the work.** The ≤2.5 V output drop is a 300 mA
specification and this network draws 290 µA. If the drop is small, the bands
have 63 counts of margin; if it is really 2.5 V, they have 23. Nothing in the
datasheet distinguishes those, so it goes on the bench with the units already
there — replacing the LJ18A3 internal-pull-up measurement that the change made
moot.

---

### The installation is a star — decision, 2026-08-07

The PCB is the hub; the draw-wire and **each** end switch run their own cable
back to it. There is no field junction, so the 100 k summing resistors and the
470 k have nowhere to live except the PCB.

This invalidates the supervision the whole ladder was chosen for, and it is
worth being blunt about why, because the reasoning above reads as if the
supervised loop were free. It was never free — it was paid for with a junction
box at the window, and that box is what the star declines to install.

**What a cut costs, in counts.** With the summing on the board, an open sensor
cable removes that branch's pull-up, and *removed* lands between *inactive*
and *active*:

| | Node | Counts |
|---|---|---|
| Normal, both inactive | 5.52 V | 547 |
| One sensor at a stop | 3.02 V | **299** |
| One sensor cable open | 3.40 V | **337** |

38 counts apart, inside one band. So a cut does not read as a fault, it reads
as **a stop that did not happen** — and a false stop is worse than a detected
fault, because the controller acts on it rather than alarming.

**And it cannot be tuned out.** §4.4.4 needs ≥45 counts of margin just for the
±15 % supply tolerance, so 38 was never going to survive. Nothing at the far
end helps either: a cut removes the branch whatever is fitted there, and the
resulting level is set entirely by what remains on the board. This is the same
wall as "What a 2-switch ladder can and cannot do" above — one 10-bit pin,
four bands, no room for a fifth state. The pin is out of
resolution, not the values out of tune.

**What the star buys back.** Not nothing, and the gain is where the
leakage analysis under "Humidity" below already taught us to look. Field-mounted 100 k and 470 k would sit uncoated in the
dampest, least controlled part of the installation:

| Leakage in the junction | Breaks at | Effect |
|---|---|---|
| signal → 0 V | 37 kΩ | *normal* reads as a stop — false stop |
| signal → +V | **182 kΩ** | *one active* reads as normal — **a real stop is missed** |

The second is five times easier to reach, sits between adjacent terminals, and
fails in the direction where the window keeps driving. On the PCB, inside IP65
and coated, both stop mattering. So the star moves one hidden failure out of
the harness and turns one detectable failure into a hidden one. A trade, not a
rout — but the losing side of it is now a **Must** requirement narrowed
(FR-E16) and that deserved recording rather than absorbing.

**The mitigation that is still available.** Firmware, not hardware: once
FR-E19 has taught the endpoints, a stop claimed while the wiper sits far from
either calibrated end is implausible, and the two independent front-ends can
check each other. That would catch most of this class for free. Not specified
— it needs a tolerance, and an answer for what to do before the first teach.
Recorded in TDS §6.

---

# Open questions

Raised 2026-07-28, not yet decided. Neither is in the TDS as a requirement;
both are flagged in TDS §6 pointing here.

## Q1 — can the end switches auto-calibrate the endpoints? — **ANSWERED, implemented**

**Policies (a) report-only and (b) teach-on-command were taken; (c) always-on
was not.** FR-E18 publishes the raw code seen at each stop in 30013/30014;
FR-E19 adds a commanded teach through 40007, committing only once both stops
have been reached *and* both values read. Always-on self-calibration stays
rejected for the flash-wear and accumulator-churn reasons below.

The analysis that led there is kept below.

---

**Yes, and it fixes exactly the right failure mode — but not naively.**

When a switch closes, the window is *known* to be at that stop. The raw ADC
code at that instant is, by definition, the calibration point for that end.
So the device could re-learn 40005/40006 by itself.

**Why this is more than a convenience.** Think about what actually drifts.
The wire slips on the drum, or someone re-strings it after a service: the
same physical travel now maps to a *different raw span*, so the reported
millimetres go wrong. But the physical travel itself — the tape-measure fact
in 40004 — has not changed at all. Re-learning the two raw endpoints while
leaving 40004 alone corrects precisely that, and nothing else. The split
between "raw endpoints, learnable" and "millimetres, measured once" turns
out to be the right one.

### The use case that changes the arithmetic (2026-07-29)

Until the greenhouse M3 requirements study landed, this was a convenience
feature: *the endpoints could re-learn themselves and save a commissioning
step.* Weighed against flash wear and the which-end-fired ambiguity, that was
a thin case, and the honest answer was "probably not worth it".

The study reframes it, because it states what the sensor is actually *for*.
Its §1.2 — "Position is currently open-loop dead reckoning… Invisible today:
motor slip, drive-belt/chain failure, obstruction, ice, end-switch failure, a
window physically blocked part-way" — is a request for **mechanical fault
detection**, and its AT-WP09 acceptance test is *obstruct the window mid-travel
and detect the divergence*. Detecting that a mechanism has drifted is not a
side benefit of fitting the sensor; it is a third of the justification for
fitting it at all.

**And this is the one failure mode the device is otherwise blind to.** A wire
that has slipped on the drum produces a perfectly plausible number. Nothing in
the wiper path can tell — the reading is smooth, in range, stable, and wrong.
Both `description.md` §10 and the compliance analysis say so plainly.

The end switches are the **only independent physical reference the device
has**, and auto-calibration is what turns that reference from *a bit you can
read* into *a measurement of how wrong the calibration has become*:

> at the moment a switch fires, compare the raw code being read against the
> stored endpoint for that stop. Any difference is drift, measured against a
> physical stop rather than against anybody's model of how long the motor ran.

That is sharper than what the study itself plans. Its scheme is
**commanded-versus-measured** in the controller — energise the relay for N
seconds, expect X mm, compare — which works but inherits every error in the
controller's travel-time model and only catches gross faults. The device's
version needs no model at all: the stop is where the stop is.

Three capabilities fall out, in increasing boldness, and they map onto the
three policies below:

1. **Report the discrepancy.** A master that trends it over months watches a
   wire slip *before* it matters. That is condition monitoring, not fault
   detection, and it is nearly free.
2. **Teach on command.** Having seen the drift, re-learn deliberately.
3. **Self-heal.** The device corrects itself — attractive, and the one that
   carries all the problems below.

So the question is no longer "is this worth building?" but "how much authority
should it have?". That is a smaller and much more answerable question.

### Five things that make the naive version wrong

**1. Which end fired?** The ladder deliberately does not say (§4.4). So the
firmware must infer it. Comparing the current raw code against the midpoint
of the *existing* calibration is the obvious rule, and it is fine for
correcting drift — but it is circular on a device that has never been
calibrated, and it breaks if the mechanism's usable span sits entirely on
one side of the default midpoint (511). Any auto-calibration needs a guard:
refuse to learn when the reading is not unambiguously nearer one endpoint
than the other.

*Direction of travel would settle it cleanly* — moving toward closed when
the switch fires means the closed end. That is a second, independent
argument for the signed movement rate discussed under §Movement rate. Two
open questions leaning on the same answer is worth noticing.

**2. Flash wear is the real constraint.** The store is good for ~20k writes
across its two pages (`persist.h`). A vent cycling ten times a day, writing
a couple of counts each time, spends that in roughly five years — and a
faster duty cycle spends it much sooner. Save-on-change does not save you
here, because the learned value genuinely does change by an LSB or two every
cycle. Anything always-on needs a deadband (ignore deltas under, say, 5
counts) and probably a rate limit as well.

**3. It would clear the averaging accumulator every cycle.** FR-E05 clears
the boxcar on any calibration change, and rightly so. An auto-calibration
firing on every window cycle would re-assert status bits 0/1 on every window
cycle. Same fix as above: deadband.

**4. You are calibrating to the switch, not to the stop.** A mechanical
switch operates somewhere before the hard stop, with its own hysteresis and
mounting tolerance. That is fine — consistent is what matters — but it means
40004 must be the distance **between switch operating points**, not between
hard stops. That is a documentation trap and belongs in the installation
notes, not just here.

**5. Capture the code at the right instant.** The switch is debounced 20 ms,
and an actuator driving into a stop keeps moving during it. Capture the raw
code when the *candidate* state first appears and hold it, committing only
if the candidate survives the debounce. Capturing after the debounce
completes samples a window that has already been pushed further into its
stop.

### Three policies, in increasing boldness

| | Behaviour | Cost | Risk |
|---|---|---|---|
| (a) **Report only** | Expose "raw code at the last end-switch event" as an input register. The master decides whether to write it to 40005/40006. | One register — but the map edge is a compatibility commitment | None. Master keeps authority |
| (b) **Teach mode** | A holding register arms a one-shot: the next end-switch event captures, commits and disarms. | One register + the arm/disarm logic | Low, and it is the classic industrial pattern |
| (c) **Always on** | Every qualifying end-switch event commits. | Deadband + rate limit + wear budget | Silent scale changes; flash wear; needs 1, 2 and 3 above solved properly |

**Recommendation: (a) and (b), not (c).** Reporting costs almost nothing and
makes the whole thing testable; teach mode gives a commissioning engineer a
one-button calibration without handing the device permission to silently
redefine its own scale. Revisit (c) once there is field data on how often
the endpoints actually move.

Whichever is chosen: an internal write must still satisfy FR-E06 (and any
minimum-span rule, see Q2) — it bypasses Modbus, so it bypasses FR-MB19, and
that validation has to be re-asserted on the internal path or it is not
there at all.

## Q2 — how is the direction of opening set? — **ANSWERED, implemented**

**Option A was taken. The calibration points may now be given in either
order** (TDS v0.4, FR-E04/FR-E06), so a reversed mounting calibrates exactly
like a normal one with no extra installer step. FR-E06 constrains the
*distance* between the points, not their ordering, and additionally requires a
minimum span of 64 counts. The arithmetic lives in `software/firmware/src/
scale.c` and is host-tested at its corners in both senses by
`software/firmware/test/test_scale.c`.

The analysis that led there is kept below.

---

**The original problem.**

Whether the wiper code rises or falls as the window opens depends on how the
drum, the wire and the pot are assembled, and on which way round the sensor
is mounted. FR-E06 currently requires `40006 > 40005`, so a reversed
installation is **not representable** — the scaling would run backwards and
the range check would reject the honest calibration.

Three ways out:

**A. Let the calibration points cross over.** Relax FR-E06 from
`raw_open > raw_closed` to "the two must differ by at least a minimum span",
and make FR-E04 sign-aware.

**This is what was implemented.** It needs no new register, no extra installer step,
and it falls straight out of the existing procedure — *close it, store
40005; open it, store 40006* — which records the reversal automatically
without anyone having to notice there was one. It also covers the related
question of reporting convention: a site that wants 0 to mean *fully open*
just calibrates the other way round.

The arithmetic needed care, and the implementation went further than the
sketch. With the points crossed, `(raw − raw_closed)` and `(raw_open −
raw_closed)` are both negative between the endpoints, so the quotient is
already positive in signed form — but the intermediate does not fit `int32`.
The shipped version therefore works entirely in **magnitudes in `uint32`**,
which sidesteps the sign question altogether and keeps the overflow bound
where the §Scaling proof puts it.

Two details that only surfaced in the writing:

- **Clamp before the multiply, and at both ends.** Clamping the distance to
  the span before multiplying is what holds the intermediate at 65535 × 65534;
  clamping afterwards would overflow first and then clamp a wrapped value.
  Clamping at *both* ends is what makes the result monotonic in `raw` across
  the whole ADC range — the original draft's "raw below raw_closed reports 0"
  would have put a step at the closed point whenever the offset was non-zero.
- **A degenerate pair could come from flash.** FR-E06 guards Modbus writes,
  but a record written by an older firmware would reach the divisor
  unchallenged. `regs_init` now applies the same span check on load and falls
  back to the §2.8 defaults if it fails — the FR-S21 defined state.

**B. An invert flag.** A holding register or a spare bit. Explicit and
simple, but strictly less general than A, and it costs a register on a map
whose edge is already a compatibility commitment.

**C. Swap the two pot end connections in the field.** Genuinely valid and
free — it is a potentiometer. But it is a wiring instruction that will
eventually be got wrong, and diagnosing it needs someone to realise the
reading runs backwards. Firmware that simply accommodates it is kinder.

### While we are in here: minimum span — **also implemented**

FR-E06 only required the endpoints to differ. Two *adjacent* codes satisfied
that, and would have made one LSB of ADC noise swing the entire reported
travel. **64 counts** — a sixteenth of full scale — is now the minimum, as
`CAL_MIN_SPAN` in `scale.h`, enforced on every Modbus write and on every load
from flash. One comparison, and a plausible mis-calibration goes from
silently catastrophic to a rejected write.
## Q3 — how fresh is a value when a master reads it? — **ANSWERED**

**Contract: the value in 30001 is never older than the configured measurement
window (40002).** That is now FR-E17, with a test that proves the age tracks
40002 rather than anything else.

Stating it as a *maximum age* is better than the alternatives because it makes
staleness the master's choice and nothing else's. A controller that needs a
reading no more than 200 ms old sets 40002 = 200 ms; one that would rather
have a quieter bus and a longer window sets it longer. Nothing in the protocol
changes either way, and there is one number to reason about instead of an
interaction between poll rate and internal cadence.

Sampling on demand — taking the ADC burst when the read arrives — was
considered and dropped. It is not needed once the age is bounded by
configuration, and it would have required a hook in the Modbus driver while
leaving the averaging, envelope and movement-rate registers without the
regular cadence they depend on.

One deliberate exception, worth remembering because it is the only place the
guarantee bends: during the FR-E07 two-second fault-hold the last valid
opening is held on purpose, so it can be up to 2 s old. 30011
(seconds-since-valid) is the tell, and it is non-zero for the whole of that
window.
---

# Modbus configuration

Inherited wholesale from the sibling project — 9600 8N1, FC03/04/06/16,
jumper-derived address, no address register, standard exception codes only,
never exception 04, no clamping on out-of-range writes, atomic FC16. See
TDS §2. None of this is worth re-deriving; it is a solved problem with a
verified implementation already in this tree.

## Address allocation

40 (jumper open) / 45 (bridged), deliberately clear of the windmeters
family's 30–37 so both can share one RS-485 segment.

**One jumper means two devices per segment.** A building with more than two
instrumented windows on one bus needs a second jumper — a hardware change,
since there is deliberately no address register. Decide before the PCB is
laid out; it is a pad and a pull-up, and it is free now and expensive later.

---

# Hardware

No schematic yet. The working assumption is the windmeters board with the
sensor front-end swapped: CH32V003J4M6 + MAX3485, 24 V passive PoE → DB207
bridge → HLK-K7803-500R3 → 3.3 V, two RJ45 for the daisy chain, a sensor
connector, a 3-pin SWIO header, and solder jumpers for termination, A/B pair
select and address. Datasheets for all of it are already in
`hardware/Documentation/`.

Things to think about when the schematic starts:

- **Sensor connector.** The windmeters board used RJ14 (6P4C) for
  weather-mounted sensors. A draw-wire unit on a window frame is a different
  environment — likely a screw terminal or an M12, and it needs conductors
  for the pot (3) plus the end-switch loop (2).
- ~~**Wiper ESD/clamp.**~~ **DONE 2026-08-07** — and the note was right that
  "a clamp diode pair is a different question from a filter". What it did not
  anticipate is that **a diode pair is the wrong answer**: Schottky leakage on
  a 2.5 kΩ node reaches ~32 µA at +65 °C, which is 25 counts — 2.4 % of full
  scale against a sensor specified at 0.2 %. So does a 3V3 zener, non-linearly.
  The wiper node's ≥10 MΩ leakage rule turns out to govern component choice,
  not just cleanliness. Fitted instead: R11 10 kΩ as the actual current
  limiter (a TVS cannot hold a sustained 24 V short — it is a transient part),
  C6 1 nF as a charge reservoir so the 10 kΩ costs nothing at the ADC, and D3
  a TVS specified at ≤100 nA. See TDS §4.3, §4.6.1 and FR-E21.
- **Keep the wiper node clean, short and away from the gland entries.** It is
  the one node on this board where a moisture film is an accuracy problem
  rather than a reliability one (see below). Generous clearance costs nothing
  at layout time.
- **End-switch loop.** Mandatory, on PC4 (ADC A2) as a supervised ladder —
  see above. Needs the end-of-line resistor fitted **in the field, at the far
  end of the cable**, not on the PCB: on the board it would supervise
  nothing. Say so on the schematic and in the installation notes, because it
  is exactly the part an installer leaves in the bag.
- **Switch polarity.** The ladder above assumes normally-open switches
  shorting to GND when the end is reached. Normally-closed switches invert
  the table and change which state is "cable cut" — pick before the resistor
  values are fixed, not after.
- **Cable length.** The wiper divider is in the sensor; the wire back to the
  ADC drops a little voltage against the ADC's input current. Small, but not
  zero over tens of metres, and it is a *gain* error the ratiometric trick
  does not cancel.
- **Actuator noise.** A window actuator is a motor, and it is right next to
  this board's sensor cable. Shielding and routing matter here in a way they
  do not for a sensor sitting on its own at the end of a long run.

---

## Ingress: IP65 (decision, 2026-07-29)

**NFR-ENV03 narrowed from IP67 to IP65**, set by the selected Kopp 99966478
(`hardware/Documentation/`). Same treatment as the +65 °C ceiling: state what
the bill of materials actually delivers and name the part that limits it,
rather than assert a number nothing in the design meets. The greenhouse study
asks "IP65 minimum, IP67 preferred", and its preference for IP67 was written
for hardware *at the aperture, which may be rain-wetted with the vent open*.
This box holds the electronics and is mounted inside the structure, so IP65 is
the level that applies to it.

That is the decision, and it took about a minute. The rest of this note is
about why it was nearly the wrong argument to be having.

### The digit that matters is the first one, and nothing here changes it

| | First digit (solids) | Second digit (water) |
|---|---|---|
| IP67 | 6 — dust-tight | 7 — temporary immersion |
| **IP65** | **6 — dust-tight** | **5 — jets from any direction** |
| IP50 (draw-wire unit) | 5 — dust-*protected*, ingress not excluded | **0 — none** |

IP65 and IP67 differ only in the second digit, and the difference is *jets
versus immersion*. Neither happens to a box bolted inside a greenhouse. What
actually happens is **condensation**, and condensation forms on the *inside*
of the enclosure from air that was already in it. **No IP rating addresses
that at all** — the IP test is about what gets in from outside, and water that
condenses in place never crossed the seal. A perfect IP68 box in this
application would condense exactly as much as an IP65 one, and possibly more,
since it could not breathe out during the day.

So the IP digit is close to orthogonal to this device's real environmental
risk. What addresses that risk is the **vent plug** and the **conformal
coating** — see the next section, where the wiper-node leakage table shows a
damp uncoated board failing FR-E03 silently. That is the failure mode worth
spending money on, and it is not on the enclosure line of the BOM.

### Where the rating does matter, we do not have it

The exposed part is not the box. It is the **draw-wire unit**, hanging on the
window frame, and it is **IP50**: dust-protected, no water protection
whatsoever. The asymmetry is worth stating plainly —

- the part that is **already fine** (dust-tight, water-jet-proof, mounted out
  of the weather, holding only electronics) is the one the requirement
  argument was about;
- the part that is **actually exposed** and rated for *no* water at all is the
  one nobody wrote a requirement against.

Fixing the box from IP65 to IP67 would buy nothing. Fixing the sensor buys
everything, and the options are a sheltered mounting position, a shroud, or a
higher-rated unit. Tracked as the live gap in
[`requirementsCompliance.md`](requirementsCompliance.md) §4 and TDS §6.

### Two BOM traps this leaves behind

- **The vent plug is a hole in the box.** A rated pressure-equalisation vent
  keeps IP65 through its membrane; an unrated one silently becomes the
  limiting element and the enclosure's number stops meaning anything. Buy the
  rating, not just the vent. NFR-ENV03's verification explicitly includes it.
- **Glands must be sized to the cable, not to the entry.** An M20 gland
  clamping a cable thinner than its range is a gap with a nut around it. The
  Kopp box supplies three glands for what the install needs five entries of —
  see the entry table in `hardware/Documentation/readme.md`.

### What would change this

A mounting position where the box can be rain-wetted or hosed — a washdown
regime, or an installation on the outside of the structure. Then the second
digit starts earning its keep and the box has to be re-selected. Nothing about
the current design says that, so IP65 stands.

---

## Humidity: what the vent plug does and does not fix

The enclosure has a **pressure-equalisation vent plug**, and that is the right
call — but it is worth being precise about which problem it solves, because it
is not the obvious one.

**The problem it solves.** A fully sealed box cools at night, its internal
pressure drops, and it draws replacement air in through whichever path leaks
first — a gland, the lid gasket. That path carries liquid water and dirt with
it. Repeated nightly, this pumping is what actually destroys sealed
enclosures: the seal does not fail, it gets used as a valve. The vent gives
the pressure a legitimate route, so the seals stop breathing, and it lets the
box dry out during the day when the inside is the warmer, higher-vapour-
pressure side.

**The problem it does not solve.** The interior now equilibrates with
greenhouse air, which is above 85 % RH most nights. So the inside sits near
saturation and can still condense whenever the box radiates heat away faster
than the surrounding air cools. The vent converts a bulk-water problem into a
film-of-moisture problem. That is a large improvement, not a cure.

### Why the residual film matters here specifically

Not for corrosion over decades — for **accuracy next week**.

The wiper on PA2 is a high-impedance node: a 10 kΩ pot at mid-scale is a
2.5 kΩ Thevenin source. Any leakage across the board from that node to a rail
divides against it. And greenhouse condensate is not clean water — fertiliser
aerosols and ammonia make the films ionic:

| Leakage, wiper to rail | Error, % of full scale |
|---|---|
| 100 kΩ | **1.22 %** |
| 1 MΩ | 0.13 % |
| 10 MΩ | 0.012 % |
| 100 MΩ | 0.001 % |

Clean dry FR4 is in gigohms. A contaminated film across a few millimetres
reaches 100 kΩ–10 MΩ without difficulty. **So the rule is: keep wiper-node
leakage above ~10 MΩ** — which keeps the error inside the FR-E03 firmware
budget rather than merely inside the system budget.

This inverts the usual intuition about conformal coating. Here it is not a
longevity nicety, it is **part of the accuracy budget**. An uncoated board on
a damp night would fail FR-E03 silently — plausible readings, no fault flag,
nothing visibly wrong. That is the worst failure mode this device has, and a
few euros of coating removes it.

## Q4 — should the device report the health of the window's mechanics and sensors? — **OPEN, costed**

Raised 2026-09-01, after FR-E07 was narrowed to open circuits only. Not
implemented; recorded because establishing it took real work and the reasoning
should not have to be rediscovered.

### The capability, stated properly

**The purpose is to let the controlling function estimate the health and state
of the window's mechanics and sensors.** Not a safety interlock for one use
case — a general diagnostic capability.

This device already sees everything needed for it. Two independent front-ends
observe the same physical window, and their agreement — **statically** at rest,
and **dynamically** through a movement — characterises whether the system is
operating properly. Nothing else in the installation is positioned to make that
comparison.

**Today there is no indication at all.** A draw-wire that is tangled, snapped,
seized or slipping produces a stable, plausible, in-range number that passes
every existing test: the FR-E07 pull test, FR-E03's ≤3 LSB stability, the whole
Group C matrix. The device cannot distinguish a working mechanism from a dead
one, and neither can the master.

*(An earlier draft of this note framed the rationale around storm protection —
"check everything is shut before a storm" from `description.md`. That is one
**consequence** among several, not the reason. Corrected 2026-09-01: the reason
is health and state reporting generally, of which a wrongly-reported "closed" is
one symptom.)*

### The two blind spots it closes as a side effect

They are documented separately and neither has any other mitigation:

- **FR-E07's limit.** A wiper shorted to a rail is undetectable. R11 sits
  between the field wiring and PA2, so a short to either rail presents 10 kΩ to
  that rail — electrically identical to the wiper resting at the corresponding
  end stop. **A wiper shorted to 0 V reports the window as fully closed**, which
  is the fail-unsafe direction.
- **§4.4.6's limit.** *"There is no fault band at all. Inactive, cable open and
  signal shorted to 0 V all read the same ~0 counts."* A cut end-switch cable
  produces a **missed stop** — the window reaches its limit and nothing says so.

They are complementary, and the two front-ends are genuinely independent:
separate sensors, separate cables, separate ADC channels, different physics. So
**each can witness the other's failure**.

### The comparison

| Opening | End switch | Verdict |
|---|---|---|
| At a clamped endpoint | Active | consistent |
| At a clamped endpoint | **Inactive** | **disagree** — shorted wiper, or cut switch cable |
| Mid-travel | **Active** | **disagree** — stuck switch, or wiper reading wrong |
| Mid-travel | Inactive | consistent |

### The precondition, which is the whole difficulty

**It only works after a completed FR-E19 teach.**

FR-E04 clamps the opening to the calibrated span, so "position at an endpoint"
means the wiper is at or beyond a calibration point. After a teach the
calibration points *are* the switch actuation points — the 2026-09-01 run gave
40005 = 56 and 40006 = 834, exactly where the switches fire. With EM-M05
measured (the switch holds from actuation through to the mechanical limit), that
gives a clean equivalence:

> **opening clamped ⟺ switch active**

and any mismatch is a fault.

With the **default** calibration (0 / 1023) the switches fire at openings 547 and
8150 — nowhere near either clamp — and the check would report continuously. So
it must be armed only when the calibration was *taught*, not merely *written*.
That is new state the register map does not carry today, and it means the
protection is **absent until commissioning performs a teach**. A device shipped
on defaults has none of it.

### Cost

Small. `regs.c` already holds both values; it is a comparison in
`regs_publish_opening`, a persisted "calibration was taught" flag, and a
debounce — the opening updates once per window (up to 60 s) while switches
update at 20 Hz, so the two legitimately disagree during travel for up to one
window. **Status bit 6 is free**: FR-S33 allocates bits 0–5 and pins 6–15 to 0.

### Two forms, and the second is the stronger one

The comparison above is **static** — it holds at rest, and it says *"these two
disagree"*. It does **not** say which front-end is at fault. Opening clamped
closed with the switch inactive fits a shorted wiper, a cut switch cable, and a
failed or misaligned switch equally well.

Attribution needs one more fact: **evidence that the carriage moved**. The
switches supply it.

> **A switch transition proves the carriage moved. If the reported opening does
> not change across it, the wiper is not following the carriage.**

| Observation | Attribution |
|---|---|
| Switch transitions, opening changes normally | both healthy |
| Switch transitions, **opening frozen** | **the position path is at fault** |
| Opening sweeps the full range, switch never fires at the endpoint | **the switch path is at fault** |

**This is the heart of the capability, not a bonus.** A short is only one way to freeze the reading. So is a seized drum,
a snapped draw-wire, a slipped grub screw on the pot shaft, or a coupling that
has let go. In every one of those the potentiometer is **electrically perfect**:
the FR-E07 pull test passes, the reading is stable and plausible, FR-E03's
≤3 LSB criterion passes — and the number is simply wrong, because the wire is
not turning the shaft.

For a draw-wire mechanism on a moving window, **mechanical failure is
considerably more likely than a cable short.** The dynamic check addresses the
more probable fault, and nothing else in this design could.

The two forms are complementary rather than alternatives:

- **Static** works at rest and flags *something is inconsistent now*. It is the
  only one available on a window that is not moving, which is most of the time.
- **Dynamic** needs a switch transition, so it only speaks when the window
  travels through a stop — but when it speaks it **names the faulty path**, and
  it covers a failure class the static form and every electrical test miss.

A device implementing only the static form still reports the fault; it just
cannot tell the installer which end to look at.

### What it still would not catch

- A short occurring while the window is genuinely at that stop — the two agree,
  because the reported position happens to be right. It is caught as soon as the
  window moves off, which is when the wrong answer starts to matter.
- Both front-ends failing consistently. This is corroboration, not redundancy.
- Anything at all before a teach.

### What the two bits say together

Separating them earns its place in the combination, not just in each bit alone:

| Bit 6 (static) | Bit 7 (dynamic) | Most likely cause |
|---|---|---|
| clear | clear | healthy, or nothing has moved yet to test it |
| clear | **SET** | **the mechanism is stuck** — seized drum, tangled or snapped wire, slipped coupling. The wiper is electrically perfect and reads a plausible constant. |
| **SET** | clear | **the switch path is suspect** — cut sensor cable, failed or misaligned proximity switch. Position is tracking fine. |
| **SET** | **SET** | **the position path is dead** — wiper shorted to a rail, or its conductor broken. It neither follows the carriage nor agrees with the stops. |

That third row is the one a single bit could not give, and it is the one that
tells an installer which end of the machine to walk to.

**Bit 7 stays silent when nothing moves**, which is most of the time — it can
only speak across a switch transition. Bit 6 covers the at-rest case. Neither
subsumes the other, which is the argument for both.

### Draft, if it is ever wanted

> **FR-E22 (Should) — static consistency.** When the calibration endpoints have
> been established by a completed FR-E19 teach, the firmware shall compare the
> two front-ends and report a disagreement in **status bit 6**: the opening
> clamped at a calibrated endpoint while the corresponding end switch is
> inactive, or the opening more than [X] % from either endpoint while an end
> switch is active, in either case persisting for ≥ 2 × 40002. The bit shall be
> reported and nothing more — it shall not suppress or alter 30001–30004,
> following FR-E16's precedent for a cross-front-end fault. The comparison shall
> be inactive when the calibration has not been taught.
>
> **FR-E23 (Should) — the position path follows the carriage.** On each debounced
> end-switch transition (FR-E14/E15), the firmware shall compare the raw wiper
> code against its value at the previous transition. A change of less than [Y]
> counts across a transition indicates the position path is not following the
> carriage — a shorted wiper, a broken conductor, or a mechanical failure of the
> draw-wire — and shall be reported in **status bit 7**. Unlike FR-E22 this
> needs no taught calibration, since it compares the wiper against **itself**
> rather than against the endpoints.

Note FR-E23's independence: it is the more valuable of the two and the cheaper,
because it needs neither a teach nor a calibrated relationship between the front
ends. Two raw codes and a switch edge are the whole input. If only one is ever
built, build that one.

### What is actually still open

The *whether* is settled: this is a general health-and-state capability the
device is uniquely placed to provide, and without it a stuck or broken wire has
no indication whatsoever. What remains is **how**, and these need answering
before the requirements are written:

1. ~~One concept or two?~~ **DECIDED 2026-09-01: two bits**, so a master can
   tell them apart. See the combinations below — they point at different faults
   and, taken together, at a third.
2. ~~Bit allocation.~~ **DECIDED: bit 6 static, bit 7 dynamic.** FR-S33 pins
   bits 6–15 to 0, so both are free. This is still a §2.7 register-map change
   and integrators code against that bitfield.
3. **Thresholds.** FR-E23's [Y] — how little raw movement across a switch
   transition counts as "not following"? The rig gives real numbers to work
   from: the switches fire at raw 56 and 834 against a 0–1022 traverse, so a
   healthy transition moves the wiper by hundreds of counts. FR-E22's [X], the
   band around a calibrated endpoint, is the harder one.
4. **What a master should do with it.** The device reports and does not act
   (§10). But a health indication nobody is told how to interpret is decoration:
   `description.md` §10 or the integrator-facing text needs a sentence on it.

Deliberately **not** written into the TDS until the shape is settled. A Should
requirement added speculatively is a Should requirement nobody verifies.

# Design directives

Carried over, and they earned their place:

- **No interrupts** until someone root-causes the RXNE corruption on this
  toolchain path. Polling is provably lossless here.
- **No HDSEL** on the USART — it swallows the first byte after bus idle
  ~35 % of the time, silently. Remap-switching instead.
- **Never assert DUT accuracy against M2K absolute voltages.** Use a divider
  from the DUT's own rail.
- **Nothing in the main loop blocks for long.** The two exceptions (response
  TX, flash commit) are deliberate and placed outside the latency path.
- **Requirements first.** Behaviour changes start in the TDS.
