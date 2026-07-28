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

**Still to propagate:** TDS §3.5 and §4.2, and the firmware, still describe
the optional single-bit PC1 version. This section is the decision; the TDS
change follows.

---

# Open questions

Raised 2026-07-28, not yet decided. Neither is in the TDS as a requirement;
both are flagged in TDS §6 pointing here.

## Q1 — can the end switches auto-calibrate the endpoints?

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
- **Wiper ESD/clamp.** The cable runs to a moving frame, possibly outdoors.
  The sibling board deliberately fits no RC filter on the wiper (ratiometric
  operation plus the 73-cycle sample time carry the stability), but a clamp
  diode pair is a different question from a filter, and worth having.
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
