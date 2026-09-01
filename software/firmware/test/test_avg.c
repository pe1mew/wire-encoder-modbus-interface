/*
 * Host test for the stage E averaging engine — compiles the SHIPPED code
 * (../src/avg.c), not a copy of it.
 *
 * Build and run (any host compiler; MinGW on this bench):
 *     gcc -O2 -Wall -Wextra -I../src -o test_avg test_avg.c ../src/avg.c
 *     ./test_avg
 *
 * Why this test exists: the averaging engine has three properties that are easy
 * to get wrong, invisible on a bench where the opening barely moves, and each
 * of which produces a plausible-looking number:
 *
 *   1. FR-S23's no-zero-padding rule. A partial accumulator must divide by the
 *      windows ACTUALLY acquired, not by N. The TDS gives the exact case: a
 *      steady 500.0 mm with a 1 s window and 10 s averaging must read 5000 at
 *      t = 3 s, NOT the 1500 a zero-padded accumulator gives.
 *   2. FR-S31's two-stage blocking above 64 windows. Each block must weigh as
 *      block_size windows in the mean, or the average silently biases toward
 *      whatever is in the partial block.
 *   3. FR-E08's envelope through that blocking. A block that stored only its
 *      mean would report an envelope NARROWER than the movement that happened
 *      — which is precisely the excursion the registers exist to expose.
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "avg.h"

static int failures;

static void check(const char *name, uint32_t got, uint32_t want)
{
	int ok = (got == want);
	printf("%s %-62s got %lu\n", ok ? "ok  " : "FAIL", name,
	       (unsigned long)got);
	if (!ok) {
		printf("     wanted %lu\n", (unsigned long)want);
		failures++;
	}
}

static void check_near(const char *name, uint32_t got, uint32_t want,
                       uint32_t tol)
{
	uint32_t d = got > want ? got - want : want - got;
	int ok = (d <= tol);
	printf("%s %-62s got %lu (want %lu +/-%lu)\n", ok ? "ok  " : "FAIL", name,
	       (unsigned long)got, (unsigned long)want, (unsigned long)tol);
	if (!ok)
		failures++;
}

int main(void)
{
	/* ---- FR-S23: the partial-window mean, exactly as the TDS states it ---- */
	avg_config(1000, 10);                     /* 1 s window, 10 s averaging */
	check("span not filled before any window", avg_filled(), 0);
	for (int i = 0; i < 3; i++)
		avg_push(5000);                       /* steady 500.0 mm */
	check("FR-S23: 3 of 10 windows at 5000 reads 5000, not the padded 1500",
	      avg_mean(), 5000);
	check("FR-S23: bit 1 still set after 3 of 10 windows", avg_filled(), 0);
	for (int i = 0; i < 7; i++)
		avg_push(5000);
	check("span filled after exactly 10 windows", avg_filled(), 1);
	check("mean still 5000 once filled", avg_mean(), 5000);

	/* ---- the boxcar rolls: old values must leave -------------------------- */
	avg_config(1000, 4);                      /* N = 4, exact */
	avg_push(1000); avg_push(1000); avg_push(1000); avg_push(1000);
	check("N=4 filled with 1000", avg_mean(), 1000);
	avg_push(5000); avg_push(5000); avg_push(5000); avg_push(5000);
	check("four 5000s displace all four 1000s", avg_mean(), 5000);
	check("envelope no longer remembers the departed 1000", avg_min(), 5000);

	/* ---- FR-E08: the envelope catches an excursion the mean hides --------- */
	avg_config(1000, 10);
	for (int i = 0; i < 9; i++)
		avg_push(1000);                       /* 100.0 mm */
	avg_push(8000);                           /* one excursion to 800.0 mm */
	check("FR-E08: max sees the excursion", avg_max(), 8000);
	check("FR-E08: min holds the resting value", avg_min(), 1000);
	check_near("mean is dragged only 1/10th by it", avg_mean(), 1700, 1);

	/* ---- FR-S31 two-stage: N > 64 ---------------------------------------- */
	/* 100 ms window, 20 s averaging -> N = 200, block size ceil(200/64) = 4,
	 * 50 slots, effective span 200. */
	avg_config(100, 20);
	for (int i = 0; i < 200; i++)
		avg_push(3000);
	check("N=200 blocked: steady 3000 averages to 3000", avg_mean(), 3000);
	check("N=200 blocked: span reports filled", avg_filled(), 1);

	/* An excursion inside ONE block must still reach the envelope. This is the
	 * property a block-mean-only design loses: 4 windows of which one is 9000
	 * has a block mean of 4500, and an envelope built from block means would
	 * report 4500 as the maximum instead of 9000. */
	avg_config(100, 20);
	for (int i = 0; i < 199; i++)
		avg_push(1000);
	avg_push(9000);
	check("FR-E08 through blocking: max is the SAMPLE, not the block mean",
	      avg_max(), 9000);
	check("FR-E08 through blocking: min unaffected", avg_min(), 1000);

	/* ---- the blocked mean must weigh blocks correctly --------------------- */
	/* Half the span at 2000, half at 4000 -> 3000 regardless of blocking. */
	avg_config(100, 20);                      /* N = 200, block 4 */
	for (int i = 0; i < 100; i++)
		avg_push(2000);
	for (int i = 0; i < 100; i++)
		avg_push(4000);
	check_near("blocked mean weighs each block as block_size windows",
	           avg_mean(), 3000, 2);

	/* ---- degenerate and boundary configurations -------------------------- */
	avg_config(60000, 1);                     /* N = 0 -> clamped to 1 */
	avg_push(1234);
	check("N clamps to 1 when the averaging period is shorter than the window",
	      avg_mean(), 1234);
	check("N=1 fills immediately", avg_filled(), 1);

	avg_config(1000, 64);                     /* N = 64, the exact/blocked edge */
	for (int i = 0; i < 64; i++)
		avg_push(7000);
	check("N=64 is still an exact boxcar and fills at 64", avg_filled(), 1);
	check("N=64 mean", avg_mean(), 7000);

	avg_config(100, 600);                     /* N = 6000, the register maximum */
	for (int i = 0; i < 6000; i++)
		avg_push(65534);                      /* worst case for overflow */
	check("N=6000 at full scale does not overflow", avg_mean(), 65534);
	check("N=6000 envelope at full scale", avg_max(), 65534);

	/* ---- a reconfigure must forget everything (FR-S30/FR-E05) ------------- */
	avg_config(1000, 10);
	for (int i = 0; i < 10; i++)
		avg_push(9000);
	check("filled before reconfigure", avg_filled(), 1);
	avg_config(1000, 10);
	check("reconfigure clears the filled flag", avg_filled(), 0);
	check("reconfigure clears the mean", avg_mean(), 0);
	avg_push(100);
	check("first window after reconfigure stands alone, unseeded",
	      avg_mean(), 100);

	printf("\n");
	if (failures) {
		printf("%d FAILED\n", failures);
		return 1;
	}
	printf("all averaging tests pass\n");
	return 0;
}
