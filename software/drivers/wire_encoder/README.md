# Wire encoder driver — window-opening acquisition

**Status: written, HIL-verified, and integrated.** [`lib/we/we.c`](lib/we/we.c)
implements the contract in [`lib/we/we.h`](lib/we/we.h) and is linked into the
product firmware. Evidence is in `software/hil/testReport.md`; the driver's
requirements close through integration stages D and E rather than a standalone
`we_check.py`, because the acquisition is only observable through the Modbus
registers it feeds.

A draw-wire encoder is attached to the moving window frame. Its spring-loaded
drum pays out a wire and turns a **10 kΩ potentiometer**, so the wiper voltage
is a direct, absolute measure of how far the window is open. The driver reads
that wiper on **PA2** (ADC channel 0) with the 10-bit ADC in ratiometric mode
referenced to VDD:

- **16 conversions** folded per sample (FR-E13),
- **≥241-cycle** sample time (FR-E12) — see the warning below,
- a floating wiper detected by toggling the internal pull resistor between two
  conversions and comparing (FR-E07),
- and, on a separate call, the switch ladder on **PC4** (ADC channel 2).

## ⚠ The sample time is not the sibling project's

FR-E12 requires **≥241 cycles here**, where the sibling wind vane uses ≥71. The
difference is FR-E21's **10 kΩ series protection resistor**, which the vane does
not have: it lifts the DC source impedance from the element's 2.5 kΩ at
mid-scale to **12.5 kΩ**, above the 10 kΩ the ≥71 figure was chosen for.

This is called out because the driver **shipped wrong once** for exactly this
reason. It was written to `we.h`'s front-end note, which still carried the old
"≥71 cycles", and configured 73. The header was a copy of the requirement and
had already drifted. **Read FR-E12 in `design/TDS.md`, not a comment that
paraphrases it** — including this one. Full write-up in `docs/gotcha-log.md`.

## The contract

```c
void     we_init(void);                   /* front-end bring-up per FR-S18 step 3    */
bool     we_sample(uint16_t *raw);        /* wiper: one acquisition; false = invalid */
bool     we_switch_sample(uint16_t *raw); /* end-switch ladder, ADC channel 2        */
uint16_t we_raw_max(void);                /* 1023 — 10-bit ADC full scale            */
```

The scope is deliberately narrow: **produce a raw code and say whether it is
trustworthy.** Scaling (FR-E04), offset, windowing, averaging, the 2-second
FR-E07 fault hold and the FR-E23/FR-E24 health checks all live above the driver.
`we_sample()` returning false means *this sample is unusable*, not *the sensor
has failed* — that distinction is what keeps the driver testable in isolation.

Note that FR-E07 detects **opens only**. A wiper shorted to either rail is
indistinguishable from a legitimate end-stop reading, because FR-E21's series
resistor makes the two electrically identical. That is a deliberate, documented
limit, not a gap in the implementation.

## Cost, and why it matters

A conversion is ~21 µs at 241 cycles with the ADC clocked at 12 MHz
(`RCC_ADCPRE_DIV4`), so `we_sample()` costs ~0.34 ms against a ≥100 ms
measurement window. Cheap in that budget — but **not** against the one budget no
requirement states:

> `mb_rx_service` polls a single-byte USART register. Any main-loop pass longer
> than **one character time (1.146 ms at 9600 baud)** loses a byte to overrun,
> and FR-MB24 discards the frame — *without* incrementing 30009, because an
> overrun is not a CRC error. Requests simply vanish.

That is why `meas_open.c` services the wiper and the switch ladder on
**alternate ticks**: no single pass pays for both. Integration stage D dropped
9.7 % of requests before this was understood. If you add work to this path,
measure the pass time, not just the window budget.

## Bench notes that will save you a day

Learned here and in the sibling project, each at real cost:

- **Do not judge a ratiometric ADC against M2K absolute voltages.** The AWG
  outputs setpoint +25 mV and the scope reads ~1 %/−30 mV low. Use a resistor
  divider from the DUT's own 3.3 V rail with a DMM-measured ratio; the
  ratiometric conversion cancels everything else. FR-E03's budget is ±0.1 % of
  full travel, which the M2K cannot resolve. **FR-E03 remains open** for want of
  a precision resistance box at five ratios.
- **A "disabled" M2K AWG channel is not high-impedance** (~50 Ω to its idle
  level) — it cannot emulate a disconnected wiper for the FR-E07 fault rows.
  Physically lift the wire.
- **Keep the libm2k context open** while the DUT-side capture runs;
  `contextClose()` idles the outputs and you will silently test a dead stimulus.
- **The real mechanism is the other half of the accuracy budget.** A divider
  proves the electronics; only the actual draw-wire on the actual window proves
  the installation. FR-E03 covers the first; the second is a separate item.
- **An electrically perfect wiper can still be lying.** A draw-wire that is
  snapped, tangled or slipping reads as a stable, plausible constant and passes
  every check in this driver. That fault is caught above the driver, by FR-E23.

## Reference implementation

The sibling
[`windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface)
project's `wind_direction` driver reads an 11 kΩ potentiometer on the same pin
with the same float-detection trick. It was the starting point — but copy its
*structure*, not its register values, and check every setting against this
project's requirements before reusing it. The one setting that differs is the
one that caused the bug above.
