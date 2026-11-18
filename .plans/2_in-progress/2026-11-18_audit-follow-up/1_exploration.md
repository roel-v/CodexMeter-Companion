# Audit follow-up: delivery, maintenance and verification

## Status and baseline

Planning requested 18 November 2026. Implementation has not started.
Scope: all eight findings in [the follow-up audit](../../../docs/code-audit-2026-11-18-follow-up.md).
Baseline: c4a89a0; the audit report is currently untracked. Existing regression baseline: 395 passing Python tests.

This is bounded fix-forward work after
[architecture cleanup](../../3_done/2026-11-18_architecture-cleanup/1_exploration.md).
Retain that implementation and its historical evidence; no rollback or replacement architecture is proposed.
Correct overbroad completion claims with linked follow-up dispositions after each finding is actually verified.

Work personally in the existing checkout, without sub-agents. Preserve unrelated local changes.
Keep USB/Bluetooth fallback, legacy BLE/rollback, current Windows/macOS support, all three firmware targets,
current layouts/themes, settings, pricing history and compatibility monitoring. Keep-awake and MCP remain separate.
No new wire protocol version, release numbering policy, automatic restart, installer or network service.

This request authorizes planning only. Implementation, deployment and publication are separate actions.
On subsequent implementation authorization, follow the standing instruction: grouped baseline commits first,
then focused commits after each verified fix. Do not push or publish without a request.

## Behavioral decisions

- Keep screen-on/screen-off. With no device selector, retain broadcast intent but resolve it into independent
  per-device manual commands. Add an optional full device ID selector using the existing identity rules.
- Eligible targets are enabled, connected, outside maintenance and compatible with the requested control.
  Negotiated devices additionally require verified current boot/revision state. Preserve legacy capability rules.
  Do not queue manual commands for disconnected negotiated displays or invent revisions.
- Return per-device queued/rejected results, including reasons. Queued means admitted, not applied.
  No eligible target is an error. Partial broadcast success is reported explicitly and produces a nonzero CLI
  exit status; do not roll back targets that accepted a command. Keep existing single-device queued responses usable.
- Manual screen state and automatic lock policy are separate intents throughout queueing and delivery.
  Preserve the firmware rule that both manual and policy state determine whether the screen is on.
  CLI manual commands cannot impersonate internal lock/unlock policy; reject unsupported --reason values clearly.
  Inventory repository callers before narrowing this historical argument and migrate them together.
- An explicit negotiated intent expires at age >= 60 seconds, including time spent waiting for the send lock.
  Never refresh its timestamp/revision automatically to make a stale command succeed. Retain conflict rejection.
- Telemetry may be replayed only while its producer observation is younger than the shared 300-second limit.
  Sending or acknowledging it does not refresh observation time. Apply this to legacy and negotiated paths.
- Maintenance distinguishes definitely unsent requests from potentially applied requests. A stale local session
  is not proof of uncertain device ownership. Unknown outcomes retain the durable pause and explicit Resume behavior.
- Synthetic validation data must have a consistent outer kind and wire k, cannot compete with live producers,
  and must be verified as rendered content. A successful CRC transfer alone is insufficient.

## Execution and storage

Implement phases sequentially. Add regressions that fail on the baseline before changing the affected behavior.
Use real consumer paths with fake clocks/channels and synchronization barriers; avoid timing-dependent sleeps in tests.
Each phase ends with relevant tests, diff review and a focused commit; split independent fixes within a phase as useful.
Record finding -> change -> test -> evidence, actual deviations and remaining limits in post-implementation notes.

Use D:/build/CodexMeter for active build output, dependency caches, compiler scratch and test temporary files.
Source repository and retained ignored evidence stay on E:. Use a new
dist/windows/validation/audit-follow-up-20261118 directory; preserve prior acceptance and rollback artifacts.
Before large builds check D: headroom and inventory cold-data candidates; do not silently move active/evidence-bound data.
Do not touch the live companion or displays for unit/integration tests. Hardware tests need an explicit deployment scope.

## Phase 1 — Manual commands, queue semantics and final-send intent validation

Findings 1, 2 and 5.
Primary files: cli.py, events.py, device_manager.py, queueing.py, delivery.py, delivery_pump.py, companion_session.py.

1. Add regressions from CLI argument parsing/EventServer dispatch through manager and real negotiated session with
   fake USB/BLE channels. Demonstrate the current queued-success/rejected-delivery mismatch.
