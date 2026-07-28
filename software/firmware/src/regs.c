#include "persist.h"
#include "regs.h"
#include "sensors.h" /* BUILD_TYPE + WE_RAW_MAX_DEFAULT */
#include "version.h"
#ifdef HAVE_END_SWITCH
#include "board.h"   /* board_end_switch_active (FR-E14) */
#include "ch32fun.h" /* SysTick->CNT for the FR-E15 debounce */
#endif

/* ---- Holding registers (TDS §2.8: raw addr, min, max, default) ---- */

static uint16_t h_offset = 0;     /* 40001: 0..65534    */
static uint16_t h_window = 1000;  /* 40002: 100..60000  */
static uint16_t h_avg = 10;       /* 40003: 1..600 + FR-S31 */
static uint16_t h_travel = 10000; /* 40004: 1..65534 (= 1000.0 mm) */

/* Two-point raw calibration (FR-E05): the compile-time values below are the
 * FACTORY DEFAULTS; the running values are runtime-writable via 40005/40006 and
 * persisted (FR-S39), so one image serves any window and any wire routing with
 * no rebuild. FR-E04 opening:
 *   open_0.1mm = offset + ((raw - raw_closed) * travel) / (raw_open - raw_closed)
 * The FR-E06 cross-check (raw_open > raw_closed) is what keeps that divisor
 * sane. Defaults span the full 10-bit ADC range; a real installation calibrates
 * by closing the window, writing 40005 from 30005, opening it fully, and
 * writing 40006 the same way. */
#ifndef RAW_CLOSED_DEFAULT
#define RAW_CLOSED_DEFAULT 0
#endif
#ifndef RAW_OPEN_DEFAULT
#define RAW_OPEN_DEFAULT WE_RAW_MAX_DEFAULT /* 10-bit ADC full scale, sensors.h */
#endif
_Static_assert(RAW_OPEN_DEFAULT > RAW_CLOSED_DEFAULT,
               "default raw_open must exceed raw_closed (FR-E06) — else a fresh "
               "device boots with a degenerate calibration");
_Static_assert(RAW_OPEN_DEFAULT >= 1 && RAW_OPEN_DEFAULT <= 65535,
               "default raw_open must fit the 40006 range");
static uint16_t h_raw_closed = RAW_CLOSED_DEFAULT; /* 40005: 0..65534 */
static uint16_t h_raw_open = RAW_OPEN_DEFAULT;     /* 40006: 1..65535 */

#ifdef TEST_HOOKS
static uint16_t test_hang;       /* 0x00FF, TEST builds only (FR-S20 hook) */
#endif

static const mb_holding_t holdings[] = {
	{0x0000, 0, 65534, &h_offset},     /* 40001 zero offset (0.1 mm)      */
	{0x0001, 100, 60000, &h_window},   /* 40002 measurement window (ms)   */
	{0x0002, 1, 600, &h_avg},          /* 40003 averaging window (s)      */
	{0x0003, 1, 65534, &h_travel},     /* 40004 full travel (0.1 mm)      */
	{0x0004, 0, 65534, &h_raw_closed}, /* 40005 raw code, window closed   */
	{0x0005, 1, 65535, &h_raw_open},   /* 40006 raw code, fully open      */
#ifdef TEST_HOOKS
	{0x00FF, 0, 0xFFFF, &test_hang},
#endif
};

/* Cross-register constraints, evaluated against the STAGED pair so an FC16 that
 * moves both halves of a constraint at once is judged on its result, not on the
 * intermediate state (FR-MB22 atomicity):
 *   FR-S31: (40003 s × 1000) ≥ 40002 ms
 *   FR-E06: 40006 > 40005 */
static bool cross_validate(const uint16_t *addrs, const uint16_t *vals,
                           uint8_t n)
{
	uint16_t window = h_window;
	uint16_t avg = h_avg;
	uint16_t raw_closed = h_raw_closed;
	uint16_t raw_open = h_raw_open;
	for (uint8_t i = 0; i < n; i++) {
		if (addrs[i] == 0x0001)
			window = vals[i];
		if (addrs[i] == 0x0002)
			avg = vals[i];
		if (addrs[i] == 0x0004)
			raw_closed = vals[i];
		if (addrs[i] == 0x0005)
			raw_open = vals[i];
	}
	return (uint32_t)avg * 1000u >= window && raw_open > raw_closed;
}

