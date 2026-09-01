/**
 * @file avg.c
 * @brief Averaging engine — implementation of @ref avg.h.
 *
 * @note The outputs are RECOMPUTED from the ring on every push rather than
 *       updated incrementally. That is deliberate: an incremental minimum has
 *       to detect when the current minimum leaves the window and rescan anyway,
 *       which is the same cost with a failure mode. 64 slots at ≤20 Hz is about
 *       1300 comparisons a second — nothing beside the ADC work in the same
 *       loop, and far inside the 1.146 ms per-pass blocking budget.
 */
#include "avg.h"

/** Ring capacity. FR-S31 bounds storage at 64 entries per quantity. */
#define AVG_SLOTS 64u

static uint16_t slot_mean[AVG_SLOTS];
static uint16_t slot_min[AVG_SLOTS];
static uint16_t slot_max[AVG_SLOTS];

static uint8_t slots;        /**< slots in use, 1..AVG_SLOTS */
static uint8_t block_size;   /**< windows aggregated per slot, >=1 */
static uint8_t head;         /**< next slot to write */
static uint8_t count;        /**< slots written, saturating at `slots` */

/* The block being accumulated. Carries its own min and max: a block that kept
 * only a mean would hide the excursion FR-E08 exists to report. */
static uint32_t part_sum;
static uint16_t part_min;
static uint16_t part_max;
static uint8_t part_n;

/* Published values, recomputed on each push. */
static uint16_t out_mean;
static uint16_t out_min;
static uint16_t out_max;

/* -------------------------------------------------------------------------- */

static void reset_partial(void)
{
	part_sum = 0;
	part_min = 0xFFFFu;
	part_max = 0;
	part_n = 0;
}

void avg_config(uint16_t window_ms, uint16_t avg_s)
{
	/* N = floor(40003 x 1000 / 40002), at least 1. FR-S31 owns this formula;
	 * the register ranges make N as large as 600 000 / 100 = 6000. */
	uint32_t n = 1;
	if (window_ms > 0u)
		n = ((uint32_t)avg_s * 1000u) / (uint32_t)window_ms;
	if (n < 1u)
		n = 1u;

	/* Block size ceil(N/64), so the ring never needs more than 64 slots.
	 * At N <= 64 this is 1 and the ring is an exact boxcar. */
	uint32_t b = (n + AVG_SLOTS - 1u) / AVG_SLOTS;
	if (b < 1u)
		b = 1u;
	uint32_t s = (n + b - 1u) / b;
	if (s > AVG_SLOTS)
		s = AVG_SLOTS;
	if (s < 1u)
		s = 1u;

	block_size = (uint8_t)b;
	slots = (uint8_t)s;
	head = 0;
	count = 0;
	out_mean = 0;
	out_min = 0;
	out_max = 0;
	reset_partial();
}

void avg_push(uint16_t open_0_1mm)
{
	if (slots == 0u)                 /* avg_config not called yet */
		avg_config(1000u, 10u);

	part_sum += open_0_1mm;
	part_n++;
	if (open_0_1mm < part_min)
		part_min = open_0_1mm;
	if (open_0_1mm > part_max)
		part_max = open_0_1mm;

	if (part_n >= block_size) {
		slot_mean[head] = (uint16_t)(part_sum / part_n);
		slot_min[head] = part_min;
		slot_max[head] = part_max;
		head = (uint8_t)((head + 1u) % slots);
		if (count < slots)
			count++;
		reset_partial();
	}

	/* ---- recompute the published values ------------------------------
	 * Complete blocks are weighted by block_size, because each represents
	 * that many windows; the block in progress contributes its raw sum and
	 * its own count. Dividing by the ACTUAL number of windows accumulated —
	 * never by N — is what FR-S23's no-zero-padding rule requires.
	 *
	 * Bound: 64 slots x 65534 x block_size(<=94) is about 394 million, plus a
	 * partial sum under 6.2 million. Inside uint32_t by an order of magnitude.
	 */
	uint32_t total = 0;
	uint32_t windows = 0;
	uint16_t lo = 0xFFFFu;
	uint16_t hi = 0;

	for (uint8_t i = 0; i < count; i++) {
		total += (uint32_t)slot_mean[i] * block_size;
		windows += block_size;
		if (slot_min[i] < lo)
			lo = slot_min[i];
		if (slot_max[i] > hi)
			hi = slot_max[i];
	}
	if (part_n > 0u) {
		total += part_sum;
		windows += part_n;
		if (part_min < lo)
			lo = part_min;
		if (part_max > hi)
			hi = part_max;
	}

	if (windows > 0u) {
		out_mean = (uint16_t)(total / windows);
		out_min = lo;
		out_max = hi;
	}
}

bool avg_filled(void)
{
	return count >= slots;
}

uint16_t avg_mean(void)
{
	return out_mean;
}

uint16_t avg_min(void)
{
	return out_min;
}

uint16_t avg_max(void)
{
	return out_max;
}
