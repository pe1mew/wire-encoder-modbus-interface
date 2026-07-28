# HIL test harness

Scripted hardware-in-the-loop testing per `design/driverDevelopment.md`:
flash (`pio`) → stimulate (ADALM2000 / libm2k) → observe (Saleae Logic 2 MCP)
→ assert (Python).

> **Status: scaffolding.** The instrument-generic scripts below are carried
> over from the sibling
> [`windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface)
> project and work as-is. The encoder and register-map check scripts do not
> exist yet, and **nothing here has been run against this project's
> hardware** — there is none. Every quirk catalogued below is inherited
> knowledge: re-confirm the wiring and channel mapping before trusting a
> capture.

> **Consolidated results:** [`testReport.md`](testReport.md) is the single
> record of every HIL test with its setup, expected result, pass criteria,
> and verdict. This README covers *how* to run the harness (instruments,
> wiring, quirks); the test report covers *what was tested and the outcome*.

## Instruments

| Instrument | Interface | Role |
|---|---|---|
| Saleae Logic16 (classic, digital-only) | Logic 2 built-in MCP server, `http://127.0.0.1:10530/mcp` (JSON-RPC/HTTP) | Observer: digital captures, protocol analyzers, CSV export |
| ADALM2000 (M2K) | libm2k (Python 3.11 venv) | Stimulus: pulse trains, bursts, DC levels/ramps, programmable supply; its scope verifies analog |
| WCH-LinkE | `pio run -t upload` (`%USERPROFILE%\.platformio\penv\Scripts\pio.exe`) | Flash + 3.3 V DUT power + UART monitor RX |

## Python environments

- Saleae scripts are **stdlib-only** — any Python ≥3.10 works.
- libm2k wheels top out at **cp311**, and the wheel alone is not enough —
  it needs the system-installed libm2k/libiio DLLs. Setup (one-time):
  1. Run `PlutoSDR-M2k-USB-Drivers.exe` (admin) — IIO/RNDIS USB drivers.
  2. Run `libm2k-0.9.0-Windows-setup.exe` (admin) — runtime DLLs.
  3. `python3.11 -m venv .venv-m2k` and
     `.venv-m2k\Scripts\pip install libm2k-0.9.0-cp311-cp311-win_amd64.whl`
     (wheel from the libm2k GitHub release `python-wheels.zip`).

## Scripts

| Script | Purpose | Status |
|---|---|---|
| `smoke_test.py` | Saleae MCP link: devices, capture, export | inherited, PASS in source project |
| `blinky_check.py` | Flash→capture→assert chain on the DUT (blinky timing) | inherited, PASS in source project |
| `uart_check.py` | debug_uart exit criterion (async-serial decode) | inherited, PASS in source project |
| `m2k_smoke.py` | M2K reachable, calibrated, subsystems up | inherited, PASS in source project |
| `m2k_signal_check.py` | Generate + verify each driver-phase stimulus signal | inherited, PASS in source project |
| `saleae_serial.py` | Shared module: UART capture + timestamped line decode | library |
| `we_check.py` | Encoder driver phase-1 matrix (`driverDevelopment.md` §3.3) — divider-fed linearity, stability, fault rows | **to be written** |
| `mb_check.py` | Modbus RTU protocol matrix (TDS §2) against this register map | **to be written** — port from the source project and retarget the addresses |
| `regs_check.py` | Full TDS §2.7/§2.8 register read/write matrix | **to be written** |
| `endswitch_check.py` | FR-E14/E15/E16 rows: the five §4.4 ladder bands, 20 ms debounce, status bits 3/4 | **to be written** |
| `persist_check.py` | FR-S39 holding persistence across a watchdog reset (`*_test` build) | **to be written** |
| `version_check.py` | FR-S32 chain: `version.h` ↔ `RELEASES.md` ↔ flashed DUT | **to be written** |

**First job when a board exists:** run `smoke_test.py`, then
`blinky_check.py` and `uart_check.py`. That is the ten-minute proof that
the rig is wired correctly, before any real work rests on a capture.

## Bench wiring notes

*Inherited — the channel numbers below describe the source project's bench
and are a starting point, not a fact about yours.*

- Saleae Logic16 lead labels ≠ channel indices (two 8-lead banks). After
  rewiring, locate signals with an all-channel sweep capture first.
- Keep M2K AWG outputs configured 0–3.3 V near the DUT (hardware can swing
  ±5 V — beyond CH32V003 absolute maximums).
- All grounds common (M2K, Saleae, LinkE, DUT).
- **MAX3485 rig**: DUT transceiver DI+RO → PD6, DE+R̄Ē → PC2 with the 10 k
  pull-down; bus A/B → M2K scope 1+/2+ for the analog wire view. A **second
  MAX3485 as raw master**: M2K DIO0 → DI, DIO1 → DE+R̄Ē, **V+ → VCC
  (3.3 V)** — every raw-master script must enable V+ itself
  (`ps.enableChannel(0, True)` + `pushChannel(0, 3.3)`): an unpowered
  MAX3485 sits inert, and the static DE/DI test (drive space, drive mark,
  release) is the 10-second wiring proof.

## RS-485 rig lessons (inherited, learned the hard way)

- **A listening master never stops buffering.** A Modbus master that only
  drains its UART during its own transactions buffers every byte another
  node puts on the shared bus, then parses the stale backlog and reports
  CRC_ERR. One throwaway read IS the flush — retry once on `crc_error`
  before trusting a read that follows raw-master traffic.
- **Inter-frame marks in composed patterns must exceed t3.5 (4.01 ms).**
  A 2.5 ms gap between a garbage tail and a recovery request made the DUT
  (correctly) coalesce them into one discarded frame — 48 bit times of mark
  (5 ms) is the house gap.
- **Noise floods don't move the DUT's CRC counter** — random bytes arrive
  framing-poisoned (FE/overflow) and take the silent-discard path; only
  cleanly-framed-wrong-CRC frames increment 30009. Assert flood recovery by
  behaviour, not by that counter.
- The DUT answers master baud offsets to ±3 % in both directions; its own
  HSI adds ~+0.3 %.

## M2K / libm2k quirks (inherited; fw v0.33 + libm2k 0.9.0)

- **Firmware ≥0.32 is mandatory** for libm2k 0.9.0 (shipped fw v0.27 gave
  erratic AWG output and version errors). Update: copy `m2k.frm` from the
  m2k-fw release onto the M2K mass-storage drive and eject; it self-flashes
  (~1 min, don't unplug).
- **Analog-out session-state corruption**: within one context, repeated
  output reconfiguration misbehaves — `stop()` wedges the DAC until
  `reset()`; a second cyclic `push()` at the same sample rate is silently
  ignored; non-cyclic pushes and `setVoltage()` inherit stale state. The
  reliable pattern is a **fresh `m2kOpen()` + calibrate per analog stimulus
  configuration** (~1.5 s each). Digital out is unaffected.
- Rapid close/reopen can transiently fail ("Cannot set the number of kernel
  buffers") — retry with ~1 s backoff (`open_calibrated()` helper).
- **Pattern generator start stub**: the first period after `push()` is
  anomalous; frequency/duty measurements must judge steady state only.
- **Large cyclic digital buffers get truncated** (1 Hz @ 1 MS/s ran 6%
  fast) — scale the sample rate to keep one period at ~10k samples.
- AWG sample rates snap to a discrete ladder (75 MS/s / 10ⁿ); at low rates
  the DC output droops between buffer wraps — generate DC at 750 kS/s or
  via `setVoltage()`.
- **Absolute AWG+scope accuracy stacks badly** — DMM-anchored on that unit:
  the **AWG outputs setpoint +25 mV** (constant), the **scope reads
  ~1 %/−30 mV low** (affine, drifts ~10 mV between sessions). Never assert
  DUT accuracy against M2K absolute voltages; use a **resistor divider
  from DUT VDD** (ratiometric, DMM-measured ratio) as the method of record.
  **This matters more here than it did there:** the whole FR-E03 accuracy
  budget is ±0.1 % of full travel, which the M2K cannot resolve. The M2K
  remains fine for dynamics, end stops, and anything ratio-cancelled.
- **Keep the libm2k context OPEN while the DUT-side capture runs**:
  `contextClose()` idles the AWG outputs. Measure-then-close-then-capture
  silently tests a dead stimulus (cost a full debugging afternoon).
- A "disabled" AWG channel is NOT high-impedance (~50 Ω to its idle
  level) — it cannot emulate a disconnected sensor for the FR-E07 fault
  rows; physically lift the wire instead.

## Saleae MCP quirks (inherited)

- `add_analyzer` settings need tagged values: `{"Input Channel": {"numberValue": 8}}`.
- `export_raw_data_csv` requires `analogDownsampleRatio` even for digital-only.
- Async-serial data-table CSV holds the *literal* character per byte — CR/LF
  arrive as embedded newlines inside quoted fields; don't strip.
- A capture that starts mid-byte yields garbage + one framing error before
  the first line boundary — judge from the first clean `\n` onward.
- Classic Logic16 rejects `digitalThresholdVolts` values — omit it (default
  range suits 3.3 V logic).
- **The Logic 2 Async Serial analyzer is unreliable at 9600 baud** on this
  setup — byte values scramble while the raw edges are perfect. Binary
  protocols use `saleae_serial.uart_decode()` (software UART over the raw
  edge export) instead. Also: `decode_events(..., sync_to_newline=False)`
  for binary — the text-protocol first-LF rule silently discards LF-free
  captures.

## DUT-side gotchas (inherited)

- **HDSEL idles the line floating**: in half-duplex mode the USART releases
  TX between frames; a lightly-loaded pin drifts low and every following
  frame decodes with framing errors. `common/debug_uart` therefore runs
  plain TX (idle mark driven).
- **HDSEL also intermittently swallows the first RX byte after idle**
  (~35%, no error flags) — the Modbus driver abandoned HDSEL entirely for a
  remap-switching discipline. See `software/drivers/modbus_rtu/README.md`.
- **Interrupts are suspect on this toolchain path**: an RXNE ISR corrupted
  ~1/3 of received frames with no USART error flags; polled RX fixed it
  outright. The architecture is zero-ISR — root-cause before ever adding
  one.
- **ch32v003fun SysTick default is HCLK/8**: define
  `FUNCONF_SYSTICK_USE_HCLK 1` when pacing with raw `SysTick->CNT` math, or
  everything runs 8× slow.
- **A master must release the wire immediately after its last stop bit** —
  the DUT replies ~5 ms later; holding the line driven collides with the
  reply.
- DUT-side registers exposing error counters and a last-bad-frame stash are
  worth their flash cost many times over.
