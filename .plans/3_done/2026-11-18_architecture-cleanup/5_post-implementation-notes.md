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

### Final boundary review

Removed the remaining single-display screen-policy argument (production always passed None), leaving
only the shared policy and manager callback. The transport contract now types its negotiated identity.
Validation: 36 policy/coordinator/daemon tests passed, including the actual periodic observation loop.

## Phase 8 — Acceptance coverage

Added a bounded real-Tk standalone-panel check to the package self-test. It runs the actual asynchronous
polling worker against synthetic valid/offline/recovered ping replies and opens the details dialog.
The existing native tray check covers clicks, dialogs, recovery and clean exit. Source self-test passed
in an isolated D: profile; the final package must pass this expanded check too.

### Extraction import review

Removed unused protocol/helper imports left in the USB/BLE adapters and an unused BLE discovery type
alias. Retained the original Chinese architecture document under architecture.upstream.md while
replacing the current architecture guide. Adapter/discovery regression tests passed (recorded below).

### Maintenance race found during physical acceptance

USB task/total/cost captures passed after adding reconnect waits to the fixture. Bluetooth captures
then exposed a tool-side race: maintenance.py opened the USB port to rediscover an already-known
registered display while the daemon's USB discovery could own it. Capture tools now accept a full
expected device ID and delegate directly to daemon maintenance; the daemon pauses discovery and
verifies the identity before granting access. No identity check is removed. Validation: 35 maintenance
and coordinator tests passed, including a no-probe-before-pause regression. Earlier failed runs and
restoration logs remain retained. The high-rate initial fixture also observed a bounded serial-write
failure and correctly refused maintenance until recovery; no process crash occurred.

### Bluetooth maintenance data-preservation fix

Independent pixel inspection rejected C6 Bluetooth captures that contained waiting/unknown data despite
successful PNG transfers. The manager fenced/released BLE before claiming USB maintenance, changing the
firmware's previous owner to None and defeating its same-host telemetry-preservation rule. It now claims
maintenance first, then fences BLE; legacy devices and failed claims still fence safely. Validation: 36
coordinator/maintenance tests passed, including an ordering regression with discovery already paused.
The executable is rebuilt and the affected physical captures must be repeated; earlier transfer-only
success records are not treated as visual acceptance.

### Cancellation during native BLE disconnect

The rebuilt package reproduced an immediate GATT identity failure after maintenance twice. Ownership revocation
can start normal worker cleanup before coordinator.fence cancels that worker; its native disconnect was then
cancellable. Shield the bounded disconnect and await it before propagating cancellation, so the coordinator cannot
reuse the endpoint while cleanup is unfinished. Regression validation: 42 BLE/coordinator tests passed, including
cancellation injected after native disconnect starts. Both failed hardware runs restored settings and production;
the corrected package must pass the affected matrix before acceptance.

### Native USB probe cleanup before maintenance

The next detail capture was safely refused with 'serial operation already pending': cancelling an asynchronous
USB probe can finish before its native open worker disposes the late handle. UsbDiscovery.pause now waits up to
1.5 seconds for that cancelled probe's native admission keys to clear; timeout retains the pause and refuses access.
It does not wait on unrelated ports or bypass port exclusivity. Validation: 37 USB/coordinator tests passed,
including cancellation during native open, verified handle disposal and immediate reopening after pause returns.
A separate rejected C6 screenshot CRC exposed missing capture-tool page cleanup; the tool now restores overview
in finally, with a regression test. Rejected images remain failures, and failed runs remain retained.

### C6 bulk screenshot writer

Retained rejected-tile evidence established byte loss rather than a bad renderer: a 19,200-byte tile contained the
next TILE header at byte 15,819. The pinned HWCDC bulk-write path can discard queued bytes on a connection/buffer
stall. C6 captures now wait for the public connection-ready state, write at most 64 bytes within available ring
capacity, and bound stalled progress. Header/body/end markers use the same writer; the ISR kick is shared with
normal telemetry. The tiled-capture flag/code is compiled only for non-PSRAM boards. Wire formats and CRC checks
are unchanged. All three production targets compiled; native protocol/view tests passed. Both application images
were flashed with full identity and rollback-hash verification, and three complete C6 live-page captures passed.
The first Ball flash attempt refused to write when identity was unavailable; an explicit identity recheck and Resume
preceded the successful retry. No identity check was bypassed. Final repeated transport captures follow below.


