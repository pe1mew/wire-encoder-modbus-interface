# Gotcha log

Things that went wrong or surprised us on this project, why they happened, and
what fixed them. Kept because most of these cost hours and none of them are
visible from the code afterwards — a corrected schematic looks exactly like one
that was never wrong.

Add an entry when something surprises you. When the same thing bites twice,
promote it to a pattern in the table at the foot.

Related: [`../design/scratchBook.md`](../design/scratchBook.md) holds design
*reasoning*; this file holds the mistakes. [`../software/hil/testReport.md`](../software/hil/testReport.md)
holds measured evidence.

---

### A driver written to a stale header comment instead of the requirement (2026-09-01)
**Problem**: `we.c` configured the ADC sample time to **73 cycles**. FR-E12
requires **≥241**. The violation shipped, ran on hardware, passed every
measurement test, and was only found when Group C read the requirement directly.
**Root cause**: The driver was written to `we.h`'s front-end note, which said
"≥71-cycle sample time for the 10 kΩ source impedance". That figure is the one
FR-E12 explicitly supersedes *and names as superseded* — FR-E21's R11 puts 10 kΩ
in series, so the DC source is 12.5 kΩ, above what 71 was chosen for.
**Why it was missed**: the **same header** also described a five-state supervised
ladder that had not existed since the PNP change, and that was caught on sight —
because it contradicted the circuit visibly. The sample time did not. It read as
a considered engineering number, and a considered number in a header looks
exactly like a considered number in a requirement.
**Fix**: 241 cycles, and the ADC clock raised HCLK/8 → HCLK/4 to keep
`we_sample` inside the per-pass blocking budget. Both header notes corrected
with the date and the reason.
**Pattern**: **a header comment is not a requirement.** When a driver header
restates a numeric constraint, the requirement is the source of truth and the
header is a copy that has already drifted once. Read the FR before coding to the
comment — especially when the comment sounds authoritative.

---

### The blocking budget nobody wrote down (2026-09-01)
**Problem**: The first integration-stage-D build silently dropped **9.7 % of
Modbus requests** — 271 served of 300 — with `30009` (CRC errors) **unmoved**.
**Root cause**: `mb_rx_service` polls a **single-byte USART register** from the
main loop, and FR-MB24 discards a frame on overrun. So **any main-loop pass
longer than one character time (11 bits / 9600 = 1.146 ms) loses a byte** — and
an overrun is *not* a CRC error, so the counter that would normally shout stays
silent. `we_sample` blocked ~1.25 ms alone and shared a pass with
`we_switch_sample` for ~1.48 ms.
**Fix**: pull settle 500 → 150 µs (derived: τ = 40 µs for an open wiper, so
150 µs is 3.75 τ), and the wiper and divider now sample on alternate ticks so no
pass pays for both. 500/500 served afterwards.
**The trap**: this budget appears in **no requirement and no design document**.
FR-E12 even weighs its own cost against the *measurement window* (≥100 ms),
which is the right comparison for throughput and the wrong one for a polled
receiver. It is invisible until something exceeds it, and exceeding it fails
silently.
**Rule**: in this firmware, **no main-loop call may block for a character time**.
It is now stated with its arithmetic in `we.c` and `meas_open.c`. Any new work in
that loop needs the sum redone, not estimated.

---

### Writing Python through a shell heredoc, FOUR times in one session (2026-09-01)
**Problem**: A `python - <<'PYEOF'` block that edits a source file wrote a
literal newline where `\n` was intended, producing `print(f"` followed by a real
line break — an unterminated string literal. It happened **four times** on
2026-09-01. The two expensive ones: a 10 000-cycle soak launched into the
background that died on the syntax error immediately, and — after the rule below
had already been written down — an FR-E07 test that was syntactically dead while
the operator physically reconnected and disconnected the wiper for it. **That
one wasted a bench action, which is the only cost here that cannot be redone for
free.**
**Root cause**: Escape sequences pass through two layers — the shell heredoc and
the Python string literal that contains the generated code. `"\\n"` inside a
generating script is a backslash-n in the *generated* file, which is what is
wanted, but a single `\n` becomes a real newline at generation time and breaks
the output. The two layers are easy to lose track of, and the failure is silent
until the generated file is parsed.
**Fix**: **Use the Edit and Write tools to modify source files, not heredocs.**
They have no escaping layer at all. Reserve `python - <<'PYEOF'` for
computation that prints results, never for emitting code containing string
literals.
**Second fix, cheaper than the first**: `ast.parse` the file immediately after
generating it and before launching anything that depends on it. The third
occurrence was caught in seconds this way; the second cost a background launch.
**Pattern**: a background job that exits within seconds of launch has almost
certainly failed to start, not finished. Check its output before assuming it is
running.
**And the reason it recurred after being logged**: writing the rule down does not
enforce it. The enforcement is `ast.parse` **before** anything depends on the
file — and before asking a person to do something at the bench, syntax-check and
smoke-run first. A test that needs a human action gets one attempt per action.

