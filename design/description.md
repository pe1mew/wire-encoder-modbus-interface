# Functional Description — Wire Encoder Modbus Interface

| Field | Value |
|---|---|
| Document | Functional description — what the device does, in prose |
| Project | `wire-encoder-modbus-interface` |
| Date | 2026-07-28 |
| Status | Describes the **intended** function. The Modbus and platform half is implemented; the measurement path is not yet written (`design/integrationPlan.md` stages D–F). Nothing here has run on hardware. |
| Related docs | `design/TDS.md` — the same behaviour as numbered, testable requirements; `design/scratchBook.md` — the reasoning behind the choices; `design/softwareArchitecture.md` — how it is built |

This document is for someone who needs to understand what the device does
without reading a requirements table: an integrator writing the Modbus
master, an installer commissioning a window, or whoever picks this project up
next. The TDS is the authority on behaviour; where the two disagree, the TDS
wins.

---

## 1. What it is for

A window — a greenhouse vent, a roof light, a louvre — is opened and closed
by an actuator. Something needs to know **how far open it currently is**:
to hold a ventilation setpoint, to confirm the actuator actually moved, or
to check everything is shut before a storm.

This device measures that opening and publishes it on a Modbus RTU field bus,
alongside enough diagnostic information for a master to tell the difference
between *the window is closed* and *we have no idea where the window is*.

It is a **sensor, not a controller**. It measures and reports; every decision
belongs to the master (§10).

## 2. How it senses the opening

### 2.1 The wire encoder

A **draw-wire encoder** is mounted to the fixed frame, its steel wire
attached to the moving one. A spring-loaded drum keeps the wire taut and pays
it out as the window opens. The drum turns a **10 kΩ potentiometer**, so the
wiper voltage is a direct measure of how far the wire has been drawn out —
which is how far the window is open.

Two properties of this arrangement shape everything else:

- **It is absolute.** The wiper sits where the mechanism put it. When power
  returns, the reading is immediately correct — no homing move, no reference
  run, no accumulated count to lose. A window that opened during a power cut
  reports its true position the moment the device boots.
- **It is ratiometric.** The potentiometer is fed from the same 3.3 V supply
  the measurement is referenced against, so supply ripple and drift cancel
  out. This is why the design deliberately uses *no* precision voltage
  reference: adding one would break the cancellation rather than improve it.

The device converts the raw electrical reading into millimetres using a
two-point calibration it stores itself (§6).

### 2.2 The two end switches

Two sensors report that the window has physically reached a mechanical
stop — one at each end of travel. They exist because the measured opening
can only ever *infer* that a stop was reached, and that inference is only as
trustworthy as the calibration behind it. A wire that has been re-strung or a
drum that has slipped will report a confident, plausible, wrong number. The
switches are a second, independent opinion.

They are **inductive proximity switches** (3RG4023-3AB00), not mechanical
contacts: an M18 barrel that detects a steel target within 8 mm, powered from
the same 24 V that feeds the device. Nothing touches, so nothing wears, and
the generous sensing range tolerates a window frame that shifts and settles
over the years. Each has an LED at the sensor itself, which makes
commissioning possible without a meter, and terminates in an **M12 connector**
so the run back to the device is a cordset rather than a field splice. Each
needs a **ferrous target** at its end stop — mild steel, 24 × 24 × 1 mm or
better — so an aluminium or stainless frame means adding target plates.

Each switch runs its own cable back to the device, and the two are summed
there onto a single analog input. The device therefore does not simply see "a
switch is closed" — it sees which of three levels the summed signal is at:

| What the device sees | What it means |
|---|---|
| Quiescent level | Neither switch operated; the window is between its stops |
| One-switch level | The window is at an end stop |
| Both-switches level | Both operated at once — impossible on a working installation, so a wiring or mounting fault |

The device deliberately does **not** report *which* of the two switches
operated. It does not need to: the master already knows the measured opening,
so it knows which end the window is at. (The reasoning, including why one
analog input cannot resolve both *which* switch and the state of the cable, is
in `design/scratchBook.md`.)

**What it cannot tell you, and this is worth reading before relying on the
switches.** A cut switch cable is **not** detectable. The proximity sensors
source current when they operate and nothing at all when they do not, so "no
switch operated", "cable cut" and "cable shorted to 0 V" are the same
electrical condition. A severed cable therefore reads as *no stop reached* —
the window may be at its limit and the device will not say so. Only the
both-switches-at-once fault is flagged.

