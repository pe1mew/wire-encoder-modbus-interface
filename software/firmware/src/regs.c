#include "persist.h"
#include "regs.h"
#include "sensors.h" /* BUILD_TYPE + WE_RAW_MAX_DEFAULT */
#include "scale.h"
#include "version.h"
#include "ch32fun.h" /* SysTick->CNT for the FR-E15 debounce */

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
 * Defaults span the full 10-bit ADC range; a real installation calibrates by
 * closing the window, writing 40005 from 30005, opening it fully, and writing
 * 40006 the same way.
 *
 * The two points may be given in EITHER ORDER (FR-E04). raw_open < raw_closed
 * describes a mounting where the wiper code falls as the window opens, which is
 * decided by how the draw-wire happens to be fitted — a coin toss, and not
 * something an installer should have to notice. What FR-E06 does require is
 * that the two differ by at least CAL_MIN_SPAN: two adjacent codes would
 * satisfy "not equal" while making one LSB of ADC noise swing the entire
 * reported travel. */
#ifndef RAW_CLOSED_DEFAULT
#define RAW_CLOSED_DEFAULT 0
#endif
#ifndef RAW_OPEN_DEFAULT
#define RAW_OPEN_DEFAULT WE_RAW_MAX_DEFAULT /* 10-bit ADC full scale, sensors.h */
#endif

/* CAL_MIN_SPAN and cal_span() come from scale.h, next to the arithmetic that
 * depends on them. Spelled out longhand here rather than calling cal_span():
 * a _Static_assert needs a constant expression, and C11 does not admit a
 * function call in one — not even an inline that would obviously fold. */
_Static_assert((RAW_OPEN_DEFAULT > RAW_CLOSED_DEFAULT
                    ? RAW_OPEN_DEFAULT - RAW_CLOSED_DEFAULT
                    : RAW_CLOSED_DEFAULT - RAW_OPEN_DEFAULT) >= CAL_MIN_SPAN,
               "the default calibration points must be at least CAL_MIN_SPAN "
               "apart (FR-E06) — else a fresh device boots degenerate");
static uint16_t h_raw_closed = RAW_CLOSED_DEFAULT; /* 40005: 0..65534 */
static uint16_t h_raw_open = RAW_OPEN_DEFAULT;     /* 40006: 1..65535 */

/* 40007 teach command (FR-E19). Deliberately NOT in persist_settings_t: a
 * teach left armed across a power cut would be a surprise, not a convenience,
 * so this reads 0 after every reset whatever it held before. */
static uint16_t h_teach;

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
	{0x0006, 0, 1, &h_teach},          /* 40007 teach command (FR-E19)    */
#ifdef TEST_HOOKS
	{0x00FF, 0, 0xFFFF, &test_hang},
#endif
};

/* Cross-register constraints, evaluated against the STAGED pair so an FC16 that
 * moves both halves of a constraint at once is judged on its result, not on the
 * intermediate state (FR-MB22 atomicity):
 *   FR-S31: (40003 s × 1000) ≥ 40002 ms
 *   FR-E06: |40006 - 40005| >= CAL_MIN_SPAN — a magnitude, not an ordering, so
 *           a reversed mounting calibrates as naturally as a normal one. */
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
	return (uint32_t)avg * 1000u >= window &&
	       cal_span(raw_closed, raw_open) >= CAL_MIN_SPAN;
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
static uint16_t r_rate;          /* 30012 SIGNED movement rate (FR-E10)   */
static uint16_t r_pct;           /* 30015 percent of travel (FR-E20)      */
static int8_t   last_dir;        /* +1 opening, -1 closing, 0 unknown     */
static uint16_t r_at_closed;     /* 30013 raw code seen at the closed stop */
static uint16_t r_at_open;       /* 30014 raw code seen at the open stop   */

#define STATUS_FIRST_WINDOW_INCOMPLETE 0x0001 /* bit 0 (FR-S23/S30) */
#define STATUS_AVG_NOT_FILLED          0x0002 /* bit 1 (FR-S23/S30) */
#define STATUS_WIPER_FAULT             0x0004 /* bit 2 (FR-E07)     */
#define STATUS_END_REACHED             0x0008 /* bit 3 (FR-E14)     */
#define STATUS_SWITCH_FAULT            0x0010 /* bit 4 (FR-E16)     */
#define STATUS_TEACH_ACTIVE            0x0020 /* bit 5 (FR-E19)     */

#define OPEN_FAULT_SENTINEL 65535u /* §2.7 — reported by 30001..30004 */
#define FAULT_HOLD_S        2u     /* FR-E07: hold the last value this long */

