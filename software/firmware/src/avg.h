/**
 * @file avg.h
 * @brief Averaging engine — 30002 mean and 30003/30004 envelope (stage E).
 *
 * Consumes one completed measurement window at a time and maintains the
 * rolling average (FR-S31) and the movement envelope (FR-E08) over the last
 * N windows, where N = floor(40003 × 1000 / 40002).
 *
 * **One buffer serves all three registers.** The mean, the minimum and the
 * maximum are all taken over the same set of published openings, so they share
 * a single ring rather than three.
 *
 * **Two-stage above 64 windows (FR-S31).** N reaches 6000 at the register map's
 * extremes (40003 = 600 s over a 40002 = 100 ms window), which cannot be stored
 * exactly in the RAM budget. Above 64, consecutive windows are aggregated into
 * blocks of ⌈N/64⌉ and the ring holds blocks instead, giving an effective span
 * within ±one block of N and bounding storage at 64 entries.
 *
 * @warning Each block carries its own **minimum and maximum**, not just a mean.
 *          A block that stored only its mean would report an envelope narrower
 *          than the movement that actually happened — the excursion FR-E08
 *          exists to expose is exactly what a mean hides.
 *
 * @note At N ≤ 64 the block size is 1 and the two-stage path degenerates to an
 *       exact boxcar, so there is one code path rather than two.
 */
#ifndef AVG_H
#define AVG_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief Set the averaging span from the current 40002/40003 and reset.
 *
 * Called at init and whenever a write changes the window, the averaging period
 * or the calibration (FR-S30/FR-E05) — a boxcar holding two scales at once
 * reports a number that was never true at any moment.
 *
 * @param window_ms 40002, measurement window in ms.
 * @param avg_s     40003, averaging period in seconds.
 */
void avg_config(uint16_t window_ms, uint16_t avg_s);

/**
 * @brief Feed one completed measurement window.
 * @param open_0_1mm The window's published opening (30001), 0.1 mm units.
 * @note Only trustworthy windows reach here; a faulted sample never enters the
 *       average (FR-E07), so the mean can never be dragged by a fault value.
 */
void avg_push(uint16_t open_0_1mm);

/**
 * @brief Has the span filled once since the last @ref avg_config?
 * @return True once the ring has wrapped. Drives status bit 1 (FR-S23/S33).
 */
bool avg_filled(void);

/**
 * @brief Rolling mean → 30002.
 *
 * Before the span has filled this is the mean of **only the windows actually
 * acquired** — FR-S23 forbids zero-padding and stale seeding. With a 1 s
 * window, 10 s averaging and a steady 500.0 mm opening, 30002 reads 5000 at
 * t = 3 s, not the 1500 a zero-padded accumulator would give.
 */
uint16_t avg_mean(void);

/** @brief Minimum opening across the span → 30003 (FR-E08). */
uint16_t avg_min(void);

/** @brief Maximum opening across the span → 30004 (FR-E08). */
uint16_t avg_max(void);

#endif /* AVG_H */