/* ---- Input-register state (TDS §2.7) ---- */

static uint16_t r_open_inst;     /* 30001 instantaneous opening (0.1 mm)  */
static uint16_t r_open_avg;      /* 30002 averaged opening (stage E)      */
static uint16_t r_open_min;      /* 30003 window minimum (stage E)        */
static uint16_t r_open_max;      /* 30004 window maximum (stage E)        */
static uint16_t r_raw;           /* 30005 raw ADC code (FR-E09)           */
static uint16_t r_status;        /* 30006 bitfield (FR-S33)               */
static uint16_t r_uptime_s;      /* 30008 saturating (FR-S34)             */
static uint16_t r_reading_age_s; /* 30011 (FR-S36)                        */
static uint16_t r_rate;          /* 30012 movement rate (FR-E10)          */

#define STATUS_FIRST_WINDOW_INCOMPLETE 0x0001 /* bit 0 (FR-S23/S30) */
#define STATUS_AVG_NOT_FILLED          0x0002 /* bit 1 (FR-S23/S30) */
#define STATUS_SENSOR_FAULT            0x0004 /* bit 2 (FR-E07)     */
#define STATUS_END_SWITCH              0x0008 /* bit 3 (FR-E14)     */

#define OPEN_FAULT_SENTINEL 65535u /* §2.7 — reported by 30001..30004 */
#define FAULT_HOLD_S        2u     /* FR-E07: hold the last value this long */

/* FR-E07 fault machine state. `invalid_s` counts whole seconds of consecutive
 * invalid samples (advanced by regs_second_tick); the sentinel is published
 * only once it exceeds FAULT_HOLD_S, so a single dropped sample is invisible to
 * the master. */
static uint16_t invalid_s;
static bool     sample_invalid;
static bool     have_prev_open; /* FR-E10 needs two windows before a rate */
static uint16_t prev_open;

static uint16_t input_read(uint16_t addr, bool *ok)
{
	switch (addr) {
	case 0x0000: return r_open_inst;
	case 0x0001: return r_open_avg;
	case 0x0002: return r_open_min;
	case 0x0003: return r_open_max;
	case 0x0004: return r_raw;
	case 0x0005: return r_status;
	case 0x0006: return (uint16_t)((BUILD_TYPE << 8) | FW_VERSION);
	case 0x0007: return r_uptime_s;
	case 0x0008: return mb_crc_error_count();
	case 0x0009: return mb_served_count();
	case 0x000A: return r_reading_age_s;
	case 0x000B: return r_rate;
	default:
		*ok = false; /* FR-MB13/14: exception 02 past the map edge */
		return 0;
	}
}

static mb_config_t cfg;

/* Shadow copies: a change against these is what triggers the FR-S30/FR-E05
 * accumulator clear. Window/averaging change the span; the three calibration
 * registers change the SCALE, so the boxcar must not mix entries across them. */
static uint16_t shadow_window;
static uint16_t shadow_avg;
static uint16_t shadow_travel;
static uint16_t shadow_raw_closed;
static uint16_t shadow_raw_open;

/* FR-S39: last-persisted snapshot. Gates flash access — regs_persist_service
 * only touches flash when a holding register differs from this. */
static persist_settings_t persisted;

#ifdef HAVE_END_SWITCH
/* FR-E15 debounce: a new level must hold for DEBOUNCE_MS before it is
 * published. Timed off raw SysTick->CNT like everything else in this firmware
 * (design/softwareArchitecture.md) — no timer peripheral, no ISR. */
#define DEBOUNCE_MS 20u
static bool     sw_published;  /* the debounced level currently in bit 3 */
static bool     sw_candidate;  /* level we are timing */
static uint32_t sw_since;      /* SysTick stamp when the candidate appeared */
#endif

