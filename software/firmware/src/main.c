/*
 * Wire encoder Modbus interface — product firmware (CH32V003J4M6, SOIC-8)
 *
 * Measures how far a window is open. A draw-wire encoder attached to the moving
 * frame turns a 10 kΩ potentiometer; the wiper is read ratiometrically on PA2
 * and published over Modbus RTU (TDS §1.1, §3.4).
 *
 * Zero-ISR cooperative super-loop (design/softwareArchitecture.md).
 * Stage C state (design/integrationPlan.md): board bring-up, the full register
 * image (regs.c) and flash persistence are in place and answer the complete
 * TDS §2.7/§2.8 map. There is NO measurement service yet — the encoder driver
 * (software/drivers/wire_encoder/) is unwritten. Measurement registers
 * therefore read their FR-S23 pre-first-window value and status bits 0/1 stay
 * set: correct behaviour for a device that has never completed a window, and
 * not to be mistaken for a finished product.
 *
 * Assumed pin map (TDS §4.2 — no schematic exists yet): PD6 Modbus line
 * (remap-switching discipline, no HDSEL), PA2 potentiometer wiper, PC2 DE/R̄Ē,
 * PC4 address jumper, PD1 SWIO, and PC1 — the one spare pin — for the optional
 * end-of-travel switch input.
 */

#include "board.h"
#include "ch32fun.h"
#include "mb.h"
#include "regs.h"
#include "sensors.h"

int main(void)
{
	SystemInit();
	funGpioInitAll();

	/* FR-S18 init order:
	 * (1) PC2/DE low first + (2) PC4 address latch + IWDG + PVD
	 * (+ the optional PC1 end-switch input) ... */
	board_init_early();

	/* (3) sensor front-end ready — stage D: we_init() goes here, after the
	 * board and before regs_init, so the ADC self-calibration is complete
	 * before anything can be read. */

	/* regs_init loads the persisted holdings (FR-S39) BEFORE the measurement
	 * service latches the window, so the first window already uses the stored
	 * duration — no spurious first-window abort at boot. */
	regs_init(board_mb_address());

	/* (4) USART receiver enabled last. */
	mb_init(regs_cfg());

	const uint32_t second_ticks = FUNCONF_SYSTEM_CORE_CLOCK;
	uint32_t t_second = SysTick->CNT;

	while (1)
	{
		mb_poll();
		regs_service();          /* FR-S30/FR-E05 config change -> clear;
		                          * FR-E15 end-switch debounce */
		regs_persist_service();  /* FR-S39: save changed settings to flash
		                          * (after mb_poll sent any response) */

		/* Stage D: meas_open_service() goes here — window pacing, we_sample(),
		 * FR-E04 scaling, then regs_publish_opening(). */

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
