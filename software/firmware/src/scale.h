/**
 * @file scale.h
 * @brief Two-point opening scaling — pure integer arithmetic (TDS FR-E04/FR-E06).
 *
 * Split out of @ref regs.h deliberately: this is the most error-prone code in
 * the firmware (a sign-aware map with a tight overflow bound and clamping at
 * both ends) and it has **no hardware dependency at all**. Keeping it in its
 * own translation unit means the host test in `software/firmware/test/` compiles
 * and exercises the shipped code rather than a copy of it.
 *
 * @see software/firmware/test/test_scale.c — the corner and monotonicity tests.
 */
#ifndef SCALE_H
#define SCALE_H

#include <stdint.h>

/**
 * @def CAL_MIN_SPAN
 * @brief Smallest legal distance between the two calibration points (FR-E06).
 *
 * A sixteenth of the 10-bit ADC range. FR-E06 constrains the *distance*, not the
 * ordering, so a reversed mounting is legal — but two adjacent codes are not:
 * they would satisfy "not equal" while making one LSB of ADC noise swing the
 * entire reported travel.
 */
#define CAL_MIN_SPAN 64u

/**
 * @brief Distance between two calibration points, regardless of their order.
 * @param a One calibration point.
 * @param b The other.
 * @return |a − b|.
 */
static inline uint32_t cal_span(uint16_t a, uint16_t b)
{
	return (uint32_t)((b > a) ? (b - a) : (a - b));
}

/**
 * @brief Map a raw ADC code onto a window opening in 0.1 mm (FR-E04).
 *
 * @code
 *   opening = offset + ((raw - raw_closed) * travel) / (raw_open - raw_closed)
 * @endcode
 *
 * @par Direction-agnostic
 * @p raw_closed and @p raw_open may be given in **either order**.
 * `raw_open < raw_closed` describes a mounting where the wiper code *falls* as
 * the window opens — which is decided by how the draw-wire happens to be fitted
 * relative to the moving frame, i.e. a coin toss. Handling it here costs a
 * branch; pushing it onto the installer as a "swap the two pot wires"
 * instruction costs a site visit when someone gets it wrong.
 *
 * @par Clamping and monotonicity
 * Clamped to `[offset, offset + travel]`, and never above 65534 — 65535 is the
 * FR-E07 fault sentinel and must stay unreachable by a healthy measurement.
 * Clamping at **both** ends is what makes the result monotonic in @p raw across
 * the whole ADC range, with no step at either calibration point.
 *
 * @param raw        Raw ADC code from the wiper.
 * @param offset     40001 — opening reported at the closed point, 0.1 mm.
 * @param travel     40004 — full travel between the calibration points, 0.1 mm.
 * @param raw_closed 40005 — raw code with the window closed.
 * @param raw_open   40006 — raw code with the window fully open.
 * @return Window opening in 0.1 mm units.
 *
 * @warning The caller must guarantee `cal_span(raw_closed, raw_open) >=
 *          CAL_MIN_SPAN`. FR-E06 enforces it on every Modbus write and
 *          @ref regs_init re-checks it on every load from flash, so the divisor
 *          here is never zero.
 * @note The distance from the closed point is clamped to the span **before**
 *       the multiply, which is what bounds the largest intermediate at
 *       65535 × 65534 = 4 294 770 690 — inside `uint32_t` by just 196 605,
 *       about 0.0046 %. That margin holds only because both operands are
 *       16-bit; widening either register invalidates it immediately. (An
 *       earlier hand calculation of this product was wrong and overstated the
 *       margin threefold — hence the host test.)
 */
uint16_t scale_opening(uint16_t raw, uint16_t offset, uint16_t travel,
                       uint16_t raw_closed, uint16_t raw_open);

/**
 * @brief Express an opening as a percentage of full travel (FR-E20).
 *
 * @code
 *   percent[0.1 %] = (opening - offset) * 1000 / travel
 * @endcode
 *
 * For a window the percentage is arguably the natural unit and the millimetres
 * are the implementation detail — so this exists to spare every master the same
 * division. Derived from the *instantaneous* opening, so it tracks the value a
 * positioning loop actually reads.
 *
 * @param open_0_1mm Window opening from @ref scale_opening, 0.1 mm units.
 * @param offset     40001 — the opening reported at the closed point.
 * @param travel     40004 — full travel, 0.1 mm. Must be non-zero (the 40004
 *                   range starts at 1); guarded anyway.
 * @return 0..1000, i.e. 0.0 %..100.0 %, clamped.
 *
 * @note Largest intermediate is 65534 x 1000 = 65 534 000, comfortably inside
 *       `uint32_t` — a far easier bound than @ref scale_opening's.
 */
uint16_t scale_percent(uint16_t open_0_1mm, uint16_t offset, uint16_t travel);

#endif /* SCALE_H */