void regs_init(uint8_t mb_address)
{
	cfg.address = mb_address;
	cfg.holdings = holdings;
	cfg.n_holdings = (uint8_t)(sizeof(holdings) / sizeof(holdings[0]));
	cfg.input_read = input_read;
	cfg.cross_validate = cross_validate;

	/* FR-S39: seed the holdings from persistent storage; a blank/corrupt
	 * store leaves the compile-time defaults (FR-S21 defined state). */
	persist_settings_t ps;
	if (persist_load(&ps)) {
		h_offset = ps.offset;
		h_window = ps.window;
		h_avg = ps.avg;
		h_travel = ps.travel;
		h_raw_closed = ps.raw_closed;
		h_raw_open = ps.raw_open;
	}
	persisted.offset = h_offset;
	persisted.window = h_window;
	persisted.avg = h_avg;
	persisted.travel = h_travel;
	persisted.raw_closed = h_raw_closed;
	persisted.raw_open = h_raw_open;

	r_status = STATUS_FIRST_WINDOW_INCOMPLETE | STATUS_AVG_NOT_FILLED;
	shadow_window = h_window;
	shadow_avg = h_avg;
	shadow_travel = h_travel;
	shadow_raw_closed = h_raw_closed;
	shadow_raw_open = h_raw_open;

#ifdef HAVE_END_SWITCH
	/* Seed the debounce with the level actually present at boot, so a window
	 * parked against an end stop reports bit 3 from the first response rather
	 * than after a spurious 20 ms transition. */
	sw_published = board_end_switch_active();
	sw_candidate = sw_published;
	sw_since = SysTick->CNT;
	if (sw_published)
		r_status |= STATUS_END_SWITCH;
#endif
}

void regs_persist_service(void)
{
	/* FR-S39: persist a changed holding set. The RAM compare gates flash
	 * access (no read/write unless something actually changed since the
	 * last save); persist_save is a no-op if it already matches flash.
	 * Called from the main loop AFTER the Modbus response, so the ~6 ms
	 * flash op never lands in the response path (FR-MB20/21). */
	if (h_offset == persisted.offset && h_window == persisted.window &&
	    h_avg == persisted.avg && h_travel == persisted.travel &&
	    h_raw_closed == persisted.raw_closed &&
	    h_raw_open == persisted.raw_open)
		return;
	persisted.offset = h_offset;
	persisted.window = h_window;
	persisted.avg = h_avg;
	persisted.travel = h_travel;
	persisted.raw_closed = h_raw_closed;
	persisted.raw_open = h_raw_open;
	persist_save(&persisted);
}

void regs_service(void)
{
	/* FR-S30: a valid write to 40002/40003 clears the averaging accumulator.
	 * FR-E05: so does a calibration write (40004/40005/40006) — those rescale
	 * every future reading, and a boxcar holding both scales at once reports a
	 * number that was never true at any moment.
	 * 30002/30003/30004 RETAIN their last published values until the first new
	 * window completes (the publishers overwrite them); status bits 0/1
	 * re-assert. */
	bool changed = h_window != shadow_window || h_avg != shadow_avg ||
	               h_travel != shadow_travel ||
	               h_raw_closed != shadow_raw_closed ||
	               h_raw_open != shadow_raw_open;
	if (changed) {
		shadow_window = h_window;
		shadow_avg = h_avg;
		shadow_travel = h_travel;
		shadow_raw_closed = h_raw_closed;
		shadow_raw_open = h_raw_open;
		/* TODO stage E: avg_config(h_window, h_avg) once avg.c exists. */
		r_status |= STATUS_FIRST_WINDOW_INCOMPLETE | STATUS_AVG_NOT_FILLED;
		have_prev_open = false; /* the rate baseline is stale too */
	}

#ifdef HAVE_END_SWITCH
	/* FR-E14/E15: debounce, then publish as status bit 3. Non-blocking — the
	 * candidate level simply has to survive DEBOUNCE_MS of main-loop passes,
	 * so nothing here delays the FR-MB20 response or the watchdog feed. */
	{
		bool now = board_end_switch_active();
		uint32_t t = SysTick->CNT;
		if (now != sw_candidate) {
			sw_candidate = now;
			sw_since = t;
		} else if (sw_candidate != sw_published &&
		           (uint32_t)(t - sw_since) >=
		               DEBOUNCE_MS * (FUNCONF_SYSTEM_CORE_CLOCK / 1000u)) {
			sw_published = sw_candidate;
			if (sw_published)
				r_status |= STATUS_END_SWITCH;
			else
				r_status &= (uint16_t)~STATUS_END_SWITCH;
		}
	}
#endif
}

