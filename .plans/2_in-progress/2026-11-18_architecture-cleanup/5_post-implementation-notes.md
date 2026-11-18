# Implementation evidence

Implementation authorized 18 November 2026; primary assistant only, no delegation.
Clean baseline: 266e6b8 after six grouped commits. Baseline regression: 365 passed.
Build artifacts, logs and backups remain ignored.

## Phase 1 — Control-panel health

Removed eager evaluation of an obsolete nested status response. Added a bounded IPC wait and
validated the response shape before publishing it to Tk. Regression tests invoke MeterApp.poll
through its non-tray worker path, including missing/malformed responses and recovery.

## Phase 1 — Display totals and costs

Both renderers now use token_display_row for availability, checked cost totals and partial flags.
Native fixtures cover valid totals without breakdown, unknown pricing and sum overflow.
Layout-specific currency formatting remains separate.

Validation: native firmware protocol/view-model harness passed. Existing host time_t-to-long warnings remain in model.cpp.

## Phase 2 — Neutral identity and board metadata

DeviceIdentity now lives outside BLE; all production, test and validation-tool imports migrated.
Metadata normalizes fw/app aliases for both transports and rejects conflicting canonical fields.
Firmware uses a shared board descriptor for model, geometry and capabilities. C6 now advertises
its firmware/application versions and dimensions; original S3 no longer claims to be a C6.
USB recognizes the retained S3 target. Identity output is bounded on every board.
Validation: 82 focused identity/BLE/USB/multi-display tests passed. Full board compilation remains
part of the final firmware build gate; no firmware has been installed during these edits.

## Phase 3 — Service power lifecycle

Added window-independent PowrProf notifications owned by the daemon service. Callbacks are fenced
to the asyncio loop and unregistered at shutdown. Duplicate resume events do not extend grace.
The long-gap heuristic is now fallback-only. No sleep-prevention or physical sleep was triggered.
Validation: 25 power/compatibility tests passed, including actual Windows registration/unregistration
and simulated short/long suspend, resume grace, cancellation and late callback fencing.

Phase 3 follow-up: empty-root success now originates only from a fresh inventory read, not
the publication timer. Actual observer-loop regression verifies the first publication preserves
the incident until the next source read. Chat/compatibility integration tests passed.