/* FR-E07 fault machine state. `invalid_s` counts whole seconds of consecutive
 * invalid samples (advanced by regs_second_tick); the sentinel is published
 * only once it exceeds FAULT_HOLD_S, so a single dropped sample is invisible to
 * the master. */
/* FR-E19 teach state. `got_*` mark an endpoint captured since arming; `read_*`
 * mark it collected by the master. The commit needs all four, which is what
 * makes the handshake race-free: a master polling slowly cannot miss a
 * capture, because the device will not retire it until it has been read. */
static bool teach_got_closed, teach_got_open;
static bool teach_read_closed, teach_read_open;

static uint16_t invalid_s;
static bool     sample_invalid;
static bool     have_prev_open; /* FR-E10 needs two windows before a rate */
static uint16_t prev_open;

static void teach_service(void); /* FR-E19, defined below */

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
	case 0x000C: teach_read_closed = true; return r_at_closed;
	case 0x000D: teach_read_open = true;   return r_at_open;
	case 0x000E: return r_pct;
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

/* ---- End-switch divider (TDS §4.4 / FR-E14/E15/E16) ----
 *
 * The two LJ18A3-8-Z/BX proximity sensors are summed in a field junction and
 * attenuated at the board:
 *
 *   +V --[470k]--+                          (470k = end-of-line, in the field)
 *   A  --[100k]--+---- signal ----[10k]--+-- PC4
 *   B  --[100k]--+                       |
 *                                      [4k7]
 *                                        |
 *                                       GND
 *
 * The sensors are NOT open-collector: each has an internal 10k pull-up to +V
 * (LJ_en.pdf p.2), so an inactive sensor SOURCES 24 V rather than floating.
 * Hence a divider down from the sensor supply, not a pull-up to 3V3 — the
 * earlier pull-up topology would have put 10-14 V on this pin.
 *
 * Nominals at 24 V, and the bands that decode them. Note the ordering is
 * INVERTED relative to the old design: healthy is now the highest reading and
 * a dead cable is zero.
 *
 *   normal, between the stops   547   >= 420
 *   one sensor active           299   >= 150   -> end reached
 *   both active (wiring fault)   56   >=  25   -> fault
 *   cable open or shorted         0   <   25   -> fault
 *
 * Two properties worth not breaking:
 *
 *   - FAIL-SAFE AGAINST A SHORT, NOT AGAINST AN OPEN. The 4k7 is on the
 *     board, so an input shorted to 0 V or never connected reads 0 and lands
 *     in the fault band. But since the star topology (TDS §4.4, 2026-08-07)
 *     the 100k summing resistors are on the PCB, so an open SENSOR CABLE
 *     never reaches this pin: it leaves that branch unterminated and the node
 *     sits at ~337 counts, which this function decodes as SW_ONE_ACTIVE.
 *     A cut therefore reports a FALSE END OF TRAVEL, silently. That is a
 *     documented limit (FR-E14/FR-E16), not a bug here — do not "fix" it by
 *     moving a threshold, because 337 is only 38 counts from a genuine stop
 *     at 299 and the bands need 45 for supply tolerance alone.
 *   - The 100k summing resistors swamp the sensors' saturation voltage: at
 *     Vsat = 1.5 V "one active" moves by 17 counts, where the old topology
 *     moved 296 and mis-decoded as "normal".
 *
 * Tightest margin is 45 counts (normal at -15 % supply vs the 420 threshold).
 * These are computed, not yet measured — see TDS §6. */
#define SW_TH_NORMAL 420u
#define SW_TH_ONE    150u
#define SW_TH_BOTH    25u

typedef enum {
	SW_CABLE_FAULT = 0, /* shorted to 0 V, or nothing fitted. NOT an open
	                     * sensor cable — that reads as SW_ONE_ACTIVE */
	SW_BOTH_ACTIVE,     /* impossible on a working window — wiring fault */
	SW_ONE_ACTIVE,      /* at an end stop */
	SW_NORMAL,          /* between the stops */
} sw_state_t;

static sw_state_t sw_classify(uint16_t raw)
{
	if (raw >= SW_TH_NORMAL)
		return SW_NORMAL;
	if (raw >= SW_TH_ONE)
		return SW_ONE_ACTIVE;
	if (raw >= SW_TH_BOTH)
		return SW_BOTH_ACTIVE;
	return SW_CABLE_FAULT;
}