---

### A threshold that fragmented one drive window into one per bit (2026-09-01)
**Problem**: TP-B32 (FR-MB04) reported **FAIL** — DE release lagging the last
stop bit by **−6.5 ms**, a nonsense figure, and a drive window of 1.04 ms.
**Root cause**: The DUT's drive window was found by thresholding |A−B| above
0.7 V. But the RS-485 differential swings ±1.4 V and **passes through zero at
every bit transition**, so the magnitude dips under the threshold for a few
microseconds on each edge. One drive window became one fragment per bit, and
the code measured the last fragment.
**Fix**: Threshold first, then **close** gaps shorter than two bit times before
taking spans. No genuine release is that brief — t3.5 alone is 35 bit times.
With that, DE lead measures 3–82 µs and lag 3–6 µs against a 1 146 µs budget,
and the row passes with ~14x margin.
**The tell, printed and ignored**: the measured drive window was **1.04 ms for a
frame that takes 7.29 ms**. The frame length was known before the measurement
started. **When a measurement has a duration you can predict from first
principles, check the prediction before reading the verdict** — the same rule
that caught the retracted latency figure one row earlier, missed one row later.
**Also**: a FAIL was published against the DUT for what was entirely an analysis
error. A row should not return FAIL until its own sanity checks pass; until then
the honest verdict is that nothing has been measured.

---

### A latency figure that was wrong by 3x and looked entirely reasonable (2026-09-01)
**Problem**: FR-MB20 response latency was measured at **11.85 ms** — inside the
100 ms limit, inside FR-MB21's 15 ms preference, and tightly distributed at
0.06 ms spread. Every property of it invited belief. The true figure is
**4.08 ms**.
**Root cause**: The measurement needs the instant our own last stop bit ended.
It was taken from the RX line: first edge in the capture, plus the known frame
length. That assumes our transmission appears on RO. **It does not** — R̄Ē is
tied to DE on the raw master, so the DUT's receiver is disabled while we
transmit and the first edge in the capture is RO's *enable transient*. Every
sample was measured from an origin about 70 bit times adrift.
**Fix**: Measure against **DE**, which we drive ourselves and which the M2K
captures on the same timebase in the same acquisition — `our last stop bit ends
at (DE falling edge) − LEAD_SAMPLES`, nothing inferred. The DE **pulse width**
validates the readback: it must equal `2·LEAD + 10 bit times per byte`, and
across 1000 polls the error was **zero samples**.
**What caught it**: not review — a **cross-check**. The row was recorded as
provisional because its derivation rested on a single route, and a second route
was added for that reason alone. All 1000 samples then disagreed and the row
reported `1000 suspect` instead of a number. Without it, 11.85 ms would have
entered the test report as evidence.
**Sanity check worth keeping**: the corrected figure is *physically coherent* —
t3.5 at 9600 is 4.01 ms, and 4.08 ms is that mandatory silence plus ~20 µs of
firmware. The wrong figure had no such explanation, and nobody had asked it for
one. **A timing measurement that cannot be accounted for from first principles
has not been understood, however comfortably it sits inside its limit.**
**Also fixed**: the row reported FAIL when it could not measure. An
unmeasurable timing says nothing about whether the device met it; it now reports
BLOCKED, so a limitation of the rig cannot be read as a defect in the DUT.

---

### A buffered background run looked hung, and killing it left the DUT misconfigured (2026-09-01)
**Problem**: A long Group B run (1 000 polls plus a 10-minute uptime row) was
started in the background and produced **no output at all** for ten minutes. It
was diagnosed as hung — on the evidence that its CPU had gone flat, 0.02 s over
a 20-second sample — and killed.
**Root cause**: Two mistakes stacked.
1. **Python block-buffers stdout when it is redirected.** The run had printed
   perhaps 3 kB, under the ~8 kB buffer threshold, so nothing reached the file.
   Silence was an artefact of buffering, not of a hang.
