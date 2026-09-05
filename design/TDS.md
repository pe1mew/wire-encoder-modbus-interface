# Technical Design Specification — Wire Encoder Modbus Interface

| Field        | Value                                    |
|--------------|-------------------------------------------|
| Document     | Technical Design Specification            |
| Project      | `wire-encoder-modbus-interface` (DUT firmware) |
| Version      | 0.7 (draft — **v0.7 adds FR-E23 and FR-E24, the sensing-health indications, and defines status bits 6 and 7 for them. This is a §2.7 register-map change: FR-S33 previously pinned bits 6–15 to zero.** They report the credibility of the position signal — FR-E23 that it follows the carriage, FR-E24 that it is within a reachable range — and between them address the two documented blind spots, FR-E07's undetectable short and §4.4.6's absent fault band. FR-E24's sensitivity depends on the installation leaving electrical headroom; see `description.md` §8.1. Reasoning and rejected alternatives in `scratchBook.md` Q4. v0.6 — §2 Modbus contract inherited and proven; §2.7/§2.8 register map new; §3 lifecycle inherited + new FR-E measurement series. **v0.6 changes the end switch to the 3RG4023-3AB00, which is PNP where the previous part was NPN — every §4.4 band inverts, the fault band is gone, and NFR-ENV01's ceiling rises to +70 °C.** v0.5 added FR-E17…FR-E20, the signed movement rate and the IP65 enclosure; v0.4 made the opening scaling direction-agnostic) |
| Date         | 2026-07-28                                |
| Status       | **Draft.** The Modbus half of this document is settled — it is the sibling project's verified contract. The measurement half (§2.7/§2.8 semantics, §3.3–§3.5, §4) is a first draft written before any hardware exists, and is expected to move. Open items in §6. |
| Related docs | `design/description.md` (the same behaviour in prose, for integrators and installers); `design/scratchBook.md` (working notes and the reasoning behind the choices); sibling [`windmeters-modbus-interface`](https://github.com/pe1mew/windmeters-modbus-interface) `design/TDS.md` v0.9 — the source of §2, §3.1/§3.2, §5 and their bench evidence |

---

## 1. Purpose and scope

### 1.1 What this device does

A window — a greenhouse vent, a roof light, a louvre — is opened and closed by
an actuator, and something needs to know **how far open it currently is**. This
device measures that and publishes it on Modbus RTU over RS-485.

The measurement comes from a **draw-wire encoder**: a spring-loaded drum pays
out a steel wire attached to the moving window frame, and the drum turns a
**10 kΩ potentiometer**. The wiper voltage is therefore a direct, absolute
measure of how far the wire has been pulled out — that is, of the window
opening. Absolute in the sense that matters here: the reading is valid the
instant power returns, with no homing move and no count to lose.

Two **end-of-travel switches** report that the window has reached a
mechanical limit, read as a supervised resistor ladder that also monitors
its own cable (§3.5).

This document holds the things the firmware **must** do, each with a testable
pass/fail — including the failure paths (unsupported function codes,
unimplemented registers, out-of-range writes) that otherwise get decided
implicitly, one `if` statement at a time.

### 1.2 What is inherited and what is new

This project is a sibling of `windmeters-modbus-interface`: same MCU, same
RS-485 front-end, same architecture, same author. The requirement set is
therefore split by provenance, and it matters when reading a row:

| Part | Provenance | Confidence |
|---|---|---|
| §2.1–§2.6 (FR-MB01…FR-MB30) | Inherited verbatim from the sibling TDS v0.9 | **High.** Implemented by the same `mb.c` binary carried into this repo, HIL-verified there (26/26 protocol matrix, 40/40 endurance, 1000-request latency histogram) |
| §2.7/§2.8 (register map) | **New** — window-opening semantics | Draft. Addresses and ranges will move as the measurement path is designed |
| §3.1, §3.2 (FR-S01…FR-S03, FR-S18…FR-S24, FR-S30…FR-S36, FR-S39) | Inherited, retargeted | **High** for the lifecycle mechanics (watchdog, PVD, init order, persistence — same code); the register-specific wording is draft |
| §3.3–§3.5 (FR-E…) | **New** — opening measurement, potentiometer front-end, end switches | Draft |
| §4 (hardware) | **Open** — no schematic exists | To be written from the KiCad design, as §4 of the sibling TDS was |
| §5 (NFR-…) | Inherited | High — same MCU, same ceilings |

Requirement ID scheme: **FR-MB…** Modbus protocol, **FR-S…** software
lifecycle and diagnostics, **FR-E…** measurement (new series, so no ID
silently means something different here than in the sibling project),
**NFR-…** non-functional.

Key design decisions fixed in this version:

- **One build.** There is one sensor read one way, so there is no build
  variant and no capability macro (FR-S01). Address pair 40/45, selected by
  the **PC1** solder jumper (FR-S03) and deliberately clear of the windmeters
  family's 30–37 so both can share an RS-485 segment.
- Holding registers persisted across reset in flash-emulated non-volatile
  storage (FR-S39); §2.8 defaults apply only on first boot / erased store
  (FR-S21).
- Device address is hardware-configured only (solder jumper); there is no
  address register — see FR-S03/FR-MB07.
- Exception 04 never emitted; faults handled by watchdog and defined register
  values — see FR-MB29.
- Opening is scaled by a **two-point runtime calibration** (raw code at closed,
  raw code at fully open) plus a travel span, all persisted — so one image
  serves any window size and any wire routing without a rebuild (FR-E05).
- **The scaling is direction-agnostic** (FR-E04). Whether the wiper code rises
  or falls as the window opens depends on how the draw-wire happens to be
  fitted, which is a coin toss; the calibration points may therefore be given
  in either order and the firmware sorts it out. FR-E06 constrains their
  *distance*, not their ordering.
- **End switches are mandatory** (§3.5), because the measured opening can
  only ever *infer* that a stop was reached and that inference is only as
  good as a calibration that a re-strung wire or a slipped drum invalidates.
- **The address jumper is on PC1 and the switch ladder on PC4**, not the
  other way round (§4.2). PC4 carries an ADC channel and PC1 does not; the
  jumper is a boot-time digital read that does not need one, while the switch
  loop can spend the extra states on supervising its own cable.

---

## 2. Modbus requirements

> §2.1–§2.6 are inherited verbatim from the sibling project's TDS v0.9 and
> are implemented by the driver carried into
> `software/drivers/modbus_rtu/`. Register-specific examples in the
> pass/fail criteria have been retargeted to this project's map (§2.7/§2.8);
> the normative requirement text is unchanged.

### 2.1 Physical layer, framing, and receiver robustness

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB01 | Must | The firmware shall communicate using Modbus RTU framing at 9600 baud, 8 data bits, no parity, 1 stop bit (8N1). | Connect a Modbus analyser or the tester at 9600 8N1; all frames are decoded without framing errors. |
| FR-MB02 | Must | Frames with an invalid CRC-16 shall be silently discarded. No response shall be sent. | Send a frame with a deliberately corrupted CRC; confirm no reply within 200 ms. |
| FR-MB03 | Must | The firmware shall detect the inter-frame gap (3.5 character times) as the frame boundary. One character time is defined as 11 bits per the Modbus RTU specification (11/9600 s ≈ 1.15 ms), so 3.5 character times ≈ 4.0 ms at 9600 baud; this definition applies wherever this document says "character time". A new frame starts after this silence. | Two back-to-back valid requests separated by ≥5 ms are both processed correctly. Send the first 4 bytes of a valid request, pause ≥5 ms, then send the remaining bytes: no response of any kind within 200 ms; an immediately following complete valid request receives a correct response, proving the receiver state machine recovered. |
| FR-MB04 | Must | The RS-485 driver-enable line (DE/RE on PC2) shall be asserted before the first transmitted byte and de-asserted after the last transmitted byte, within one character time (≈1.15 ms at 9600 baud). | Scope DE/RE and TX lines: DE asserts before TX start bit; DE de-asserts within one character time after the last stop bit. |
| FR-MB23 | Must | While the firmware is transmitting (DE asserted), any bytes appearing on the USART receiver shall be discarded and shall not be evaluated as an incoming frame. (The MAX3485 RO and DI are tied on the shared PD6 data node; RO is high-Z while DE is asserted, and the firmware uses a remap-switching line discipline — USART1 RX native on PD6, TX remapped onto PD6 only for the response — rather than HDSEL, which bench testing showed intermittently swallows the first byte after bus idle.) Frame reception shall re-arm only after DE is de-asserted and a 3.5-character idle time has elapsed. | Bus-analyser capture: send one valid FC04 request and confirm exactly one response frame is transmitted and the bus then stays idle — no self-triggered frame within 500 ms. Repeat 100 times back-to-back with zero spurious frames. |
| FR-MB24 | Must | On any USART receive error (overrun, framing, noise) or on receiving more bytes without a 3.5-character gap than the receive buffer holds (the buffer shall accept frames up to the 256-byte Modbus RTU ADU maximum), the firmware shall discard the frame in progress, clear the error condition, and resynchronise on the next ≥3.5-character idle gap. No buffer overflow and no receiver lockup shall occur. | Transmit continuous pseudo-random bytes at 9600 baud with no idle gaps for 60 s, then one valid FC04 request: a valid response arrives within the FR-MB20 budget; repeat 10 times with 100% success. Send a 400-byte "frame" followed by a ≥5 ms gap and a valid request: no response to the burst, valid response to the request; 20 repetitions without failure or reset. |
| FR-MB25 | Must | All 16-bit register values and 16-bit address/quantity fields in request and response PDUs shall be transmitted big-endian (high byte first). The CRC-16 field shall be transmitted low byte first, high byte second, per the Modbus RTU specification. | With the opening held at a known 90.0 mm (register value 900 = 0x0384), an FC04 read of raw 0x0000 returns data bytes 0x03 then 0x84 in that order, decoded as 900 by the tester with no byte-swap option. The final two bytes of every captured frame validate as CRC low-byte-first. |

### 2.2 Addressing

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB05 | Must | The firmware shall respond only to requests addressed to its currently active Modbus address. Requests addressed to any other unicast address shall be silently ignored. | With the DUT as the only slave on the bus, send a valid FC04 request to address 247 (never assigned in this product family per FR-S03): no reply within 200 ms. Send the same request to the DUT's own address: valid reply. |
| FR-MB06 | Must | Broadcast requests (address 0) shall be silently ignored — not executed, no response sent. *Deliberate deviation from Modbus-over-Serial-Line V1.02 §2.2, which requires slaves to execute broadcast writes. Rationale: broadcast execution of configuration writes risks unintended fleet-wide reconfiguration and offers no benefit given jumper-derived addressing (FR-S03). This deviation shall be stated in user-facing register-map documentation.* | Send a valid FC06 write to address 0; confirm no reply within 200 ms and no register change on follow-up read. |
| FR-MB07 | Must | The device address shall be latched at startup per FR-S03 (the single normative source of the address table) and shall not change until the next reset. There is no Modbus-accessible address register. | Power cycle with the solder jumper open → device responds at 40 and not at 45; with the jumper bridged → responds at 45 and not at 40. A jumper change mid-cycle has no effect until the next reset. |

### 2.3 Supported function codes

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB08 | Must | FC04 (Read Input Registers) shall be supported for all input register addresses in §2.7. | FC04 request for each register in §2.7 returns a valid response with correct byte count and data. |
| FR-MB09 | Must | FC03 (Read Holding Registers) shall be supported for all holding register addresses in §2.8. | FC03 request for each register in §2.8 returns a valid response with correct byte count and data. |
| FR-MB10 | Must | FC06 (Write Single Register) shall be supported for all holding register addresses. | FC06 write of a valid value to each holding register is accepted; follow-up FC03 read confirms the new value. |
| FR-MB11 | Must | FC16 (Write Multiple Registers) shall be supported for holding registers. | FC16 write of valid values to two consecutive holding registers is accepted; follow-up reads confirm both values changed. |
| FR-MB12 | Must | Any function code other than FC03, FC04, FC06, FC16 shall be rejected with exception 01 (Illegal Function). | Send FC01, FC02, FC05; confirm exception 01 response for each. |
| FR-MB30 | Must | The normal (success) response to FC06 shall be a byte-exact echo of the request frame. The normal response to FC16 shall contain: slave address, function code 0x10, starting address (2 bytes), quantity of registers written (2 bytes), CRC — not the register data. | Capture request and response for FC06 write 40001 = 100: the two frames are byte-identical. For an FC16 write of 2 registers at raw 0x0001: the response PDU after the function code is exactly 0x00 0x01 0x00 0x02. |

### 2.4 Register access rules

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB13 | Must | A read request for any register address not listed in §2.7 or §2.8 shall return exception 02 (Illegal Data Address). | FC04 or FC03 request for raw address 0x0020; confirm exception 02. |
| FR-MB14 | Must | A multi-register read (FC03/FC04) whose range spans at least one unimplemented address shall return exception 02 for the entire request. No partial data shall be returned. | FC04 request starting at the last valid input address (0x000E) with count 2; confirm exception 02, not partial data. |
| FR-MB15 | Must | A write to an unimplemented holding register address shall return exception 02. | FC06 write to raw holding address 0x0020; confirm exception 02 and no side effect. |
| FR-MB27 | Must | The firmware shall implement the §2.7/§2.8 register map in full: raw input addresses 0x0000–0x000E (15 registers) and raw holding addresses 0x0000–0x0006 (7 registers). No mapped register shall return exception 02. | FC04 read of raw 0x0000 quantity 15 returns a normal response with 30 data bytes; FC03 read of raw 0x0000 quantity 7 returns 14 data bytes; FC04 of 0x000F returns exception 02. |
| FR-MB28 | Must | FC03/FC04 requests with quantity = 0 or > 125 shall return exception 03 (Illegal Data Value). FC16 requests with quantity = 0, or a byte-count field not equal to 2 × quantity, shall return exception 03 and shall modify no register. *(A quantity > 123 clause was dropped 2026-09-01: an FC16 ADU is 9 + 2N bytes, so N = 124 is 257 bytes and exceeds the 256-byte RTU maximum. Every such frame is caught by FR-MB24's length limit first, making the clause structurally unverifiable. The firmware's own quantity check is harmless and is left in place.)* Quantity validation shall be performed before address validation. | FC04 at raw 0x0000 with quantity 0 returns exception 03 (not 02, not an empty data frame) within 200 ms. FC03 with quantity 126 returns exception 03. FC16 to raw 0x0001 with quantity 2 but byte count 5 returns exception 03 and follow-up reads show both registers unchanged. |

### 2.5 Exception handling

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB17 | Must | For any addressed request the firmware cannot fulfil, a well-formed Modbus exception response shall be returned. The firmware shall never stay silent on a valid addressed request. | Send FC04 for an unimplemented address; confirm a response arrives within 200 ms. (A silent device is invisible to a master's bus scanner, which detects devices precisely because they exception-reply.) |
| FR-MB18 | Must | Exception responses shall use only the standard Modbus exception codes: 01 Illegal Function, 02 Illegal Data Address, 03 Illegal Data Value. No vendor-specific codes shall be used. (Code 04 is standard but deliberately never emitted — FR-MB29.) | For each exception path (FR-MB12/13/15/19/28), confirm the exception byte is one of 01/02/03 and is decoded correctly by the tester's `exception_name` field. |
| FR-MB19 | Must | A write (FC06/FC16) with a value outside the valid range defined in §2.8 shall return exception 03 (Illegal Data Value). The register shall be left unchanged. The firmware shall not clamp the value to the nearest valid bound, and shall not echo success while discarding the value. | Write measurement window (40002) = 65000 (out of range); confirm exception 03; follow-up read shows the register unchanged (not clamped to 60000). |
| FR-MB22 | Must | An FC16 write shall be atomic: if any value in the request is outside its valid range (including the cross-register constraints FR-S31 and FR-E06), the entire request shall be rejected with exception 03 and no register in the range shall be modified. | FC16 write to 40001–40002 with a valid offset (e.g. 100) and an invalid window (e.g. 65000); confirm exception 03 and follow-up reads show both registers unchanged — including the one whose value was valid. |
| FR-MB29 | Should | The firmware shall never emit exception 04 (Slave Device Failure). Internal faults are handled by watchdog reset (FR-S20) and defined register values (FR-S21) instead. Exceptions shall be emitted only per the enumerated triggers: 01 per FR-MB12; 02 per FR-MB13/14/15; 03 per FR-MB19/22/28 and FR-S31/FR-E06. | Code review confirms no code path emits exception 04. Fault injection of documented conditions (bad function code, bad address, bad value, bad quantity) produces only the enumerated codes. |

### 2.6 Response timing

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB20 | Must | The firmware shall transmit its response within 100 ms of receiving the last byte of a valid request. | Measure time from last RX byte to first TX byte using the tester's raw frame timestamps; confirm ≤100 ms for FC03, FC04, FC06, and FC16 requests. |
| FR-MB21 | Should | Under default configuration, at least 95% of responses shall start within 15 ms of the last request byte. | Issue 1,000 FC04 requests at 50 ms spacing with default configuration: at least 95% of responses start within 15 ms of the last request byte, and 100% within the FR-MB20 limit of 100 ms. |

### 2.7 Input register map (FC04, read-only)

**New in this project — draft.** Measurement registers 30001–30004 and
30012 read 0 from reset until the first measurement window completes
(FR-S23). Identification, status, uptime and counter registers
(30005–30010) are valid immediately after reset. The map edge is 0x000E
(15 registers) — an FC04 past it returns exception 02 (FR-MB13).

> **30012 is signed.** It is the only register in the map that is, and a
> master reading it as unsigned sees ≈65500 for a closing window rather than a
> small negative number. Two's complement, so `int16_t` on the master side.
> Everything else in §2.7 and §2.8 is unsigned.

> **A read of 30013/30014 has a side effect while teach is armed** — it is
> half of the FR-E19 handshake. That is deliberate: it means a master polling
> at 1 Hz cannot miss the captured values, because the device will not retire
> them until they have actually been collected. Outside teach the registers
> are inert diagnostics and reading them changes nothing.

30013/30014 are the **calibration-drift diagnostic** (FR-E18). Each holds the
wiper reading taken the moment the window was last known to be physically at
that stop. Comparing them against 40005/40006 measures how far the calibration
has drifted, against a physical reference rather than against any model — and
a slipped draw-wire is otherwise undetectable, because it produces a
plausible, stable, wrong reading.

| Raw | Modicon # | Description | Unit | Range |
|-----|-----------|-------------|------|-------|
| `0x0000` | 30001 | Window opening, instantaneous | 0.1 mm | 0–65534; 65535 = sensor fault (FR-E07) |
| `0x0001` | 30002 | Window opening, averaged | 0.1 mm | 0–65534; 65535 = sensor fault (FR-E07) |
| `0x0002` | 30003 | Window opening, minimum in the current averaging window | 0.1 mm | 0–65534; 65535 = sensor fault (FR-E08) |
| `0x0003` | 30004 | Window opening, maximum in the current averaging window | 0.1 mm | 0–65534; 65535 = sensor fault (FR-E08) |
| `0x0004` | 30005 | Raw ADC code — diagnostic, pre-calibration | counts | 0–1023, 10-bit (FR-E09) |
| `0x0005` | 30006 | Status flags (normative definition: FR-S33) | bitfield | bit 0 = no completed window yet; bit 1 = averaging accumulator not filled; bit 2 = wiper fault; bit 3 = end of travel reached; bit 4 = end-switch loop fault; bit 5 = teach in progress; bit 6 = implausible raw code (FR-E24); bit 7 = position not following the carriage (FR-E23); bits 8–15 = 0 |
| `0x0006` | 30007 | Identification | — | high byte = build type (0x01); low byte = firmware version (FR-S32) |
| `0x0007` | 30008 | Uptime since reset | s | 0–65535, saturating (FR-S34) |
| `0x0008` | 30009 | Bus CRC error count | — | 0–65535, wrapping (FR-S35) |
| `0x0009` | 30010 | Served request count | — | 0–65535, wrapping (FR-S35) |
| `0x000A` | 30011 | Seconds since the last valid sensor reading | s | 0–65535, clamped (FR-S36) |
| `0x000B` | 30012 | Movement rate — **signed**; positive = opening, negative = closing | 0.1 mm/s | **two's-complement int16**, −32768…+32767, clamped (FR-E10) |
| `0x000C` | 30013 | Raw ADC code captured at the last **closed-end** stop event | counts | 0–65535; 0 = no such event since reset (FR-E18) |
| `0x000D` | 30014 | Raw ADC code captured at the last **open-end** stop event | counts | 0–65535; 0 = no such event since reset (FR-E18) |
| `0x000E` | 30015 | Window opening as a **percentage of full travel** | 0.1 % | 0–1000; 65535 = sensor fault (FR-E20) |

*Open (§6): whether the movement rate should be signed (opening vs closing)
rather than a magnitude, and whether a percentage-of-travel register should
join the map for masters that would otherwise have to divide by 40004.*

### 2.8 Holding register map (FC03/FC06/FC16, read-write)

**New in this project — draft.** Holding registers 40001–40006 persist across reset in non-volatile storage
(FR-S39); the Default column is the value on first boot / when the store is
blank or corrupt (FR-S21). **40007 is deliberately excluded from
persistence** — it is a command, not a setting, and an armed teach surviving a
power cut would be a surprise rather than a convenience (FR-E19). Writes outside the
valid range are rejected per FR-MB19/FR-MB22. Two cross-register
constraints apply, defined and enforced solely by FR-S31 (40002/40003) and
FR-E06 (40005/40006).

| Raw | Modicon # | Description | Unit | Valid range | Default |
|-----|-----------|-------------|------|-------------|---------|
| `0x0000` | 40001 | Zero offset — opening reported at the calibrated closed point | 0.1 mm | 0–65534 | 0 |
| `0x0001` | 40002 | Measurement window duration | ms | 100–60000 | 1000 |
| `0x0002` | 40003 | Averaging window | s | 1–600, subject to FR-S31 | 10 |
| `0x0003` | 40004 | Full travel — opening span between the two calibration points | 0.1 mm | 1–65534 | 10000 (= 1000.0 mm) |
| `0x0004` | 40005 | Raw code with the window **closed** (FR-E05) | ADC counts | 0–65534, subject to FR-E06 | 0 |
| `0x0005` | 40006 | Raw code with the window **fully open** (FR-E05) | ADC counts | 1–65535, subject to FR-E06 | 1023 |
| `0x0006` | 40007 | Teach command / state — **not persisted** (FR-E19) | — | 0 = idle, 1 = arm/active | 0 |

40005 and 40006 are the *closed* and *open* points, not a low and a high one:
**40006 may legally be less than 40005**, which is how a reversed sensor
mounting is expressed (FR-E04). FR-E06 constrains only the distance between
them. In practice both lie in 0–1023, the 10-bit ADC range.

The device address is not a register: it is hardware-configured per FR-S03
and unreachable over Modbus (FR-MB07).

---

## 3. Software requirements

### 3.1 Build configuration and startup

*(Inherited from the sibling project, reduced to a single build. The
mechanics — init order, jumper latch, bus-idle sync — are implemented by the
carried-over `board.c` and `mb.c`.)*

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S01 | Must | The firmware shall build as a single release image from one source tree. The only compile-time option shall be the bench-only test hooks, off by default; the release image is the one built without them. There shall be no build-variant selector and no optional product feature. | `pio run` from a clean checkout produces the release binary without any `-D` beyond the defaults. |
| FR-S02 | Must | A single hardware PCB shall support the device without modification. | Flash the release binary onto an unmodified PCB: the device passes its full §2/§3 acceptance suite. |
| FR-S03 | Must | The power-on Modbus device address shall be determined at startup by the state of the solder jumper on PC1. This table is the single normative source of the address assignment: jumper open = 40, bridged = 45. There is no address register; the address cannot be changed at runtime (FR-MB07). | Reading PC1 GPIO at startup selects the address per the table; the device responds only on that address after power-on (FR-MB07's criterion). |
| FR-S18 | Must | Initialization shall complete in this order before the main loop starts: (1) PC2 (DE/RE) configured as output driven low — receiver enabled, driver disabled — as the first GPIO action after reset; (2) PC1 read and the Modbus address latched; (3) sensor front-end ready — ADC self-calibration executed before the first conversion of either channel (PA2 wiper, PC4 switch ladder); (4) USART1 receiver enabled last. | (a) The first non-zero value after power-on at a fixed window position is within the FR-E03 tolerance, with no settling sequence of wrong values. (b) A valid request sent repeatedly from power-on is never answered from a wrong address. (c) The first published switch state matches the physical switch position, with no spurious transition. |
| FR-S19 | Must | The firmware shall never transmit on the bus except in response to a valid addressed request (no boot banner, no test bytes). After any reset, received bytes shall be discarded until a bus-idle period of ≥3.5 character times has been observed. | Scope PC2 and the bus across 20 power cycles while another master/slave pair actively exchanges frames: DE never asserts except to answer a valid request to the DUT, and a DUT reset injected mid-frame of third-party traffic produces no response to that partial frame. |

### 3.2 Reliability and lifecycle

*(Inherited; same watchdog/PVD/persistence implementation.)*

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S20 | Must | The independent watchdog (IWDG) shall be enabled before the main loop starts, with a timeout between 100 ms and 2 s, refreshed only from the main loop after both the Modbus service and the measurement service have run — never from an interrupt handler. | (a) Via a debug-build hook that enters an infinite loop, confirm the device resumes answering a valid FC04 within 3 s without a power cycle. (b) 24 h of continuous polling under normal operation triggers zero watchdog resets. |
| FR-S21 | Must | After any reset (power-on, brown-out, watchdog, software), the firmware shall enter a defined state: holding registers restored to their last persisted values (FR-S39), or to §2.8's Default column when the persistent store is blank/corrupt; all measurement accumulators cleared. No Modbus-commanded reset shall exist; power cycling is the only reset a master or installer can invoke. | Trigger each reset source in turn: after each, the device responds at the jumper-derived address within 1 s, FC03 of raw 0x0000–0x0005 returns the last committed values (FR-S39), and all accumulators are cleared (status bits 0/1 set). On a device with an erased store the same read returns exactly the §2.8 Default column. |
| FR-S22 | Must | The device shall resume full normal operation (all §2 and §3 requirements) after any supply interruption or dip, without manual intervention. Brown-out protection (hardware POR plus PVD) shall guarantee the MCU either operates correctly or is held in reset — no third state. | With a programmable supply, apply a dip matrix (3.3 V rail from 3.0 V to 0 V in 0.3 V steps; durations 1 ms to 10 s; 10 repetitions each): after every event the device answers a valid FC04 within 1 s of rail recovery with register contents equal to the defined post-reset state; zero hung/silent/garbage outcomes across the matrix. |
| FR-S23 | Must | Measurement input registers (30001–30004, 30012) shall be initialised to 0 at reset and shall read 0 until the first measurement window completes (status bit 0, FR-S33). From the first completed window until the averaging accumulator has filled once (status bit 1, FR-S33), averaged register 30002 shall be computed over only the samples actually acquired since reset — partial-window mean, no zero-padding and no stale seeding. | With the window held at a fixed 500.0 mm opening from before power-on, measurement window 1 s / averaging 10 s: every FC04 response before the first window boundary reads 0 in all measurement registers; at t = 3 s register 30002 reads 5000 ±2 LSB, not ~1500 (the zero-padded value). |
| FR-S24 | Must | All register values returned in a single FC03/FC04 response shall form a coherent snapshot from one measurement update. In particular, 30001 and 30005 in the same response shall be consistent: 30001 equals the FR-E04 scaling applied to that response's 30005 — never a mixture of two windows. | Drive the window continuously between two positions while polling FC04 for 30001–30005 back-to-back for ≥1 hour (≥50,000 responses): the 30001/30005 consistency rule holds in 100% of responses and no response mixes values from two windows. |
| FR-S30 | Must | A valid write to 40002 shall abort the in-progress measurement window; the partial result shall be discarded (not published) and a new window of the new duration shall start immediately. A valid write to 40002 or 40003 shall clear the averaging accumulator; 30002/30003/30004 shall retain their last published values until the first new window completes, then follow the partial-window rule (FR-S23). Status bits 0 and 1 (FR-S33) shall re-assert accordingly. | At a fixed opening, write 40002 = 5000 mid-window: the next publish occurs no sooner than 5000 ms after the write; status bit 0 is set from the write until that window completes. Write 40003 = 5 mid-average: bit 1 sets and clears within 5 s. |
| FR-S31 | Must | The firmware shall enforce (40003 × 1000) ≥ 40002 at all times: any FC06/FC16 write violating this shall be rejected with exception 03 and leave the register(s) unchanged (respecting FR-MB22 atomicity). This row is the single normative source of the constraint. The average shall span N = floor((40003 × 1000) / 40002) completed windows (N ≥ 1). For N ≤ 64 the boxcar shall be exact; for N > 64 a two-stage boxcar is permitted: consecutive windows aggregated into blocks of ⌈N/64⌉ windows (block mean for the opening, block minimum/maximum for 30003/30004), with an effective span within ±one block of N windows. This bounds storage at ≤64 entries per quantity. **Kept deliberately, 2026-09-01**: the instantaneous reading measures **0 LSB of spread over 60 reads** on the bench, so the mean is not smoothing measurable noise there — but that is a clean-bench figure (short cable, still carriage, no wind loading) and the engine costs 384 B of a 1 792 B budget currently at 61 %. Revisit with *field* noise data, not bench data. | Precondition: write 40003 = 60, then 40002 = 60000. FC06 write 40003 = 30 then returns exception 03 and 40003 is unchanged; write 40003 = 60 is accepted. With 40002 = 100 and 40003 = 600 at a fixed opening, the device meets FR-MB20 timing for ≥10 minutes and 30002 settles to 30001 ±1 LSB. |
| FR-S39 | Must | The six *setting* holding registers (40001–40006) shall persist across every reset and power-loss in on-chip non-volatile storage. The teach command register 40007 shall @b not persist: it reads 0 after any reset regardless of its value beforehand (FR-E19). On a write that *changes* a holding value (FC06/FC16, after it passes FR-MB19/FR-MB22/FR-S31/FR-E06 validation and the Modbus response has been transmitted), the firmware shall commit the whole holding set so a subsequent reset restores it (superseding the §2.8 defaults, per FR-S21). The commit shall be power-loss atomic — a reset at any point during a commit leaves the previously committed set intact, never a partial/corrupt configuration — and shall fall back to the §2.8 compile-time defaults when no valid record exists (first boot / erased store). Unchanged writes shall not wear the store. | Write non-default 40001–40006, trigger a watchdog reset, confirm FC03 returns the written values (not §2.8 defaults) within 1 s. On an erased store the read returns the §2.8 defaults. Re-writing identical values causes no additional non-volatile write. Power interrupted mid-commit never yields a partial configuration. |

### 3.3 Window-opening measurement

**New — draft.**

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-E01 | Must | The reported opening shall be absolute — derived from a reading that has no dependence on prior samples — so it is correct immediately after any reset with no homing move or reference run. | Power-cycle with the window held at a fixed opening: the first published 30001 is within FR-E03 tolerance of the pre-reset value, with no movement of the window. |
| FR-E02 | Must | The measurement window duration shall be configurable via holding register 40002 (default per §2.8); each completed window shall publish one instantaneous opening (30001) and feed the averaging engine. | At a fixed opening, with 40002 = 500 the publish cadence is 500 ms ±2% (FR-S17); with 40002 = 2000 it is 2000 ms ±2%. |
| FR-E17 | Must | **Maximum age of a read value.** The value in input register 30001 at the instant a read is served shall be no older than the configured measurement window (40002). A master therefore bounds staleness by configuration alone — there is no separate freshness protocol, and no need for the device to sample on demand. The same bound applies to 30005, which is always drawn from the same acquisition as 30001 (FR-S24). *Exception:* during the FR-E07 fault-hold grace period the last valid opening is deliberately held and may be up to 2 s older; input register 30011 is the indication and is non-zero throughout. | With 40002 = 200 ms, drive the sensor with a ramp of known slope and poll 30001 at a rate uncorrelated with the window for 10 minutes: no response differs from the true position at the moment it was served by more than (slope × 200 ms) + the FR-E03 tolerance. Repeat with 40002 = 1000 ms and confirm the error bound scales with the window, proving the age is set by 40002 and not by anything else. |
| FR-E03 | Must | Reported opening accuracy — with the potentiometer replaced by a precision divider of ≤0.1 % ratio accuracy — shall be within ±0.1 % of the configured full travel (40004), covering quantization and INL. End-to-end accuracy including the draw-wire mechanism's linearity and the potentiometer's own conformity is a separate hardware/calibration item (§6). | At each of 5 known divider ratios spanning the range, the reported value is within ±0.1 % of full travel; 100 reads over 60 s at a fixed ratio span ≤3 LSB. |
| FR-E04 | Must | Opening shall be computed as `opening[0.1 mm] = offset + ((raw − raw_closed) × travel) / (raw_open − raw_closed)`, where offset = 40001, travel = 40004, raw_closed = 40005 and raw_open = 40006. **The two calibration points may be given in either order:** `raw_open < raw_closed` describes a mounting in which the wiper code falls as the window opens, and shall produce a correct, increasing opening — the firmware shall not require the installer to reverse the sensor wiring. The result shall be clamped to `[offset, offset + travel]`, so it is monotonic in `raw` across the entire ADC range with no step at either calibration point, and shall never exceed 65534 (65535 is reserved for the FR-E07 fault value). The computation shall be integer-only with no intermediate overflow over the full input domain (raw 0–65535, travel 1–65534): with the distance from the closed point clamped to the calibrated span before the multiply, the largest intermediate is 65535 × 65534 = 4,294,770,690, inside an unsigned 32-bit integer by 196,605 (0.0046 %). | Host-test the scaling function at its corners in **both** mounting senses: with (raw_closed, raw_open) = (0, 1023) and again (1023, 0), the closed point reads `offset`, the open point reads `offset + travel`, and mid-scale reads `offset + travel/2` ±1 LSB. Sweeping `raw` across 0–1023 yields a monotonic non-decreasing series in both senses. (raw = 65535, raw_closed = 0, raw_open = 65535, travel = 65534) → 65534, not a wrapped value. A raw code beyond the closed point reads exactly `offset`, with no discontinuity at the point itself. |
| FR-E05 | Must | The opening scaling shall be runtime-configurable and persistent via three holding registers: 40004 full travel, 40005 raw code at the closed point and 40006 raw code at full opening, applied per FR-E04. A change to any of them shall clear the averaging accumulator (as FR-S30 does for 40002/40003) so the boxcar never mixes pre- and post-calibration values. One firmware image shall therefore serve any window size and wire routing with no rebuild. | At a fixed window position, halving 40004 halves the reported opening ±1 LSB. All three survive a reset (FR-S39). Changing any of them re-asserts status bits 0/1 (FR-S33) until a fresh averaging span fills. |
| FR-E06 | Must | The firmware shall enforce **\|40006 − 40005\| ≥ 64** at all times — a constraint on the *distance* between the calibration points, not on their order, so a reversed mounting (FR-E04) calibrates as naturally as a normal one. Any FC06/FC16 write violating it shall be rejected with exception 03 and leave the register(s) unchanged (respecting FR-MB22 atomicity). This row is the single normative source of the constraint. It serves two purposes: it guarantees the FR-E04 divisor is never zero, and it rejects a degenerate calibration — two near-adjacent codes would satisfy "not equal" while making one LSB of ADC noise swing the entire reported travel. The same check shall be applied to values loaded from non-volatile storage; a stored pair that fails it shall be treated as a blank store and the §2.8 defaults used instead (FR-S21). | With 40005 = 0 and 40006 = 1023: FC06 write 40006 = 0 returns exception 03 and leaves 40006 at 1023; FC06 write 40006 = 63 likewise (span 63 < 64); FC06 write 40006 = 64 is accepted. An FC16 write setting 40005 = 900 and 40006 = 100 in one request is **accepted** — span 800, reversed but legal. An FC16 write setting 40005 = 200 and 40006 = 250 is rejected (span 50). A device whose stored record holds a degenerate pair boots on the §2.8 defaults and reports them over FC03. |
| FR-E07 | Must | A sensor fault — an **open** wiper, detected by toggling the internal pull resistor on PA2 between two conversions and comparing the readings: a connected wiper is a stiff source and shifts ~242 counts, a floating one follows the pull across the full ~1023 — shall cause 30001 to hold the last valid opening for up to 2 s; if the condition persists >2 s, registers 30001–30004 shall report 65535 (sensor fault, §2.7) and status bit 2 (FR-S33) shall be set until valid readings resume. Faulted samples shall be excluded from the averaging engine. | Disconnect the wiper at the connector: 65535 in 30001–30004 and status bit 2 within 3 s; recovery within 2 s of reconnection. A 10-minute full open/close cycle produces no false fault. **A SHORTED wiper is NOT detectable and this requirement does not claim it (narrowed 2026-09-01).** FR-E21's R11 sits between the field wiring and PA2, so a field short to either rail presents 10 kΩ to that rail — electrically identical to the wiper resting at the corresponding end stop. No pull test, and no measurement at this pin, can separate them. The consequence is worth stating plainly: **a wiper shorted to 0 V reports the window as fully closed.** Detecting it would need a cross-check against the end switches (an end-stop *position* with the corresponding switch inactive is inconsistent), which is not required here and is not implemented. |
| FR-E08 | Should | Input registers 30003 and 30004 shall report the minimum and maximum instantaneous opening observed within the current averaging window (rolling, same window semantics as 30002; exact or two-stage per FR-S31), giving the master the movement envelope without polling at window rate. | With the window held at 100.0 mm and one excursion to 800.0 mm lasting 3 s: within one measurement window 30004 reads 8000 ±2 LSB while 30002 stays below 3000; one full averaging window after the excursion ends, 30004 returns to 1000 ±2 LSB. |
| FR-E09 | Should | The raw ADC code for the last measurement window shall be available in input register 30005 for diagnostic purposes, before offset and scaling are applied (FR-E04). | With the window fully closed and fully open, 30005 reads the two calibration codes ±3 LSB. |
| FR-E10 | Should | Input register 30012 shall report the **signed** opening change between the last two completed measurement windows, expressed as 0.1 mm/s (i.e. scaled by the window duration) as a two's-complement 16-bit value: **positive while opening, negative while closing**, zero at rest. It shall be clamped to −32768…+32767 — ±3276.7 mm/s, orders of magnitude beyond any window actuator, so the clamp exists only to make the arithmetic total. | With the window driven at a controlled 50.0 mm/s for ≥3 windows, 30012 reads +500 ±5 % while opening and −500 ±5 % while closing, once two windows of the movement have completed; at rest it reads 0. A master interpreting the register as unsigned sees ≈65036 for the closing case, which is the same bit pattern. |

### 3.4 Potentiometer front-end

**New — draft.** The sensor is a draw-wire encoder whose drum turns a 10 kΩ
potentiometer; the wiper is read on PA2. This is the same front-end topology
the sibling project uses for its vane, and its driver is the reference
implementation.

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-E11 | Must | The raw code shall be obtained by reading the potentiometer wiper voltage on PA2 using the ADC in 10-bit ratiometric mode referenced to VDD. No external reference shall be used. | Via 30005: wiper at each mechanical end stop reads ≤5 and ≥1018 respectively. **PC4 shall be configured as an analog input with no pull-up or pull-down.** A pulled-up digital input sources ~63 µA into the §4.4 summing node from the MCU's own 47 kΩ, shifting every band and presenting exactly as sensor leakage — observed on the bench 2026-08-31 and diagnosed only after a full day. | Code review confirms PC4's mode and that no pull is enabled. On the bench, PC4 with both sensors disconnected reads ≤5 counts. |
| FR-E12 | Must | The ADC sample time shall be configured to **≥241 cycles**. The pot contributes 2.5 kΩ at mid-scale and FR-E21's protection adds 10 kΩ in series, so the DC source impedance is 12.5 kΩ — above the 10 kΩ the previous ≥71-cycle setting was chosen for. The C6 reservoir (§4.3) means the sample capacitor does not actually charge through that resistance, but the longer sample time costs nothing measurable (~42 µs per conversion against a ≥100 ms window) and removes the need to rely on the reservoir argument. | Code review confirms the sample-time setting. Via 30005: 32 consecutive reads at a fixed mid position span ≤3 counts, and the mid-scale code shifts ≤1 count when R11 is shorted out on the bench. |
| FR-E13 | Must | Each update of 30001 shall be derived from ≥16 ADC conversions (mean, or median with outlier rejection) at an update rate of ≥10 Hz. | Code review of the conversion scheme; the FR-E03 stability criterion (span ≤3 LSB over 100 reads) passes. |

### 3.5 End-of-travel switches

**New — draft. Mandatory.** Two end switches report that the window has
physically reached a stop. They are read as a **supervised resistor ladder
on PC4** (ADC channel 2, §4.4), which resolves not only "an end was reached"
but also whether the switch cable is intact — a distinction one digital
input cannot make, and one that matters for a sensor on a roof window.

The measured opening already indicates *which* end is near, so the ladder
spends its resolution on supervision rather than on telling the two switches
apart. That trade-off is a property of the topology, not a choice of
resistor values; the derivation is in `design/scratchBook.md`.

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-E20 | Should | Input register 30015 shall report the window opening as a percentage of the configured full travel, in units of 0.1 % (0–1000), derived from the *instantaneous* opening (30001) so that it tracks the same value a positioning loop reads. It shall be computed as `(30001 − 40001) × 1000 / 40004`, clamped to 1000, and shall carry the FR-E07 fault sentinel 65535 whenever 30001 does. | With the window at the calibrated closed point 30015 reads 0; at full travel it reads 1000; at the midpoint 500 ±1. Halving 40004 doubles the reported percentage for the same physical position. Disconnecting the wiper drives it to 65535 alongside 30001. |
| FR-E21 | Must | The wiper input shall survive a **sustained** short of any J4 field conductor to the +24 V rail, indefinitely and without damage, while keeping the current injected into PA2 within the CH32V003's **±4 mA** absolute maximum (datasheet §3.2). This is met by a **10 kΩ series element** (R11), which limits the fault to **2.4 mA** at 27.6 V — 24 V passive PoE at +15 % — with the MCU's own clamp conducting at ≈3.9 V. A **bidirectional TVS to GND** (D3, **PESD5V0S1BA**, SOD-323) and a **1 nF reservoir capacitor** (C6) sit on the protected side of R11. The clamp shall have a standoff of **≥5 V** and leak **≤100 nA at 3.3 V across the whole NFR-ENV01 range**; §4.6's ≥10 MΩ wiper-node rule applies here and is what disqualifies the obvious candidates (§4.6.1). **The standoff figure is not a rounding of 3.3 V:** the wiper swings to 3.3 V, so a 3.3 V-standoff part would sit at 100 % of its rated working voltage at full scale, which is exactly where leakage is largest and most temperature-dependent. A 5 V part is well below its knee across the whole measurement range. Note the resistor, not the TVS, is the current limiter: a TVS is a transient device and cannot hold a low-impedance 24 V short. | Apply +27.6 V to each J4 pin in turn for 60 s. The device reports status bit 2 (FR-E07) during, and after removal meets FR-E03 unchanged. Measure the mid-scale raw code with D3 fitted and unfitted at both NFR-ENV01 extremes: the difference shall be ≤1 count. |
| FR-E23 | Should | **The position path shall be shown to follow the carriage.** A *departure sequence* is a debounced end-switch classification (FR-E14/FR-E15) going **at-a-stop → not-at-a-stop → at-a-stop**, with the middle state persisting ≥ 2 × 40002. Across each departure sequence the firmware shall record the raw wiper code's total excursion (maximum − minimum). When **three consecutive** departure sequences each show an excursion below **16 counts**, status bit 7 (FR-S33) shall be set; it shall clear on the first sequence exceeding that threshold. The bit shall be reported and nothing more — it shall not suppress or alter 30001–30004, following FR-E16's precedent. This requires **no calibration**: it compares the wiper against itself, never against the endpoints. *Rationale for a count of sequences rather than a single event:* the sensor's 0.04–1.76 mm hysteresis is one to two ADC counts, so a legitimate micro-crossing of a switch threshold and a frozen wiper are indistinguishable in any single sequence. Three consecutive are not. This detects what no electrical test can — a tangled, snapped, seized or slipping draw-wire, where the potentiometer is electrically perfect and reports a stable, plausible constant. | With the draw-wire detached from the carriage, drive the window through three full traverses: bit 7 sets. Re-attach and traverse once: bit 7 clears. A window rocking at a stop, crossing the switch threshold repeatedly with the wire attached, never sets it. |
| FR-E24 | Should | **An implausible raw code shall be reported.** A raw wiper code outside `[40005 − M, 40006 + M]`, where **M = 25 % of |40006 − 40005|**, persisting ≥ 2 × 40002, shall set status bit 6 (FR-S33). The margin exists because the window legitimately travels beyond both end sensors (§4.4, `description.md` §8.1). The bit shall be reported and nothing more. **The check is self-disabling and requires no configuration flag:** where the calibrated span approaches the full ADC range — as on the factory default 0/1023, and as on a draw-wire sized so its ends coincide with the window's — the band covers every reachable code and the bit never sets. **Its sensitivity is therefore a property of the installation, not of the firmware.** `description.md` §8.1 requires the draw-wire to leave ≥10 % of its electrical range unused at each end; where that is followed, a signal conductor broken or shorted to either rail produces a code the window cannot legitimately reach, and this reports it. Where it is not followed, a shorted conductor produces exactly the reading of a correctly closed window and nothing can distinguish them. | Write 40005/40006 to a deliberately narrow sub-range of the observed travel, then drive the window beyond it: bit 6 sets after ≥2 windows and clears on return. On the factory default calibration the bit never sets, whatever the window does. |
| FR-E14 | Must | The firmware shall sample the end-switch divider on PC4 (ADC channel 2) at ≥10 Hz and classify each reading into exactly one of the three states of the §4.4.3 band table: neither active, one sensor active, both active. Status bit 3 (FR-S33) shall be set while the classification is "one sensor active". **Inverted 2026-08-29 with the PNP sensor:** *neither active* is now the **lowest** band and *both active* the highest, so there are **three** states, not four. Zero counts is a healthy reading. Status bit 3 shall be set while the classification is "one sensor active". | At each of the three nominal divider values the classification matches the table and status bit 3 follows. Disconnecting one sensor cable reads ~0 counts and classifies as *neither active* — the known limit (§4.4.5), not a defect. |
| FR-E15 | Must | The classified switch state shall be debounced in firmware: a change shall be published only after the new state has been observed continuously for ≥20 ms. Sampling and debouncing shall never gate, delay or suppress the FR-MB20 response timing, the measurement path, or the FR-S20 watchdog feed. | Inject a 5 ms bounce burst: bit 3 changes exactly once, with no intermediate toggling visible to a master polling at 50 ms. The FR-MB21 latency histogram matches one taken with the switch input idle, within 2 ms. |
| FR-E16 | Must | Status bit 4 (FR-S33) shall be set while the classification is "both active" or "cable fault" — the states that cannot occur on a healthy installation — and cleared otherwise. **Scope, narrowed again 2026-08-29 with the PNP sensor:** bit 4 now covers **both switches active at once, and nothing else.** A PNP normally-open output sources nothing when inactive, when its cable is open, and when its signal is shorted to 0 V, so all three read ~0 counts and are indistinguishable (§4.4.5). The device cannot detect an open or shorted sensor cable and must not be documented as if it can. A switch-loop fault shall be reported only; it shall never suppress, hold or alter the reported opening (30001–30004), which comes from an independent front-end. | Operate both switches at once: bit 4 sets within 200 ms, and 30001 continues to track the window unchanged. Restore: bit 4 clears within 200 ms. **Two negative tests, both confirming documented limits rather than contradicting them:** disconnect one sensor cable — bit 4 stays clear, bit 3 stays clear, and the device reports no stop; short the switch input to 0 V — the same. |
| FR-E18 | Should | On every debounced transition into "one sensor active" (FR-E14), the firmware shall capture the current raw wiper code and publish it to **30013** if that stop is the closed end or **30014** if it is the open end, deciding which by the **direction of the last movement** (FR-E10): a window
that was opening has reached the open end, one that was closing has reached the
closed end. Where no direction is known — no movement since reset — it shall
fall back to whichever of 40005/40006 the captured code lies nearer. Both registers shall read 0 until their first such event since reset. This is a diagnostic only: it shall never alter the calibration of its own accord. | Drive the window to each stop in turn with a known calibration: 30013 and 30014 each read the raw code observed at that stop, within the FR-E03 stability tolerance. Deliberately shift the sensor mounting by a known amount and repeat: the affected register moves by the corresponding number of counts while 40005/40006 are unchanged. Both read 0 after a reset until a stop is next reached. |
| FR-E19 | Should | The firmware shall support a **commanded teach** of the calibration endpoints, sequenced as follows. (a) A write of 1 to holding register **40007** arms teach: status bit 5 (FR-S33) is set and any previously captured endpoints are discarded. (b) While armed, each stop reached per FR-E18 captures its endpoint as before. (c) When **both** endpoints have been captured since arming **and** the master has read **both** 30013 and 30014, the firmware shall commit them to 40005 and 40006, persist them (FR-S39), clear status bit 5 and reset 40007 to 0. (d) A write of 0 to 40007 aborts at any point, discarding captures and leaving 40005/40006 untouched. The commit shall be refused — leaving teach armed and the captures visible — if the pair would violate FR-E06, so a degenerate teach cannot be committed. 40007 shall not persist across reset (FR-S39). | Arm teach; bit 5 sets. Drive to one stop: bit 5 stays set. Drive to the other: bit 5 still set until both 30013 and 30014 have been read, then clears within one measurement window, with 40005/40006 equal to the captured pair and surviving a subsequent reset. Arm, reach one stop only, then write 40007 = 0: bit 5 clears and 40005/40006 are unchanged. Arm and teach two codes closer than the FR-E06 minimum span: no commit occurs, bit 5 remains set, and the captures stay readable. Arm, then reset the device: bit 5 is clear and 40007 reads 0. |

### 3.6 Clock and timing

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S16 | Must | The firmware shall operate from the CH32V003 internal 48 MHz RC oscillator (HSI). No external crystal is required. | With no external crystal fitted: 10,000 Modbus request/response cycles at 9600 baud complete with zero framing/CRC errors, and the FR-S17 room-temperature window-timing criterion passes. |
| FR-S17 | Must | The measurement window timing error shall not exceed ±2% relative to the configured window duration at 25 ±10 °C, and ±3% over the full NFR-ENV01 temperature range (HSI drift dominates outside room temperature). | Window measured with an external timer: error ≤ ±2% over 10 consecutive windows at room temperature; ≤ ±3% at the NFR-ENV01 chamber extremes. |

### 3.7 Diagnostics and identification

*(Inherited; register numbers retargeted to §2.7.)*

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S32 | Must | Input register 30007 shall identify the device: high byte = build type, fixed at compile time, independent of PC4; low byte = firmware version, incremented per release. The build type shall be **0x01 for the release image** and **0x81 for any bench build carrying the FR-S20 test hooks** — the high bit means *not for release*. A master shall be able to tell the two apart from this register alone. | FC04 read returns 0x01vv on a release binary and 0x81vv on a `encoder_test` binary. The value is identical with jumper open/bridged. The version byte matches the release records for the flashed binary. |
| FR-S33 | Must | Input register 30006 shall report status flags — this row is the single normative bitfield definition: bit 0 = no completed measurement window since reset or since the last 40002 write (FR-S23/FR-S30); bit 1 = averaging accumulator not yet filled since reset or since the last 40002/40003/40004/40005/40006 write (FR-S23/FR-S30/FR-E05); bit 2 = wiper fault (FR-E07); bit 3 = end of travel reached (FR-E14); bit 4 = end-switch loop fault (FR-E16); bit 5 = teach in progress (FR-E19); **bit 6 = implausible raw code (FR-E24); bit 7 = position path not following the carriage (FR-E23)**; bits 8–15 = 0. Bits 2 and 4 report two independent front-ends and may be set in any combination. **Bits 6 and 7 are health indications, not alarms**: they report the credibility of the position signal and are deliberately slow (FR-E23 needs three movements before it speaks). Their combination is diagnostic — bit 7 alone indicates the mechanism, bit 6 alone a signal out of range, both together a dead position path. | At power-on bits 0 and 1 are set; bit 0 clears after the first window, bit 1 after one full averaging window; both re-assert after a 40002 write per FR-S30's criterion. Disconnecting the wiper sets bit 2 (FR-E07) and leaves bit 4 clear. Operating both end switches at once sets bit 4 (FR-E16) and leaves bit 2 clear; disconnecting a sensor cable, or shorting the switch input to 0 V, sets neither bit 3 nor bit 4 — the FR-E16 limit. |
| FR-S34 | Must | Input register 30008 shall report whole seconds since the last reset, starting at 0 and saturating at 65535, allowing the master to detect restarts (value went backwards). | A read shortly after power-on returns a low value; a later read has incremented consistently with FR-S17 timing accuracy; a watchdog reset via the test hook returns the register to 0. |
| FR-S35 | Should | Input registers 30009 and 30010 shall count, respectively, every frame discarded for invalid CRC-16 (regardless of address) and every request for which a normal or exception response was transmitted. Both reset to 0 at power-on and wrap at 65535. | After a power cycle both read 0. 100 valid FC04 requests increment 30010 by exactly 100 and leave 30009 unchanged. 20 corrupted-CRC frames increment 30009 by exactly 20 and 30010 by 0. |
| FR-S36 | Should | Input register 30011 shall report elapsed whole seconds since the last *valid* sensor reading — initialised to 0 at reset and counting up until the first valid reading — clamped at 65535 and reset to 0 on each valid reading. It is the plausibility-check companion to the FR-E07 fault flag: a rising 30011 with status bit 2 clear means readings have stopped arriving without the fault detector having tripped yet. | Disconnect the sensor: the register increments 1/s (±2%). Reconnect: the next read returns ≤1. |

---

## 4. Hardware

**Open — no schematic exists yet.** This section is to be written from the
KiCad design once it exists, as §4 of the sibling TDS was: architecture,
normative MCU pin assignment, RS-485 interface, power supply, sensor
front-end, connectors and as-built deviations. Until then the following is
the **assumed baseline**, inherited from the sibling board (which this design
reuses apart from the sensor front-end) and used by the firmware already
written.

### 4.1 Assumed architecture

A CH32V003J4M6 drives a MAX3485 RS-485 transceiver. Power is 24 V passive PoE
on the Ethernet spare pairs → a DB207 polarity-protection bridge → an
HLK-K7803-500R3 3.3 V regulator. The bus is brought out on two RJ45 jacks for
daisy-chaining; the draw-wire sensor connects on its own jack; a 3-pin header
exposes SWIO for the WCH-LinkE programmer. Termination, RS-485 pair selection
and address selection are solder jumpers. Datasheets for all of it are in
`hardware/Documentation/`.

### 4.2 MCU pin assignment (normative for the firmware)

The J4M6 is the SOP-8 package. It has **eight pins, two of which are power**,
and — critically — **several GPIO share one physical pin**: pin 1 carries both
PD6 and PA1, and pin 8 carries PD1, PD4 and PD5. There are therefore **six
physical I/O pins, not the seven a port-name list suggests**. Any front-end
proposal has to be checked against this table, not against the list of port
names the part datasheet mentions.

| Pin | Port(s) on the pin | Capability | Function here | Firmware |
|-----|--------------------|------------|---------------|----------|
| 1 | PD6 (= PA1) | USART | Modbus data — USART1 RX native, TX remapped in for the response; to MAX3485 RO+DI | FR-MB23, FR-S19 |
| 2 | VSS | — | Ground | — |
| 3 | PA2 | **ADC ch0** | Potentiometer wiper — ratiometric | FR-E11/E12/E13 |
| 4 | VDD | — | +3.3 V supply | — |
| 5 | PC1 | digital, 5 V tolerant | Address-select jumper — 10 k pull-up + jumper to GND | FR-S03 |
| 6 | PC2 | digital, 5 V tolerant | RS-485 driver enable (DE/RE) — to MAX3485; 10 k pull-down | FR-MB04, FR-S18 |
| 7 | PC4 | **ADC ch2** | End-of-travel switches — two outputs summed on-board, §4.4 | FR-E14/E15/E16 |
| 8 | PD1 (= PD4/PD5) | SWIO | Single-wire debug/flash — reserved, not used for I/O | — |

**Every pin is committed; there is no spare.**

The assignment of PC1 and PC4 is deliberate and is the reverse of the obvious
one. **PC4 carries an ADC channel and PC1 does not.** The address jumper is a
board-local solder blob read once at boot — a one-bit question that does not
need an ADC. The end-switch loop runs to the far end of a cable on a moving
window and has more than one bit's worth to say, so it takes the analog pin
(§4.4). Swapping them back would cost the supervision for nothing.

Consequence: the ADC is multiplexed between channel 0 (wiper) and channel 2
(switch ladder). Both sit behind the same ≥241-cycle sample time — the
ladder's source impedance with a switch closed is ≤5 kΩ, comfortably
inside the 12.5 kΩ that setting is sized for (FR-E12).

The only thing given up is PC1's 5 V tolerance on the switch loop; the §4.4
ladder is fed from the board's own 3.3 V pull-up and never needed it.

### 4.3 Wiper front-end (protected, 2026-08-07)

The draw-wire encoder's 10 kΩ potentiometer is fed ratiometrically from the
3.3 V rail. The ADC is 10-bit ratiometric to VDD with no external reference
(FR-E11), with a ≥241-cycle sample time (FR-E12).

```
   3V3 ──── J4.1
                            protected side
   J4.2 ──[ R11 10k ]──┬────────┬───────────► PA2 (ADC ch0)
        wiper           │        │
                     [ C6 1n ] [ D3 TVS ]
                        │        │
   0 V ──── J4.3        └────────┴─────────── GND
```

Until 2026-08-07 the wiper ran **bare** from the terminal block to PA2 — no
series element, no clamp — while the switch input two pins away had all three.
That asymmetry was inherited from the sibling board, whose `ANALOG_IN` also
went straight from the RJ14 to the MCU, and it had been sitting in §6 as
"wiper ESD protection" since the first draft. FR-E21 closes it.

- **R11 10 kΩ is the current limiter, not the TVS.** A TVS is a transient
  device; it cannot hold a low-impedance 24 V short, and a miswired terminal
  is not a transient. 10 kΩ holds a 27.6 V fault to 2.4 mA against the
  CH32V003's ±4 mA injected-pin maximum — the same ≈2 mA design point §4.4.2
  already chose for the switch input.
- **C6 1 nF is what makes a 10 kΩ series resistor affordable.** The ADC's
  sample capacitor charges from the reservoir rather than through the
  resistor, which only has to recharge 1 nF between conversions: 12.5 µs
  against a ≥100 ms window. It is also sized *small* on purpose — FR-E07
  detects an open wiper by toggling the internal pull resistor between
  conversions, and that pull is tens of kΩ, so 1 nF settles in ~40 µs where
  100 nF would take 4 ms and start eating the measurement cadence.
- **D3 covers what the RC cannot** — fast ESD arriving on a cable that runs
  to a moving frame. Its leakage specification is the hard part; see §4.6.

No RC *filter* is fitted in the signal sense, and the reason usually given —
"ratiometric operation cancels rail ripple, so an external reference would
break the cancellation" — argues against a **reference**, not against a series
resistor or a clamp. Neither of those breaks ratiometric behaviour. The
sibling board's decision not to filter was about bandwidth; it was never an
argument for leaving the pin unprotected.

### 4.4 End-switch interface — summing divider (PNP, 2026-08-29)

**Sensor: 3RG4023-3AB00** inductive proximity switch, Pepperl+Fuchs
(`documentation/6561.pdf`). As specified:

| Parameter | Value |
|---|---|
| Output | **3-wire DC PNP, normally open** |
| Supply | 10–65 V DC, 24 V rated; no-load current 10 mA |
| Rated output current | 300 mA; short-circuit and overload protection built in |
| **Output voltage drop** | **≤2.5 V** — *specified at 300 mA*; see §4.4.4 |
| **Off-state current** | **0.01 mA** — sets the floor of the *normal* band |
| Sensing | 8 mm rated, 7.2–8.8 mm effective, 6.48 mm assured |
| Hysteresis | **0.04 … 1.76 mm** |
| Target | Mild steel St 37, 24 × 24 × 1 mm reference |
| Repeatability | 0.2 mm |
| Response | 300 Hz; 40 ms ready-delay from power-up |
| Protection | Reverse voltage, wire breakage, inductive overvoltage, switch-on pulse suppression — all built in |
| Ambient | **−25 … +85 °C** — no longer sets NFR-ENV01's ceiling |
| Ingress | IP67 |
| Body | M18 brass, non-embeddable, switching-state LED |
| Termination | **M12 connector**: pin 1 = L+, pin 3 = L−, pin 4 = output |

> ⚠️ **-3AB00 is NO; -3AA00 is NC.** The same datasheet covers both, and they
> are one character apart in the order code. Fitting an NC part to this network
> inverts every band in §4.4.3 without any other visible symptom — *normal*
> would read as *both active*. Check the label on the sensor, not the box.

#### 4.4.1 Why the polarity change rewrites this section

The previous sensor (LJ18A3-8-Z/BX) was **NPN** with an internal 10 kΩ pull-up,
so an inactive sensor sat *high* and an operated one pulled *low*. This one is
**PNP**: the output transistor sources from +V, so an inactive sensor is *open*
and an operated one drives *high*. Every level in this section is therefore
inverted relative to every previous revision, and so are the firmware
thresholds.

Two consequences follow immediately, and neither is cosmetic:

- **The board must supply the pull-down.** A PNP output needs a load to 0 V to
  define its inactive state; there is no internal element doing it. The
  existing 10 k + 4k7 attenuator already is that load, which is why no new part
  is needed for it.
- **The 470 k pull-up (R10) must come out.** It was there to hold *both active*
  off the floor when the NPN outputs pulled down. Against a PNP output it does
  nothing but inject a constant offset into a network that now needs a
  pull-down.

The lesson from the LJ18A3 stands and is worth restating: **read the output
structure in the datasheet, not the part description.** That sensor's internal
pull-up was the difference between a working divider and 14 V on a 3.3 V pin,
and it appeared on page 2 of a document nobody would have opened if the words
"open collector" had been believed.

#### 4.4.2 The network

The installation is a **star**: the PCB is the hub, and the draw-wire and each
end switch run their own cable back to it. There is no field junction, so
summing happens on the board.

```
   +24V ──────────────────────────────────────────► +V to both sensors
                                         |
   OUT A ─[ 68k ]─┐                      |   star: three separate runs
                  ├── sum ──[ 10k ]──┬───┼──── PC4 (ADC ch2)
   OUT B ─[ 68k ]─┘                  │   |
                                  [ 4k7 ]    ── end switch A  (own cable)
   0 V ────────────────────────────────┴───    ── end switch B  (own cable)
                                        │
                                   clamp to 3V3 + GND
```

- **68 k per sensor output (R8, R9).** Sized in §4.4.4: large enough that
  *both active* does not clip at +15 % supply, small enough that the 10 µA
  off-state leakage stays well clear of the *one active* band.
- **10 k series + 4k7 to ground (R6, R5).** Unchanged. They attenuate by 0.32,
  provide the pull-down the PNP outputs need, and limit the clamp current to
  ≈2 mA if a sensor output is ever shorted straight onto the summing node.
- **No pull-up.** R10 is deleted.
- **A clamp to 3V3 and GND (D2)** is not optional. It is the only thing
  standing between a field wiring error and a dead MCU.

Load current at 24 V is **290 µA** — three orders below the sensor's 300 mA
rating, which is the basis for the drop argument in §4.4.4.

#### 4.4.3 Bands — MEASURED 2026-08-31

Measured at `Von` = 23.09 V against a 24.1 V rail. `Von` is confirmed by
**three independent routes agreeing to 0.2 %** — each switch alone, and both
together, which carries no leakage term at all:

| State | PC4 measured | Counts | Status (FR-S33) |
|---|---|---|---|
| Neither active — between the stops | **−0.019 V** | **0** | — |
| One sensor active — at a stop | **1.291 V** | **401** | bit 3 |
| Both active — wiring or mounting fault | **2.210 V** | **686** | bit 4 |

Decision thresholds: **<170** neither, **≥170** one active, **≥522** both
active.

> **This is the fourth set taken today and the only trustworthy one.** The
> earlier three were measured on a bench that variously had **R10 fitted**,
> **R5 floating**, another wiring error, and — the one that survived all the
> rig fixes — **the MCU's internal pull-up on PC4**. Each set produced a
> plausible fit. All three are discarded. The rig check (TP-A00 in
> [`testPlan.md`](testPlan.md)) is what eventually caught them.

**The ordering is inverted** relative to any revision before 2026-08-29: with
a PNP output, *normal is the lowest reading* and a fault the highest.

#### 4.4.4 What the bench measurement established

**The sensors do not leak.** Connecting or disconnecting both of them moves
PC4 by **0.9 mV** — below the noise floor, and far inside the 10 µA the
datasheet allows. Every "off-state leakage" figure this document previously
carried (35 µA, then 33 µA) was **the MCU's own internal pull-up on PC4**:
about 47 kΩ to 3V3, sourcing ~63 µA into the summing node, enabled by whatever
image was in flash. It disappeared the moment the current firmware was
programmed, because that build never configures PC4 and the reset default is a
floating input.

Two things follow, and the second is a design constraint rather than a
measurement.

- The leakage-versus-temperature question that gated the PCB **dissolves.**
  There is no leakage for temperature to act on, so TP-A01 is not needed.
- **PC4 must be an analog input with no pull.** If `we_init()` ever leaves it
  as a pulled-up digital input the 63 µA returns, every band shifts, and it
  presents exactly as sensor leakage — which is what cost a full bench day.
  Now explicit in FR-E11.

**There is an output drop after all: 1.01 V at 290 µA.** An earlier revision
of this section claimed it was zero, fitted to data taken while the pull-up was
fighting the divider. The datasheet's ≤2.5 V is specified at 300 mA and does
not scale down to nothing at microamps — which is unsurprising for a protected
industrial output stage, and is why `Von` is 23.09 V rather than the rail's
24.1 V.

**A constant −19 mV** sits at PC4 with the sensors disconnected, roughly 4 µA
sunk board-side. It is 6 counts, does not vary with state, and correcting for
it tightens the `Von` agreement from 0.8 % to 0.2 % — which is the evidence
that it is real and constant rather than noise. Unexplained; too small to
matter, large enough to write down.

**Margins across ±15 % supply:**

| | worst low | worst high |
|---|---|---|
| Neither active | 0 | **0** |
| One active | **340** | **462** |
| Both active | **582** | 790 |

That is **170/170** counts either side of `SW_TH_ONE` and **60/60** either
side of `SW_TH_BOTH` — comfortably better than the 38/39 the leakage-corrupted
fit predicted, because with no leakage there is neither a floor to lift nor an
offset added to *one active*. 68 kΩ remains a good choice; nothing needs
re-sizing.

#### 4.4.5 Which switch is active — and why the device does not say

It cannot, by construction: both sensors sum through identical 68 kΩ resistors
onto one node, so the two one-active states are the same state electrically.
The bench confirms it — OPEN 1.505 V against CLOSE 1.498 V, **7 mV apart, two
counts**, which is component tolerance rather than information and will differ
per unit and drift with temperature.

This is intentional, but the reason has changed and the earlier one is no
longer sound. `design/scratchBook.md` argued that a two-switch ladder can
resolve *which* switch **or** *both closed* but not both, as a property of the
topology. **That was true of the NPN arrangement and is not true of this one.**
With a PNP output sourcing through its summing resistor the arithmetic
differs, and asymmetric resistors *can* separate four states: scanning E24
against the measured bands finds 202 workable pairs at ±15 % supply, the best
being 75 k / 110 k at 102 / 326 / 434 / 591 counts.

It remains the wrong choice, for a measurable reason rather than an
impossibility. That arrangement leaves **7 counts** at its tightest point
where the symmetric pair leaves **38**, and 7 is inside the noise — FR-E12
allows ±3 counts of ADC spread at a fixed input, and 1 % resistors alone
consume about 6 of the 7. Nothing would remain for temperature, still less for
the leakage question above.

The sound argument is simpler: **the position registers already resolve which
end, far more robustly than the switch path could.** A stop reported at 3 % of
travel is the closed end and one at 97 % is the open end, separated by most of
the ADC range instead of by 7 counts. FR-E18 attributes an end-stop capture
exactly this way. So the switch path spends its resolution on the one thing
position cannot report — both switches active at once.

#### 4.4.6 What is given up

**There is no fault band at all.** This is the significant loss and it is
inherent to a PNP normally-open output. *Inactive*, *cable open* and *signal
shorted to 0 V* all read the same ~0 counts, because "no current being
sourced" is what all three look like. Status bit 4 and FR-E16 now cover
**both active** and nothing else.

Note this inverts the *direction* of the undetected failure rather than
removing it. Under the NPN part an open cable read 337 counts and reported a
**false stop**; under this one it reads ~0 and reports a **missed stop**. The
controller consequences differ — a false stop makes a master believe the window
reached its limit, a missed stop makes it believe the window never did — but
neither is detected, and no wording in this document should imply otherwise.

**The measurement is not ratiometric.** The bands derive from the 24 V supply,
not from the 3.3 V ADC reference, so supply variation moves them instead of
cancelling. §4.4.4 shows the margins absorb ±15 %, but this remains a genuine
regression against the wiper path, where the ratiometric trick makes supply
drift disappear entirely. Do not narrow the bands later on the assumption they
are stable.

**Losing the +V conductor is undetected**, as before — the sensor goes quiet,
which is indistinguishable from inactive.

#### 4.4.7 What the change buys

Three things, and the first is worth more than the fault band that was lost.

**The temperature ceiling is released.** The LJ18A3's +65 °C limit was
NFR-ENV01's ceiling and the single requirement this design knowingly failed
against the greenhouse study (NF-WP03 asks +70 °C). At **+85 °C** this sensor
stops being the constraint, the limit reverts to the electronics, and that gap
closes. See `requirementsCompliance.md`.

**Protection that was previously ours to provide.** Reverse voltage, wire
breakage, inductive overvoltage, short-circuit and overload are all built in,
and switch-on pulse suppression removes a class of false trigger at power-up
that the 40 ms ready-delay would otherwise have exposed.

**No internal pull-up to be surprised by**, and an **M12 connector** instead of
a 1.1 m flying lead — so the field joint that §6 required to be sealed to the
enclosure's standard becomes a cordset, and stops being a workmanship item.

### 4.5 Enclosure and field wiring (decided 2026-07-28)

The device is installed **inside a greenhouse**, in an environment that is
condensing on most nights and warm in summer, but **not** in direct UV and
not rain-wetted. The enclosure strategy follows from that:

| Decision | Consequence |
|---|---|
| **IP65 enclosure** — **Kopp 99966478**, 110 × 110 × 40 mm, 6 entries, 3 × M20 glands supplied (`hardware/Documentation/`) | Everything electrical is inside it. Ingress protection is a property of the box and its glands, not of the connectors. This box sets NFR-ENV03's figure |
| **All connectors are internal** | The RJ45 bus connectors sit *inside* the enclosure. They are ordinary connectors in a sealed box, not exposed ones, so their own (non-)rating does not matter |
| **Waterproof cable glands** | Field cables enter through glands; the gland is the seal. **The star costs an entry:** bus in, bus out, draw-wire, end switch A, end switch B and the vent plug is **six — every entry the Kopp box has, with none spare.** Count them before ordering |
| **Pressure-equalisation vent plug** | A hydrophobic membrane vent, IP-rated in its own right. Air passes; liquid water does not |
| **Terminal blocks inside** for the draw-wire and the end switches | Field-wireable without special tooling; the installer strips and screws rather than crimping a connector in situ |
| **Mounted out of direct UV** | Removes the UV exposure question from the enclosure material |

**Why the vent plug matters more than it looks.** A fully sealed box in a
greenhouse is worse than it sounds. Its internal air cools at night, the
pressure drops, and the box draws replacement air in through whatever path
leaks first — normally a gland or the lid gasket, bringing liquid water and
dirt with it. Repeated every night, that pumping is the mechanism that
actually kills sealed enclosures: the seal does not fail so much as get used
as a valve. A hydrophobic vent gives the pressure somewhere legitimate to
equalise, so the seals stop being the breathing path, and it lets the box dry
out again during the day when the interior is the warmer, higher-vapour-
pressure side.

**What the vent does not do** is keep the interior dry. It equalises with
greenhouse air, which is above 85 % RH most nights, so the inside sits near
saturation and can still condense on the coldest surface when the box
radiates heat away faster than the air cools. The vent converts a bulk-water
problem into a film-of-moisture problem — a large improvement, not a cure.

That residual matters here for a specific and slightly non-obvious reason —
see §4.6.

Two BOM notes:

- **Gland sizes are a BOM item, not an afterthought.** Each cable entry needs
  a gland matched to the actual cable diameter to achieve the rated seal. An
  oversized gland on a thin cable is an open hole with a nut on it.
- **Count the entries.** The selected box has six and ships with three glands.
  The installation needs five: bus in, bus out (the daisy chain needs both),
  draw-wire sensor, end-switch loop, and the vent plug. So two further glands
  and the vent are still to buy — and the vent consuming an entry is easy to
  miss when a box is chosen by cable count alone.
- **The vent has an IP rating of its own**, and it must be at least the
  enclosure's. Mount it where water cannot pool on the membrane, and make
  sure nothing in the installation blocks it.

### 4.6 Surface leakage on the wiper node — why coating is specified

With the vent plug fitted, the surviving risk is not corrosion over decades.
It is a **measurement error next week.**

The potentiometer wiper on PA2 is a high-impedance node: a 10 kΩ element at
mid-scale presents a Thévenin source of 2.5 kΩ. Any leakage path across the
board from that node to a rail forms a divider with it. Condensate in a
greenhouse is not clean water — it carries fertiliser aerosols and ammonia,
so the films that form are ionic and conductive:

| Surface leakage, wiper node to a rail | Resulting error (% of full scale) |
|---|---|
| 100 kΩ | **1.22 %** — blows the whole system accuracy budget |
| 1 MΩ | 0.13 % — inside a ±1 % system budget, outside the FR-E03 firmware budget |
| 10 MΩ | 0.012 % — negligible |
| 100 MΩ | 0.001 % |

Clean dry FR4 measures in gigohms; a contaminated moisture film across a few
millimetres can easily reach the 100 kΩ–10 MΩ range. **The requirement is
therefore that surface leakage from the wiper node stay above ~10 MΩ**, which
is what NFR-ENV02's coating clause exists to guarantee.

Worth stating plainly, because it inverts the usual intuition: conformal
coating on this board is not a longevity nicety. It is part of the accuracy
budget. A damp uncoated board would fail FR-E03 quietly — plausible readings,
no fault flag, nothing visibly wrong.

#### 4.6.1 The same rule governs the clamp part (FR-E21)

The table above is usually read as being about *moisture*. It is really about
**any** current path off the wiper node, and that makes it a component
selection rule as well as a cleanliness one. D3 sits directly on that node, so
its reverse leakage lands in the same column — and this disqualifies both
obvious candidates:

| Candidate | Leakage on a 2.5 kΩ node | Verdict |
|---|---|---|
| **BZX84-C3V3** — the clamp already used on PC4 | µA-scale well below breakdown, and **voltage-dependent** | ≈12 mV, ~4 counts, and **non-linear** — calibration cannot remove it |
| **BAT54S** — the reflex ADC clamp | ~2 µA at 25 °C, roughly doubling per 10 °C → ≈32 µA at +65 °C | ≈80 mV, **25 counts, 2.4 % of full scale** against a sensor specified at 0.2 % |
| **PESD5V0S1BA** — 5 V standoff, bidirectional, SOD-323 (selected) | ≤100 nA required across the NFR-ENV01 range | ≤0.25 mV, <0.1 count — acceptable |

The trap is that PC4 and PA2 sit at comparable impedance — 4.35 kΩ and 2.5 kΩ
— so the PC4 clamp *looks* transferable. It is not, and the difference is not
impedance but what is being measured: PC4 resolves four bands with 45 counts
of margin, PA2 is the 10-bit measurement the product exists to make. A part
that is invisible on one is disqualifying on the other.

**D3's part number is therefore a specification, not a preference**, and it is
the one line of the BOM chosen against a datasheet leakage figure rather than a
package and a voltage. Selected: **PESD5V0S1BA**, 5 V standoff, bidirectional,
SOD-323 — with the leakage still to be confirmed on the bench, because most
datasheets quote reverse current only at `V_RWM` and 25 °C, which says little
about 3.3 V at +70 °C. FR-E21's verification is exactly that measurement.

---

## 5. Non-functional requirements

*(Inherited — same MCU, same ceilings.)*

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| NFR-ENV01 | Must | All §2 and §3 requirements shall be met over an ambient temperature range of **−25 °C to +70 °C** (**raised 2026-08-29**). The ceiling was previously +65 °C, set by the LJ18A3-8-Z/BX end switch. The **3RG4023-3AB00** that replaces it is rated **−25…+85 °C** (§4.4) and is no longer the narrowest part, so the limit reverts to the electronics — which the sibling project's part set carries to +70 °C. This meets the greenhouse study's NF-WP03 in full; see `requirementsCompliance.md`. The low end is now set by the sensor at −25 °C, comfortably below the −20 °C asked. | In a climate chamber at both extremes: (a) 10,000 FC04 cycles at 9600 8N1 complete with zero framing/CRC errors; (b) the FR-S17 window measurement passes at its full-range tolerance; (c) the §4.4 switch bands decode correctly at both extremes, since the sensor's saturation voltage is itself temperature-dependent. |
| NFR-ENV02 | Must | The device shall operate in a **condensing** environment, up to 100 % relative humidity. Two measures are required and neither substitutes for the other: (a) a **pressure-equalisation vent** so the enclosure does not pump moist air and liquid water in through its seals as it cools (§4.5); (b) protection of the assembled board against the moisture films that will still form — conformal coating or an equivalent documented on the BOM — such that **surface leakage from the wiper node to any rail stays above 10 MΩ** under condensing conditions (§4.6). | Cycle the device through a condensing night in the installed enclosure — a temperature swing carrying the internal air below its dew point — while polling continuously: zero read failures, and the reported opening at a fixed sensor position moves by no more than the FR-E03 tolerance. Measure wiper-node-to-rail insulation resistance immediately after the cold soak, with condensate present: ≥10 MΩ. Inspect the glands and the vent for water ingress. |
| NFR-ENV03 | Must | The enclosure shall be rated at least **IP65**, with every field cable entering through a gland sized to that cable and every connector and termination inside the enclosure (§4.5). The figure is set by the selected **Kopp 99966478** box (`hardware/Documentation/`), which is IP65; the electronics themselves impose no such limit. IP65 — protection against water jets — is the level the greenhouse study asks of hardware not mounted at the aperture, and this box holds only the electronics. | Inspection against the enclosure and gland datasheets; a spray test per the IP65 definition on a fully assembled and glanded unit, including the vent plug. |
| NFR-ENV04 | Should | The device shall be mounted out of direct UV exposure (§4.5). Where that cannot be guaranteed for a given installation, the enclosure material shall be UV-stabilised. | Installation inspection. Where the mounting position is exposed, the enclosure datasheet shall state UV stabilisation. |
| NFR-ENV05 | Must | The device shall tolerate the vibration and end-stop shock of the window actuator without loss of calibration or mechanical drift of the sensor mounting. | After 100 full open/close cycles of the installed mechanism, the reported opening at both end stops is unchanged within FR-E03 tolerance, and the persisted calibration registers read back identical values. |
| NFR-RES01 | Should | The release build shall occupy no more than 14,336 bytes of flash (87.5% of 16 KB); static RAM (.data + .bss) plus documented worst-case stack shall not exceed 1,792 bytes (87.5% of 2 KB). | The linker map of the release build shows totals at or below the ceilings; the build fails when exceeded (`board_upload.maximum_size` / `maximum_ram_size`). |
| NFR-BLD01 | Should | The firmware shall build from a clean checkout with a single documented command using a pinned toolchain (compiler name and exact version recorded in the repository). Two consecutive clean builds of the same commit shall produce bit-identical binaries. | Run the documented command twice from fresh clones of the same commit: SHA-256 of the two binaries are identical; the recorded toolchain version matches the installed one. |
| NFR-TST01 | Should | Every protocol-level pass/fail criterion in §2 that is executable over the serial link shall be implemented as an automated test case in the acceptance suite, and the build shall pass 100% of these cases before any release is tagged. Excepted (verified manually per release with bench instruments): FR-MB01 (analyser decode), FR-MB04 (scope timing), FR-MB23 (bus capture), FR-MB07 (the address latch needs a power cycle; added 2026-09-01 — the *no-address-register* half of FR-MB07 IS link-testable and is covered by TP-B13/TP-B27, but *latched at startup* cannot be shown without a reset). | The suite's run report for the release commit lists every non-excepted, active FR-MB ID with result PASS; any FAIL or missing ID blocks the release. |

---

## 6. Open items

Everything here is genuinely undecided. Items are removed (or kept with a
"resolved" note for traceability) as they close.

- **Sensor identification.** Manufacturer, model, wire travel length, and the
  potentiometer's conformity/linearity grade. FR-E12's ≥241-cycle sample time
  is sized for a 12.5 kΩ source — the element's 2.5 kΩ at mid-scale plus
  FR-E21's 10 kΩ series protection — so a different element changes it; the accuracy split in FR-E03 (firmware
  ±0.1 % of full travel vs the mechanism's own error) cannot be closed
  without the mechanical specification.

- **Resolution and range.** 0.1 mm in a 16-bit register caps travel at
  6553.4 mm — ample for a window vent, but the decision is baked into the
  register map. If any installation needs more than 6.5 m of travel, the
  choice is 1 mm resolution (65 m) or a 32-bit two-register opening. Decide
  before any master integrates against the map.

- **Percentage-of-travel register — CLOSED (2026-07-29).** Added as 30015
  (FR-E20), 0–1000 = 0.0–100.0 %, derived from the instantaneous opening. For
  a window the percentage is arguably the natural unit and the millimetres are
  the implementation detail, so the common case no longer needs the master to
  divide.

- **Auto-calibration — SPECIFIED (2026-07-29), one policy still open.**
  FR-E18 (report the raw code seen at each stop, 30013/30014) and FR-E19
  (commanded teach via 40007, with the both-reached-and-both-read handshake)
  are in §2.7/§2.8 and implemented in `regs.c`. Together they cover the
  reporting and teach-on-command policies. **Always-on self-calibration is
  deliberately not specified** — it would clear the averaging accumulator on
  every window cycle and write flash at a rate the ~20 k-cycle store cannot
  sustain (`design/scratchBook.md` §Q1). Revisit only with field data on how
  often the endpoints actually move.

  *Residual — largely closed.* Which stop a capture belongs to is now decided
  by the direction of the last movement (FR-E10 became signed on the same
  day), which works on an uncalibrated device where the old proximity
  heuristic was circular. Proximity remains only as the fallback for the case
  where nothing has moved since reset — reaching a stop without having
  travelled to it, which in practice means the window was already sitting
  there at power-on.

- **Movement-rate sign — CLOSED (2026-07-29).** 30012 is now a signed
  two's-complement `int16`: positive opening, negative closing (FR-E10). The
  range halves to ±3276.7 mm/s, which is still three orders of magnitude
  beyond anything a window actuator does. Direction turned out to be worth
  more than the range twice over — it also settles which stop an FR-E18
  capture belongs to, which the proximity heuristic could not do on an
  uncalibrated device.

- **Direction of opening — CLOSED (v0.4).** FR-E04 now accepts the two
  calibration points in either order, so a mounting where the wiper code falls
  as the window opens calibrates exactly like a normal one, with no extra
  installer step and no invert register. FR-E06 constrains the *distance*
  between the points rather than their ordering. The scaling is host-tested at
  its corners in both senses (`software/firmware/test/test_scale.c`).

- **Minimum calibration span — CLOSED (v0.4).** FR-E06 now requires ≥64 counts
  between the calibration points, and the same check is applied to values
  loaded from flash so a degenerate stored pair cannot reach the divisor.

- **The §4.4 band nominals — CLOSED 2026-08-31. They are now measured.** All
  three states were read on the bench and the fitted model agrees to ≤0.1 mV
  (§4.4.3). The item this replaces was written for the LJ18A3 and asked for its
  internal pull-up and `Vsat`; the sensor change retired both questions before
  they were answered. What the measurement found instead was a 35 µA off-state
  leakage, which is now the item below.

- **An open sensor cable is undetected, and reports a *missed* stop**
  (§4.4.6) — a standing limitation, not a closed decision. With a PNP
  normally-open output, *inactive*, *cable open* and *shorted to 0 V* are one
  electrical condition: nothing sourcing, ~0 counts. So the device says
  "between the stops" when the truth is "I have lost the sensor". **Note the
  direction changed on 2026-08-29:** under the previous NPN part a cut landed
  at 337 counts and reported a *false* stop; it now reports a missed one.
  Neither is detected, and FR-E16 and status bit 4 are narrowed to say so. **A firmware mitigation is available and not yet specified:** once
  FR-E19 has taught the endpoints, a stop claimed while the wiper sits far
  from either calibrated end is implausible, and the two independent
  front-ends can cross-check each other. That would catch most of this class
  without any hardware change. It needs its own requirement, a decision about
  what to do before the first teach, and a tolerance — none of which exist
  yet.

- **A broken +V conductor is also undetected** (§4.4). Lose the supply to one
  sensor and its output goes quiet, which reads identically to a cut signal
  conductor — a false stop. Powering the sensors down their own cables is what
  introduced this; the dry-contact design did not have it. Now a sub-case of
  the item above rather than a separate problem.

- **Output drop and off-state leakage — BOTH CLOSED 2026-08-31, and both
  differently from the first answer.** The drop is **1.01 V at 290 µA**, not
  the zero an earlier fit reported; `Von` is 23.09 V against a 24.1 V rail,
  confirmed by three routes agreeing to 0.2 %. The leakage is **nil** —
  connecting or disconnecting both sensors moves PC4 by 0.9 mV. What had been
  recorded as 35 µA and then 33 µA of sensor leakage was the **MCU's internal
  pull-up on PC4**, ~47 kΩ to 3V3, left enabled by the image in flash. It went
  away when the current firmware was programmed.

  Consequences: **TP-A01 is not needed** — no leakage for temperature to act
  on — and the thresholds improve to 170/522 with 170 and 60 counts of margin
  against the 38/39 the corrupted fit predicted. **PC4 must be an analog input
  with no pull**, now explicit in FR-E11; if that regresses the 63 µA returns
  and presents as sensor leakage all over again.

  Recorded at length because three plausible fits were published and retracted
  before the rig was believed over the arithmetic. The tell was there early:
  *one active* to *both active* stepping 50 mV where the topology requires it
  to roughly double.

- **Sensor polarity is fixed, but the target is not.** The 3RG4023-3AB00 is
  PNP normally-open, so §4.4's sense is settled. What is not settled is the
  target: the 8 mm rating assumes mild steel St 37 at 24 × 24 × 1 mm. Confirm
  the window frame is ferrous and presents enough area at both stops, or add
  target plates to the installation scope. Note the reduction factors —
  aluminium 0.40, stainless 0.70 — a non-ferrous frame roughly halves the
  working distance.

- **Temperature ceiling — CLOSED (2026-08-29).** NFR-ENV01 was narrowed to
  +65 °C on 2026-07-29 because the LJ18A3-8-Z/BX capped it there, and that was
  recorded as the one requirement this design knowingly failed against the
  greenhouse study. The 3RG4023-3AB00 is rated **−25…+85 °C**, so the sensor
  stops being the constraint, NFR-ENV01 goes to **+70 °C**, and NF-WP03 is met
  in full. The answer turned out to be "a wider-range end switch" exactly as
  the old entry predicted — it simply arrived as a change of part rather than
  as a survey. *Residual:* +70 °C is now an assertion about the **electronics**
  and is inherited from the sibling project rather than measured here; it needs
  the NFR-ENV01 chamber run to become evidence.

- **Cable length and joints — much improved** (§4.4). The 3RG4023-3AB00
  terminates in an **M12 connector**, so the run to the hub is a cordset of
  the required length rather than a 1.1 m flying lead spliced in the field.
  The workmanship item disappears; what replaces it is a procurement one —
  specify cordset length and IP rating per sensor, and remember the connector
  itself now sits outdoors on the frame, where the flying-lead joint used to
  be the exposed part. Maximum cable length is 300 m, which is not a
  constraint here.

- **Enclosure and environment — CLOSED (v0.4, ingress figure settled v0.5).**
  IP65 box (Kopp 99966478), all connectors
  inside it, field cables through glands, terminal blocks for the sensor and
  switch loop, mounted out of direct UV (§4.5, NFR-ENV02…05). Residual: gland
  sizes are a BOM item, and the condensation strategy (conformal coating is
  the recommended default) must be picked before the first build.

- **Hardware — schematic now exists** (2026-08-07), verified with
  `kicad-cli` for ERC and netlist. **Wiper protection is CLOSED**: §4.3 and
  FR-E21 fit R11/C6/D3, replacing a bare run from the terminal block to PA2
  that had been inherited from the sibling board. Residual: the physical form
  of the end-switch runs (§4.4). **D3 is now selected — PESD5V0S1BA**, 5 V
  standoff, SOD-323 — and every component on the schematic carries a
  footprint. What remains is evidence rather than choice: its leakage at
  3.3 V and +70 °C is not something the datasheet answers, so FR-E21's
  fit/unfit mid-scale measurement still has to be made. Actuator
  motor noise on the sensor cable has no precedent in the sibling project's
  bench work and is the most likely source of an installation surprise; R11
  and C6 now give it a 12.5 µs time constant to fight, which it did not have
  before.

- **Averaging engine.** FR-S31's two-stage boxcar is carried over from the
  sibling design. The opening is a scalar, so that project's circular-mean
  machinery is not needed here — but the min/max tracking of FR-E08 is new
  and needs its own block-aggregation rule. To be settled in
  `design/integrationPlan.md` stage E.

- **Enclosure ingress — DECIDED (2026-07-29): NFR-ENV03 narrowed to IP65,
  set by the Kopp 99966478.** The same treatment as the temperature ceiling:
  state the figure the bill of materials actually delivers and name the part
  that sets it. IP65 is the greenhouse study's stated minimum, and its
  preference for IP67 was written for hardware *at the aperture, which may be
  rain-wetted with the vent open* — this box holds the electronics and is
  mounted inside the structure. *Residual:* the box is not the exposed part.
  The draw-wire unit is, and it is IP50 — see below.

- **The draw-wire unit is IP50 and sits outside the enclosure — open.** Its
  specification (transcribed in `documentation/product-images/readme.md`)
  gives IP50: dust-protected, **not** water-protected. The IP65 enclosure and
  its glands protect the electronics and do nothing for the sensor, which
  hangs on the window frame in an environment that condenses most nights.
  Options are a sheltered mounting position, a shroud over the unit, or a
  higher-rated sensor. This is the weakest environmental point in the design
  and it is outside the box, where NFR-ENV02…05 do not reach.

  *Resolved by the same specification:* **accuracy 0.2 % max** (comfortably
  inside the ±1 % repeatability and ±2 % accuracy asked of the mechanism, so
  FR-E03's split between firmware and mechanism closes), **endurance
  >100 000 cycles** (4× the ~25 000 needed over twenty years, so the
  contacting-wiper concern is answered), and **maximum wire speed 100 mm/s**
  against the M3 flap's 11.7 mm/s. Order the **RE38, 0–10 kΩ, 2000 mm**
  variant — the resistance output is the passive potentiometer the design
  depends on; the 4–20 mA, 0–5 V and 0–10 V variants would break the
  ratiometric measurement.

- **Address capacity.** One solder jumper gives two devices per segment
  (40/45). A building with more than two instrumented windows on one bus
  needs a second jumper — a hardware change, since there is deliberately no
  address register (FR-MB07). Worth deciding before the PCB is laid out.

---

*End of Technical Design Specification v0.7 (2026-09-01: FR-E23 and FR-E24 add
sensing-health reporting on status bits 6 and 7 — a §2.7 register-map change,
since FR-S33 previously pinned those bits to zero. FR-E23 needs no calibration
and works in every installation geometry; FR-E24 is self-disabling wherever the
draw-wire leaves no electrical headroom, which makes its usefulness a property
of the installation rather than of the firmware. v0.6, 2026-08-31: end switch changed to
the 3RG4023-3AB00 — PNP, so §4.4's bands invert and the fault band is lost;
R10 deleted and R8/R9 retuned to 68 k; FR-E14/FR-E16/FR-S33 narrowed to match;
NFR-ENV01 raised to +70 °C, which closes NF-WP03. v0.5 added the FR-E17
maximum-age contract, FR-E18/E19 teach, FR-E20 percentage, FR-E21 wiper
protection and the IP65 enclosure; v0.4 direction-agnostic scaling; v0.3
mandatory end switches on PC4 with the address jumper on PC1;
§2/§3.1/§3.2/§5 inherited from `windmeters-modbus-interface` TDS v0.9,
§2.7/§2.8 and the FR-E series new).*