## Final acceptance and local delivery — 18 November 2026

All eight phases are complete. All eleven audit findings have a disposition in
[the audit](../../../docs/code-audit-2026-11-18.md); [code structure](../../../docs/architecture.md)
documents the resulting boundaries. The original Chinese architecture notes are retained separately.

- Final Python regression suite: **395 passed in 25.30 seconds**. Native firmware protocol/view-model tests passed;
  the existing MSVC time_t-to-long warning remains in the host harness.
- All three production firmware targets built successfully. No release numbering change: 3.12.3.4 remains unreleased.
- Final Nuitka onefile self-test passed in an isolated D: profile with no Python on PATH: compiled entrypoint,
  child command, Tk, external-panel worker/offline/recovery/details, native tray interactions, pricing/update/device
  panels, WinRT and DPAPI. The exact installed final executable also passed repeated-launch/single-panel/close-to-tray.
- Both final application images were flashed with identity checks and verified writes. Full-flash recovery backups
  were checked first. No bootloader, partition table or NVS overwrite was requested.
- Installed the final executable at the existing dist/windows/CodexMeter.exe startup path. Its SHA-256 matches the
  tested candidate. Both displays reconnected over USB in auto mode, with no maintenance pauses. C6 brightness 70,
  auto-rotation enabled; Ball brightness 60, manual rotation 0; both overview pages and manual screen-on restored.
  The final live observer reported available data (2 running, 1 waiting, 7 completed unread chats at capture).

| Target | Static RAM bytes | Flash bytes |
| --- | ---: | ---: |
| Original Waveshare S3 | 127288 | 1641259 |
| Waveshare C6 | 54604 | 2413742 |
| Spotpear Ball V2 | 190784 | 1212126 |

C6/Ball static RAM is unchanged from the recorded baseline. C6 flash grew 448 bytes; Ball flash fell 2024 bytes.
Active builds, caches and scratch stayed on D: (about 99 GB free before the final builds); no unrelated storage was moved.
Retained artifacts/logs stayed under ignored E: dist/windows/validation/architecture-20261118. Full recovery images
remain in E:/DeviceBackups. The validation rollback subfolder preserves the original installed app and app partitions.

### Hardware evidence and rejected runs

The final firmware matrix in hardware-complete-final captured **42 complete screenshots without CRC failure**.
It exercised both models over USB and Bluetooth, equal identities/capabilities, known/unknown/partial task counts,
totals without breakdown, partial costs, all pages, mixed transports, forced/auto modes, applied brightness/rotation,
manual-off preservation across handover, completion notifications, waiting views, daemon restart and recovery.

Capture transfer success is not visual acceptance. Images were inspected independently. The isolated profile's real
chat observer can report unavailable between injected synthetic samples. Consequently, use hardware-complete-final's
usb-partial-0.png for C6 and hardware-partial-final's usb-partial-1.png for Ball as the accepted USB partial-count
images; the other attempt on each board showed the observer's unknown state. Both Bluetooth partial-count images in
hardware-complete-final show the intended partial values. Settled Ball Today/seven-day captures verify distinct totals;
earlier immediate-after-swipe captures were rejected because they caught an incomplete redraw.

The full matrix's final Ball settings-restoration request was refused against a reconnecting session. The fixture was
corrected to wait for a freshly acknowledged USB session; explicit restoration and subsequent hardware-partial-final
readbacks passed. installed-final.json and live-final-c6.png/live-final-ball.png confirm the final real-data state.
Earlier failed runs, including rejected CRC transfers, remain retained; they are not counted as passes. The retained
bad tile established dropped bytes, and the bounded writer then passed the complete 42-image matrix plus live captures.

