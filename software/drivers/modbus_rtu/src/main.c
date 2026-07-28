#include "ch32fun.h"
#include "mb.h"

// Modbus RTU driver HIL test shell — TTL-level rig (no MAX3485 yet).
//
// NO debug UART here: PD6 IS the bus (FR-S19 — never transmit except in
// response to a valid addressed request). Observability = the bus itself,
// decoded on the Saleae; DE on PC2 is observable on a second channel.
//
// Slave address 40 (TDS FR-S03 jumper-open value; the PC4 jumper itself is
// handled at integration). Holding registers mirror TDS §2.8; input
// registers serve known patterns for read/byte-order tests plus live uptime
// and the driver's own diagnostic counters, so the protocol matrix can run
// long before the measurement path exists.

static uint16_t h_offset = 0;      // 40001 zero offset: 0..65534, default 0
static uint16_t h_window = 1000;   // 40002 meas. window: 100..60000, def 1000
static uint16_t h_avg = 10;        // 40003 averaging: 1..600, def 10 (FR-S31)
static uint16_t h_travel = 10000;  // 40004 full travel: 1..65534, def 10000
static uint16_t h_raw_closed = 0;  // 40005 raw @ closed: 0..65534 (FR-E06)
static uint16_t h_raw_open = 1023; // 40006 raw @ open:   1..65535 (FR-E06)

static const mb_holding_t holdings[] = {
	{0x0000, 0, 65534, &h_offset},
	{0x0001, 100, 60000, &h_window},
	{0x0002, 1, 600, &h_avg},
	{0x0003, 1, 65534, &h_travel},
	{0x0004, 0, 65534, &h_raw_closed},
	{0x0005, 1, 65535, &h_raw_open},
};

static volatile uint32_t uptime_s;

// FR-S31: (averaging window x 1000) >= measurement window, and FR-E06:
// raw_open > raw_closed. Both evaluated against the staged pair (falling
// back to current values where not staged), so an FC16 that moves both
// halves of a constraint at once is judged on its result (FR-MB22).
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

static uint16_t input_read(uint16_t addr, bool *ok)
{
	switch (addr) {
	case 0x0000: return 1234;          // fixed pattern
	case 0x0001: return 250;           // fixed pattern
	case 0x0002: return 900;           // 0x0384 — byte-order probe (FR-MB25)
	case 0x0003: return 0;
	case 0x0004: return 511;
	case 0x0005: return 3;             // synthetic status bits
	case 0x0006: return 0x0107;        // build/version pattern (FR-S32 shape)
	case 0x0007: return (uint16_t)uptime_s;
	case 0x0008: return mb_crc_error_count();
	case 0x0009: return mb_served_count();
	case 0x000A: return 42;
	case 0x000B: return 80;
	case 0x000C: return mb_fe_count();
	case 0x000D: return mb_ne_count();
	case 0x000E: return mb_ore_count();
	case 0x0010: return mb_last_bad(0);
	case 0x0011: return mb_last_bad(1);
	case 0x0012: return mb_last_bad(2);
	case 0x0013: return mb_last_bad(3);
	default:
		*ok = false;
		return 0;
	}
}

static const mb_config_t cfg = {
	.address = 40,
	.holdings = holdings,
	.n_holdings = sizeof(holdings) / sizeof(holdings[0]),
	.input_read = input_read,
	.cross_validate = cross_validate,
};

int main()
{
	SystemInit();
	funGpioInitAll();
	mb_init(&cfg);

	const uint32_t second_ticks = FUNCONF_SYSTEM_CORE_CLOCK;
	uint32_t t0 = SysTick->CNT;

	while (1)
	{
		mb_poll();
		if ((uint32_t)(SysTick->CNT - t0) >= second_ticks)
		{
			t0 += second_ticks;
			uptime_s++;
		}
	}
}