/* FR-E15 debounce: a new classification must hold for DEBOUNCE_MS before it is
 * published. Timed off raw SysTick->CNT like everything else in this firmware
 * (design/softwareArchitecture.md) — no timer peripheral, no ISR, no delay. */
#define DEBOUNCE_MS 20u
static sw_state_t sw_published = SW_CABLE_FAULT; /* until the first sample */
static sw_state_t sw_candidate = SW_CABLE_FAULT;
static uint32_t   sw_since;    /* SysTick stamp when the candidate appeared */
static bool       sw_seen;     /* a sample has arrived at least once */

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
	if (persist_load(&ps) &&
	    cal_span(ps.raw_closed, ps.raw_open) >= CAL_MIN_SPAN) {
		/* The span check is not paranoia about our own store: it is the guard
		 * that keeps regs_scale_opening's divisor away from zero no matter
		 * what is in flash — a record written by an older firmware, or one
		 * that predates FR-E06's minimum span, would otherwise divide by a
		 * degenerate span on the first measurement. A record that fails it is
		 * treated exactly like a blank store: fall back to the §2.8 defaults,
		 * which is the FR-S21 defined state. */
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

	/* Until the first ladder sample arrives the loop is, as far as this device
	 * knows, unverified — so report the fault rather than an unearned clean
	 * bill of health. The first regs_publish_switches call corrects it. */
	r_status |= STATUS_SWITCH_FAULT;
	sw_since = SysTick->CNT;
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

	teach_service(); /* FR-E19 */
}

void regs_note_end_stop(void)
{
	/* FR-E18: the window is physically at a stop, so the raw wiper code being
	 * read right now IS that endpoint — by definition, not by inference. This
	 * is the device's only independent reference: a draw-wire that has slipped
	 * on its drum reports a plausible, stable, wrong opening, and nothing in
	 * the wiper path can tell. Comparing these registers against 40005/40006
	 * measures that drift against a physical stop rather than against anyone's
	 * model of how long the actuator ran. */
	const uint16_t raw = r_raw;

	/* Which stop? The ladder deliberately does not say (TDS §4.4). Direction of
	 * travel answers it outright — a window that was opening has arrived at the
	 * open end — and, unlike comparing the reading against the calibration,
	 * that works on a device whose calibration is not yet trustworthy. Fall
	 * back to proximity only when nothing has moved since reset, which in
	 * practice means the window was already sitting at the stop at power-on. */
	const bool at_open = (last_dir > 0) ? true
	                   : (last_dir < 0) ? false
	                   : (cal_span(raw, h_raw_open) < cal_span(raw, h_raw_closed));
	if (!at_open) {
		r_at_closed = raw;
		teach_got_closed = true;
		teach_read_closed = false; /* a new value has to be read again */
	} else {
		r_at_open = raw;
		teach_got_open = true;
		teach_read_open = false;
	}
}

/* FR-E19: arm / abort / commit. Driven from regs_service so the commit lands
 * in the main loop rather than inside a Modbus read. */
static void teach_service(void)
{
	if (!h_teach) {
		/* Idle, or an abort: discard captures and drop the status bit. A write
		 * of 0 at any point leaves 40005/40006 untouched. */
		if (r_status & STATUS_TEACH_ACTIVE) {
			r_status &= (uint16_t)~STATUS_TEACH_ACTIVE;
			teach_got_closed = teach_got_open = false;
			teach_read_closed = teach_read_open = false;
		}
		return;
	}

	if (!(r_status & STATUS_TEACH_ACTIVE)) {
		/* Freshly armed: start from nothing, so a stale capture from an
		 * earlier session can never be committed. */
		r_status |= STATUS_TEACH_ACTIVE;
		teach_got_closed = teach_got_open = false;
		teach_read_closed = teach_read_open = false;
		return;
	}

	/* Both stops reached AND both values collected — the second half is what
	 * keeps a slow poller from missing a capture. */
	if (!(teach_got_closed && teach_got_open &&
	      teach_read_closed && teach_read_open))
		return;

	/* FR-E06 applies to an internal write exactly as it does to a Modbus one:
	 * this path bypasses the driver's range checking, so re-assert it here or
	 * it is not enforced at all. A degenerate pair leaves teach armed with the
	 * captures still readable, so the operator can see what went wrong. */
	if (cal_span(r_at_closed, r_at_open) < CAL_MIN_SPAN)
		return;

	h_raw_closed = r_at_closed;
	h_raw_open = r_at_open;
	h_teach = 0;
	r_status &= (uint16_t)~STATUS_TEACH_ACTIVE;
	/* regs_service's shadow compare sees the change and clears the averaging
	 * accumulator (FR-E05); regs_persist_service commits it to flash. */
}