2. **Flat CPU is not evidence of a hang** when the code contains
   `time.sleep(15)`. The uptime row sleeps in 15-second blocks; a sleeping
   process and a blocked one look identical through a CPU sample. A 500-exchange
   reproducer afterwards ran to completion at a steady 140 ms per exchange,
   which is what actually cleared libm2k of suspicion.
**Consequence**: `SIGKILL` does not run `finally`. The run's holding-register
restore never happened, and the DUT was left with TP-B09's test values
(40002 = 60000, 40003 = 60) instead of the §2.8 defaults. The next run reported
this correctly — "differs from §2.8 defaults ... not verified here" — because
the row prints its precondition rather than assuming it. That is the only
reason it was noticed at once.
**Fix**: Always run background jobs with `python -u`. The buffered output from
the killed run was lost entirely, so nothing was salvageable from ten minutes of
bench time. Bench state that must survive a kill cannot live only in a `finally`
block — record it to a file before touching the device, and check for that file
on the next startup.

---

### A silent DUT, then a "truncated" reply that was nothing of the kind (2026-09-01)
**Problem**: The DUT answered nothing at all; then, once it answered, short
replies decoded perfectly and long ones came back four bytes short. Both looked
like the DUT misbehaving. Neither was.
**Root cause**: Three separate faults, none in the firmware.
1. **No RS-485 fail-safe bias.** Idle differential was **−0.011 V** where a
   receiver needs ≥200 mV, so the DUT's RX input had no defined state and PD6
   sat at space. A ~120 Ω termination was present and 20 kΩ bias could not pull
   against it — `3.3 × RL/(40 000 + RL) = 0.011` gives RL ≈ 133 Ω, which is
   what pointed at the termination.
2. **A leading null byte.** DE and R̄Ē tied on the master means RO floats
   during our own transmission; its enable transient decodes as one spurious
   byte, shifting the whole frame.
3. **The decoder, not the link.** `decode_uart` advanced a fixed ten bit times
   per character. The CH32V003 transmits **0.8 % fast** (measured: 9.92 bit
   times per character) — nothing across a 7-byte reply, a whole bit time
   across a 35-byte one, at which point the stop-bit check fails and characters
   are dropped.
**Fix**: Bench — termination removed, bias 680 Ω, idle now +258 mV. Software —
resync on every start edge as a real UART does, and hunt for the span that
starts with the expected unit address *and* has a valid CRC instead of trusting
the first byte received. Regression tests now cover a 35-byte frame at ±1 %
baud, including the all-zeros case where the stop bit is the only edge to lock
onto.
**The number that settled it**: input register 30009, the DUT's own **CRC error
count, read 0**. Every frame it received was well-formed, so the corruption
could only be on the master's side. That was available before any of the
guessing.
**The tell, missed twice**: the capture held **61.8 ms of idle after the last
edge**. A truncated capture cannot look like that. Length was assumed from the
decoded byte count instead of measured from the samples — twice, once for each
wrong theory.

---

### An instrument's stale buffer accused the rig for an hour (2026-09-01)
**Problem**: The M2K selftest reported that the master's RS-485 driver would
not release the bus — `released` measured identical to `drive mark`. An hour
went into hunting a wiring fault that did not exist: continuity checks, bias
resistors added, powering the master's transceiver down to see which end was
driving, and a 20-cycle intermittency test that came back 20/20 good and was
therefore *disbelieved*.
**Root cause**: **libm2k's analog input is buffered, and the first
`getSamples()` after a state change returns the buffer already in flight** —
so a single read per state reports the *previous* state. The selftest read
once per state; the ad-hoc diagnostic scripts happened to read two or three
times, which primed the pipeline and hid it. That is why the two disagreed,
which should have been the clue.
**Fix**: Discard one buffer after every state change, with a comment saying
why so nobody deletes it as redundant (`m2k_master.py`, `selftest`). Three
consecutive runs then passed deterministically.
**The tell, missed for an hour**: `released` was **bit-identical** to
`drive mark` — 0.817 V / 2.138 V, to three decimals. Two independent physical
measurements never agree to three decimals. Identical values are a repeated
buffer, not a measurement.

