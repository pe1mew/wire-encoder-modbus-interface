/*
 * Host test for the FR-E23/FR-E24 sensing-health indications — compiles the
 * SHIPPED code (../src/health.c), not a copy of it.
 *
 * Build and run (MinGW shipped with Code::Blocks on this bench):
 *     "C:/Program Files/CodeBlocks/MinGW/bin/gcc.exe" -O2 -Wall -Wextra \
 *         -I../src -o test_health test_health.c ../src/health.c
 *     ./test_health
 *
 * Why this test exists: both checks are state machines whose failure mode is
 * silence or a false alarm, neither of which is visible on a bench where the
 * window is working. And each has one property that is easy to get wrong and
 * produces a plausible-looking result when you do:
 *
 *   1. FR-E24 must be SELF-DISABLING on a full-range calibration. If the margin
 *      arithmetic underflows, the band inverts and every code reads as
 *      implausible — a firmware bug that looks like a field fault.
 *   2. FR-E23 must not count a window ROCKING on its stop as a departure. The
 *      sensor's hysteresis is one to two ADC counts, so a rocking window and a
 *      frozen wiper produce nearly identical excursions; only the time spent
 *      away separates them.
 *   3. FR-E23 must measure excursion across the WHOLE sequence, not end to end.
 *      A carriage that travels out and returns shows no end-to-end difference
 *      while having plainly moved.
 */

#include <stdint.h>
#include <stdio.h>

#include "health.h"

static int failures;

static void check(const char *name, int got, int want)
{
	int ok = (got == want);
	printf("%s %-64s got %d\n", ok ? "ok  " : "FAIL", name, got);
	if (!ok) {
		printf("     wanted %d\n", want);
		failures++;
	}
}

/* Helpers: a "window" is one call to health_note_window at a fixed calibration. */
static uint16_t cal_lo = 300, cal_hi = 700, win_ms = 1000;

static void windows(uint16_t raw, int n)
{
	for (int i = 0; i < n; i++) {
		health_note_window(raw, cal_lo, cal_hi, win_ms);
		health_note_raw(raw);
	}
}

static void at_stop(uint16_t raw) { health_note_switch(HEALTH_SW_AT_STOP, raw, win_ms); }
static void off_stop(uint16_t raw) { health_note_switch(HEALTH_SW_CLEAR, raw, win_ms); }

/* One departure: leave a stop, spend `away` windows travelling to `far`, return. */
static void departure(uint16_t at, uint16_t far, int away)
{
	off_stop(at);
	windows(far, away);
	at_stop(far);
}