void regs_publish_switches(uint16_t raw)
{
	/* FR-E14/E15/E16: classify, debounce, publish as status bits 3 and 4.
	 * Non-blocking — the candidate state simply has to survive DEBOUNCE_MS of
	 * calls, so nothing here delays the FR-MB20 response or the watchdog feed.
	 * The debounce measures elapsed time, not call count, so the caller's
	 * sampling rate is free to change. */
	sw_state_t now = sw_classify(raw);
	uint32_t t = SysTick->CNT;

	if (now != sw_candidate) {
		sw_candidate = now;
		sw_since = t;
		if (sw_seen)
			return; /* a fresh candidate always has to serve its 20 ms */
	}
	if (sw_seen && sw_candidate == sw_published)
		return;
	if (sw_seen && (uint32_t)(t - sw_since) <
	                   DEBOUNCE_MS * (FUNCONF_SYSTEM_CORE_CLOCK / 1000u))
		return;

	/* First sample, or a candidate that has held long enough. Publishing the
	 * very first sample immediately means a window parked against an end stop
	 * reports bit 3 from its first response, rather than after a spurious
	 * transition (FR-S18 criterion c). */
	const bool was_at_stop = sw_seen && (sw_published == SW_ONE_ACTIVE);
	sw_seen = true;
	sw_published = sw_candidate;

	if (sw_published == SW_ONE_ACTIVE) {
		if (!was_at_stop)
			regs_note_end_stop(); /* FR-E18: transition, not level */
		r_status |= STATUS_END_REACHED;
	} else {
		r_status &= (uint16_t)~STATUS_END_REACHED;
	}

	/* FR-E16: the three states a healthy installation cannot produce. Reported
	 * only — the opening registers come from an independent front-end and are
	 * never suppressed or altered by a switch-loop fault. */
	if (sw_published == SW_NORMAL || sw_published == SW_ONE_ACTIVE)
		r_status &= (uint16_t)~STATUS_SWITCH_FAULT;
	else
		r_status |= STATUS_SWITCH_FAULT;
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

uint16_t regs_scale_opening(uint16_t raw)
{
	/* The arithmetic itself lives in scale.c — hardware-free, and host-tested
	 * at its corners by software/firmware/test/test_scale.c. This wrapper's
	 * only job is to supply the calibration values, which regs.c owns.
	 *
	 * The span is guaranteed >= CAL_MIN_SPAN by FR-E06 on every Modbus write
	 * and by the regs_init guard on every load from flash, so scale_opening's
	 * divisor is never zero. */
	return scale_opening(raw, h_offset, h_travel, h_raw_closed, h_raw_open);
}

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
			r_status |= STATUS_WIPER_FAULT;
			r_open_inst = OPEN_FAULT_SENTINEL;
			r_open_avg = OPEN_FAULT_SENTINEL;
			r_open_min = OPEN_FAULT_SENTINEL;
			r_open_max = OPEN_FAULT_SENTINEL;
			r_pct = OPEN_FAULT_SENTINEL; /* FR-E20 follows 30001 */
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
	r_status &= (uint16_t)~STATUS_WIPER_FAULT;
	r_reading_age_s = 0; /* FR-S36 */

	r_open_inst = open_0_1mm; /* 30001 */

	r_pct = scale_percent(open_0_1mm, h_offset, h_travel); /* 30015, FR-E20 */

	/* FR-E10 movement rate: SIGNED Δopening over one window, in 0.1 mm/s —
	 * positive opening, negative closing. Needs two consecutive valid windows;
	 * a fault or a window-duration change invalidates the baseline. Worst case
	 * ±65534 × 1000 = ±65 534 000, comfortably inside int32_t.
	 *
	 * The sign is not merely nicer to read: it is what tells FR-E18 which stop
	 * a capture belongs to, on a device whose calibration cannot yet be
	 * trusted to answer that. */
	if (have_prev_open) {
		int32_t d = (int32_t)open_0_1mm - (int32_t)prev_open;
		int32_t v = (d * 1000) / (int32_t)(h_window ? h_window : 1u);
		if (v > 32767) v = 32767;      /* ±3276.7 mm/s — the clamp exists to */
		if (v < -32768) v = -32768;    /* make the arithmetic total, not     */
		r_rate = (uint16_t)(int16_t)v; /* because a window could get there   */
		if (d > 0) last_dir = 1;
		else if (d < 0) last_dir = -1; /* zero leaves it sticky: the last
		                                * direction of travel still stands */
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
