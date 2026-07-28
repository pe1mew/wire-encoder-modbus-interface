/**
 * @file regs.h
 * @brief Modbus register image — the complete TDS §2.7/§2.8 map.
 *
 * Owns the device's holding and input registers and presents them to the
 * @ref mb.h "Modbus driver" via @ref regs_cfg(). Built during integration
 * stage C (`design/integrationPlan.md`).
 *
 * The map is fixed (FR-MB27): raw input addresses 0x0000–0x000B (12 registers)
 * and raw holding addresses 0x0000–0x0005 (6 registers).
 *
 * @par Current state — no measurement service
 * The encoder driver does not exist yet (`design/driverDevelopment.md` §3), so
 * nothing calls @ref regs_publish_opening. Measurement registers 30001–30005
 * and 30012 therefore read 0 and status bits 0/1 stay set. That is not a
 * placeholder: it is exactly the FR-S23 pre-first-window state a conforming
 * device must present before its first window closes. A device flashed with
 * this build answers the whole map correctly and reports, truthfully, that it
 * has never completed a measurement.
 *
 * The six holding registers persist across reset (@ref persist.h, FR-S39).
 */
#ifndef REGS_H
#define REGS_H

#include <stdbool.h>
#include <stdint.h>
#include "mb.h"
#include "sensors.h"

/**
 * @brief Initialise the register image and load persisted settings.
 *
 * Builds the @ref mb_config_t (holding table, input-read callback, cross-
 * validate hook for FR-S31 and FR-E06) and seeds the six holding registers
 * from non-volatile storage (@ref persist_load; blank/corrupt store → §2.8
 * compile-time defaults, FR-S21). Call after the sensor front-end and before
 * the measurement service, so the first window already uses the stored window
 * duration — no spurious first-window abort at boot.
 *
 * @param mb_address Latched Modbus slave address (FR-S03), from
 *                   @ref board_mb_address().
 */
void regs_init(uint8_t mb_address);

/**
 * @brief Modbus configuration for the driver.
 * @return Pointer to the internal @ref mb_config_t (holdings, input_read,
 *         cross-validate hook). Valid after @ref regs_init.
 */
const mb_config_t *regs_cfg(void);

/** @name Holding-register accessors (TDS §2.8, owned here) */
/** @{ */
uint16_t regs_offset_0_1mm(void); /**< 40001 zero offset, 0.1 mm units. */
uint16_t regs_window_ms(void);    /**< 40002 measurement window, ms. */
uint16_t regs_avg_s(void);        /**< 40003 averaging window, s. */
uint16_t regs_travel_0_1mm(void); /**< 40004 full travel, 0.1 mm (FR-E05). */
uint16_t regs_raw_closed(void);   /**< 40005 raw ADC code, window closed (FR-E05). */
uint16_t regs_raw_open(void);     /**< 40006 raw ADC code, window fully open (FR-E05). */
/** @} */

/**
 * @brief Scale a raw ADC code to a window opening in 0.1 mm (FR-E04).
 *
 * Applies the persisted two-point calibration:
 * @code
 *   opening = offset + ((raw - raw_closed) * travel) / (raw_open - raw_closed)
 *              40001                40005      40004      40006     40005
 * @endcode
 *
 * @par Direction-agnostic
 * The calibration points may be given in @b either order. `raw_open <
 * raw_closed` describes a mounting where the wiper code @e falls as the window
 * opens — which is a coin toss determined by how the draw-wire is fitted
 * relative to the moving frame — and is handled here rather than being pushed
 * onto the installer as a wiring instruction. FR-E06 requires only that the two
 * points differ by at least @ref CAL_MIN_SPAN.
 *
 * @par Clamping and monotonicity
 * The result is clamped to `[offset, offset + travel]` and never exceeds 65534
 * (65535 is the FR-E07 fault sentinel). Clamping at @e both ends is what makes
 * the reported opening monotonic in the raw code across the whole ADC range,
 * with no step at the calibration points.
 *
 * @param raw Raw ADC code from the wiper.
 * @return Window opening in 0.1 mm units.
 *
 * @note Integer-only, and the overflow bound is tight enough to be worth
 *       stating: the distance from the closed point is clamped to the
 *       calibrated span @b before the multiply, so the largest intermediate is
 *       65535 × 65534 = 4 294 770 690 — inside `uint32_t` by just 196 605,
 *       about 0.0046 %. It holds only because both operands are 16-bit. Any
 *       widening of the registers invalidates it immediately.
 * @note Lives here rather than in the measurement service because the
 *       calibration values live here; the measurement service calls it once per
 *       window (integration stage D).
 */
