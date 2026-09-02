/**
 * @file health.c
 * @brief Sensing-health indications — implementation of @ref health.h.
 *
 * No hardware, no SysTick, no register access. Time is counted in measurement
 * windows supplied by the caller, so every branch is reachable from a host
 * test.
 */
#include "health.h"

/* ---- FR-E24: the plausible band -------------------------------------------
 * A raw code outside [raw_closed - M, raw_open + M], M = 25 % of the span.
 *
 * The margin exists because the window legitimately travels beyond both end
 * sensors: the sensors mark the ends of the OPENING RANGE, not of travel
 * (description.md §8.1). 25 % of span is more overtravel than any installation
 * should have.
 *
 * SELF-DISABLING, WHICH IS THE POINT. Where the calibrated span approaches the
 * full ADC range the band covers every reachable code and this never reports.
 * That happens on the factory default (0/1023, band [-256, 1279]) and on any
 * draw-wire sized so its ends coincide with the window's — which is exactly the
 * installation §8.1 tells you not to build, because in it a shorted conductor
 * produces the reading of a correctly closed window and NOTHING can separate
 * them. So the check needs no "was taught" flag and no persisted state: the
 * arithmetic disables it wherever it could not work anyway.
 */
#define BAND_MARGIN_NUM 1u   /* M = span / 4 */
#define BAND_MARGIN_DEN 4u

/* ---- FR-E23: the departure sequence ---------------------------------------
 * at-a-stop -> not-at-a-stop -> at-a-stop, middle state >= 2 windows.
 */
#define STUCK_EXCURSION 16u  /* counts; ~1.5 % of the 10-bit range */
#define STUCK_SEQUENCES 3u   /* consecutive low-excursion sequences to report */
#define AWAY_WINDOWS    2u   /* the middle state must last this many windows */

/* FR-E24 state */
static uint16_t implausible_windows;
static bool bit_implausible;

/* FR-E23 state */
typedef enum {
	SEQ_IDLE = 0,   /**< not at a stop, or nothing seen yet */
	SEQ_AT_STOP,    /**< at a stop; a departure may begin */
	SEQ_AWAY,       /**< left a stop; waiting to reach one again */
} seq_t;

static seq_t seq;
static uint16_t away_windows;   /**< windows elapsed in SEQ_AWAY */
static uint16_t seq_lo, seq_hi; /**< raw excursion across the whole sequence */
static uint8_t low_sequences;   /**< consecutive sequences under the threshold */
static bool bit_stuck;

/* -------------------------------------------------------------------------- */

void health_init(void)
{
	implausible_windows = 0;
	bit_implausible = false;
	seq = SEQ_IDLE;
	away_windows = 0;
	seq_lo = 0xFFFFu;
	seq_hi = 0;
	low_sequences = 0;
	bit_stuck = false;
}

static void seq_track(uint16_t raw)
{
	if (raw < seq_lo)
		seq_lo = raw;
	if (raw > seq_hi)
		seq_hi = raw;
}

static void seq_restart(uint16_t raw)
{
	seq_lo = raw;
	seq_hi = raw;
	away_windows = 0;
}

void health_note_raw(uint16_t raw)
{
	/* Only while a sequence is in flight. Outside one the extremes are
	 * meaningless and would carry stale range into the next sequence. */
	if (seq == SEQ_AT_STOP || seq == SEQ_AWAY)
		seq_track(raw);
}

void health_note_switch(health_sw_t sw, uint16_t raw, uint16_t window_ms)
{
	(void)window_ms; /* timing is counted in windows by health_note_window */

	switch (seq) {
	case SEQ_IDLE:
		if (sw == HEALTH_SW_AT_STOP) {
			seq = SEQ_AT_STOP;
			seq_restart(raw);
		}
		break;

	case SEQ_AT_STOP:
		if (sw == HEALTH_SW_CLEAR) {
			seq = SEQ_AWAY;
			away_windows = 0;
			seq_track(raw);
		}
		break;

	case SEQ_AWAY:
		if (sw != HEALTH_SW_AT_STOP)
			break;
		seq_track(raw);

		/* A complete departure sequence — but only if the carriage was away
		 * long enough to have gone somewhere. A brief release and re-make is
		 * switch chatter or a window rocking on its stop, not a departure, and
		 * counting it would let a rocking window look like a stuck wiper. */
		if (away_windows >= AWAY_WINDOWS) {
			uint16_t excursion = (uint16_t)(seq_hi - seq_lo);
			if (excursion < STUCK_EXCURSION) {
				if (low_sequences < STUCK_SEQUENCES)
					low_sequences++;
				if (low_sequences >= STUCK_SEQUENCES)
					bit_stuck = true;
			} else {
				/* The wiper moved. One good sequence clears it: this is a
				 * health indication, and a mechanism that has started working
				 * again should stop being reported immediately. */
				low_sequences = 0;
				bit_stuck = false;
			}
		}
		/* Either way we are at a stop again, which is where the next sequence
		 * begins. */
		seq = SEQ_AT_STOP;
		seq_restart(raw);
		break;
	}
}

void health_note_window(uint16_t raw, uint16_t raw_closed, uint16_t raw_open,
                        uint16_t window_ms)
{
	(void)window_ms;

	if (seq == SEQ_AWAY && away_windows < 0xFFFFu)
		away_windows++;

	/* ---- FR-E24 ---------------------------------------------------------
	 * Span as a magnitude: 40006 may legally be below 40005 for a reversed
	 * mounting (FR-E04), and the band is the same either way.
	 */
	uint16_t lo_cal = (raw_closed < raw_open) ? raw_closed : raw_open;
	uint16_t hi_cal = (raw_closed < raw_open) ? raw_open : raw_closed;
	uint32_t span = (uint32_t)(hi_cal - lo_cal);
	uint32_t margin = (span * BAND_MARGIN_NUM) / BAND_MARGIN_DEN;

	/* Saturating, not wrapping: a band that underflowed to a huge unsigned
	 * value would report every code as implausible, which is the opposite of
	 * this check's intent and exactly the kind of failure that looks like a
	 * firmware bug in the field. */
	uint32_t lo_band = (margin >= (uint32_t)lo_cal) ? 0u
	                                                : (uint32_t)lo_cal - margin;
	uint32_t hi_band = (uint32_t)hi_cal + margin;

	bool outside = ((uint32_t)raw < lo_band) || ((uint32_t)raw > hi_band);
	if (outside) {
		if (implausible_windows < 0xFFFFu)
			implausible_windows++;
		if (implausible_windows >= AWAY_WINDOWS)
			bit_implausible = true;
	} else {
		implausible_windows = 0;
		bit_implausible = false;
	}
}

bool health_raw_implausible(void)
{
	return bit_implausible;
}

bool health_position_stuck(void)
{
	return bit_stuck;
}
