# Audit reliability cleanup

## Scope and baseline

Planning requested 18 November 2026; implementation has not started.
Baseline: main at `1398e9a`, 423 passing Python cases. The second follow-up audit is currently uncommitted:
[findings and reproductions](../../../docs/code-audit-2026-11-18-second-follow-up.md).
The preceding [completed follow-up](../../3_done/2026-11-18_audit-follow-up/1_exploration.md) remains historical evidence.

Address all seven new findings through bounded fixes and extraction of duplicated code. Retain the working architecture;
no rollback or replacement project is proposed. Work personally, without delegation, following the user's standing request.
Keep unrelated keep-awake/MCP plans out of scope. No release-version change, installer, automatic restart or new wire version.

Preserve Windows/macOS support, USB preference and Bluetooth fallback, supported legacy BLE, maintenance fencing,
all three firmware targets, current layouts/themes, pricing history, settings and compatibility monitoring.
Do not remove old-wire/header compatibility just because it is older. Original S3 remains compile-only on this machine.

This request creates the plan and future commit boundaries, not implementation or publication. On implementation:
move the whole plan directory to 2_in-progress, preserve existing user work and make the baseline commit first.
Installing a new candidate, flashing or publishing it must be separately included in the execution scope; earlier
acceptance of the previous candidate does not establish acceptance of this candidate.

## Behavioral decisions

### Honest manual command results

- Keep admission asynchronous and backwards compatible: existing ok/queued/per-device fields remain. Add an opaque
  command ID per admitted manual command and a bounded, authenticated IPC result lookup. Broadcast has one ID per target.
- Model queued and sending separately. Terminal outcomes are applied, rejected, expired, superseded, cancelled and unknown.
  Applied requires a matching device ACK. Settings readback is confirmation, not a substitute for the ACK.
- A proven ACK remains applied if subsequent state readback fails; show readback unavailable separately. Do not report
  a rejected command as applied because the display happens to have the requested value already.
- Unknown means a write may have applied but its outcome could not be established. Never silently rebase or retry an
  unknown manual command in a fresh session. Existing bounded same-sequence retries within the original session remain.
  Preserve telemetry/alert recovery and replay of definitely-unsent, still-valid explicit intents.
- Record supersession, queue eviction, expiry, disabling/removal and ownership-generation changes. Definitely unsent
  commands may be cancelled; potentially sent ones must not be labelled cancelled merely because a task was cancelled.
  Maintenance preserves the existing pause/replay policy and original deadlines for definitely-unsent commands.
- Retain terminal records in memory for ten minutes, at most 64 per device. Track at most 64 nonterminal commands per
  device and reject further admission clearly rather than evicting unresolved results. Prune terminal records by age/count.
  On daemon restart an old ID is unavailable, never implied successful; do not persist or replay the result ledger.
- Telemetry success must not erase a manual result. GUI polling must not overwrite unresolved/result messages with generic
  status. Track the selected command by both ID and device; switching selection cannot display another device's result.
- Display Queued/Sending until a terminal result. Conflict explains that settings changed on the display, shows refreshed
  settings when available and offers an explicit Retry using a new ID and newly observed boot/revision. Disable Retry
  until connected state is verified; never auto-rebase old intent. Unknown offers a state check before any explicit retry.
- Two fast commands may legitimately conflict under optimistic revision protection. The second must report that outcome
  accurately; this work does not silently serialize/rebase user intent against later physical settings.
- Negotiated and legacy controls use the same result contract. Legacy ACK proves application only to the existing legacy
  protocol's extent; do not invent boot/revision protection or ACK guarantees absent from that protocol.

### Resource and diagnostic boundaries

- Every SQLite reader closes its own connection on success and exceptions, without relying on GC. Keep read-only URI,
  schema validation, timeout and reader-generation checks intact; do not share connections across polling threads.
- Full-frame header search gets one monotonic deadline, using the existing line_timeout argument as the total header budget.
  Pass remaining time into each read; logs/blank lines cannot renew it. A valid header must arrive before the deadline.
  Raw-image and optional end-marker budgets remain separate. Recognize supported explicit failure markers promptly.
- Keep new checksummed and older full-frame headers working; retain tiled C6 integrity checks and maintenance cleanup.

### Refactoring boundaries

- Shared negotiated orchestration owns reconciliation, replay, queue consumption and logical-state lifecycle. Adapters own
  discovery, connection setup, identity acquisition, serial/GATT I/O and their outer handle cleanup.
- Resolve one host identity per manager and pass it to USB and BLE, including workers added/reloaded later. Resolve lazily
  when needed if existing construction tests/tools depend on avoiding user-data I/O at construction.