---

### Three measurement sets fitted to a broken bench (2026-08-31)
**Problem**: Four sets of switch-band measurements were taken across one day.
The first three were each fitted to a model, documented in the TDS as
"MEASURED", and committed — then invalidated by the next set.
**Root cause**: The bench did not match the schematic, in four separate ways
discovered one at a time: R10 still fitted, R5 (4k7) floating, a third wiring
error, and the MCU's internal pull-up on PC4 sourcing ~63 µA into the summing
node. Each fault admitted a plausible fit, so the arithmetic never complained.
**Fix**: TP-A00 — a rig-verification row that must pass before any reading is
believed. Its criterion (PC4 ≤ 5 counts with both sensors disconnected) is what
eventually caught all four.
**The tell that was missed**: *one active* → *both active* stepped 50 mV where
the topology requires it to roughly double. Visible in the very first set.

---

### An MCU pin masquerading as sensor leakage (2026-08-31)
**Problem**: 33–35 µA of apparent sensor off-state leakage, 3.5× the datasheet
maximum, recorded twice in the TDS and used to move firmware thresholds.
**Root cause**: PC4's **internal pull-up**, ~47 kΩ to 3V3, enabled by whatever
image was in flash. The pre-swap design and the sibling project both used PC4
as a pulled-up address jumper. An ohmmeter cannot find it — an internal pull-up
is an active structure and reads as nothing when unpowered.
**Fix**: Flash the current build, which leaves PC4 at its reset default
(floating input). The 63 µA vanished. FR-E11 now requires PC4 to be an analog
input with **no pull**, so the regression is a requirement violation rather
than a mystery.

---

### A proof that went stale under a part change (2026-08-31)
**Problem**: Nearly repeated a claim from `scratchBook.md` that a two-switch
ladder cannot resolve *which* switch and *both closed* simultaneously.
**Root cause**: The proof was derived for the **NPN** sensor. The PNP part
sources through its summing resistor and the arithmetic differs — 202 workable
asymmetric E24 pairs exist at ±15 % supply.
**Fix**: Scanned before asserting. The conclusion survives (7 counts of margin
vs 38) but as a *measurement*, not an impossibility. Both documents corrected.
**Pattern**: a margin argument that has quietly become an impossibility claim
is exactly what to re-derive after a part change.

---

### Divergent library copy nearly lost two footprints (2026-08-07)
**Problem**: `hardware/KiCad/<project>/my-KiCad-library/` looked like a
duplicate of the submodule one level up and was a candidate for `.gitignore`.
**Root cause**: It was *ahead* of the submodule — `DB207-DIP-4` and
`HLK-K7803-500R3`, the bridge rectifier and buck regulator on this board,
existed only there and in one other working tree. Untracked in both.
**Fix**: Diffed before ignoring. Submodule moved to `master` (`1ebcfbc`), which
carries them; pointer bumped in the parent.
**Rule**: never `.gitignore` a directory that looks like a duplicate without
diffing it first.

---

### KiCad edits that look right and net wrong (2026-08-07)
**Problem**: Renaming a net label to move R5 from 3V3 to GND shorted the two
rails. Separately, a new wire overlapped a pre-existing GND run while carrying
a `3V3` label.
**Root cause**: Labels name whole multi-segment buses, not the local node. And
schematic geometry can overlap invisibly.
**Fix**: Never trust a hand edit to `.kicad_sch`. Export the netlist with
`kicad-cli sch export netlist` and diff it against the previous one — that is
the only check that catches a silently-wrong net.

---

### A rig "defect" that was the mechanism working correctly (2026-09-01)

**Problem**: EM-M05 showed the end-stop sensor still active with the carriage at
its mechanical limit. I called it a rig defect and recommended **moving the
sensor** — a change to hardware that was working. The user pushed back on
domain grounds: *"when the window stops at its mechanical limit you do not want
to have the sensor active?"* Re-measured against the requirement, EM-M05 PASSES;
EM-M03 **requires** the hard limit to lie beyond the actuation point, so a
sensor that goes inactive at the limit would be the defect.

**Root cause**: I read a single ambiguous observation as a fault without first
reading the requirement that governs the geometry. The observation was
compatible with both "sensor misplaced" and "sensor correctly placed"; nothing
in the data chose between them, and I chose the one that made my reading right.

