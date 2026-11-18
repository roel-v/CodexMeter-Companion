# Architecture cleanup and audit fixes

## Status, ownership and scope

Requested 18 November 2026. Plan for addressing every finding in docs/code-audit-2026-11-18.md.
This turn prepares the plan only. The primary assistant will implement the phases itself, sequentially;
no delegation, subagents or model substitution. Implementation, deployment and publication are separate actions.

Work against the existing CodexMeter-Companion checkout, including the uncommitted USB and compatibility changes.
Do not reset, discard, sweep into unrelated commits, or replace that baseline with the last published release.
This is one bounded remediation project; the keep-awake and MCP features are not part of its implementation.

## Outcomes and fixed decisions

- Correct the separate control panel, inconsistent identities and divergent token/cost validity semantics.
- Finish production integration of compatibility generations and suspend/resume handling.
- Separate logical devices, shared protocol/delivery policy, transport backends and concrete firmware boards.
- Remove obsolete internal entry points and wrappers after migrating actual callers, including tests and tools.
- Give shared constants and release metadata explicit owners; preserve intentional differences in timing/capacity.
- Preserve current layouts, pages, gestures, themes, settings, alerts, pricing history and user configuration.
- Preserve Windows and existing macOS paths. USB remains Windows-supported; do not expand platform support here.
- Preserve the original S3 build target and give it its correct identity. Compile-check it; do not claim hardware
  validation without that board. C6 and Ball remain the physically verified targets.
- Preserve reachable legacy BLE and firmware-upgrade/rollback behavior behind explicit adapters. Remove internal
  import/status aliases once all repository consumers are migrated; do not maintain shims solely for old tests.
- Keep current wire/application versions and limits. No new ownership/preemption or retry semantics in this cleanup.
- Centralize release versions without choosing a new numbering scheme. Existing version-comparison behavior stays.
- No automatic restart/installation machinery, telemetry uploads, new network checks or physical sleep tests.
- No commit, push or GitHub release without a subsequent request.

## Target boundaries

Desktop dependencies:

Application/telemetry/UI -> DeviceManager -> logical device state + delivery policy -> DeviceCoordinator
-> backend connection worker -> CompanionSession -> SerialChannel or BleWireChannel.

Device discovery returns a canonical DeviceIdentity plus a transport endpoint. Model, geometry and capabilities
are data, not C6/Ball subclasses in the desktop. DeviceCoordinator alone selects/fences transport workers.
Registry persistence and maintenance use explicit methods; callers do not mutate discovery internals or session locks.

CompanionSession owns negotiated claim, lease, sequence/ACK correlation, revisions and maintenance protocol.
The shared delivery pump owns replay, freshness, alert identity and explicit control intent. USB and BLE adapters
supply discovery/connection/framing. BLE fragmentation/MTU and serial handle/line behavior stay backend-specific.
An isolated LegacyBleSession supplies the older JSON/ACK behavior where required; it must not weaken negotiated rules.

Firmware dependencies:

Serial/BLE framing -> shared ownership/protocol -> application state/shared view model -> concrete board renderer.
Board descriptors own identity, dimensions and capabilities. Board adapters own display, power, touch and orientation.
Optional themes/audio/settings are explicit capabilities, not a long list of dummy implementations on the Ball.
Static/compile-time interfaces are preferred; do not add heap-heavy abstraction to the C6.

## Execution rules

Each phase ends with targeted tests and a review of its diff and dependency direction. Record actual results before
advancing. If a required gate fails, fix it within that phase; do not mark it passed on the strength of unrelated tests.
Use production entry points where the defect was integration-related, rather than testing only a new helper.

Before implementation, move the whole work item to 2_in-progress and expand detailed phase files only as useful.
Maintain a finding-to-change/test ledger and 5_post-implementation-notes.md during implementation. Preserve the audit
and earlier compatibility evidence; add a correction pointing to this work for lifecycle claims that were too broad.

Active builds, caches and compiler scratch: D:/build/CodexMeter. Check headroom and inventory cold-data candidates
before large builds; do not move source, active dependencies or evidence-bound data without authorization.
Retained artifacts, logs, captures and rollback copies: ignored dist/windows/validation/architecture-cleanup-20261118
on E:. No bulky build output on C:. Build/test directories must be configured explicitly, including native tests.

## Phase 1 — Baseline and immediate behavior fixes

Scope: audit findings 1 and 3; establish evidence for every later removal.

1. Record working-tree status, relevant source/file hashes, current configuration schema, build targets and existing
   standalone/firmware artifact hashes. Preserve current candidate/rollback evidence; do not commit the dirty baseline.