- Keep the existing three-model support policy. Move it out of the generic codec into an explicit shared support policy;
  do not silently claim support for arbitrary new hardware. Validate model syntax separately from support membership.
- Separate structural negotiated identity parsing, application compatibility and transport eligibility. Preserve current
  wire-v1 fields, including the historically named usb field; BLE must not inherit USB-only mandatory control capabilities.
  Require advertised controls only where controls are offered. Missing/malformed declared fields never downgrade to legacy.
- Keep application and wire versions distinct. Consolidate truly identical values/classifiers, not coincidentally equal
  numbers. Preserve legacy aliases exclusively at the legacy adapter boundary.

## Execution and evidence

Use D:/build/CodexMeter for active builds, isolated test environments, compiler scratch and caches through windows-env.ps1.
Before large builds check D: space and inventory cold-data candidates; do not move unrelated data or fall back to C:/E:.
Retain ignored evidence under dist/windows/validation/audit-reliability-cleanup-20261118 on E:.
Never commit binaries, captures, logs, scratch profiles, caches or private data. Retain earlier failed and passing evidence.

Each functional fix starts with a regression demonstrated against the unfixed code, then a focused passing test run.
Use fake clocks and explicit synchronization barriers rather than fragile sleeps. Use the real consumer paths with fake
wire/OS boundaries, not a second implementation of the behavior under test. Every phase ends in a reviewed staged diff,
relevant tests and a focused commit; update post-implementation notes with evidence and any deviations.
No new flaky process-wide exact handle-count assertion in the general suite: test deterministic connection closure directly.

## Phase 0 — Freeze the audit and plan baseline

Inspect git status, confirm current HEAD, separate any unrelated changes and preserve the audit reproduction paths.
Commit this plan and the second follow-up audit together before touching production code. Do not include ignored evidence.
Suggested subject: `Audit reliability cleanup: Record audit and phased remediation plan`.

## Phase 1 — Repair the contributor test entry point (finding 4)

Files: pyproject.toml, tests/run_tests.py, CONTRIBUTING.md, .github/PULL_REQUEST_TEMPLATE.md,
.github/workflows/python-tests.yml; scoped references to the old runner elsewhere.

1. Add a development/test extra containing pytest with a supported range; keep it out of runtime/onefile dependencies.
2. Replace the old function-calling runner with a thin pytest.main entry point forwarding CLI arguments and exit codes.
   Canonical command is python -m pytest; retain the wrapper only as the working historical entry point, not a custom engine.
3. Rewrite the contribution guide in English for this fork: correct issue/repository URLs, Windows/macOS setup, target
   names, current test/build commands and platform storage instructions. Align the PR checklist and CI dependency install.
4. Verify canonical and wrapper collection produce identical node IDs, including fixture-based and parametrized tests.
   Execute the documented commands in a clean D: dev environment. A deliberately failing isolated test must return nonzero.
   Keep tests of the wrapper narrow; do not recursively invoke the full suite from within itself.

Acceptance: documented setup installs its stated dependencies; all collected cases execute through pytest; no module list.
Commit: `Audit reliability cleanup phase 1: Replace obsolete contributor test runner`.

## Phase 2 — Close SQLite resources deterministically (finding 2)

Files: compatibility_readers.py and focused compatibility-reader tests.

1. Inventory open_database callers. Choose one closing context-manager contract and update every caller atomically.
2. Add close-tracking tests for read_roots/read_unread_snapshot: normal/empty results, schema failure, query failure,
   malformed input after database access and account-change rejection. Verify closure before the reader returns/raises.
3. Exercise real disposable read-only databases in repeated reads with GC disabled. Verify handles/connections are released
   without GC; use platform handle measurements as retained diagnostic evidence rather than exact portable assertions.
4. Keep account/generation fencing and error classification tests passing; run the relevant compatibility integration suite.

Commit: `Audit reliability cleanup phase 2: Close metadata database connections after each read`.

## Phase 3 — Bound screenshot acquisition (finding 3)

Files: tools/capture_screenshot.py, tests/test_screenshot_tool.py, affected capture/maintenance tests.

1. Add fake-clock noisy-stream, blank-line, missing-header and deadline-boundary regressions through capture_rgb565le.
2. Implement the single header deadline and concise timeout error. Handle ERR/FAILED/UNSUPPORTED/screen-off responses
   actually emitted by supported firmware; do not accept a tiled frame as a valid full frame.
3. Test remaining-budget propagation, no raw read after header timeout, valid response just before deadline, valid CRC,
   corrupt CRC, older headers, raw timeout and optional missing end marker. Keep serial handles and maintenance released
   on failure, and page restoration tests green.