2. Introduce one manager entry point for manual control admission, usable by targeted UI/IPC and broadcast CLI.
   Resolve each target independently, validate eligibility and bind its own boot/revision. Never reuse one device's
   Payload identity or intent ledger entry for another device. Preserve the legacy adapter's supported controls.
3. Route screen events through that entry point; keep internally generated screen policy on a separate explicit path.
   Report per-target admission outcomes. Document the CLI selector, partial-failure exit status and queued semantics.
4. Give controls semantic coalescing keys: screen/manual, screen/policy, brightness and rotation.
   Retain only the latest request within the same key, preserving order across distinct keys. Review desired_control,
   desired_settings, explicit_payloads and reconnect bookkeeping so the queue fix does not leave a second conflation.
   Remove evicted/superseded intent entries; a discarded request must not reappear during reconnect.
5. Centralize explicit-intent validation and pruning. Validate age, boot and revision on replay and immediately before
   the first wire write, after waiting for serialization. Carry the original deadline to the session boundary;
   a pump-only check before acquiring the session lock is insufficient.
   An already-written transaction may finish its bounded same-sequence ACK/retry resolution; do not turn expiry into
   a new transaction or discard uncertainty. Expired unsent intents are removed and reported without reconnecting.
6. Reject malformed/manual policy-spoofing events at admission. Do not change firmware's conflict checks to hide errors.

Tests:
- Single target and broadcast across USB, negotiated BLE and legacy BLE; independent revisions and mixed eligibility.
- No targets, disconnected device with/without cached state, disabled, maintenance and incompatible devices.
- Manual off followed by unlock and reverse order; manual on plus lock; repeated brightness and repeated manual state.
- Queue-pressure eviction, superseded controls and reconnect: no silently resurrected explicit request.
- Intent ages just below/exactly at/above TTL; expired while waiting for send lock; boot/revision conflict;
  dropped ACK after a timely first write resolves under the existing bounded unknown-outcome rules.
- UI and CLI responses distinguish queued/rejected; firmware state changes are verified in session/harness tests.

Exit: all public manual routes use the same admission rules; policy and manual intents coexist; stale unsent controls
produce no DATA write on either negotiated backend.

## Phase 2 — Legacy freshness through actual connection and refresh consumers

Finding 3.
Primary files: delivery.py, ble.py and legacy BLE integration tests.

1. Extract/use a common telemetry freshness predicate based on producer observation time, separate from same-host
   replay rules that legacy firmware cannot negotiate. Do not pass legacy state through negotiated_replay merely
   to make its helper test pass.
2. Apply it to initial/reconnect replay, normal queued telemetry, device-requested refresh and health-check resends.
   Check usage and activity independently. A fresh activity sample must not be blocked by stale usage.
3. When neither is fresh, do not manufacture a data heartbeat. Preserve disconnect detection through backend
   connection state or an already-supported read-only health operation; do not invent a new legacy wire command.
4. Keep legacy ACKs, reason translation, alerts and upgrade/rollback behavior intact. ACK/replay never changes observed_at.

Tests: exercise BleTransport.connect_and_write with fake GATT lifecycle/notifications, not only delivery helpers.
Cover fresh/stale combinations at the TTL boundary, repeated refresh/health checks, producer recovery, disconnect,
alerts and cancellation. Assert exact wire writes and unchanged observation timestamps.

Exit: the reproduced one-hour-old reconnect payload and all stale refresh variants cause zero telemetry writes.

## Phase 3 — Explicit maintenance lifecycle and transport ownership

Finding 4 and lifecycle-contract portion of 7.
Primary files: device_manager.py, device_coordinator.py, usb_worker.py, ble_worker.py, ble.py,
companion_session.py, transport_types.py and usb_transport.py.

1. Define small typed worker/lifecycle and maintenance contracts around real consumers. Expose states such as
   connecting, ready, closing and closed, plus a completion signal for cleanup. Keep DeliveryPump's session contract small.
2. Serialize maintenance acquisition with worker teardown/transport changes, rather than reading worker.session with
   getattr and assuming it is usable. Define lock order and ensure fencing a worker never waits while holding a lock
   that its cancellation cleanup needs. Cover both USB-exposed and BLE-local negotiated sessions.
3. Preserve durable pause before opening maintenance handles and pause USB discovery before probing.
   If the original session is already failing/closing, await bounded native cleanup, reverify the endpoint identity,
   then acquire via a new exclusive USB maintenance connection. Readiness checks alone are not atomic enough.