2. Run the existing relevant regression baseline. Record pre-existing failures separately from introduced failures.
3. Add a failing regression through the non-tray-managed control panel's polling path using the actual ping shape
   (`status` is a string and `compatibility` is top-level). Fix projection and exception handling. Test daemon absent,
   malformed health data and subsequent recovery; keep Tk changes on the UI thread and IPC bounded.
4. Add shared display-data fixtures for valid totals with unavailable breakdown, independently unknown counts,
   partial/unpriced/unknown costs, cost-addition overflow, and stale activity. Fix C6 total suppression and unsafe sums.
   Preserve differing layout precision where required, but agree on numeric meaning, unknowns and '+' semantics.
5. Inventory entry points/imports/string consumers and currently reachable legacy paths. Mark removal candidates with
   their callers and intended replacement. Do not delete code based only on one no-reference search.

Exit: failing repros pass through the actual affected routes; baseline is recorded; no user layout/settings change.

## Phase 2 — Canonical device identity and board descriptions

Scope: audit finding 2 and identity portion of 8.

1. Define a neutral DeviceIdentity independent of USB/BLE discovery wrappers. Separate common device metadata from
   negotiated-session facts (boot generation, wire version, ownership support) and backend endpoint addresses.
2. Normalize existing fw/firmware and app/protocol aliases once. Reject contradictory declarations rather than silently
   selecting one. Preserve strict ID/short-ID checks, unknown versus absent capabilities, and malformed-metadata rejection.
3. Make USB and BLE identity readers consume the same validated representation. Registry binding must not lose known
   version/capabilities when changing transport. Remove USB's conversion through BleIdentity.
4. Add board descriptors for C6, Ball and original S3 using verified hardware configuration. Generate consistent identity
   JSON, including actual dimensions, touch/manual rotation and auto-rotation capabilities. Do not infer battery presence.
5. Keep emitted identities within the existing BLE identity and serial frame bounds; check snprintf truncation for every
   branch. Preserve device IDs and persisted registry/settings keys; correct only inaccurate model metadata.

Exit: same identity bytes yield equal common metadata on USB/BLE; switching does not downgrade metadata; both current
boards and original S3 have correct distinct identity fixtures; old compatible identity shapes remain readable.

## Phase 3 — Complete compatibility lifecycle integration

Scope: audit finding 7 and supported-format diagnostic duplication.

1. Introduce a lifecycle event source owned by the running service, with bounded Windows suspend/resume notifications
   delivered safely to asyncio. It must work in packaged and headless entry modes, unsubscribe on shutdown, and not
   rely on a control panel being open. Reuse existing native infrastructure where suitable.
2. Keep the existing long-gap guard only as conservative fallback when explicit power events are unavailable. Do not
   present an event-loop stall as confirmed sleep. Avoid double-counting/resume grace when both signals arrive.
3. On resume: pause accounting for sleep, apply the existing 30-second grace, reassess source freshness and preserve
   unresolved incidents/deduplication. Preserve the five-minute awake-eligible outage policy and known-closed behavior.
4. Bind generation tokens to actual stream connections and reader/account contexts. Invalidate on reconnect/rebind and
   capture tokens before asynchronous reads; discard late obsolete successes AND failures before state/payload mutation.
   Keep account ambiguity explicit and use existing bounded identity signals, not transcript reads or extra network polls.
5. Count empty-root stream success only after a fresh successful inventory/coverage observation. Repeated publications
   must not count as recovery. Expose supported stream versions from the same source used by validation.
6. Add integration tests driving the service lifecycle/reader completion paths: short and long suspend, resume grace,
   late results, account rebind, cancellation, empty inventory, closed Codex, persistence/restart deduplication, and
   monitor failure without loss of telemetry delivery. Do not merely call power()/begin() directly in all tests.

Exit: lifecycle protections have production callers and service-level evidence. Physical host sleep remains excluded.

## Phase 4 — Common negotiated session and delivery pump

Scope: audit findings 4 and 6.

1. Define minimal, actually consumed typed interfaces: wire channel, discovery endpoint, negotiated session and worker.
   Specify send revision/boot preconditions, open/state/failure/generation, maintenance and close/release semantics.
   Keep optional maintenance in its own interface if not common to legacy sessions.
2. Extract shared framing/envelope validation into a neutrally named protocol module; retain USB line and BLE fragment
   decoders at backend boundaries. Preserve all current bounds, deadlines, correlation rules and error outcomes.
3. Extract CompanionSession from UsbSession. USB and BLE construct it directly with their channel/endpoint; no fake USB
   candidates for BLE, no backend importing the other's worker, and neutral error names for common failures.
