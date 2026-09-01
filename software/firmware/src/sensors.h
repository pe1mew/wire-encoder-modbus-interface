/**
 * @file sensors.h
 * @brief Build configuration → capability-macro mapping (TDS FR-S01).
 *
 * This firmware has @b one release build. The sensor is a draw-wire encoder
 * whose drum drives a 10 kΩ potentiometer, read ratiometrically on PA2 — the
 * same front-end the sibling `windmeters-modbus-interface` project uses for its
 * wind vane. There is nothing to select between, so unlike that project there
 * is no `SENSOR_*` build selector: the single build is the product.
 *
 * One compile-time option remains: `TEST_HOOKS`, the bench-only hooks (FR-S20
 * watchdog hang trigger), off by default. Never release a binary built with it.
 *
 * The end-of-travel switches are @b not optional (FR-E14): they are read as a
 * supervised resistor ladder on PC4 (TDS §4.4), and the address jumper takes
 * PC1 — the reverse of the obvious assignment, because PC4 has an ADC channel
 * and PC1 does not.
 *
 * @see board.h for the Modbus address map.
 */
#ifndef SENSORS_H
#define SENSORS_H

/**
 * @def BUILD_TYPE
 * @brief Build-type code — high byte of input register 30007 (FR-S32).
 *
 * 0x01 is the potentiometric draw-wire release build. The byte is kept (rather
 * than hard-coding 30007) so a future variant can claim a distinct code without
 * a master having to guess what it is talking to.
 *
 * @warning **The high bit means "not for release."** `[env:encoder_test]`
 * overrides this to 0x81 so a bench image is identifiable over the bus. That
 * image carries the FR-S20 hang hook — holding 0x00FF, magic 0xDEAD, which
 * stops the main loop refreshing the watchdog — and until 2026-09-01 both
 * builds reported 0x01, so a field device carrying it was indistinguishable
 * from a correct one. Do not collapse this back to an unconditional define.
 */
#ifndef BUILD_TYPE
#define BUILD_TYPE 0x01
#endif

/**
 * @def WE_RAW_MAX_DEFAULT
 * @brief Native full-scale raw code of the readout — seeds holding 40006 (FR-E05).
 *
 * 1023 = the 10-bit ADC full scale (FR-E11). Must equal the driver's
 * @c we_raw_max(): a mismatch calibrates a fresh device to nonsense on first
 * boot, and the FR-E04 scaling has no way to notice.
 */
#define WE_RAW_MAX_DEFAULT 1023

#endif /* SENSORS_H */
