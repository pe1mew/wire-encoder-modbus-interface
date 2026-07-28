/*
 * Wire encoder driver — HIL test shell (design/driverDevelopment.md §3).
 *
 * THE DRIVER IS NOT WRITTEN. lib/we/we.h holds the agreed API contract; there
 * is no we.c, because a stub that compiled would let the product firmware link
 * and appear to work.
 *
 * This shell therefore does exactly one useful thing: it proves the bench is
 * alive (flash → run → trace → capture) and says out loud that there is no
 * driver behind it. Replace the body with the real acquisition loop when
 * lib/we/we.c exists:
 *
 *     we_init();
 *     for (;;) {
 *         uint16_t raw;
 *         bool ok = we_sample(&raw);
 *         dbg_print("raw="); dbg_print_u16(raw);
 *         dbg_print(ok ? " ok\r\n" : " INVALID\r\n");
 *         Delay_Ms(100);
 *     }
 *
 * — which is the trace format design/driverDevelopment.md §3.3 asserts
 * against, so keep it if you can.
 */

#include "ch32fun.h"
#include "debug_uart.h"

int main(void)
{
	SystemInit();
	funGpioInitAll();

	dbg_init(); /* TX-only trace on PD6, 115200 8N1 */

	uint32_t n = 0;
	while (1) {
		dbg_print("we: NO DRIVER — see lib/we/we.h, tick=");
		dbg_print_u32(n++);
		dbg_print("\r\n");
		dbg_flush();
		Delay_Ms(1000);
	}
}
