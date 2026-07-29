# Product images

Supplier photographs and marketing images for the two bought-in sensors,
moved here out of `documentation/` (which holds datasheets and chip
reference material) and renamed from their original hash filenames.

**Three of these are not photographs — they carry specification data that
appears nowhere else in the repository.** Those are listed first.

## Carrying technical data

| File | What it shows |
|---|---|
| `drawwire-specification-table.avif` | **The draw-wire sensor's only specification table.** Reproduced below, because a screenshot is a poor place to keep numbers the design depends on. Also carries the working-principle schematics for the 4–20 mA, 0–10 V and **0–10 kΩ resistance** output variants |
| `drawwire-RE38-10k-2000mm-dimensions.avif` | **Identifies the exact variant to order** — "RE38 Resistance 0-10 kΩ, drawstring length 2000 mm" — with a dimensioned outline drawing (Ø38 body, mounting detail) |
| `lj18a3-connection-diagrams.jpg` | Connection diagrams for the LJ18A3 proximity-switch family. Diagram 4, *NPN NO type*: brown = +V, blue = 0 V, black = output, load between + and the output |

### The draw-wire specification, transcribed

| Parameter | Value | Bearing on this design |
|---|---|---|
| Type | Pull-cord linear position, self-resetting elastomer | — |
| Working power supply | 24 V DC | Applies to the *active* output variants only; the 0–10 kΩ variant is a passive potentiometer and needs no supply |
| Signal type | 0–10 kΩ, 4–20 mA, 0–5 V, 0–10 V | **Order the 0–10 kΩ variant.** The others break the ratiometric measurement (TDS §4.3) |
| Steel cable | 0.62 mm coated steel wire rope | — |
| Max wire speed | **100 mm/s** | The greenhouse M3 flap moves at 11.7 mm/s — 8.5× margin |
| Measuring travel | 0–1000 mm *(this image; 1.5 m and 2 m variants exist)* | M3 needs the **2000 mm** variant |
| Resolution | Infinitesimal (analogue) | The 10-bit ADC sets the resolution, not the sensor |
| Comprehensive error | **0.2 % max** | Comfortably inside the ±1 % repeatability and ±2 % accuracy the greenhouse study asks for |
| Endurance | **>100 000 cycles** | 4× the ~25 000 the greenhouse study requires over 20 years |
| Protection level | **IP50** | ⚠️ Dust only — **no water protection.** See the warning below |
| Shielding | Fitted | Helps with the actuator-noise concern |

> ⚠️ **The draw-wire unit is only IP50, and it lives outside the enclosure.**
> The IP65 box and its glands protect the electronics; they do nothing for the
> sensor itself, which hangs on the window frame in an environment that
> condenses most nights. IP50 means dust-protected and *not* water-protected.
> This is recorded as an open item in `design/TDS.md` §6 — the options are a
> sheltered mounting position, a shroud, or a higher-rated sensor.

## Photographs

| File | What it shows |
|---|---|
| `drawwire-body-1.avif` … `-5.avif` | The unit from various angles: Ø38 drum on a square alloy body, wire exit through a brass ferrule |
| `drawwire-wire-extended.avif` | Wire drawn out, showing the 0.62 mm cable and ferrule |
| `drawwire-label-0-5V-1000mm.avif` | Label of a **0–5 V, 1000 mm, 0.1 %** unit — a different variant from the one this project uses |
| `drawwire-label-5k-wiring.avif` | Label of a **5 kΩ** unit with its wiring legend — again a different variant |
| `drawwire-label-and-flying-leads.avif` | Label and flying leads together |

> Note the labels above show **0–5 V**, **5 kΩ** and **1000 mm** units. The
> supplier photographs the family, not the specific order. Do not read a
> variant off a photograph — read it off the unit that arrives.

## Not our part

| File | What it shows |
|---|---|
| `drawwire-ENCODER-VARIANT-not-our-part.avif` | Specification table for the **rotary-encoder** version of the same body: A/B/Z quadrature, open-collector / push-pull / voltage / line-driver outputs, 300 kHz, 6000 rpm, −10…+70 °C. The same mechanical unit is sold with an encoder instead of a potentiometer. **This project uses the potentiometer variant** (TDS §3.4) — that table describes a different product |
