# Contents

| File | What it is |
|---|---|
| `CH32V003.pdf`, `CH32V003RM.PDF` | WCH CH32V003 datasheet and reference manual |
| `CH32V003J4M6-Pinout.jpg` | **Pinout of the SOP-8 package.** Worth looking at before proposing any front-end change: pin 1 carries PD6 *and* PA1, pin 8 carries PD1, PD4 *and* PD5, so there are six physical I/O pins, not seven (TDS §4.2) |
| `WCH-LinkUserManual.PDF` | WCH-LinkE programmer manual |
| `Proximity-Switch-LJ18A3-8-Z-BX.pdf` | **The selected part.** Full spec table: 6–36 V (12–24 V nominal), <13 mA consumption, <300 mA output, 8 mm ±10 % against 30 × 30 × 1 mm iron, <10 % hysteresis, 500 Hz, −30…+65 °C, reverse-connection + surge + short-circuit protection, nickel-plated brass body with ABS sensing face |
| `LJ_en.pdf` | **Finglai LJ-series manual — the authoritative document.** Model decoder (`Z/BX` = NPN NO 6–36 V, `Z/BX-5V` = NPN NO 5 V, `Z/BY` = PNP NO), safety notes, and — most importantly — the **internal output circuit diagrams**, which show a 10 kΩ pull-up from the output to +V inside the NPN part. See the warning below |
| `5911600_lj18a3.pdf` | LJ18A3 family **selection chart** (Yueqing Hengwei) — confirms the model coding and the M18×1 outline drawing. No electrical parameters |
| `14_PROXIMITY_INDUCTIVE_18BY.pdf` | ⚠️ **This is the LJ18A3-8-Z/BY — the PNP variant, not the part we use.** Its page 2 model table covers the whole family (including our /BX) and its outline drawing is right, but **its specification table is for a PNP output.** See the warning below |
| `S9b9323826f2e48bca2893117435ce239v.pdf` | Mann Hwa / Zhongyang **ZY-series encoder catalogue** — see the warning below |
| [`product-images/`](product-images/readme.md) | Supplier photographs for both sensors, renamed and indexed. **Three of them carry specification data found nowhere else** — including the draw-wire unit's only spec table (0.2 % error, >100 000 cycles, **IP50**) and the drawing that identifies the exact variant to order. Start at its [readme](product-images/readme.md) |

> ⚠️ **The NPN output is not a bare open collector.** `LJ_en.pdf` page 2 shows
> an **internal 10 kΩ pull-up from the output (black) to +V (brown)** inside
> the sensor. Powered at 24 V, the output therefore *sources* roughly 2 mA at
> 24 V when no target is present — it does not simply float. Any interface
> that assumes an open collector and pulls the line up to 3.3 V will be driven
> well above the rail. Verify on the actual part before wiring: with the sensor
> unpowered, measure brown-to-black; ~10 kΩ confirms the internal pull-up.

> ⚠️ **`14_PROXIMITY_INDUCTIVE_18BY.pdf` describes the PNP variant.** The
> suffix is the giveaway: **/BX = NPN** (what we use), **/BY = PNP**. The two
> are otherwise near-identical in size, range and supply, so the documents look
> interchangeable and are not.
>
> This matters more than a documentation nit. The board pulls PC4 up to 3.3 V
> and relies on the sensor **sinking** it — safe, because an open-collector
> output sources nothing. A PNP part *sources* its supply rail instead, so
> wiring one in would put **24 V onto an ADC pin** and destroy it. Check the
> suffix on the actual sensor before connecting anything, not the datasheet
> that came with it.

> ⚠️ **The ZY-series catalogue does not describe the sensor this project
> uses.** It is a generic multi-model catalogue of **incremental** rotary
> encoders (A/B quadrature, optional Z index; NPN/PNP/push-pull/line-driver
> output stages; 10–3000 P/R), covering ZY2504, ZY3806, ZY3808B, ZY4006,
> ZY5006 and the ZY7 handwheel series. Its "本体 Absolute rotary encoders"
> section heading is a mistranslation — 本体 means "main body", not
> "absolute" — and every model decoder underneath reads
> "C: 增量式编码器 Incremental Rotary Encoder".
>
> The unit this project uses is a **draw-wire encoder with a 10 kΩ
> potentiometer** (TDS §1.1, §3.4): absolute, analog, read on one ADC pin.
> Keep the catalogue for reference if you like, but do not design against
> it.