**Fix**: Retracted, re-derived from EM-M03, re-measured — PASS. The escalation
that matters is the *remedy*: every earlier instance of this pattern proposed
changing a **test**, which is cheap and reversible. This one proposed changing
**working hardware**, on the strength of one sample.

### Telling the user a blocked requirement was closable, three times (2026-09-01)

**Problem**: I repeatedly described FR-E03 as closable from the rig's own
readout. It is not: FR-E03 constrains the **electronics** driven by a precision
divider, and the draw-wire mechanism's contribution is a separate item. Saying
so three times risked the user buying the wrong instrument.

**Root cause**: I inferred the requirement's scope from the section it sits in
rather than reading its text. Its ≤3 LSB stability half genuinely does pass on
the bench, which made the whole requirement feel nearly closed.

**Fix**: FR-E03 is listed as needing a precision resistance box and **five
ratios**, and the two halves are recorded separately so the passing half cannot
be mistaken for the whole.

## Promoted patterns

Recurrences that have earned a standing rule.

### A test that blames the device must first rule out the instrument

Promoted after this happened **seven times in one bench session** (2026-09-01),
each time reporting a defect in the DUT that did not exist. It then recurred
through the rest of that day — roughly ten instances in total against **two**
genuine firmware bugs (the FR-E12 sample time and the blocking regression). The
base rate is the finding: when this bench says FAIL, the rig is the way to bet.

| Row | Reported | Actually |
|---|---|---|
| FR-MB20 latency | 11.85 ms | **4.08 ms** — the origin was taken from RX, where our own frame does not appear |
| TP-B32 (FR-MB04) | FAIL, −6.5 ms release lag | PASS — a magnitude threshold split one drive window into one fragment per bit |
| TP-B35 (FR-S16) | FAIL, 4 captures "implicate the TX clock" | PASS — truncated captures have edges too, and were filed under the DUT's fault |
| TP-B20 (FR-S39) | one round "corrupt" | not corrupt — the operator had not switched power back on yet |
| FR-E07 hold | FAIL, "18 s" | the test timed its own first poll against a device already faulted |
| FR-E16 isolation | FAIL, 88 counts | wiper drift between transitions; the question was correlation, not range |
| FR-E04 offset | FAIL, 6578 vs 7078 | a race that read the value *before* the write took effect |

Three of those seven were **statistic-choice errors**: a range where a
correlation was needed, an edge-to-edge delta spanning seconds of drift, and a
span where per-transition movement was the question. Picking the wrong statistic
does not look like a bug — it produces a number, and the number is wrong.

Every one had the same shape: **a verdict was computed before the measurement's
own sanity check was applied.** In each case the check existed and was cheap:

- a 7-byte frame cannot occupy a 1.04 ms drive window — the frame length was
  known before the measurement started;
- 30009 read **0** throughout, so the DUT's receive path was provably fine and
  the corruption could only be ours;
- the DUT's own served counter advanced by *exactly* the number of requests
  sent, while our capture claimed to have missed some.

Concrete rules:

- **Predict the measurement's duration from first principles and check it
  before reading the verdict.** A timing you cannot account for has not been
  understood, however comfortably it sits inside its limit.
- **"My capture contains something" is not evidence the something is correct.**
  Truncated, clipped and empty captures all "contain edges" to a naive test.
  Classify them apart or do not classify at all.
- **Ask the device what it thinks happened.** It counts its own CRC errors and
  served requests. Those counters sit on the far side of the link and settle
  most arguments in one read.
- **Never return FAIL when the honest verdict is "could not measure".** An
  unmeasurable quantity says nothing about whether the device met it. Report
  BLOCKED or INCONCLUSIVE, so a limitation of the rig can never be read later
  as a defect in the product.

### A copy of a requirement has already drifted once — read the original

Promoted after `we.h` misled the driver **twice in one file**, in opposite ways:

- **Caught on sight**: it described `we_switch_sample` as reading a five-state
  supervised ladder with an end-of-line resistor. That circuit had not existed
  since the PNP change of 2026-08-29, and the contradiction with §4.4 was
  visible immediately.
- **Missed, and shipped**: it said "≥71-cycle sample time". FR-E12 requires
  **≥241** and explicitly names 71 as the value it supersedes. The driver was
  written to the comment, ran on hardware, and passed every measurement test.

