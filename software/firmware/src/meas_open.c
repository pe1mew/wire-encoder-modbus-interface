/**
 * @file meas_open.c
 * @brief Measurement service — implementation of @ref meas_open.h.
 *
 * @note Zero-ISR, no delays. Every branch here returns promptly; the longest
 *       thing it can do is one @c we_sample (~1.2 ms, dominated by the two
 *       FR-E07 pull settling waits), which is well inside the FR-MB20 budget
 *       of 100 ms and the FR-MB21 preference of 15 ms.
 */
#include "ch32fun.h"

#include "meas_open.h"
#include "regs.h"
#include "we.h"

/**
 * @brief Wiper and ladder sampling rate, Hz.
 *
 * FR-E14 requires the end-switch divider at >=10 Hz. FR-E13 requires each 30001
 * update to fold >=16 conversions: `we_sample` already folds 16 internally, so
 * even a single sample per window satisfies the count — but sampling across the
 * window rather than once at its end is what makes the published value
 * representative of the window instead of of one instant in it.
 *
 * 20 Hz gives 2x margin on FR-E14 and, at the 100 ms minimum window (40002's
 * floor), still puts two samples in the shortest window the register map
 * allows.
 */
#define MEAS_SAMPLE_HZ 40u

/* The wiper and the divider are sampled on ALTERNATE ticks, so each runs at
 * MEAS_SAMPLE_HZ/2 = 20 Hz — twice what FR-E14 requires — while no single
 * main-loop pass ever pays for both.
 *
 * That is not tidiness. The Modbus receiver is polled from this same loop
 * against a single-byte USART register, so a pass that blocks for one character
 * time (11 bits / 9600 = 1.146 ms) loses a byte and FR-MB24 discards the frame.
 * Doing both samples in one pass cost ~1.48 ms and the DUT dropped 9.7 % of
 * requests, with 30009 unmoved because an overrun is not a CRC error. Apart,
 * the worst pass is we_sample at ~552 us. */
static bool sample_wiper_turn;

/** SysTick ticks per sampling interval. SysTick counts at the core clock. */
#define MEAS_SAMPLE_TICKS (FUNCONF_SYSTEM_CORE_CLOCK / MEAS_SAMPLE_HZ)

/** Ticks per millisecond, for converting 40002. */
#define MEAS_TICKS_PER_MS (FUNCONF_SYSTEM_CORE_CLOCK / 1000u)

static uint32_t t_window;        /**< SysTick when the current window opened */
static uint32_t t_sample;        /**< SysTick of the last sample pass */
static uint32_t window_ticks;    /**< the latched 40002 duration, in ticks */
static uint16_t window_ms_latched; /**< the 40002 value window_ticks came from */

/* Accumulator for the window in progress. Only VALID samples are summed; a
 * window that collected none publishes invalid, which is what drives the
 * FR-E07 machine in regs.c. Bound: 60 s at 20 Hz is 1200 samples, and
 * 1200 * 1023 = 1 227 600 — three orders of magnitude inside uint32_t. */
static uint32_t acc_sum;
static uint16_t acc_count;
static uint16_t acc_last_raw;    /**< most recent valid raw, for FR-E09 */

/* -------------------------------------------------------------------------- */

/**
 * @brief Latch 40002 and (re)start the window clock from @p now.
 */
static void window_restart(uint32_t now)
{
	window_ms_latched = regs_window_ms();
	window_ticks = (uint32_t)window_ms_latched * MEAS_TICKS_PER_MS;
	t_window = now;
	acc_sum = 0;
	acc_count = 0;
}

void meas_open_init(void)
{
	uint32_t now = SysTick->CNT;
	window_restart(now);
	t_sample = now;
}

void meas_open_service(void)
{
	uint32_t now = SysTick->CNT;

	/* FR-S30: a valid write to 40002 aborts the window in progress. The
	 * partial result is discarded rather than published short, and status
	 * bit 0 re-asserts until the new window completes. Detected by comparing
	 * against the LATCHED value, not by asking regs.c whether it changed —
	 * this layer owns the window, so it owns noticing. */
	if (regs_window_ms() != window_ms_latched) {
		regs_window_aborted();
		window_restart(now);
		return;
	}

	/* ---- sampling cadence ------------------------------------------- */
	if ((uint32_t)(now - t_sample) >= MEAS_SAMPLE_TICKS) {
		t_sample += MEAS_SAMPLE_TICKS;

		sample_wiper_turn = !sample_wiper_turn;

		if (sample_wiper_turn) {
			/* The wiper accumulates across the window. An untrusted sample
			 * is dropped, not counted — one bad conversion should not poison
			 * a window, and a window with NO good sample is what legitimately
			 * signals a fault. */
			uint16_t raw;
			if (we_sample(&raw)) {
				acc_sum += raw;
				acc_count++;
				acc_last_raw = raw;
			}
		} else {
			/* The divider publishes every time: there is nothing to average,
			 * and regs_publish_switches does its own FR-E15 debounce from
			 * elapsed time, so it wants a steady cadence. */
			uint16_t sw_raw;
			if (we_switch_sample(&sw_raw))
				regs_publish_switches(sw_raw);
		}
	}

	/* ---- window close ------------------------------------------------ */
	if ((uint32_t)(now - t_window) >= window_ticks) {
		t_window += window_ticks;

		if (acc_count > 0u) {
			uint16_t mean = (uint16_t)(acc_sum / acc_count);
			/* 30005 reports the raw code for THIS window (FR-E09). The mean
			 * is the honest answer: it is what 30001 was derived from, and
			 * reporting the last instantaneous sample instead would leave a
			 * diagnostic register that disagrees with the measurement it is
			 * supposed to explain. */
			regs_publish_opening(mean, regs_scale_opening(mean), true);
		} else {
			/* No trustworthy sample all window. regs.c holds the last value
			 * for 2 s and then reports the 65535 sentinel with status bit 2
			 * (FR-E07); that timer is deliberately not duplicated here.
			 * acc_last_raw is passed through so 30005 still shows the last
			 * code the front-end produced, which is a diagnostic even when
			 * — especially when — it is not trustworthy. */
			regs_publish_opening(acc_last_raw, 0u, false);
		}

		acc_sum = 0;
		acc_count = 0;
	}
}