# WCH MCU documentation on the web

 - https://github.com/limingjie/WCH-MCU-Pinouts/tree/main


# Source downloaded PDF

 - https://www.olimex.com/Products/RISC-V/WCH/WCH-LinkE/resources/WCH-LinkUserManual.PDF
 
# Wiring WCH-Link 

## to nanoCH32V003


```
        nanoCH32V003             WCH-LinkE
      +--------------+    +----------------+
      |              |    |                |
      |          GND o----o GND            |
      |          DI0 o----o SWDIO/TMS      |
      |          VCC o----o 3V3            |
      |              |    |                |
      +--------------+    +----------------+
```

## CH32V003 J4M6 D03

You need a WCH-LinkE programmer to flash this MCU. You connect SWIO to PD1 (pin 8), VDD to pin 4 and VSS to pin 2.

```
     CH32V003J4M6D03             WCH-LinkE
   +-----------------+    +----------------+
   |                 |    |                |
   |         VSS (2) o----o GND            |
   |         PD1 (8) o----o SWDIO/TMS      |
   |         VDD (4) o----o 3V3            |
   |                 |    |                |
   +-----------------+    +----------------+
```

# Platformio an the WCH CH32V Platform

 - https://ch405labs.net/ch32v003_intro/
 
 
 
# The draw-wire sensor (supplier description)

Supplier copy for the pull-rope displacement sensor, kept verbatim below. Two
points from it matter to the design and are worth pulling out first:

- **Output options are 4–20 mA, 0–5 V, 0–10 V, or 10 kΩ resistance.** This
  project uses the **10 kΩ resistance** variant — a bare potentiometer, which
  is what makes the measurement passive, absolute and ratiometric (TDS §3.4,
  §4.3). The three active outputs would all need their own supply and would
  break the ratiometric cancellation; do not substitute one.
- **Lengths: 1 m, 1.5 m, 2 m.** The greenhouse M3 flap travels ~2 m, so the
  2 m variant is the one to order — and TDS §6's note about matching the
  register resolution to the wire length is satisfied: 2 m is well inside the
  6.5 m the 0.1 mm register range allows.

The "5–24 V DC input power supply" in the copy below applies to the
active-output variants. A 10 kΩ resistance output is passive and takes no
supply of its own; this board feeds it from its own 3.3 V rail so that the
divider and the ADC reference are the same rail.

---

Precision displacement measurement with multiple output options The pull rope displacement sensor offers accurate distance measurement with various output types including 4-20mA, 0-5V, 0-10V, and 10kΩ resistance, ensuring compatibility with diverse industrial systems.

Flexible range options for different applications Available in three lengths: 1M, 1.5M, and 2M, this sensor supports a wide range of displacement needs, making it ideal for automation, machinery, and monitoring systems requiring precise positioning.

Wide input voltage compatibility Designed for stable operation with an input power supply of 5–24V DC, this sensor ensures reliable performance across various electrical environments without voltage fluctuations.

Durable alloy construction for long-term use Made from high-quality alloy material, the sensor resists wear and environmental stress, providing long-term durability in industrial and mechanical applications.

CE certified for safety and compliance Certified with CE, this sensor meets European safety and electromagnetic compatibility standards, ensuring reliable and compliant operation in regulated environments.

Compact and lightweight for easy integration With a package size of 10 x 10 x 7 cm and a weight of 0.550 kg, it is easy to install and integrate into tight spaces without adding bulk to existing systems.

One piece per pack, simple and efficient Sold as 1 piece per pack, this sensor is ideal for direct replacement, spare parts, or small-scale projects, offering convenience and cost-efficiency for users.
