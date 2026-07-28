/**
 * @file version.h
 * @brief Single source of truth for the firmware version byte (FR-S32).
 *
 * Defines @ref FW_VERSION, the low byte of Modbus input register 30007
 * ("firmware version / build type") owned by the @ref regs.h "register image".
 * 30007 pairs this per-release version with the build-type high byte (0x01,
 * the only build) so a master can identify exactly which binary a device is
 * running.
 *
 * Bump it @b only at release, in lockstep with a new row in
 * `software/firmware/RELEASES.md` and a `git tag fw-v<N>` on the released
 * commit — the RELEASES.md / register-30007 chain that ties source, changelog
 * and flashed device together.
 *
 * @note Version 1 is NOT released and must not be tagged until the measurement
 *       service exists (`design/integrationPlan.md` stages D–F). A device
 *       flashed with today's skeleton reports 0x0101 while returning 0 for
 *       every measurement register — correct per FR-S23, but not a product.
 * @see regs.h  Register image that publishes 30007.
 */
#ifndef VERSION_H
#define VERSION_H

/**
 * @brief Firmware release version — low byte of input register 30007 (FR-S32).
 *
 * Bump only at release, together with a RELEASES.md row and a `fw-v<N>` git
 * tag. @see the file-level chain above.
 */
#define FW_VERSION 1

#endif