Key retained evidence: final-artifacts.json; complete-packaged-selftest.json; installed-final.json;
installed-tray-final/tray-live.json; architecture-complete-regression.log; architecture-final-native.log;
architecture-capture-firmware-verified.log; flash-capture-C6.log; flash-capture-Ball-retry.log;
hardware-complete-final/package-results.json; hardware-partial-final/package-results.json.
The final desktop rebuild after hardware acceptance only removed an unused dictionary lookup and stale comment;
the exact rebuilt package passed self-test, installation/hash, live connection/settings and tray checks.

### Limits and follow-up choices

No physical PC sleep/reboot, overnight soak or separate no-Bluetooth-PC test was performed. Native power registration
and simulated lifecycle/backend failures are covered; they do not substitute for those physical tests. Original S3
was compiled, not flashed locally. More than two simultaneous displays was not tested. The user's separate-machine
USB acceptance and the future MCP/keep-awake features remain separate, unfinished work. No automatic restart machinery,
push or GitHub release was added/performed.

Fix forward remains appropriate for a bounded new defect. Replan if the strategy proves inadequate; restart if its
requirements or assumptions fail; supersede if the objective is replaced. None is currently needed to close this
cleanup. This closes only the architecture-remediation work item.

### Commit ledger (before this closeout)

The first six commits establish the grouped clean baseline; subsequent commits implement and validate the fixes.

- 7d94fc9 USB fallback phase 2: Add negotiated firmware ownership and metric validity
- a6904e3 USB fallback phases 3-4: Add host transport coordination and maintenance
- 86e103b Compatibility monitor phases 1-4: Integrate source health and desktop status
- b61dc32 USB fallback phase 5: Add safe firmware and physical validation tools
- 5dac706 Document USB fallback and compatibility baseline verification
- 266e6b8 Plan architecture remediation and future companion features
- 5a10498 Architecture cleanup phase 1: Fix standalone panel health polling
- c90b1d5 Architecture cleanup phase 1: Share token and cost validity rules
- 990c236 Architecture cleanup phase 2: Unify display identities across transports
- 7a30b4b Architecture cleanup phase 3: Connect health monitoring to power events
- 5246020 Architecture cleanup phase 3: Require fresh empty-inventory evidence
- b163ce9 Architecture cleanup phase 3: Fence obsolete reader observations
- 3dfca75 Architecture cleanup phase 4: Share negotiated sessions and delivery
- 474049a Architecture cleanup phase 5: Separate logical devices and backend policy
- 7fc4b78 Architecture cleanup phase 6: Separate board services and activity semantics
- bfa1f27 Architecture cleanup phase 7: Remove obsolete host entry points
- c316e67 Architecture cleanup phase 7: Consolidate protocol and validity limits
- 3e14aa2 Architecture cleanup phase 7: Generate build versions from package metadata
- 6621070 Architecture cleanup phase 7: Remove single-display policy coupling
- 69e6e7e Architecture cleanup phase 8: Verify both packaged panel paths
- 381d1b6 Architecture cleanup phase 7: Remove extraction import leftovers
- 4c11b4e Architecture cleanup phase 8: Broker known-device captures through maintenance
- b18fc9e Architecture cleanup phase 8: Preserve telemetry across BLE maintenance
- 501b039 Architecture cleanup phase 8: finish BLE disconnect before cancellation
- 91af6dc Architecture cleanup phase 8: document current boundaries and audit fixes
- 0bbd194 Architecture cleanup phase 8: restore page after rejected capture
- 2cb411e Architecture cleanup phase 8: await native USB probe quiescence
- f14a0aa Architecture cleanup phase 8: capture settled Ball frames
- ad4c0f3 Architecture cleanup phase 8: retain rejected capture evidence
- 16b903b Architecture cleanup phase 8: bound C6 screenshot USB writes
- 4eca4de Architecture cleanup phase 7: remove stale status migration remnants
- 4b9a7e9 Architecture cleanup phase 8: wait for reconnect before fixture restoration
- a8bd19f Architecture cleanup phase 8: retain exact-package acceptance matrix
