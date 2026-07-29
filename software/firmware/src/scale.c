#include "scale.h"

uint16_t scale_opening(uint16_t raw, uint16_t offset, uint16_t travel,
                       uint16_t raw_closed, uint16_t raw_open)
{
	/* Work in magnitudes. Two reasons, both load-bearing:
	 *   1. the arithmetic is then identical whichever way round the two
	 *      calibration points are (FR-E04, direction-agnostic);
	 *   2. the whole computation stays in uint32. The signed form is
	 *      mathematically equivalent — both differences go negative on a
	 *      reversed mounting, so the quotient stays positive — but the
	 *      intermediate exceeds int32 and would force int64. */
	const uint32_t span = cal_span(raw_closed, raw_open);
	uint32_t delta;

	if (raw_open > raw_closed) {
		/* Normal sense: the code rises as the window opens. */
		delta = (raw > raw_closed) ? (uint32_t)(raw - raw_closed) : 0u;
	} else {
		/* Reversed mounting: the code falls as the window opens. */
		delta = (raw < raw_closed) ? (uint32_t)(raw_closed - raw) : 0u;
	}

	/* Clamp BEFORE the multiply. This is what bounds the intermediate at
	 * 65535 * 65534 (see scale.h); clamping afterwards would overflow first
	 * and clamp a wrapped value. Clamping at both ends is also what keeps the
	 * result monotonic in `raw` with no step at either calibration point. */
	if (delta > span)
		delta = span;

	const uint32_t pos = (uint32_t)offset + (delta * (uint32_t)travel) / span;

	/* 65535 is the FR-E07 fault sentinel and must stay unreachable here. */
	return (pos > 65534u) ? 65534u : (uint16_t)pos;
}

uint16_t scale_percent(uint16_t open_0_1mm, uint16_t offset, uint16_t travel)
{
	/* scale_opening() already clamps to [offset, offset + travel], so the
	 * subtraction cannot go negative in normal use — but this is also called
	 * with the FR-E07 sentinel and with values from a half-configured device,
	 * so both edges are guarded rather than assumed. */
	if (open_0_1mm <= offset || travel == 0u)
		return 0u;

	const uint32_t p = ((uint32_t)(open_0_1mm - offset) * 1000u) / travel;
	return (p > 1000u) ? 1000u : (uint16_t)p;
}