An earlier revision of this design did supervise the cable, by summing the two
switches in a junction box at the window with an end-of-line resistor. That
was given up when the installation became a star — one cable per sensor back
to the device — and the trade is recorded in `design/TDS.md` §4.4. If cable
integrity matters for your installation, the defence is the same one that
covers a slipped draw-wire: compare commanded movement against measured
movement in the controller.

## 3. What it reports

Everything is read over Modbus as input registers. Grouped by what they are
for:

**Where the window is**

- The **instantaneous opening**, updated once per measurement window.
- The same opening as a **percentage of full travel** (0.0–100.0 %), which for
  a window is usually the number people actually want — the millimetres are
  the implementation detail.
- The **averaged opening**, smoothed over a configurable period.
- The **minimum and maximum** opening seen within the current averaging
  period — the movement envelope. These tell a master that the window moved
  between two polls, which a single averaged value would hide.

All four are in units of 0.1 mm.

**How it is moving**

- A **movement rate**: how fast the opening is changing, in 0.1 mm/s, and in
  which direction — **positive while opening, negative while closing**. Useful
  for answering "is the actuator actually running, and which way?"; it reads
  zero at rest. This is the only signed value the device reports, so a master
  must read it as a signed 16-bit integer.

**Whether it is at a stop**

- A **status bit** set while an end switch is closed.

**Whether to believe any of it**

- A **status bit** for a wiper fault — the position sensor is disconnected or
  shorted.
- A **status bit** for a switch-loop fault — the switch cable is cut,
  shorted, or wired wrongly.
- Two status bits covering warm-up: *no measurement window has completed
  yet*, and *the averaging period has not filled yet*. A master reading
  immediately after power-on knows the numbers are not yet meaningful rather
  than having to guess.
- **Seconds since the last valid reading**, a plausibility companion to the
  fault bits: a rising count with no fault flagged means readings have
  stopped arriving without the fault detector having tripped yet.
- The **raw electrical reading**, before calibration is applied — the
  diagnostic you need when the millimetres look wrong, and the value read
  during commissioning (§6).

**What it is**

- An **identification register** carrying the device type and firmware
  version, so a master can confirm what it is talking to.
- **Uptime in seconds**, which lets a master detect that the device restarted
  (the value went backwards).
- **Bus counters**: frames rejected for a bad checksum, and requests served.
  Useful for judging the health of the RS-485 wiring itself.

The two fault front-ends are independent: a broken switch cable does not stop
the opening being reported, and a broken wiper does not stop the switches
being reported.

## 4. The measurement cycle

The device works on a repeating **measurement window**, configurable from
100 ms to 60 s and 1 s by default. Each time a window closes, the device
takes a fresh reading, converts it to millimetres, publishes it as the
instantaneous opening, and feeds it to the averaging engine.

The **averaging period** — 1 s to 600 s, 10 s by default — determines how
many of those windows are averaged together, and over what span the
minimum/maximum envelope is computed.

A window is a *publishing* cadence, not an accumulation interval. Because the
sensor is absolute, a missed window costs one sample and nothing more; there
is no count to fall behind.

**How fresh is the number you read?** Never older than the measurement window.
That is a guarantee, not a tendency: set the window to 200 ms and every read
returns a value acquired within the last 200 ms. It is the one knob that
controls staleness, so a control loop that needs recent data simply sets it
short — there is nothing else to configure and no special request to make.

(The single exception is deliberate: while the device is holding the last good
reading through a brief sensor glitch — see §5 — the value can be up to two
seconds old. The seconds-since-last-valid-reading register is non-zero for the
whole of that period, so a master that cares can always tell.)

Changing either period, or any calibration value, discards the accumulated
average rather than mixing old and new — and says so through the warm-up
status bits until the fresh average has filled.

## 5. What happens when something is wrong

**The position sensor fails** (wiper disconnected or shorted): the device
holds the last good reading for two seconds, in case it was a momentary
glitch. If the condition persists, the four opening registers all report a
distinctive out-of-range value — no real window opening can produce it — and
the wiper-fault status bit is set. Both clear automatically within two
seconds of the sensor recovering. Faulty readings never enter the average.

**The switch cable fails** (cut, shorted, or both switches somehow closed):
the switch-loop fault bit is set. The opening continues to be measured and
reported exactly as before — a fault in one front-end is never allowed to
suppress the other.

**Condensation forms inside the enclosure**: the electronics are protected
against it (§8), and the measurement is ratiometric, so a damp night does not
move the reading. What condensation can do over years is corrode — hence the
sealed, glanded enclosure rather than a reliance on the board's own tolerance.

**The supply browns out**: the device is either operating correctly or held
in reset. There is no third state where it reports plausible nonsense. It
resumes on its own when the supply recovers, with its stored configuration
intact.

