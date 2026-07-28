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

| Pin | Port(s) | Committed to |
|---|---|---|
| 1 | PD6 (= PA1) | Modbus data |
| 3 | PA2 | Pot wiper (ADC ch0) |
| 5 | **PC1** | **spare** |
| 6 | PC2 | RS-485 DE/RE |
| 7 | PC4 | Address jumper |
| 8 | PD1 (= PD4/PD5) | SWIO |

**One spare pin: PC1.** It is digital-only (no ADC channel) and it is 5 V
tolerant while VDD is 3.3 V.

That single pin is what the optional end switches use. Anything else that
wants a pin is competing with them.

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

Overflow check: `65535 × 65534 = 4,294,377,690` fits `uint32_t`
(max 4,294,967,295) with about 0.014 % headroom. That is tight enough to be
worth a comment in the code — it holds only because both operands are 16-bit.
If the opening ever becomes 32-bit (see below), redo this.

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

## End switches

Optional (`-D HAVE_END_SWITCH`), on PC1, because PC1 is all there is. Both
switches share the input; **which** end was reached follows from the reported
opening, which the device already knows. Distinguishing them electrically
costs the address jumper (PC4 — which is also an ADC channel and could read a
resistor ladder) or a fixed address. Neither is free; the inference is free
and is correct whenever the calibration is.

Debounce in firmware, 20 ms, as a SysTick comparison — never a delay. Nothing
in this loop is allowed to block.

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
- **End-switch loop.** PC1 is 5 V tolerant, so a longer loop at 5 V is safe.
  Decide NO vs NC — normally-closed fails safe (a cut wire looks like "at the
  end stop") but inverts the logic in `board_end_switch_active()`.
- **Cable length.** The wiper divider is in the sensor; the wire back to the
  ADC drops a little voltage against the ADC's input current. Small, but not
  zero over tens of metres, and it is a *gain* error the ratiometric trick
  does not cancel.
- **Actuator noise.** A window actuator is a motor, and it is right next to
  this board's sensor cable. Shielding and routing matter here in a way they
  do not for a sensor sitting on its own at the end of a long run.

---

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
