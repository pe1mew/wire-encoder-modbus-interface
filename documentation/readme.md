# Contents

| File | What it is |
|---|---|
| `CH32V003.pdf`, `CH32V003RM.PDF` | WCH CH32V003 datasheet and reference manual |
| `CH32V003J4M6-Pinout.jpg` | **Pinout of the SOP-8 package.** Worth looking at before proposing any front-end change: pin 1 carries PD6 *and* PA1, pin 8 carries PD1, PD4 *and* PD5, so there are six physical I/O pins, not seven (TDS §4.2) |
| `WCH-LinkUserManual.PDF` | WCH-LinkE programmer manual |
| `S9b9323826f2e48bca2893117435ce239v.pdf` | Mann Hwa / Zhongyang **ZY-series encoder catalogue** — see the warning below |
| `S4a98f76ed9f049c3ac94bcd5a02d4304h.avif` | Seller's product image accompanying the above |

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
 
 
 
Precision displacement measurement with multiple output options The pull rope displacement sensor offers accurate distance measurement with various output types including 4-20mA, 0-5V, 0-10V, and 10kΩ resistance, ensuring compatibility with diverse industrial systems.

Flexible range options for different applications Available in three lengths: 1M, 1.5M, and 2M, this sensor supports a wide range of displacement needs, making it ideal for automation, machinery, and monitoring systems requiring precise positioning.

Wide input voltage compatibility Designed for stable operation with an input power supply of 5–24V DC, this sensor ensures reliable performance across various electrical environments without voltage fluctuations.

Durable alloy construction for long-term use Made from high-quality alloy material, the sensor resists wear and environmental stress, providing long-term durability in industrial and mechanical applications.

CE certified for safety and compliance Certified with CE, this sensor meets European safety and electromagnetic compatibility standards, ensuring reliable and compliant operation in regulated environments.

Compact and lightweight for easy integration With a package size of 10 x 10 x 7 cm and a weight of 0.550 kg, it is easy to install and integrate into tight spaces without adding bulk to existing systems.

One piece per pack, simple and efficient Sold as 1 piece per pack, this sensor is ideal for direct replacement, spare parts, or small-scale projects, offering convenience and cost-efficiency for users.