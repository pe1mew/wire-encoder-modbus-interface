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

The release is the `encoder` environment. `encoder_test` is never
released.

## Releases

| Version | Date | Commit / tag | Binary (SHA-256) | Notes |
|---|---|---|---|---|
| 1 | — | *unreleased* | — | **Candidate, not yet tagged.** The original blocker is gone: integration stages A–F are complete and the firmware measures, publishes and reports health (verified — `software/hil/testReport.md`). Outstanding before a tag is warranted: **FR-E03** (five-ratio linearity, needs a precision resistance box), **FR-E15** (switch bounce, needs a 5 ms injector) and **TP-A03/TP-B23** (±15 % supply margin, needs an adjustable PSU). All three are blocked on instruments, not on code. Whether to release against open requirements is the maintainer's call. |