uint16_t regs_scale_opening(uint16_t raw);

/**
 * @brief Per-loop register housekeeping.
 *
 * FR-S30/FR-E05: on a valid write to 40002/40003 (window/averaging) or to
 * 40004/40005/40006 (calibration), clears the averaging accumulator and
 * re-asserts status bits 0/1 — a rescale must never let the boxcar mix pre- and
 * post-calibration values. Call once per main-loop pass.
 */
void regs_service(void);

/**
 * @brief Persist a changed holding set to flash (FR-S39).
 *
 * No-op unless a holding register differs from the last-saved snapshot.
 * Blocking (~6 ms) when it writes — call from the main loop @b after the
 * Modbus response so the flash op stays out of the FR-MB20/21 latency path.
 * @see persist_save
 */
void regs_persist_service(void);

/**
 * @brief One-second tick: advance uptime (FR-S34) and reading-age (FR-S36).
 * @note Call at a 1 Hz cadence from the main loop.
 */
void regs_second_tick(void);

/**
 * @brief Mark the in-progress measurement window aborted (FR-S30).
 *
 * Re-asserts status bit 0 (no completed window) until the restarted window
 * finishes. Called by the measurement service on a 40002 change.
 */
void regs_window_aborted(void);

/**
 * @brief Publish one closed measurement window (FR-E04/E07/E09/E10).
 *
 * @param raw          Raw ADC code for this window → 30005 (FR-E09).
 * @param open_0_1mm   Scaled, offset-applied window opening → 30001 (FR-E04).
 *                     Ignored when @p valid is false.
 * @param valid        False when the sample could not be trusted — drives the
 *                     FR-E07 fault machine (hold the last value for 2 s, then
 *                     report the 65535 sentinel in 30001–30004 and set status
 *                     bit 2). Faulted samples never enter the averaging engine.
 *
 * @warning Nothing calls this yet — the measurement service is integration
 *          stage D. It is declared here so the register image's contract with
 *          the measurement layer is fixed before that code is written.
 */
void regs_publish_opening(uint16_t raw, uint16_t open_0_1mm, bool valid);

/**
 * @brief Publish one end-switch ladder reading (FR-E14/E15/E16).
 *
 * Classifies @p raw into one of the five TDS §4.4 states, debounces the
 * classification for 20 ms (FR-E15), and maintains status bit 3 (end of travel
 * reached) and bit 4 (switch-loop fault) accordingly.
 *
 * The band thresholds live here rather than in the driver so they sit next to
 * the status bits they drive and next to the requirement that defines them.
 * The driver (@ref we_switch_sample) only produces the raw code.
 *
 * @param raw Raw ADC code from the ladder on PC4.
 *
 * @note Debouncing is a SysTick comparison, never a delay: a candidate state
 *       simply has to survive 20 ms of calls. Call once per main-loop pass, or
 *       at whatever rate the measurement service samples the ladder (≥10 Hz,
 *       FR-E14) — the debounce measures elapsed time, not call count.
 * @note FR-E16: a switch-loop fault is reported and nothing more. It never
 *       suppresses or alters the opening registers, which come from an
 *       independent front-end.
 * @warning Nothing calls this yet — the measurement service is integration
 *          stage D.
 */
void regs_publish_switches(uint16_t raw);

#ifdef TEST_HOOKS
/**
 * @brief FR-S20 watchdog-recovery test trigger (TEST_HOOKS builds only).
 * @return True once holding register 0x00FF has been written 0xDEAD, telling
 *         the main loop to hang so the IWDG resets the device.
 * @warning Absent from release binaries — never ship a test build.
 */
bool regs_test_hang_requested(void);
#endif

#endif /* REGS_H */