The difference is instructive. A stale *description* contradicts the thing it
describes and gets caught. A stale **number** does not contradict anything
visible — it reads as a considered engineering value, because it once was one.

**Rule: when a header, comment or design note restates a numeric constraint,
open the requirement.** The comment is a copy, and a copy in a file that has
drifted once has no claim to being current. This applies with most force to
exactly the values that look most authoritative.

Corollary, from the same day: `design/testPlan.md` cited the wrong requirement
for four rows, and a **mis-citing row satisfies a traceability check while
testing something else** — FR-S02 looked covered until the row citing it was
deleted. "Is every requirement cited?" is a weaker question than "does the row
exercise what it cites?", and only the second one is worth the name.

### If a measurement does not fit the model, suspect the rig before refitting

A model that needs a **new free parameter for every measurement** is describing
the wrong circuit. Watch for readings that violate the *topology* rather than
the values — here, *one active* → *both active* stepped 50 mV where a summing
network must roughly double, and that was visible in the first data set.

Run a rig-verification step and make it **pass** before believing any data
([`../design/testPlan.md`](../design/testPlan.md), TP-A00). Note that an
ohmmeter cannot find an active structure: an MCU internal pull-up reads as
nothing when unpowered, so some faults are only findable by changing the
firmware state.

### If editing a `.kicad_sch` by hand, verify by netlist diff

Reading the S-expressions is not a check. Export and compare:

```
kicad-cli sch export netlist --format kicadsexpr --output <file> <sch>
kicad-cli sch erc --severity-error --severity-warning --output <rpt> <sch>
```

Diff the netlist against the previous one; confirm the ERC delta introduces no
new categories. Snap new coordinates to the **1.27 mm** connection grid —
off-grid endpoints do not connect and look identical to ones that do. And never
edit while KiCad has the file open (check for `~*.lck`), or the next save
discards the work.

### Before blaming the far end, read the raw signal and the far end's own counters

Promoted after the second bench session in which a fault in **our own
measurement software** was attributed to the hardware — first an instrument's
stale buffer, then a UART decoder that could not hold sync.

Two cheap checks, both available before any theorising:

- **Ask the DUT what it thinks happened.** The device counts its own CRC errors
  and served requests (30009, 30010). A CRC error count of **0** while the
  master sees garbage proves the corruption is on the master's side and ends
  the argument in one read. Design registers like these in, and read them
  *first*.
- **Measure the signal, not somebody's decode of it.** Dump run-lengths and
  edge positions before trusting any decoder — including a diagnostic you just
  wrote, which can carry the same bug as the code under test. Here the run
  lengths gave the answer directly (9.92 bit times per character) and the idle
  tail (61.8 ms) disproved the truncation theory that two decoders had
  independently suggested.

Corollary: **a fault that scales with message length is a synchronisation
fault.** If short frames work and long ones do not, stop looking for a
truncation or a buffer limit and go measure the bit rate.

### When two measurements of the same thing disagree, that disagreement *is* the data

Promoted after this bit twice in one day, from opposite directions: first a
model was refitted three times against a bench that did not match the
schematic, then a bench was accused for an hour on the word of an instrument
that was returning stale buffers.

Both times the contradiction was visible early and was explained away instead
of investigated. Two concrete tells worth keeping:

- **Readings identical to full precision are an artefact.** Two independent
  physical measurements do not agree to three decimals. When they do, suspect
  a cached buffer, a repeated read, or a value that never updated.
- **When a purpose-built test and an ad-hoc script disagree, stop.** Do not
  pick the one that fits the story. The difference between them is the fault —
  here it was one script reading twice per state and the other once.

Corollary: a diagnostic that returns a *clean* result you did not expect
(20/20 releases when you are hunting an intermittent fault) is evidence, not
noise. Disbelieving it cost most of the hour.
- **The remedy must be as reversible as the evidence is strong.** One ambiguous
  sample can justify re-reading a requirement or re-running a measurement. It
  cannot justify modifying working hardware. If the proposed fix is less
  reversible than the observation is certain, the fix is wrong — see the EM-M05
  entry, where the observation was correct and the conclusion inverted.
- **Before calling a physical arrangement wrong, find the requirement that
  governs it.** EM-M05 looked like a misplaced sensor until EM-M03 turned out to
  mandate exactly that placement.