Commit: `Audit reliability cleanup phase 3: Bound screenshot header waits`.

## Phase 4 — Carry command outcomes from admission to the panel (finding 1)

Files: device_manager.py, delivery.py, delivery_pump.py, queueing.py, ble.py, events.py, ipc_projection.py,
device_dialog.py and targeted CLI/panel/session tests. Add a focused command-result module if it keeps ownership clear.

1. Implement the bounded per-device ledger and additive authenticated result query. Allocate IDs at admission, attach
   them to host delivery metadata rather than changing firmware payloads. Preserve CLI broadcast/partial admission semantics.
2. Integrate transitions into both negotiated delivery and legacy writes. Ensure superseded/evicted requests cannot linger
   as queued or resurrect through replay. Expire unsent requests even while disconnected, with an explicit maintenance hook
   or manager timer; do not wait for another telemetry event. Distinguish ACK from follow-up readback failure.
3. Fence stale completions by command/device/session identity. Cover send cancellation, daemon shutdown, session failure,
   same-boot unsent replay, boot/owner change and ambiguous writes. Unknown explicit commands do not silently replay.
4. Drive the panel from correlated outcomes and refresh/retry rules above. Preserve older-daemon usability: if a successful
   admission response lacks an ID, say Queued, confirmation unavailable rather than Applied. Do not create a background
   automatic retry loop. CLI output continues to describe admission accurately; expose result lookup to CLI/tools if needed.
5. Tests: real EventServer -> manager -> queue -> pump -> session with fake channels, plus legacy ACK path. Exercise all
   terminal outcomes, result retention/capacity, telemetry after rejection, stale IDs, rapid commands, local swipe/rotation
   before control, mixed-device broadcast and selected-device changes. Assert unknown never becomes success by inference.
6. Add Tk/panel tests for Queued -> Applied/Rejected/Unknown, conflict Retry creating a new request, disconnected retry
   disabled, readback failure after ACK, window closure and late poll results. Verify actual widget behavior in the packaged
   self-test rather than only duplicating label-selection logic in a test.

Commits (keep backend/API and UI changes independently reviewable):
- `Audit reliability cleanup phase 4: Track manual command delivery outcomes`
- `Audit reliability cleanup phase 4: Show confirmed control results and explicit retry`

## Phase 5 — Share the negotiated connection lifecycle (finding 5, orchestration)

Files: usb_worker.py, ble.py, ble_worker.py, device_manager.py, transport_types.py; new shared runner if appropriate.

1. First characterize both existing adapter paths with the same fixture scenarios and explicit injected host identity.
2. Extract only common state setup, stale queue reconciliation, policy/replay ordering, delivery loop and cleanup.
   Keep serial discovery invalidation/active-port ownership and BLE client disconnect/notification fencing in adapters.
3. Pass the manager-owned host ID to both initial and dynamically added workers. Reuse _transport_options at construction.
4. Preserve coordinator-only retries, one active owner, maintenance lifecycle lock ordering and bounded cancellation.
   Avoid a shared runner that imports either hardware backend or calls back into coordinator locks during cleanup.
5. Parameterized tests through actual USB/BLE adapters: open/identity mismatch, same/different host, replay freshness,
   controls and outcomes from phase 4, completion dedupe, policy reconciliation, failure/cancel during each lifecycle stage,
   maintenance transfer, mixed-device independence and injected identity on both transports. Assert no orphan tasks/handles.

Commit: `Audit reliability cleanup phase 5: Share negotiated session orchestration`.

## Phase 6 — Separate wire validation from device support policy (findings 5 and 7)

Files: companion_protocol.py, device_metadata.py, device_identity.py, USB/BLE identity consumers, coordinator/worker/manager.

1. Characterize acceptance/rejection of all three current model identities through both transports, including legacy fallback.
2. Extract explicit model/application support policy from structural parsing, preserving the current supported-model set.
   Place transport feature requirements at USB/BLE entry points and capability decisions at the control consumer.
   Improve errors to name the actual transport/unsupported contract, retaining actionable incompatibility reporting.
3. Share application-version support, busy-reason classification and any identical manual/policy predicates identified in
   scope. Preserve distinctions among wire/app versions, negotiated policy reasons and legacy translated aliases.
4. Test unknown-but-well-formed models, unsupported application/wire versions, absent/empty/partial capabilities, malformed
   declarations, aliases, and older identities. Unsupported devices must be surfaced without claims/DATA writes. Disabled
   controls cannot be admitted. Test busy reasons consistently at retry, failure accounting and recovery filtering boundaries.