**The firmware hangs**: a watchdog resets it, and it returns to service
within a couple of seconds without anyone visiting the site.

## 6. Commissioning and calibration

The device ships knowing nothing about the window it is attached to. Teaching
it is a field procedure done entirely over Modbus — no rebuild, no
programmer, no special tool:

1. **Close the window fully.** Read the raw electrical value and write it
   back as the *closed* calibration point.
2. **Open the window fully.** Read the raw value again and write it back as
   the *open* calibration point.
3. **Measure the actual travel** with a tape and write it, in tenths of a
   millimetre, as the full travel.

That is the whole procedure. From then on the device reports real
millimetres. All settings are stored in non-volatile memory and survive
power loss, so it never needs re-teaching after a reset — and repeated
identical writes do not wear the storage.

The same mechanism means one firmware image serves any window, of any size,
with any wire routing.

The procedure is **direction-agnostic**: it does not matter whether the raw
value rises or falls as the window opens. Read the closed point, read the open
point, write each to its own register — the device works out the sense for
itself. There is nothing to check, no wire to swap, and no setting to get
backwards.

> **Note for the installer:** the calibration points are wherever the window
> actually was when you took the readings. If the end switches are used as
> the reference, the travel figure must be the distance between the *switch
> operating points*, not between the hard stops.
>
> The two readings must differ by at least 64 counts. In practice a real
> window spans hundreds; a write that fails this check is telling you the
> sensor barely moved between the two points, which means something is wrong
> with the mechanism or with which position you were actually at.

## 7. Behaviour at power-on

- The reported opening is correct **immediately** — there is no homing move
  and no settling sequence of wrong values.
- The stored calibration and settings are restored before the first
  measurement.
- Until the first measurement window closes, the opening registers read zero
  and say so through a status bit, rather than publishing a guess.
- The device answers at its configured address within a second.
- It never transmits unprompted. On a bus shared with other traffic, a device
  restarting mid-frame stays silent rather than corrupting someone else's
  exchange.

## 8. Installation and environment

The device is designed to live **inside a greenhouse**: warm, condensing on
most nights, and chemically unkind, but not in direct sunlight and not
rain-wetted.

- The electronics sit in an **IP65 enclosure** — protected against water
  jets from any direction. Every field cable — bus, sensor, end switches —
  enters through a **waterproof gland** sized to that cable, and *all*
  connectors and terminations are inside the box. Ingress protection is a
  property of the enclosure and its glands, not of any individual connector.
  Note that this covers the *electronics*: the draw-wire unit itself is only
  IP50 and hangs outside on the window frame, which is the weakest
  environmental point in the design.
- The draw-wire sensor and the end-switch loop land on **terminal blocks**
  inside the enclosure, so they can be wired in the field with a screwdriver
  rather than a crimp tool.
- The unit should be **mounted out of direct UV**. Inside the greenhouse
  structure this is normally automatic; it is worth a moment's thought when
  choosing the spot.
- Operating range is **−25 °C to +65 °C**, condensing. The upper figure is
  set by the end-of-travel sensors rather than by the electronics; a
  wider-range switch is what would raise it.

> A sealed box in a condensing environment still breathes a little with daily
> temperature swings, so the board itself is protected against condensation
> rather than relying on the seal alone. This matters when specifying a
> replacement or a second unit — it is not merely a nice-to-have.

### 8.1 Positioning the end sensors and sizing the draw-wire

Two mechanical choices decide how much this device can tell you. Both are made
at installation, neither can be corrected in firmware, and one of them is the
difference between detecting a broken draw-wire and never knowing.

#### The end sensors mark the ends of the *opening range*, not the ends of travel

The window has two different pairs of extremes, and they are not the same thing:

- **The mechanical end positions** — where the leaf physically stops, against
  its frame or its hard limits.
- **The end sensors** — where this device is told the opening range begins and
  ends.

Mount the sensors so they mark **the opening range you want reported**. A teach
(§6) captures exactly those two points as 0 mm and full travel. The leaf may
travel a little beyond them in each direction; that is expected, and the
reported opening simply holds at 0 or at full travel while it does.

**Each sensor must remain active from the moment the leaf reaches it, all the
way to where the leaf comes to rest.** This is the requirement most easily got
wrong, because a proximity sensor with a short sensing range will trigger as the
leaf passes and release again as it continues to its mechanical stop. The
window then sits fully closed while the device reports *"not at an end
position"* — the one moment that indication matters most.

The remedy is mechanical, not electrical: use a target long enough, or a sensor
with enough range, that the sensor stays made across the whole overtravel. If
the leaf can coast 15 mm past the sensor, the sensing zone must be at least
that long.

