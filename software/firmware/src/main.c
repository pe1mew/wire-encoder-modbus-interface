/*
 * Wire encoder Modbus interface — product firmware (CH32V003J4M6, SOIC-8)
 *
 * Measures how far a window is open. A draw-wire encoder attached to the moving
 * frame turns a 10 kΩ potentiometer; the wiper is read ratiometrically on PA2
 * and published over Modbus RTU (TDS §1.1, §3.4).
 *
 * Zero-ISR cooperative super-loop (design/softwareArchitecture.md).
 * Stage D state (design/integrationPlan.md): board bring-up, the register image
 * (regs.c), flash persistence, the encoder driver (we.c) and the measurement
 * service (meas_open.c) are all in place, so 30001/30005/30012/30015 and status
 * bits 2/3/4 are live. Still missing is stage E — the averaging engine — so
 * 30002 (mean) and 30003/30004 (window min/max) do not yet update and status
 * bit 1 stays set.
 *
 * Assumed pin map (TDS §4.2 — no schematic exists yet): PD6 Modbus line
 * (remap-switching discipline, no HDSEL), PA2 potentiometer wiper (ADC ch0),
 * PC2 DE/R̄Ē, PC1 address jumper, PC4 end-switch divider (ADC ch2), PD1 SWIO.
 * Every pin is committed; PC1/PC4 are assigned the reverse of the obvious way
 * because PC4 has an ADC channel and the switch divider needs it.
 */

#include "board.h"
#include "ch32fun.h"
#include "mb.h"
#include "meas_open.h"
#include "regs.h"
#include "sensors.h"
#include "we.h"

int main(void)
{
	SystemInit();
	funGpioInitAll();

	/* FR-S18 init order:
	 * (1) PC2/DE low first + (2) PC1 address latch + IWDG + PVD ... */
	board_init_early();

	/* FR-S18 (3): sensor front-end ready. Before regs_init, so the ADC
	 * self-calibration is complete before anything can read a register. */
	we_init();

	/* regs_init loads the persisted holdings (FR-S39) BEFORE the measurement
	 * service latches the window, so the first window already uses the stored
	 * duration — no spurious first-window abort at boot. */
	regs_init(board_mb_address());

	/* The measurement service latches 40002 AFTER regs_init has loaded the
	 * persisted holdings, so the first window already runs at the stored
	 * duration and does not abort itself on the first pass (FR-S30). */
	meas_open_init();

	/* (4) USART receiver enabled last. */
	mb_init(regs_cfg());

	const uint32_t second_ticks = FUNCONF_SYSTEM_CORE_CLOCK;
	uint32_t t_second = SysTick->CNT;

	while (1)
	{
		mb_poll();
		regs_service();          /* FR-S30/FR-E05: config change -> clear */
		regs_persist_service();  /* FR-S39: save changed settings to flash
		                          * (after mb_poll sent any response) */

		/* Window pacing, wiper and ladder sampling, FR-E04 scaling and
		 * publication. Placed after regs_persist_service so a flash write
		 * never sits between a sample and its publication. */
		meas_open_service();

		if ((uint32_t)(SysTick->CNT - t_second) >= second_ticks)
		{
			t_second += second_ticks;
			regs_second_tick();
		}

#ifdef TEST_HOOKS
		if (regs_test_hang_requested())
			for (;;)
				; /* FR-S20 test: stop servicing AND feeding — dog bites */
#endif
		/* FR-S20: refresh only here, at the end of a full loop pass, and
		 * only while the rail is healthy (FR-S22). */
		if (board_power_ok())
			board_iwdg_feed();
	}
}