5. Update architecture documentation to state where supported-model policy lives and why new hardware still needs review.

Commit: `Audit reliability cleanup phase 6: Separate identity validation and shared device policies`.

## Phase 7 — Remove obsolete scaffolding and consolidate theme utilities (findings 6 and 7)

1. Recheck references after phases 5/6, including tests/tools/string consumers. Remove unused discovery wait_for/change events,
   now-unreferenced wait_any/alias imports, and ignored used_successfully bookkeeping. Do not delete supported legacy behavior.
2. Remove the test-only exclusive_delivery production API; replace its one test caller with a focused synchronization fixture
   around the existing send lock, preserving the final-send deadline regression. Retain try_maintenance lifecycle fencing.
3. Move identical set_label_text_if_changed and font_or implementations into a small dependency-light LVGL utility header.
   Preserve exact behavior, linkage and null handling; migrate all nine/ten callers after confirming bodies match.
   Leave theme geometry, typography and assets unchanged. Avoid unrelated formatting churn.
4. Run discovery/coordinator, legacy, maintenance and expiry tests. Build C6, Ball and original S3 after shared-header changes;
   record RAM/flash deltas and investigate material regressions. Exercise changed helper behavior through a minimal fake-LVGL
   test or existing render harness, covering unchanged/changed/null current text and preferred/fallback font selection.

Commits:
- `Audit reliability cleanup phase 7: Remove obsolete discovery and retry scaffolding`
- `Audit reliability cleanup phase 7: Share common theme label and font helpers`

## Phase 8 — Integrated verification and acceptance record (all findings)

1. Run full Python tests via the documented command; check wrapper collection parity. Run native firmware protocol/core and
   production/reduced-limit parser tests. Confirm all three firmware builds include the final source state.
2. Build a standalone Windows candidate on D: with pinned build dependencies. Retain executable/firmware manifests and hashes
   on E:. Run the isolated runtime/Tk/tray/CLI self-test, including the new command result/retry behavior, without live producers
   or hardware. Ensure test-only dependencies are not shipped as new runtime requirements.
3. Review cumulative diff and reference searches: every audit finding maps to a change and a meaningful regression or explicit
   cleanup verification. Update CHANGELOG.txt, architecture/contributor docs and audit disposition without rewriting historical
   findings as if they had never existed. Record actual test counts, commits, failures and limits in post-implementation notes.
4. If local deployment is in scope, back up/verify rollback artifacts, install the candidate and flash both boards. Restore
   original settings afterwards. Check USB/BLE/mixed modes, fallback, maintenance, waiting/completion/recovery, screenshots and
   real control outcomes after swipe/rotation and rapid commands. Review current images; CRC alone does not prove layout.
   Repeat five-minute freshness checks if lifecycle/replay changed. Do not test failure paths by killing the production app
   when an isolated fixture suffices. No overnight soak or other-machine test is a completion blocker.
5. If deployment is outside scope, record hardware acceptance as pending separately; do not claim it passed or mark the entire
   candidate hardware-verified using the previous release's evidence. Keep the work item in progress if that required gate
   remains open. Move the whole directory to 3_done only once the agreed scope and gates are actually complete.

Commit: `Audit reliability cleanup phase 8: Record integrated verification and audit disposition`.
No push/release unless requested. A later authorized deployment can add a focused phase-8 evidence commit.

## Coverage and ordering check

| Audit finding | Main phase | Required evidence |
| --- | --- | --- |
| 1: false Applied / lost results | 4 | End-to-end delivery outcomes and actual panel tests |
| 2: SQLite lifetime | 2 | Deterministic close on both readers' success/error paths |
| 3: unbounded header wait | 3 | Fake-clock deadline and capture cleanup regressions |
| 4: obsolete test entry point | 1 | Clean setup, collection parity, exit-code verification |
| 5: lifecycle/identity boundaries | 5, 6 | Both adapters, injected host identity, support-policy rejection |
| 6: unused machinery | 7 | Reference inventory and retained synchronization regressions |
| 7: duplicated helpers/constants | 5, 6, 7 | Consumer behavior tests, theme helper checks and three builds |

Implement sequentially 0–8. Phase 4 establishes delivery-result regression coverage before phase 5 changes orchestration;
phase 6 stabilizes policy ownership before phase 7 removes obsolete paths. Phase 8 verifies the final combination.
There is no existing feature_dependencies.dot to update and no dependency on the unrelated in-progress features.
No unresolved product questions are needed to write this plan; the decisions above are explicit implementation defaults.