4. Extract the shared delivery pump from UsbDeviceWorker._deliver and negotiated loops. Use one path for freshness,
   replay, accepted/unknown/rejected outcomes, pending alerts, settings revision conflicts and cleanup.
5. Preserve cancellation fencing: old callbacks/results cannot update a new session. Preserve stable alert IDs on
   uncertain delivery, queue bounds, manual screen-off, and settings reconciliation before replay.
6. Run the same session/delivery contract tests against fake serial and BLE channels, then backend-specific tests for
   partial frames, MTU 23, late notifications, serial removal/blocked open, lease expiry, malformed replies and reconnect.

Exit: Bluetooth does not inherit USB or call its private worker; both implementations satisfy used contracts and
retain the existing wire behavior. Legacy handling remains isolated and explicitly tested.

## Phase 5 — Logical device management and common policy

Scope: audit finding 5 and policy/status part of 11.

1. Move the real DeviceManager/DeviceSlot into neutral modules and import DeliveryState directly. Move BLE discovery
   into its backend. Migrate application/tests/tools atomically; do not leave the old facade as the new architecture.
2. Make backend construction explicit/injectable. A USB-only/no-adapter startup must not require a working Bluetooth
   runtime or attempt radio recovery. Preserve existing macOS BLE lookup behavior.
3. Keep registry storage and transactional mutations distinct from coordination. Expose public discovery pause/resume,
   invalidate/reprobe and maintenance acquire/release operations instead of accessing private sets/maps/locks.
4. Keep DeviceCoordinator responsible for mode selection, retry/fencing and owned-elsewhere behavior. No parallel
   writers, automatic maintenance release, cross-host settings replay or changed USB-preemption policy.
5. Give one host-level service ownership of lock observation and LockScreenPolicy. Both periodic delivery and reconnect
   reconciliation consume it; reconnect still takes a fresh OS observation before applying policy.
6. Emit neutral lock/unlock reasons in common code. Translate only within the legacy adapter where required; remove
   BleState and single-display screen-policy parameters after migrating their users.
7. Define the canonical local status schema with devices, per-device transport, metadata and health. Migrate all bundled
   UI/CLI/capture/validation consumers from ble aliases. Keep CLI commands/config storage supported; internal imports
   and duplicate status fields are not a public API promise. Remove aliases only after consumer verification.

Exit: neutral management imports no backend state classes; USB-only, mixed-device, lock/reconnect, maintenance and
registry-failure tests pass; a canonical-status response works with every bundled consumer.

## Phase 6 — Firmware board adapters and shared view semantics

Scope: audit finding 8, remainder of 3, and activity-freshness duplication.

1. Define a small common dashboard interface for data updates, pages, waiting/power indication, gestures and alerts.
   Keep round/square renderer code and current page behavior separate; no visual redesign or removal of C6 themes.
2. Put per-metric validity, activity freshness, token-total availability, checked cost sums and partial-cost flags in
   the shared view model. Renderers consume those results, with explicit width-dependent formatting options.
3. Split manual orientation from sensor-backed auto-rotation; split Ball touch and board power capability from its
   current combined hardware shim. Represent unavailable sensing as unknown, not a fabricated sensor/power value.
4. Expose optional theme/settings/audio/battery capabilities explicitly. Compile optional dispatch or return unsupported
   for absent operations; remove dummy theme_registry and no-op UI functions where their callers can be gated.
5. Update serial maintenance/test command dispatch to honor capabilities. Keep capture, identity, flash/recovery and
   test tools working; unsupported commands must not silently report success.
6. Rename stale BLE-specific names that now describe common companion state. Keep ownership/parser/board-driver
   boundaries clear in main.cpp without introducing per-frame heap allocation or increasing unbounded buffers.

Exit: shared semantic fixtures pass for both renderers; no Ball dummy subsystem is needed solely to satisfy linking;
all retained build targets compile and C6 memory/flash use remains within its actual limits.

## Phase 7 — Dead paths, shared constants and release metadata

Scope: audit findings 9, 10 and remaining 11.

1. Re-run reference/entry-point checks after migration. Remove _initial_worker, unused single-device BleTransport.run,
   superseded DiscoveryService.run, test-only read_inventory and exclusively owned helpers when confirmed unused.
   Retarget tests to production interfaces; do not preserve a dead wrapper just to keep its test green.
2. Remove BleState/helper re-exports and old manager import facade after all repository consumers move. Consolidate
   duplicate stop-aware wait helpers if still needed in multiple modules. Keep legacy wire adapters with real callers.
3. Define constants by owner: protocol limits, delivery freshness/alert/intent limits, view-model validity, retry policy
   and supported Codex formats. Distinguish equal-valued but unrelated limits (ATT size versus application size).
