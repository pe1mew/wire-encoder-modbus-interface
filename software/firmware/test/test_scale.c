/*
 * Host test for the FR-E04 opening scaling and the FR-E20 percentage —
 * compiles the SHIPPED code
 * (../src/scale.c), not a copy of it.
 *
 * Build and run (any host compiler; MinGW on this bench):
 *     gcc -O2 -Wall -Wextra -I../src -o test_scale test_scale.c ../src/scale.c
 *     ./test_scale
 *
 * Why this test exists at all: scale_opening() is the most error-prone code in
 * the firmware — a sign-aware linear map with clamping at both ends and an
 * overflow bound with 0.0046 % of headroom. It also has no hardware dependency,
 * so there is no excuse for not testing it. An earlier hand calculation of the
 * overflow product was wrong by ~393 000 and overstated the margin threefold;
 * this test is what caught it.
 *
 * Covered: both mounting senses, the offset behaviour at and beyond each
 * calibration point, the overflow corners, the minimum legal span, the
 * unreachability of the 65535 fault sentinel, and monotonicity swept across the
 * entire 10-bit ADC range in both senses — plus the FR-E20 percentage helper at
 * its clamps, with an offset, and swept for monotonicity.
 */

#include <stdio.h>
#include <stdint.h>
#include "scale.h"

static int fails;

static void ck(const char *name, uint32_t got, uint32_t want)
{
	if (got == want) {
		printf("ok   %-44s %u\n", name, (unsigned)got);
	} else {
		printf("FAIL %-44s got %u, want %u\n", name, (unsigned)got,
		       (unsigned)want);
		fails++;
	}
}

/* Sweep every ADC code from closed to open and confirm the result never
 * decreases. Monotonicity is what a positioning loop depends on. */
static int monotonic(uint16_t offset, uint16_t travel, uint16_t rc, uint16_t ro)
{
	uint32_t prev = 0;
	int first = 1;
	for (int i = 0; i <= 1023; i++) {
		uint16_t raw = (ro > rc) ? (uint16_t)i : (uint16_t)(1023 - i);
		uint32_t v = scale_opening(raw, offset, travel, rc, ro);
		if (!first && v < prev)
			return 0;
		prev = v;
		first = 0;
	}
	return 1;
}

int main(void)
{
	/* ---- the M3 greenhouse case: 2 m stroke, 10-bit ADC ---- */
	ck("M3 normal: closed",        scale_opening(0,    0, 20000, 0, 1023), 0);
	ck("M3 normal: fully open",    scale_opening(1023, 0, 20000, 0, 1023), 20000);
	ck("M3 normal: mid-travel",    scale_opening(511,  0, 20000, 0, 1023), 9990);

	/* ---- the same window with the draw-wire mounted the other way ---- */
	ck("M3 reversed: closed",      scale_opening(1023, 0, 20000, 1023, 0), 0);
	ck("M3 reversed: fully open",  scale_opening(0,    0, 20000, 1023, 0), 20000);
	ck("M3 reversed: mid-travel",  scale_opening(512,  0, 20000, 1023, 0), 9990);

	/* ---- offset: no step at the calibration point, clamps at both ends ---- */
	ck("offset: at closed point",       scale_opening(100,  500, 20000, 100, 900), 500);
	ck("offset: below closed, no step", scale_opening(99,   500, 20000, 100, 900), 500);
	ck("offset: at open point",         scale_opening(900,  500, 20000, 100, 900), 20500);
	ck("offset: above open, clamped",   scale_opening(1023, 500, 20000, 100, 900), 20500);

	/* ---- reversed and offset together ---- */
	ck("rev+offset: at closed",         scale_opening(900,  500, 20000, 900, 100), 500);
	ck("rev+offset: above closed",      scale_opening(901,  500, 20000, 900, 100), 500);
	ck("rev+offset: at open",           scale_opening(100,  500, 20000, 900, 100), 20500);
	ck("rev+offset: below open, clamp", scale_opening(0,    500, 20000, 900, 100), 20500);

	/* ---- overflow corners: the largest legal operands ---- */
	ck("overflow: max raw, max travel", scale_opening(65535, 0, 65534, 0, 65535), 65534);
	ck("overflow: one below max",       scale_opening(65534, 0, 65534, 0, 65535), 65533);

	/* ---- the minimum legal calibration span (FR-E06) ---- */
	ck("min span: at open",             scale_opening(64, 0, 65534, 0, CAL_MIN_SPAN), 65534);
	ck("min span: one count in",        scale_opening(1,  0, 65534, 0, CAL_MIN_SPAN), 1023);

	/* ---- the FR-E07 sentinel must be unreachable by a healthy reading ---- */
	ck("65535 sentinel unreachable",    scale_opening(1023, 65534, 65534, 0, 1023), 65534);

	/* ---- monotonicity across the whole ADC range, both senses ---- */
	ck("monotonic sweep (normal)",      (uint32_t)monotonic(250, 20000, 100, 900), 1);
	ck("monotonic sweep (reversed)",    (uint32_t)monotonic(250, 20000, 900, 100), 1);

	/* ---- cal_span is order-independent ---- */
	ck("cal_span symmetric",            cal_span(100, 900) == cal_span(900, 100), 1);

	/* ---- FR-E20 percentage of travel ---- */
	ck("pct: at closed point",          scale_percent(0,     0, 20000), 0);
	ck("pct: at full travel",           scale_percent(20000, 0, 20000), 1000);
	ck("pct: midpoint",                 scale_percent(10000, 0, 20000), 500);
	ck("pct: with offset, at closed",   scale_percent(500, 500, 20000), 0);
	ck("pct: with offset, at open",     scale_percent(20500, 500, 20000), 1000);
	ck("pct: with offset, midpoint",    scale_percent(10500, 500, 20000), 500);
	ck("pct: below offset clamps to 0", scale_percent(0,   500, 20000), 0);
	ck("pct: above travel clamps",      scale_percent(65534, 0, 20000), 1000);
	ck("pct: halving travel doubles",   scale_percent(5000,  0, 10000), 500);
	ck("pct: fault sentinel clamps",    scale_percent(65535, 0, 20000), 1000);
	ck("pct: travel=0 guarded",         scale_percent(1000,  0, 0), 0);
	ck("pct: max operands no overflow", scale_percent(65534, 0, 1), 1000);

	/* percentage must be monotonic in the opening, like the opening itself */
	{
		uint32_t prev = 0; int mono = 1;
		for (uint32_t o = 500; o <= 20500; o += 7) {
			uint32_t v = scale_percent((uint16_t)o, 500, 20000);
			if (v < prev) { mono = 0; break; }
			prev = v;
		}
		ck("pct: monotonic sweep", (uint32_t)mono, 1);
	}

	printf("\n%s\n", fails ? "*** FAILURES ***" : "all corners pass");
	return fails != 0;
}
