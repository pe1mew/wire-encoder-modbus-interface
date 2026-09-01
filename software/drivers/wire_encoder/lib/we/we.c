/**
 * @file we.c
 * @brief Wire-encoder raw-code acquisition — implementation of @ref we.h.
 *
 * Owns the ADC. Two analog inputs share it:
 *
 *   - **PA2, channel 0** — the draw-wire potentiometer wiper (FR-E11).
 *   - **PC4, channel 2** — the end-switch summing divider (FR-E14, TDS §4.4).
 *
 * Nothing here knows about millimetres, Modbus, windows or the FR-E07 fault
 * *timer*. It produces a raw code and says whether that one sample is
 * trustworthy; every policy above that lives in `meas_open.c` and `regs.c`.
 *
 * @warning **Blocking budget: one Modbus character, 1.146 ms.** The Modbus
 *          receiver is polled from the same loop against a single-byte USART
 *          register, so a longer pass loses a byte and FR-MB24 discards the
 *          frame. Measured costs: a conversion is ~14 us (73-cycle sample at
 *          6 MHz), so we_switch_sample is ~224 us and we_sample is ~552 us
 *          (two 150 us settles plus 18 conversions). Both fit; adding work to
 *          either needs this arithmetic redone, not a guess.
 */
#include "ch32fun.h"
#include "we.h"

/* ---- hardware map (TDS §4.2) --------------------------------------------- */
#define WE_CH_WIPER   0u          /**< PA2 */
#define WE_CH_SWITCH  2u          /**< PC4 */
#define WE_RAW_MAX_CODE 1023u     /**< 10-bit full scale (FR-E11) */

/* ---- conversion scheme (FR-E13) ------------------------------------------
 * 16 conversions per sample, discard the extreme pair, mean the middle 14.
 * FR-E13 permits "mean, or median with outlier rejection"; this is the mean
 * WITH outlier rejection, which keeps the sqrt(N) noise reduction a mean gives
 * while a single glitch cannot drag the result. Cheap: one pass, no buffer.
 */
#define WE_CONVERSIONS 16u

/* Sample time selector 6 = 73 ADC cycles. FR-E11's front-end note asks for
 * >=71 cycles at the 10 kOhm source impedance; 73 is the next setting up. With
 * the ADC clock at HCLK/8 = 6 MHz that is ~12 us of acquisition, against a
 * worst-case source of ~12.5 kOhm (pot mid-track 2.5 k + R11 10 k) into the
 * sample-and-hold — tens of time constants, with C6 (1 nF) at the pin acting
 * as a local charge reservoir on top. */
#define WE_SMP_73_CYCLES 6u

/* ---- FR-E07 wiper integrity ----------------------------------------------
 * Toggle PA2's internal pull between two conversions and watch how far the
 * reading moves. A connected wiper is a stiff source and barely shifts; a
 * floating one follows the pull from rail to rail.
 *
 * Arithmetic, at the mid-track worst case. Source 12.5 kOhm, internal pull
 * ~40 kOhm:
 *
 *   connected, pull-up   (1.65/12.5k + 3.3/40k) / (1/12.5k + 1/40k) = 2.04 V
 *   connected, pull-down (1.65/12.5k)           / (1/12.5k + 1/40k) = 1.26 V
 *   => spread ~0.78 V ~ 242 counts
 *
 *   open, pull-up  -> ~3.3 V (1023)
 *   open, pull-down-> ~0 V   (0)
 *   => spread ~1023 counts
 *
 * The threshold sits between them with room either side. It is deliberately
 * nearer the open end: a false "sensor faulty" costs a real reading, and this
 * test's job is to catch a disconnection, not to police noise.
 */
#define WE_PULL_SPREAD_FAULT 600u

/* C6 (1 nF) against the pull gives tau = 40 us in the worst case (an OPEN
 * wiper, where C6 charges through the ~40 kOhm pull alone; a connected one is
 * ~9.5 us because the source dominates). 150 us is 3.75 tau, 97.6 % settled —
 * ample to tell a ~1023-count swing from a ~242-count one.
 *
 * IT IS NOT ARBITRARY, AND IT IS NOT FREE TO INCREASE. The Modbus receiver is
 * POLLED from the main loop against a single-byte USART register, so any pass
 * that blocks for a whole character time (11 bits / 9600 = 1.146 ms) loses a
 * byte to overrun, and FR-MB24 then discards the frame. An earlier 500 us made
 * we_sample() ~1.25 ms on its own and the DUT silently dropped 9.7 % of
 * requests — with 30009 unmoved, because an overrun is not a CRC error. Keep
 * the whole call well inside one character time. */
#define WE_PULL_SETTLE_US 150

static bool we_ready;             /**< we_init() has run and calibrated */

/* -------------------------------------------------------------------------- */

/**
 * @brief One conversion on @p channel, with the ADC already configured.
 * @note funAnalogRead takes the ANALOG CHANNEL number, not a pin number.
 */
static inline uint16_t adc_once(uint8_t channel)
{
	return (uint16_t)funAnalogRead(channel);
}

/**
 * @brief @ref WE_CONVERSIONS conversions folded to one code (FR-E13).
 *
 * Discards the single lowest and single highest reading and means the rest.
 */
