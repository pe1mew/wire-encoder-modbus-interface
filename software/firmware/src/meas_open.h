/**
 * @file meas_open.h
 * @brief Measurement service — window pacing and publication (integration stage D).
 *
 * Sits between the encoder driver (@ref we.h, which produces raw codes and says
 * whether they are trustworthy) and the register image (@ref regs.h, which owns
 * the calibration, the FR-E07 fault timer, the movement rate and the status
 * bits). This layer owns exactly one thing the others cannot: **when a window
 * starts and ends**, and what one window's worth of samples reduces to.
 *
 * Deliberately narrow. It does not know about Modbus, does not decide that the
 * sensor has failed, does not hold the 2 s fault timer, and does not touch a
 * status bit. Everything it produces goes out through
 * @ref regs_publish_opening and @ref regs_publish_switches.
 */
#ifndef MEAS_OPEN_H
#define MEAS_OPEN_H

/**
 * @brief Start the measurement service.
 *
 * Latches the current 40002 window duration and starts the first window. Call
 * once, after @ref regs_init (so the persisted window duration is loaded) and
 * after @c we_init.
 */
void meas_open_init(void);

/**
 * @brief Run one pass of the measurement service.
 *
 * Call once per main-loop pass. Non-blocking: it samples when the schedule says
 * to and returns immediately otherwise.
 *
 * Two independent cadences run here:
 *
 * - **The wiper**, sampled at @ref MEAS_SAMPLE_HZ throughout the window and
 *   published once at the end of it (FR-E02/E13).
 * - **The end-switch divider**, sampled at the same rate and published every
 *   time (FR-E14 requires >=10 Hz, and there is no window to average over —
 *   a stop is either reached or it is not).
 *
 * @note A change to 40002 aborts the window in progress (FR-S30): the partial
 *       result is discarded, @ref regs_window_aborted is called, and a new
 *       window of the new duration starts immediately.
 */
void meas_open_service(void);

#endif /* MEAS_OPEN_H */