int main(void)
{
	/* ---- FR-E24: the band --------------------------------------------- */
	health_init();
	cal_lo = 300; cal_hi = 700;          /* span 400, margin 100 -> [200, 800] */
	windows(500, 4);
	check("mid-band code is plausible", health_raw_implausible(), 0);

	windows(150, 1);
	check("one window outside the band does not report yet",
	      health_raw_implausible(), 0);
	windows(150, 1);
	check("two windows outside the band reports (>=2 x 40002)",
	      health_raw_implausible(), 1);
	windows(500, 1);
	check("returning inside clears it immediately", health_raw_implausible(), 0);

	health_init();
	windows(199, 2);
	check("just below the low edge (199 < 200) reports",
	      health_raw_implausible(), 1);
	health_init();
	windows(200, 4);
	check("exactly on the low edge (200) does NOT report",
	      health_raw_implausible(), 0);
	health_init();
	windows(801, 2);
	check("just above the high edge (801 > 800) reports",
	      health_raw_implausible(), 1);

	/* THE SELF-DISABLING PROPERTY. This is the one that must not regress:
	 * on a full-range calibration the band covers every reachable code, so the
	 * check is inert -- which is what lets it need no "was taught" flag. */
	health_init();
	cal_lo = 0; cal_hi = 1023;           /* the factory default */
	windows(0, 8);
	check("factory default: raw 0 is NOT implausible", health_raw_implausible(), 0);
	windows(1023, 8);
	check("factory default: raw 1023 is NOT implausible",
	      health_raw_implausible(), 0);

	/* The margin must saturate, not wrap. cal_lo=10 gives margin 250, and
	 * 10 - 250 must clamp at 0 rather than becoming a huge unsigned value that
	 * would make every code implausible. */
	health_init();
	cal_lo = 10; cal_hi = 1010;
	windows(0, 8);
	check("low band saturates at 0 instead of underflowing",
	      health_raw_implausible(), 0);

	/* A reversed mounting (FR-E04 allows 40006 < 40005) uses the same band. */
	health_init();
	cal_lo = 700; cal_hi = 300;          /* deliberately inverted */
	windows(500, 4);
	check("reversed calibration: mid-band still plausible",
	      health_raw_implausible(), 0);
	windows(150, 2);
	check("reversed calibration: outside the band still reports",
	      health_raw_implausible(), 1);

	/* ---- FR-E23: the departure sequence -------------------------------- */
	health_init();
	cal_lo = 300; cal_hi = 700; win_ms = 1000;

	/* A healthy traverse: the wiper sweeps hundreds of counts each time. */
	at_stop(320);
	for (int i = 0; i < 4; i++) {
		departure(320, 680, 3);
		departure(680, 320, 3);
	}
	check("healthy traverses never report a stuck position",
	      health_position_stuck(), 0);

	/* A stuck wiper: switches transition, the raw code does not move. */
	health_init();
	at_stop(500);
	departure(500, 500, 3);
	check("one stuck departure is not enough", health_position_stuck(), 0);
	departure(500, 500, 3);
	check("two stuck departures are not enough", health_position_stuck(), 0);
	departure(500, 500, 3);
	check("THREE consecutive stuck departures report", health_position_stuck(), 1);

	/* One good sequence clears it — a mechanism that starts working again
	 * should stop being reported at once. */
	departure(500, 680, 3);
	check("a single good departure clears it", health_position_stuck(), 0);

	/* A run of stuck departures broken by a good one must restart the count. */
	health_init();
	at_stop(500);
	departure(500, 500, 3);
	departure(500, 500, 3);
	departure(500, 690, 3);              /* good: resets */
	departure(690, 690, 3);
	departure(690, 690, 3);
	check("the count restarts after a good sequence", health_position_stuck(), 0);
	departure(690, 690, 3);
	check("...and reports on the third consecutive one", health_position_stuck(), 1);

	/* A WINDOW ROCKING ON ITS STOP. The switch makes and breaks with almost no
	 * movement, exactly like a stuck wiper -- only the time away separates
	 * them. Away for fewer than AWAY_WINDOWS, so these are not departures. */
	health_init();
	at_stop(500);
	for (int i = 0; i < 10; i++) {
		off_stop(500);
		windows(501, 1);                 /* away for ONE window only */
		at_stop(500);
	}
	check("a rocking window is never counted as a departure",
	      health_position_stuck(), 0);

	/* EXCURSION IS MEASURED ACROSS THE WHOLE SEQUENCE, not end to end. The
	 * carriage leaves a stop, travels far, and returns to the same code. End
	 * to end that is zero movement; across the sequence it is hundreds. */
	health_init();
	at_stop(320);
	off_stop(320);
	windows(680, 3);                     /* travelled a long way */
	at_stop(320);                        /* ...and came back to the same code */
	off_stop(320);
	windows(680, 3);
	at_stop(320);
	off_stop(320);
	windows(680, 3);
	at_stop(320);
	check("out-and-back is movement, not a stuck wiper",
	      health_position_stuck(), 0);

	/* The two checks are independent: a stuck wiper inside the band sets only
	 * bit 7, and that is the signature of a mechanical failure. */
	health_init();
	at_stop(500);
	departure(500, 500, 3);
	departure(500, 500, 3);
	departure(500, 500, 3);
	check("mechanism stuck: bit 7 set", health_position_stuck(), 1);
	check("mechanism stuck: bit 6 CLEAR (the code is still reachable)",
	      health_raw_implausible(), 0);

	/* ...while a shorted conductor sets both, which is the dead-path signature. */
	health_init();
	at_stop(0);
	departure(0, 0, 3);
	departure(0, 0, 3);
	departure(0, 0, 3);
	check("shorted to 0 V: bit 7 set", health_position_stuck(), 1);
	check("shorted to 0 V: bit 6 also set", health_raw_implausible(), 1);

	printf("\n");
	if (failures) {
		printf("%d FAILED\n", failures);
		return 1;
	}
	printf("all health tests pass\n");
	return 0;
}
