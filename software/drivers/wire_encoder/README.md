# Wire encoder driver — window-opening acquisition

**Status: not written.** This directory is the project shell only. It holds
the agreed API contract ([`lib/we/we.h`](lib/we/we.h)) and a test harness
that reports its own absence; there is no `we.c`.

## What it will do

A draw-wire encoder is attached to the moving window frame. Its
spring-loaded drum pays out a wire and turns a **10 kΩ potentiometer**, so
the wiper voltage is a direct, absolute measure of how far the window is
open. The driver reads that wiper on **PA2** with the 10-bit ADC in
ratiometric mode referenced to VDD:

- ≥16 conversions folded per sample (FR-E13),
- ≥71-cycle sample time for the 10 kΩ source impedance (FR-E12),
- a floating/shorted wiper detected by toggling the internal pull resistor
  between two conversions and comparing (FR-E07).

## The contract

```c
void     we_init(void);            /* front-end bring-up per FR-S18 step 3   */
bool     we_sample(uint16_t *raw); /* one acquisition; false = invalid       */
uint16_t we_raw_max(void);         /* 1023 — 10-bit ADC full scale           */
```

The scope is deliberately narrow: **produce a raw code and say whether it
is trustworthy.** Scaling (FR-E04), offset, windowing, averaging and the
2-second FR-E07 fault hold all live above the driver. `we_sample()`
returning false means *this sample is unusable*, not *the sensor has
failed* — that distinction is what keeps the driver testable in isolation.

Writing a stub that compiles and returns "invalid sample" would let the
product firmware link and appear to work. That is worse than a link error,
so there is no stub.

See [`lib/we/we.h`](lib/we/we.h) for the full Doxygen contract.

## Reference implementation

The sibling
[`windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface)
project's `wind_direction` driver reads an 11 kΩ potentiometer on the same
pin with the same ADC settings and the same float-detection trick, and is
HIL-verified on silicon (±1.0° against a precision divider, ≤3 counts of
span over 100 reads). **Start from it.** What differs here is only what
happens above the driver: a linear opening instead of a circular heading,
so none of that project's circular-mean machinery is needed.

## What to do next

1. Write `lib/we/we.c` against the header.
2. Build a test shell in `src/main.c`: sample continuously and trace the
   raw code and validity flag over the debug UART, so the Saleae capture
   can be asserted against the stimulus.
3. Run the phase-1 matrix in
   [`design/driverDevelopment.md`](../../../design/driverDevelopment.md) §3.3
   as `software/hil/we_check.py`. **Every row must pass on silicon before
   the product firmware references this library.**
4. Record the results in `software/hil/testReport.md`, then wire the driver
   into the firmware per `design/integrationPlan.md` stage D.

## Bench notes that will save you a day

Inherited from the sibling project's equivalent work, and they cost real
time to learn there:

- **Do not judge a ratiometric ADC against M2K absolute voltages.** The
  AWG outputs setpoint +25 mV and the scope reads ~1 %/−30 mV low. Use a
  resistor divider from the DUT's own 3.3 V rail with a DMM-measured ratio;
  the ratiometric conversion cancels everything else. This matters more
  here than it did there — FR-E03's budget is ±0.1 % of full travel, which
  the M2K cannot resolve.
- **A "disabled" M2K AWG channel is not high-impedance** (~50 Ω to its idle
  level) — it cannot emulate a disconnected wiper for the FR-E07 fault
  rows. Physically lift the wire.
- **Keep the libm2k context open** while the DUT-side capture runs;
  `contextClose()` idles the outputs and you will silently test a dead
  stimulus.
- **The real mechanism is the other half of the accuracy budget.** A
  divider proves the firmware; only the actual draw-wire unit on the actual
  window proves the installation. Plan both.
