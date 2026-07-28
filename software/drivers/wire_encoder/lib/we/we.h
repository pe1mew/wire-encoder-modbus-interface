/**
 * @file we.h
 * @brief Wire-encoder raw-code acquisition — the TDS §3.4 driver layer.
 *
 * @warning **NOT IMPLEMENTED.** This header is the agreed API contract only;
 *          there is no `we.c` in this repository yet. Linking against it will
 *          fail — deliberately, rather than letting a stub masquerade as a
 *          driver. See `design/driverDevelopment.md` §3.
 *
 * The sensor is a draw-wire encoder attached to a moving window frame: a
 * spring-loaded drum pays out a wire and turns a 10 kΩ potentiometer, so the
 * wiper voltage is a direct, absolute measure of the window opening. It is read
 * on PA2 with the 10-bit ADC in ratiometric mode referenced to VDD — ≥16
 * conversions folded per sample, ≥71-cycle sample time for the 10 kΩ source
 * impedance (FR-E11/E12/E13). This is the same front-end topology the sibling
 * `windmeters-modbus-interface` project uses for its vane, and its driver is
 * the reference implementation.
 *
 * The driver's job is narrow on purpose: **produce a raw code and say whether
 * it is trustworthy.** Scaling (FR-E04), offset, windowing, averaging, and the
 * FR-E07 fault *timer* all live above it in `meas_open.c` and `regs.c`. The
 * driver therefore knows nothing about millimetres, Modbus, windows, or the 2 s
 * fault hold — it reports one sample at a time and whether that sample is
 * valid.
 *
 * @note Zero-ISR: every routine here runs to completion in the main loop
 *       (`design/softwareArchitecture.md`). The conversion burst costs well
 *       under 1 ms, so nothing here threatens the FR-MB20 response budget.
 * @see design/driverDevelopment.md §3 — the test matrix this driver must pass
 *      before the product firmware may reference it.
 */
#ifndef WE_H
#define WE_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief Bring up the potentiometer front-end (FR-S18 step 3).
 *
 * Configures PA2 as an analog input and runs the ADC self-calibration before
 * any conversion. Must be called after @c board_init_early (which latches the
 * Modbus address and leaves the transceiver quiescent) and before @c mb_init,
 * per the FR-S18 initialisation order.
 */
void we_init(void);

/**
 * @brief Acquire one absolute raw code.
 *
 * The reading is complete in itself — the potentiometer carries the window's
 * position in the sensor, so nothing is accumulated between calls and a missed
 * sample costs one sample, not a reference (FR-E01). Call once per measurement
 * window from the main loop.
 *
 * @param[out] raw Receives the raw ADC code, 0..@ref we_raw_max. Written only
 *                 when the function returns true; left untouched otherwise.
 * @return @c true when the sample is trustworthy; @c false when the front-end
 *         reports it is not — a floating or shorted wiper, detected by toggling
 *         the internal pull resistor on PA2 between two conversions and
 *         comparing the readings (FR-E07).
 * @note A @c false return is the @b only input to the FR-E07 fault machine.
 *       This function never decides that the sensor has failed — it decides
 *       that @e this sample is unusable. Holding the last valid value for 2 s
 *       and then reporting 65535 with status bit 2 is the caller's policy.
 */
bool we_sample(uint16_t *raw);

/**
 * @brief Native full-scale raw code of the readout.
 * @return 1023 — the 10-bit ADC full scale (FR-E11).
 * @note Must equal @c WE_RAW_MAX_DEFAULT in the firmware's `sensors.h`, which
 *       seeds the compile-time default of holding register 40006 (raw code at
 *       full opening, §2.8). A mismatch calibrates a fresh device to nonsense
 *       on first boot, and the FR-E04 scaling has no way to notice.
 */
uint16_t we_raw_max(void);

#endif /* WE_H */