4. Distinguish failure before any maintenance request is sent from a sent request with unknown outcome.
   For a definitely unsent stale-session case, finish/retry acquisition through the fresh endpoint within a bounded
   operation. If no endpoint can be verified, return a precise failure and retain the documented safe pause.
   Never automatically clear a pause when ownership may have changed.
5. Preserve BLE-to-USB maintenance ordering: claim maintenance before releasing a live same-host BLE owner, so
   telemetry survives. Preserve token persistence, wrong-device rejection, legacy quiescence limits and explicit Resume.
6. Give the whole operation a bounded deadline compatible with the existing IPC/tool caller timeout; audit callers so
   they do not time out while the daemon silently continues an unbounded acquisition.

Tests with barriers:
- Ready, connecting, failed, already closed and concurrently closing USB sessions.
- Cancellation before request, during write, after ACK and during native handle cleanup.
- Simultaneous mode change/disable, discovery probe, device removal/COM reuse and maintenance release/resume.
- Known-unsent fallback succeeds without a sticky pause; uncertain claim retains pause and token.
- Same-host BLE telemetry preservation; wrong identity, restart with stored pause, busy cross-host ownership.
- No handle leaks, overlapping readers, deadlocks or delayed tasks mutating a replacement worker.

Exit: normal close/reconnect races are handled in production, not hidden by fixture sleeps; uncertain ownership
still fails safely.

## Phase 4 — Finish worker/backend cleanup

Remaining finding 7. Depends on phase 3's lifecycle contract.

1. Inventory production/test callers, then make both workers single connection attempts. Remove single_attempt,
   redundant standalone retry loops, their backoff/jitter helpers and tests that exercise an unused production mode.
2. DeviceCoordinator alone owns retry, transport selection and fencing. Preserve current busy-owner delays, bounded
   backoff and immediate cancellation. Define how a disappeared discovery candidate ends an attempt without spinning.
3. Move bluetooth_availability to a BLE-owned module and migrate all callers/patch targets. Keep optional imports
   so USB-only operation works when Bluetooth is absent/inaccessible; preserve macOS behavior.
4. Remove obsolete imports/comments and use the explicit lifecycle boundary introduced in phase 3.
   Do not add C6/Ball desktop subclasses or compatibility re-exports with no supported consumer.

Tests: coordinator-driven attempt/failure/recovery for each backend, USB promotion/BLE fallback, absent adapter,
busy ownership and shutdown. Verify no unowned worker tasks remain. Static reference inspection confirms removed
modes/helpers have no repository consumers.

Exit: source structure matches runtime ownership; BLE capability detection no longer lives in the USB module.

## Phase 5 — Firmware limit ownership and parser boundary coverage

Finding 6.
Primary files: firmware/src/companion_protocol.cpp, protocol_limits.h and protocol agreement/native harness tests.

1. Replace parser frame/payload literals and local payload-buffer sizing with their existing owned constants.
   Audit other semantic consumers; retain unrelated 512 values such as independent ATT and memory-pool sizes.
   Do not change protocol values, frame format or board memory budgets.
2. Keep host/header agreement tests, but add actual parser dispatch tests for valid boundary-sized application/frame
   input, oversized input, truncated headers, invalid UTF-8 and no application mutation on rejection.
   Separate frame and application limits: an exact maximum frame may still have an oversized application.
3. Add compile-time relationships where buffers must hold payload_limit plus a terminator. Use a small native
   test build with deliberately reduced limits (test-only override or generated isolated header) to prove the
   parser and ledger consume the declared limits, rather than merely agreeing with today's numeric literals.
   Production artifacts must use the unchanged production header.

Exit: native parser tests enforce the boundaries; all C6, Ball and original S3 production targets compile.

## Phase 6 — Deterministic fixture inputs and screenshot content checks

Finding 8.
Primary files: events.py, daemon.py/provider wiring, tools/validate_architecture_cleanup.py,
capture tools and acceptance tests.

1. Validate the usage IPC payload's outer kind/wire k agreement and supported version before queue/state mutation.
   Reject mismatched usage/activity/control payloads clearly. Inventory existing callers and migrate the fixture.
2. Provide an explicit isolated validation mode with correctly typed usage/activity input and normal output transport.
   Select it at process startup in a disposable profile; disable live quota/chat/transcript producers for that mode.
   Expose its active state in diagnostics. Default launches must always use live producers.
   Avoid an unrestricted production IPC switch that can silently disable monitoring.
