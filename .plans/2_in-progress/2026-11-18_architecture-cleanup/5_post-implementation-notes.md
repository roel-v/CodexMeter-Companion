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

Phase 3 reader fencing: production chat connections and quota/token fetches now capture generation
leases before asynchronous work. Obsolete successes and failures cannot publish health or payloads.
Quota and unread-account context changes reset recovery evidence; unread samples reject account
changes during database reads. Context fingerprints are local and absent from status/diagnostics.
Validation: 54 reader, daemon and compatibility tests passed, including delayed success/failure
and account rebind regressions.

## Phase 4 — Shared sessions and delivery

Extracted CompanionSession, companion wire codec and DeliveryPump. USB/BLE are sibling adapters;
Bluetooth no longer manufactures serial candidates or invokes a USB worker. Session contracts now
include actual boot/revision preconditions and lifecycle fields. Policy callbacks take delivery state.
Validation: 59 focused transport tests passed. Full suite: 379 passed, one Windows launcher
lifetime fixture missed its marker; isolated rerun plus coordinator tests: 29 passed. The launcher
code is unchanged; retain this intermittent test observation for final verification.

## Phase 5 — Logical devices and shared policy

Moved DeviceManager/DeviceSlot into neutral modules and BLE discovery/worker into backend modules.
Removed the old facade and migrated production/tests/tools. DeliveryState and devices status are
canonical; the duplicate ble status projection is removed. One policy instance now owns both periodic
lock observations and reconnect reconciliation, including broadcasting transitions to other displays.
Historical reason strings are translated only at the legacy BLE wire boundary. Discovery pause/resume
and session delivery exclusivity have explicit APIs. Removed the unused alternate discovery loop and
initial-worker path; recovery tests now drive the production manager loop.
Validation: 81 initial boundary tests passed; extended affected tests 109 passed plus one outdated
fixture, corrected; final focused recovery/coordinator checks 36 passed.

## Phase 6 — Firmware capabilities and shared activity semantics

Board capabilities now select real power/settings/sensor services. Ball uses a separate manual
orientation backend and retains its stored rotation; touch owns its bus initialization. Removed
Ball dummy power, sensor, theme and settings implementations. Unsupported optional commands report
UNSUPPORTED. Both dashboards derive partial and stale task counts from the shared view model;
the square display also expires valid running-only samples at the shared 15-second boundary.
Validation: native protocol/view-model harness passed; all three PlatformIO targets built successfully
including the original S3 compile-only target. Static RAM is unchanged from the retained baseline.
The full Python run during compilation had two 2-second offline subprocess timeouts (378 passed);
a subsequent isolated hook/launcher run passed all 15. Final suite will run without compiler load.

## Phase 7 — Obsolete host paths

Removed the unused single-display BLE discovery/run loop and its private name filter, duplicate
sleep helper and connected-lookup wrapper. Production macOS lookup remains in multi-device discovery.
Removed BLE delivery forwarding methods and the test-only inventory wrapper; consumers now call
the common implementations directly. Validation: 79 affected tests passed.

### Shared limits

Protocol frame/application limits now own all corresponding host/firmware buffers and validators;
ATT values retain a separate Bluetooth limit. Named delivery freshness, alert TTL/capacity and intent
TTL preserve behavior; firmware's larger deduplication ledger and 5-second margin are documented.
Compatibility diagnostics derive supported stream versions from the validator. Screen timeout uses
its existing settings owner. Validation: 78 affected tests, then 30 protocol/delivery tests (including
cross-language bound agreement) passed; native firmware harness passed after the final changes.

### Release metadata

codexmeter/__init__.py remains the release-version authority (no numbering change). An import-free AST
reader validates four numeric Windows version components. Nuitka consumes that value and PlatformIO
generates a header in its D: build directory; the isolated MTU test suffix remains explicit.
Validation: full Python suite passed, 387 tests, without compiler contention. Header generation is
stable when unchanged and rejects malformed/duplicate/oversized versions before output. Final target
and onefile builds are running as phase-8 verification.
