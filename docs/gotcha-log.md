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

### Three measurement sets fitted to a broken bench (2026-08-08)
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

### An MCU pin masquerading as sensor leakage (2026-08-08)
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

### A proof that went stale under a part change (2026-08-08)
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

### Divergent library copy nearly lost two footprints (2026-08-08)
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

### KiCad edits that look right and net wrong (2026-08-08)
**Problem**: Renaming a net label to move R5 from 3V3 to GND shorted the two
rails. Separately, a new wire overlapped a pre-existing GND run while carrying
a `3V3` label.
**Root cause**: Labels name whole multi-segment buses, not the local node. And
schematic geometry can overlap invisibly.
**Fix**: Never trust a hand edit to `.kicad_sch`. Export the netlist with
`kicad-cli sch export netlist` and diff it against the previous one — that is
the only check that catches a silently-wrong net.

---

## Promoted patterns

Recurrences that have earned a standing rule.

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