static uint16_t adc_burst(uint8_t channel)
{
	uint32_t sum = 0;
	uint16_t lo = 0xFFFFu;
	uint16_t hi = 0;

	for (uint32_t i = 0; i < WE_CONVERSIONS; i++) {
		uint16_t v = adc_once(channel);
		sum += v;
		if (v < lo)
			lo = v;
		if (v > hi)
			hi = v;
	}
	sum -= lo;
	sum -= hi;
	return (uint16_t)(sum / (WE_CONVERSIONS - 2u));
}

/**
 * @brief Read PA2 once with a defined internal pull applied.
 * @param pull_high true for pull-up, false for pull-down.
 *
 * The pin leaves analog mode for the duration, which is what makes the pull
 * reachable at all; it is put back before the caller measures anything real.
 */
static uint16_t wiper_probe_with_pull(bool pull_high)
{
	funPinMode(PA2, GPIO_CNF_IN_PUPD);
	funDigitalWrite(PA2, pull_high ? FUN_HIGH : FUN_LOW);
	Delay_Us(WE_PULL_SETTLE_US);
	uint16_t v = adc_once(WE_CH_WIPER);
	funPinMode(PA2, GPIO_CNF_IN_ANALOG);
	return v;
}

/* -------------------------------------------------------------------------- */

void we_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_GPIOA | RCC_APB2Periph_GPIOC |
	                  RCC_APB2Periph_ADC1;

	/* Both analog pins with NO pull. FR-E11 is explicit about PC4: a pulled-up
	 * digital input sources ~63 uA into the §4.4 summing node, shifting every
	 * band and presenting exactly as sensor leakage. That cost a full bench day
	 * on 2026-08-31 — see docs/gotcha-log.md. Do not "helpfully" add a pull. */
	funPinMode(PA2, GPIO_CNF_IN_ANALOG);
	funPinMode(PC4, GPIO_CNF_IN_ANALOG);

	/* ADC clock: HCLK/8 = 6 MHz, inside the part's 14 MHz ceiling with margin.
	 * Conversion time is irrelevant here — we are nowhere near a rate limit and
	 * a slower ADC clock is easier on a high-impedance source. */
	RCC->CFGR0 = (RCC->CFGR0 & ~RCC_ADCPRE) | RCC_ADCPRE_DIV8_2;

	/* 73-cycle sample time on both channels. SAMPTR2 holds channels 0..9,
	 * three bits each. */
	ADC1->SAMPTR2 = (ADC1->SAMPTR2 &
	                 ~((7u << (3u * WE_CH_WIPER)) | (7u << (3u * WE_CH_SWITCH))))
	                | (WE_SMP_73_CYCLES << (3u * WE_CH_WIPER))
	                | (WE_SMP_73_CYCLES << (3u * WE_CH_SWITCH));

	/* Single channel per conversion; the channel is selected per read. */
	ADC1->RSQR1 = 0;
	ADC1->RSQR2 = 0;
	ADC1->RSQR3 = WE_CH_WIPER;

	/* Software-triggered regular conversions. */
	ADC1->CTLR1 = 0;
	ADC1->CTLR2 = ADC_EXTSEL;          /* SWSTART as the trigger source */

	ADC1->CTLR2 |= ADC_ADON;
	Delay_Us(100);                     /* the part needs settling after power-up */

	/* Calibrate before the first conversion — FR-S18 step 3 exists so this
	 * completes before anything can read a register. */
	ADC1->CTLR2 |= ADC_RSTCAL;
	while (ADC1->CTLR2 & ADC_RSTCAL)
		;
	ADC1->CTLR2 |= ADC_CAL;
	while (ADC1->CTLR2 & ADC_CAL)
		;

	we_ready = true;
}

bool we_sample(uint16_t *raw)
{
	if (!we_ready || raw == 0)
		return false;

	/* FR-E07 integrity check FIRST, so a floating wiper never reaches the
	 * scaling path even once. */
	uint16_t up = wiper_probe_with_pull(true);
	uint16_t down = wiper_probe_with_pull(false);
	uint16_t spread = (up > down) ? (uint16_t)(up - down) : (uint16_t)(down - up);
	if (spread >= WE_PULL_SPREAD_FAULT)
		return false;                  /* open circuit — this sample is unusable */

	/* Let the node recover from the pull before the measurement that counts. */
	Delay_Us(WE_PULL_SETTLE_US);

	uint16_t code = adc_burst(WE_CH_WIPER);
	if (code > WE_RAW_MAX_CODE)
		code = WE_RAW_MAX_CODE;        /* cannot happen on a 10-bit ADC; cheap */
	*raw = code;
	return true;
}

uint16_t we_raw_max(void)
{
	return WE_RAW_MAX_CODE;
}

bool we_switch_sample(uint16_t *raw)
{
	if (!we_ready || raw == 0)
		return false;

	/* No integrity test here, and none is possible: the §4.4 summing divider
	 * has no supervision. An open or shorted sensor cable reads as "neither
	 * active" and cannot be told apart from a window between its stops. That
	 * limit is stated in TDS §4.4.6 and in regs.c's band decode; it is a
	 * property of the star topology, not an omission here. */
	uint16_t code = adc_burst(WE_CH_SWITCH);
	if (code > WE_RAW_MAX_CODE)
		code = WE_RAW_MAX_CODE;
	*raw = code;
	return true;
}