> **Check it after installation.** Drive the window fully closed, leave it, and
> read status bit 3. It must be **set**, and stay set, with nothing touching the
> window. If it clears, the sensor is too short or mounted too far in.

#### The draw-wire must have range to spare at both ends

**Do not size the draw-wire so that its ends coincide with the window's end
positions.** The potentiometer's electrical range must be comfortably *wider*
than the travel the window actually uses, so that:

```
   0 V ────────────────────────────────────────────────────── 3.3 V
        |<-- unused -->|<---- window travel ---->|<-- unused -->|
                       ^                         ^
                  lower sensor              upper sensor
```

The window should never drive the wiper close to either electrical end.

**This is what makes a faulty wiper detectable.** A draw-wire whose signal
conductor is broken, or shorted to 0 V or to the supply, produces a reading at
or very near one electrical extreme. If the installation leaves unused range at
both ends, that reading is somewhere the window **cannot legitimately be**, and
the fault can be told apart from a genuine position. If instead the draw-wire is
sized so that fully closed sits at 0 V, a shorted signal wire produces exactly
the reading of a correctly closed window, and **no amount of firmware can
distinguish them** — the device will confidently report the window shut while
the wire lies broken.

Practical guidance:

- Choose a draw-wire whose stroke is **longer than the window's travel**, and
  mount it so the travel sits near the middle of that stroke.
- Aim to leave at least **10 % of the electrical range unused at each end**.
  More is better; there is no penalty for headroom.
- Resolution is not the constraint you might expect. Even using only half the
  electrical range, a 2 m stroke resolves to about 2 mm — well inside the 1 %
  the specification asks for. **Trade resolution for headroom without
  hesitation.**

> **Check it after installation.** With the window fully closed, then fully
> open, read register 30005 (the raw code, 0–1023). Neither reading should be
> near 0 or near 1023. If either is, the draw-wire is mounted too close to the
> end of its stroke and a broken conductor will masquerade as a valid position.

#### Why the two go together

The sensors tell the device **where the window is**; the draw-wire headroom
tells it **whether to believe its own position signal**. Get the sensors right
and the closed indication is trustworthy. Get the headroom right and a broken or
shorted draw-wire becomes visible instead of silent. Get both right and the two
measurements can be compared against each other, which is what makes it possible
to say the *mechanism* has failed while the electronics are perfectly healthy.

## 9. On the bus

Modbus RTU over RS-485, 9600 baud, 8N1. The device is a pure slave: it
answers requests and never initiates.

It supports reading input and holding registers, and writing holding
registers singly or in groups. Out-of-range values are **rejected**, never
silently clamped or accepted-and-discarded — a write that returns success
really did take effect, and one that fails leaves everything untouched.
Multi-register writes are all-or-nothing.

Its address is set by a solder jumper: one of two fixed addresses, chosen so
this device family can share a bus segment with the sibling wind-sensor
family without collision. The address cannot be changed over the bus — a
misconfigured master can never renumber a device it was not talking to.

**One jumper means two of these devices per bus segment.** A site with more
instrumented windows than that needs a hardware change; it is not a firmware
setting.

## 10. What it deliberately does not do

Knowing the boundary matters as much as knowing the function:

- **It does not move the window.** There are no outputs, no relays, no
  actuator control. It cannot open, close, or stop anything.
- **It makes no decisions.** No setpoints, no thresholds, no alarm logic, no
  hysteresis. It reports; the master decides. A "window open too far" rule
  lives in the master, not here.
- **It keeps no history.** Nothing is logged, and nothing is retained beyond
  the current averaging period. A master that wants trends must poll and
  store them.
- **It has no clock.** Uptime since reset is the only notion of time it has;
  it cannot timestamp anything.
- **It does not say which end switch closed** — by design (§2.2).
- **It cannot detect a slipping wire directly.** A wire that has slipped on
  the drum produces a perfectly plausible reading that is simply wrong. The
  end switches are the partial defence: when the window is known to be at a
  stop, a master can compare that against the reported opening and notice the
  disagreement.

## 11. Known limitations

Open design items, tracked in `design/TDS.md` §6 with the analysis in
`design/scratchBook.md`:

- **Calibration is manual.** The end switches could re-teach the calibration
  points automatically — attractive, because they would correct exactly the
  drift a slipped wire causes — but the naive version has real problems
  (storage wear, and the device does not know which end fired). Under
  consideration as a reported value plus an armed one-shot, not as an
  always-on behaviour.
- **Maximum travel is 6553.4 mm** at the current 0.1 mm resolution. Ample for
  a window vent, but it is a fixed limit of the register map.
