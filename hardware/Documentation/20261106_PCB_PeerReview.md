
## Encoder: observations

**Components**
- The first thing that stands out is the very fast RS-485 IC: an 8 ns rise time. That contains a lot of harmonics, which can cause problems in various places. The MAX3483 (700 ns) is a much better choice than the current part (xxx5). Slow is good when you don't need the speed (see page 12 of the datasheet).
- Here too, the 20 kΩ pull-up resistors are unnecessary.
- The large decoupling capacitor probably does little at the speeds the RS-485 switches at.
- The MCU decoupling capacitor has a huge loop area and a far too large footprint (high ESL).

**Recommendations (same as for the controller)**
- Everything that enters or leaves the board gets a fuse (against fire), a filter and a TVS diode (against ESD, EFT and possibly surge).
- Place the TVS diode as the first component, right next to the connector.
- Keep the bottom (or top) GND plane as intact as possible; only use interruptions as short jumpers.