3. Feed immutable named cases with independent usage/activity records. Replace sleep-based capture readiness with
   bounded evidence that both records were accepted and the renderer has consumed the intended case.
   If host ACKs cannot prove render completion, add a small read-only validation diagnostic over existing maintenance
   tools containing only model sequence/metric validity/page data. Do not expose chat content or credentials.
4. Verify screenshot content, not just CRC: fixed expected value/label crops or semantic image fixtures at each board's
   native size, plus human visual review of the retained page matrix. Exclude dynamic reset/time/USB areas only where
   documented; do not mask the metrics under test. A baseline is reviewed, never auto-approved from the same candidate.
5. Fail on a missing/overwritten case, wrong page, timeout, capture error or failed cleanup. Include case ID, expected
   metrics, transport/device identity, ACK/render evidence and capture hash in results.
6. Restore original page/settings/modes and production process configuration in finally paths. Report restoration
   failures distinctly; do not mark an overall run passed because the PNG transfer succeeded.
   Preserve the old captures as evidence of earlier limitations.

Tests:
- Reject semantic-kind mismatch before enqueueing; inject usage and activity without coalescing across kinds.
- Prove live producers cannot overwrite fixture cases and normal startup is unaffected.
- Known/unknown/independently partial running/waiting/done, totals without breakdown, partial/unpriced costs,
  all relevant pages, waiting/recovery and completion alert.
- Inject a deliberately wrong displayed value and a dropped activity fixture: acceptance must fail despite valid CRC.
- Faulted capture, wrong page and restoration failure produce explicit failing results.

Exit: repeatable fixtures establish what each screenshot contains and cannot pass on transport integrity alone.

## Phase 7 — Integrated acceptance and truthful closure

Depends on phases 1–6.

1. Run the full Python suite, native firmware harness and all three production firmware builds using configured D: paths.
   Review resource deltas against the baseline; no new dependencies or unbounded queues/allocations for these fixes.
2. Build the standalone executable; run its isolated self-test with no Python on PATH, including tray/control panel,
   IPC and the public manual-command path. Test the packaged fixture-mode selection and default live-mode separation.
3. Under separately authorized local deployment, preserve current app/firmware hashes and rollback images, then run
   the improved fixture against actual C6 and Ball over USB and Bluetooth.
   Cover targeted/broadcast manual controls, OS-policy interleaving via controlled test inputs, reconnect,
   maintenance during teardown, freshness expiry, waiting/recovery, completion and every rendered metric case.
   Test cancellation/uncertainty with fakes rather than risky physical fault injection.
4. Restore original device settings and live app; verify both devices receive real telemetry.
   Simulated suspend timing does not count as physical PC sleep. Legacy hardware remains simulated unless available;
   original S3 is compile-only. The user's separate Bluetooth-less PC test and any longer soak remain disclosed,
   nonblocking external acceptance items; do not add them as new required user work.
5. Update architecture documentation, changelog and both audit disposition records with evidence links.
   Correct the previous overclaims without rewriting the original observations. Maintain post-implementation notes
   with commit IDs, exact artifacts, test results, screenshots and unresolved limits.
6. Check working-tree status, grouped commit history and ignored artifact boundaries. Move this work item to done
   only when its required gates pass; report deployment gates separately if not authorized. No GitHub release implied.

## Finding coverage

| Audit finding | Implementation | Required evidence |
| --- | --- | --- |
| 1 Manual CLI path | Phase 1 | CLI -> IPC -> manager -> negotiated delivery and firmware effect |
| 2 Control coalescing | Phase 1 | Both ordering directions, queue pressure, no reconnect resurrection |
| 3 Legacy stale telemetry | Phase 2 | Actual legacy connect/refresh/health write traces with expired data |
| 4 Closing-session maintenance | Phase 3 | Barrier-driven close/acquire races and safe uncertain outcomes |
| 5 Intent expiry | Phase 1 | TTL boundaries including send-lock delay and bounded in-flight resolution |
| 6 Parser constants | Phase 5 | Native dispatch boundaries, reduced-limit test and three target builds |
| 7 Obsolete modes/backend leaks | Phases 3–4 | Explicit lifecycle consumers and coordinator-only retry coverage |
| 8 Fixture/content gaps | Phase 6 | Producer isolation and deliberately wrong-content negative tests |

No blocking product questions were identified. The choices above preserve existing supported behavior while making
admission, delivery and acceptance explicit. Any newly discovered conflict with a supported caller must be recorded
before changing that contract.

