/**
 * @file health.h
 * @brief Sensing-health indications — FR-E23 and FR-E24, status bits 7 and 6.
 *
 * Reports whether the **position signal is credible**, which is a different
 * question from whether the window is open. Two independent checks:
 *
 * - **FR-E24, bit 6 — is the raw code reachable?** A code outside the
 *   calibrated span plus a margin is somewhere the window cannot physically be,
 *   so the signal is not to be believed. Catches a conductor broken or shorted
 *   to either rail. Works at rest.
 * - **FR-E23, bit 7 — does the position follow the carriage?** The end switches
 *   witness movement independently. If they say the carriage travelled and the
 *   wiper did not move, the position path is not following it. Catches what no
 *   electrical test can: a tangled, snapped, seized or slipping draw-wire,
 *   where the potentiometer is electrically perfect.
 *
 * @note Pure logic, no hardware. Everything here is a function of values the
 *       caller supplies, which is what lets `test_health.c` prove it on the
 *       host — the same split as `scale.c` and `avg.c`.
 *
 * @note Neither check suppresses or alters 30001–30004. They report, following
 *       FR-E16's precedent for a cross-front-end fault; the master decides.
 */
#ifndef HEALTH_H
#define HEALTH_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief Switch classification as this module needs it (TDS §4.4.3).
 *
 * Deliberately narrower than `regs.c`'s three-state enum: FR-E23 only cares
 * whether the carriage is *at a stop*, not which one or whether both fired.
 */
typedef enum {
	HEALTH_SW_CLEAR = 0, /**< not at a stop */
	HEALTH_SW_AT_STOP,   /**< at a stop (one sensor active) */
} health_sw_t;

/** @brief Reset both checks. Call from @ref regs_init. */
void health_init(void);

/**
 * @brief Feed one measurement window's raw code and the calibration (FR-E24).
 *
 * @param raw        Raw wiper code for the window just published.
 * @param raw_closed 40005.
 * @param raw_open   40006.
 * @param window_ms  40002, for the ≥2-window persistence.
 *
 * @note Call once per completed window, from @ref regs_publish_opening, and
 *       only for a **valid** sample — a faulted one says nothing about
 *       plausibility and must not be allowed to latch the bit.
 */
void health_note_window(uint16_t raw, uint16_t raw_closed, uint16_t raw_open,
                        uint16_t window_ms);

/**
 * @brief Feed a debounced end-switch state change (FR-E23).
 *
 * @param sw        The newly published classification.
 * @param raw       The current raw wiper code.
 * @param window_ms 40002, for the departure-sequence timing.
 *
 * @note Call from @ref regs_publish_switches on a **published** (debounced)
 *       change only, never on every sample — the sequence is defined over
 *       debounced transitions.
 */
void health_note_switch(health_sw_t sw, uint16_t raw, uint16_t window_ms);

/**
 * @brief Feed the current raw code between transitions (FR-E23).
 *
 * The departure sequence needs the wiper's excursion across the **whole**
 * sequence, not just at its ends: a carriage that moves out and back would show
 * no end-to-end difference while having plainly moved. Call at the sampling
 * rate.
 */
void health_note_raw(uint16_t raw);

/** @brief FR-E24 → status bit 6: the raw code is not reachable. */
bool health_raw_implausible(void);

/** @brief FR-E23 → status bit 7: the position is not following the carriage. */
bool health_position_stuck(void);

#endif /* HEALTH_H */
