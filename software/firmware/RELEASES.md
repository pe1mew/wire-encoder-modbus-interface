# Firmware releases — version-byte registry (TDS FR-S32)

Register 30007 reports `(build_type << 8) | FW_VERSION`: build type 0x01 is
the potentiometric draw-wire build, the only one that exists; the low byte
is the release counter defined in `src/version.h`. This file is the
**release record** FR-S32's acceptance criterion refers to: every released
version byte maps to exactly one commit here.

## Release process

1. Finish and verify the work; the acceptance suite green.
2. Bump `FW_VERSION` in `src/version.h`.
3. Add a row below; commit; tag the commit `fw-v<N>`.
4. Build from the clean tagged checkout (NFR-BLD01) and record the binary
   SHA-256 in the row.
5. `software/hil/version_check.py` against a flashed DUT must pass.

The release is the `encoder` environment. `encoder_endswitch` is released
only where the mechanism has the switches fitted; `encoder_test` is never
released.

## Releases

| Version | Date | Commit / tag | Binary (SHA-256) | Notes |
|---|---|---|---|---|
| 1 | — | *unreleased* | — | Not releasable. The firmware has no measurement service (`design/integrationPlan.md` stages D–F are not started); it answers the register map but returns the FR-S23 pre-first-window value for every measurement. Version 1 will be tagged at the first release that actually measures. |
