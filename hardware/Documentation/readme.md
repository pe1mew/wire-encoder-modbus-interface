# Component datasheets

Datasheets for the bought-in parts of the board and its installation. The
sensors' own documentation lives in [`documentation/`](../../documentation/)
alongside the MCU reference material.

| File | Part | Used for |
|---|---|---|
| `99966478_nl_td.pdf` | **Kopp 99966478 enclosure** — IP65 junction box, 110 × 110 × 40 mm (50 mm deep), black, halogen-free, screwed lid, 6 cable entries with **3 × M20 glands supplied** | The device enclosure (TDS §4.5). See the two notes below |
| `MAX3483-MAX3491.pdf` | Maxim MAX3485 | RS-485 transceiver (TDS §4.1) |
| `006548_HLK-K78xx-500R3_Datasheet.pdf` | Hi-Link HLK-K7803-500R3 | 24 V → 3.3 V buck regulator (TDS §4.1) |
| `db201-db207.pdf` | Rectron DB207 | Bridge rectifier, used for reverse-polarity protection only (TDS §4.1) |
| `003223_Kradex_Z57JPH_TM_ABS.pdf` | Kradex Z57JPH ABS | **Inherited from the sibling project — superseded** by the Kopp box above. Kept because it is referenced by the windmeters design this project was bootstrapped from |

## Two things about the enclosure

**It is IP65, and that is now what TDS NFR-ENV03 asks for.** The requirement
originally said IP67; it was narrowed on 2026-07-29 to match this box, with
the box named as what sets the figure — the same treatment the temperature
ceiling got from the end-switch sensor. The greenhouse study asks "IP65
minimum, IP67 preferred", and its preference for IP67 was written for hardware
*at the aperture, which may be rain-wetted with the vent open*. This box holds
the electronics and is mounted inside the structure, so it meets the level
that applies to it. The genuinely exposed part is the draw-wire unit, which is
IP50 — that gap is live and tracked in `design/requirementsCompliance.md` §4.

**Count the cable entries before ordering.** Six are available; three M20
glands are supplied. The installation needs:

| Entry | For |
|---|---|
| 1 | RS-485 bus in |
| 2 | RS-485 bus out (daisy chain, TDS §4.1) |
| 3 | Draw-wire sensor |
| 4 | End switch A |
| 5 | End switch B |
| 6 | Pressure-equalisation vent plug (TDS §4.5) |

That is **all six entries used, with three more glands plus the vent to buy
and nothing spare.** Two things make this tighter than it looks: the vent
occupies an entry, which is easy to overlook when a box is specified by cable
count alone; and the **star topology** (TDS §4.4, decided 2026-08-07) gives
each end switch its own run to the hub instead of summing them in a field
junction, which costs the sixth entry. If anything else ever has to enter this
box, it needs a different box.