const mb_config_t *regs_cfg(void)
{
	return &cfg;
}

uint16_t regs_offset_0_1mm(void) { return h_offset; }
uint16_t regs_window_ms(void)    { return h_window; }
uint16_t regs_avg_s(void)        { return h_avg; }
uint16_t regs_travel_0_1mm(void) { return h_travel; }
uint16_t regs_raw_closed(void)   { return h_raw_closed; }
uint16_t regs_raw_open(void)     { return h_raw_open; }

void regs_second_tick(void)
{
	if (r_uptime_s < 0xFFFF)
		r_uptime_s++; /* FR-S34: saturating */
	if (r_reading_age_s < 0xFFFF)
		r_reading_age_s++; /* FR-S36: a valid publish zeroes it */

	/* FR-E07: advance the grace period and, once it is spent, publish the
	 * fault. Done on the tick rather than at publish time so a sensor that has
	 * stopped answering entirely — no publishes at all — still faults. */
	if (sample_invalid) {
		if (invalid_s < 0xFFFF)
			invalid_s++;
		if (invalid_s > FAULT_HOLD_S) {
			r_status |= STATUS_SENSOR_FAULT;
			r_open_inst = OPEN_FAULT_SENTINEL;
			r_open_avg = OPEN_FAULT_SENTINEL;
			r_open_min = OPEN_FAULT_SENTINEL;
			r_open_max = OPEN_FAULT_SENTINEL;
		}
	}
}

void regs_window_aborted(void)
{
	/* FR-S30/FR-S33: bit 0 re-asserts until the restarted window
	 * completes (a publish clears it). */
	r_status |= STATUS_FIRST_WINDOW_INCOMPLETE;
}

void regs_publish_opening(uint16_t raw, uint16_t open_0_1mm, bool valid)
{
	r_raw = raw; /* 30005: raw ADC code, pre-scaling (FR-E09) */

	if (!valid) {
		/* FR-E07: hold the last valid opening; regs_second_tick decides when
		 * the grace period is spent and the sentinel goes out. Faulted samples
		 * never reach the averaging engine or the rate estimate. */
		sample_invalid = true;
		have_prev_open = false;
		return;
	}

	sample_invalid = false;
	invalid_s = 0;
	r_status &= (uint16_t)~STATUS_SENSOR_FAULT;
	r_reading_age_s = 0; /* FR-S36 */

	r_open_inst = open_0_1mm; /* 30001 */

	/* FR-E10 movement rate: |Δopening| over one window, in 0.1 mm/s. Needs two
	 * consecutive valid windows — a fault, or a window-duration change,
	 * invalidates the baseline. Worst case 65534 × 1000 = 65 534 000,
	 * comfortably inside uint32_t. */
	if (have_prev_open) {
		uint16_t d = (open_0_1mm > prev_open)
		                 ? (uint16_t)(open_0_1mm - prev_open)
		                 : (uint16_t)(prev_open - open_0_1mm);
		uint32_t v = ((uint32_t)d * 1000u) / (h_window ? h_window : 1u);
		r_rate = (v > 65535u) ? 65535u : (uint16_t)v;
	} else {
		r_rate = 0;
	}
	prev_open = open_0_1mm;
	have_prev_open = true;

	r_status &= (uint16_t)~STATUS_FIRST_WINDOW_INCOMPLETE; /* FR-S23 */

	/* TODO integration stage E (design/integrationPlan.md): feed the boxcar
	 * and publish 30002 (mean), 30003/30004 (FR-E08 window min/max), and clear
	 * STATUS_AVG_NOT_FILLED once the accumulator has filled. Until avg.c
	 * exists those three registers keep their FR-S23 value and status bit 1
	 * stays set — which is the truth, not a placeholder. */
}

#ifdef TEST_HOOKS
bool regs_test_hang_requested(void)
{
	return test_hang == 0xDEAD;
}
#endif