4. Preserve/document intentional differences: host alert TTL versus firmware deduplication margin, host queue versus
   ledger capacity, USB versus BLE timeouts. Test cross-language protocol agreement with fixtures/static assertions.
5. Add one release-version source consumed by Python package metadata, Nuitka file/product version and firmware build
   flags/generated header. Support source installs/build isolation and explicit test suffixes; no circular package import.
   Packaging must fail clearly on invalid/mismatched metadata. Do not conflate release, status-schema or wire versions.
6. Update tools/docs/imports and build dependency declarations; remove only dependencies proven unused after extraction.
   Do not delete historical images, changelog entries, original README or retained evidence as part of code cleanup.

Exit: an audit checklist maps each candidate to removed/migrated/retained-with-reason; no unexplained obsolete facade
or duplicated authoritative constant remains; source and packaged version/identity checks agree.

## Phase 8 — Integrated verification and local delivery

1. Run the full Python suite and native firmware tests. Add import/type/contract checks that demonstrate the intended
   dependency directions; use behavioral tests for migration, not tests that simply mirror private helper bodies.
2. Build the standalone executable and C6/Ball firmware on D:. Compile-check original S3 separately. Compare resource
   use to baseline; investigate material growth, especially the no-PSRAM C6. Retain hashes/logs on E:.
3. Test the exact packaged executable outside the checkout with an isolated profile and no Python environment on PATH.
   Exercise tray-managed AND separate control panels, status/notification clicks, settings, clean exit and restart
   persistence. Verify authenticated local IPC and graceful behavior when the daemon is absent.
4. On authorized local deployment, retain rollback executable/images and settings evidence, gracefully stop the running
   companion, install at its existing startup path, and flash only identity-verified application partitions.
   Never silently overwrite a failed state before recording evidence. No automatic restart mechanism is added.
5. Test both actual displays over USB and Bluetooth: known/unknown/partial counts; totals without breakdown; cost
   flags; normal pages; waiting/recovery; manual-off preservation; completion alerts; controls; reconnect and cached
   replay; auto/forced modes; maintenance and resume. Verify equal metadata across transports and no duplicate alerts.
6. Test unavailable Bluetooth through injected backend failures and USB-only operation locally. The separate real
   no-Bluetooth-PC acceptance remains with the user; do not mark it complete based on simulation.
7. Use simulated power callbacks for host lifecycle integration; do not sleep/reboot the user's computer. No overnight
   or 30-minute soak is a completion blocker. Clearly disclose unperformed physical tests.
8. Restore live data, original connection modes/page/settings, both active connections and no maintenance pauses.
   Record sanitized final health, screenshots, checksums, rollback locations and deviations. Update README/changelog
   as unreleased work, correct earlier overbroad verification claims, and close only this remediation work item.

Exit: all mandatory automated/packaged/local-device checks pass, all audit findings have recorded dispositions,
limits are explicit, and no unrelated feature is marked complete. Publishing remains separately authorized.

## Audit coverage and dependencies

| Audit finding | Implemented in | Principal acceptance evidence |
| --- | --- | --- |
| 1: external panel projection | 1, 8 | Actual separate-panel polling and packaged recovery |
| 2: identity/board mismatch | 2, 8 | Same identity through both readers; all board descriptors |
| 3: rendering drift | 1, 6, 8 | Shared edge-case fixtures and both-device captures |
| 4: BLE inherits USB | 4 | Sibling channels, common session/delivery tests |
| 5: manager/policy coupling | 5 | Neutral imports, one policy owner, isolation tests |
| 6: unused/incomplete interface | 4 | Production consumers and backend contract checks |
| 7: lifecycle hooks not wired | 3, 8 | Service-level lifecycle, late-result and empty-root tests |
| 8: firmware dummy subsystems | 2, 6 | Capability dispatch, target builds, preserved UI behavior |
| 9: dead entry points/helpers | 7 | Reference/entry-point ledger after migration |
| 10: duplicate constants | 3, 6, 7 | Single owners and version/protocol agreement checks |
| 11: legacy paths/status | 4, 5, 7, 8 | Explicit adapters, migrated tools, maintenance/rollback tests |

Phases execute 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8, by the primary assistant alone.
The existing USB implementation is the baseline, not a request to redo its project. Its pending second-PC acceptance
and release preparation remain separate. Future MCP and keep-awake work should consume the resulting common status
and lifecycle interfaces rather than attach to BleState, a physical display, or a second chat observer.
No dependency graph currently exists; this plan does not introduce unrelated project scaffolding.
