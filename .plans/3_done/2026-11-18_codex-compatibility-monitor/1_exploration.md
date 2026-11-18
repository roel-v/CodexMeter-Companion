# Codex compatibility monitoring and warnings

Implementation completed on 18 November 2026 after explicit user authorization. The planning-only statements
below record the earlier approval boundary; see `3_overall-plan.md` and `5_post-implementation-notes.md` for results.

## Purpose and current baseline

Plan requested on 18 November 2026. Detect when an installed Codex build no longer supplies data in a format
CodexMeter understands, explain the impact, and keep unaffected readings working. Planning only; no implementation
or deployment is authorized by this document.

The real-profile incident was a version-11-only guard rejecting Codex chat-stream version 13. Desktop 3.12.3.3
explicitly accepts verified versions 11 and 13 and reports a sanitized chat observer reason. Its actual-profile
counts were verified on both displays. That targeted correction is the baseline for this broader feature.

Runtime evidence determines compatibility. Installed version numbers provide context, not a universal compatibility
guarantee. Undocumented semantic changes that still satisfy every validated contract may remain undetectable.

## Scope and behavior

- Monitor task-state streams, chat inventory/unread completion metadata, quota responses and local token data.
- Track failures independently. Running/waiting depend on the stream and inventory; completed-unread additionally
  depends on unread/history data. Token availability and pricing coverage are distinct concerns.
- Validate supported protocol versions, required fields/types, database schema and meaningful update freshness.
- Permit harmless additional fields/columns. Reject missing or incompatible fields that affect meaning; do not
  silently adopt unknown protocol versions or select an ambiguous user/account.
- Keep valid, unaffected data flowing to all displays and clients. A missing metric is unknown, not numeric zero.
- Treat Codex closed/not installed, connection loss, locked databases, authentication failures and provider/network
  failures separately from confirmed format incompatibility. Do not recommend a format update for ordinary outages.
- Provide a one-time tray notification and persistent control-panel warning for confirmed incompatibility.
- Clicking the notification or persistent warning opens the same explanation dialog. Recovery clears the warning
  only after the affected data path validates and supplies usable current data again.
- Preserve standalone Windows packaging and existing macOS behavior; Windows warning UI is the initial target.
- Do not install updates automatically, restart Codex, change its files, add tracking or transmit diagnostics.

## Proposed health contract

Introduce a shared compatibility-health service, with observations reported by existing readers rather than a
second set of watchers/pollers. Each component record contains:

- Component ID and affected public metrics.
- State: checking, compatible, unavailable, stale or incompatible.
- Stable reason code and safe structured details, such as observed/supported stream versions or a known field name.
- First observed time, last successful validation, last usable observation and current incident signature.
- CodexMeter version and best-effort version of the relevant Codex process/executable, with provenance and unknown
  represented explicitly. The GUI process and quota CLI may be different installations; do not conflate them.

Use monotonic time for deadlines and wall-clock UTC for diagnostic timestamps. Bound retained incident history.
Do not equate absence of changed values with stale data: idle chats and unchanged quota are normal. Stream freshness
must use supported liveness/snapshot evidence, not a demand for new text or job events. Where liveness cannot be
established, report uncertainty rather than inventing a successful heartbeat.

Proposed operating defaults to validate against the current polling intervals in phase 1:

- An explicitly unsupported version from a valid, correlated message is incompatible immediately.
- A missing required table/column, confirmed by read-only schema inspection, is incompatible immediately.
- Other structural failures require a second independent failed observation before an incompatibility toast;
  affected data becomes unavailable immediately. Timeouts and locks never become schema errors merely by repetition.
- Reuse existing provider deadlines/retries. Allow up to 30 seconds for initial connection/validation before showing
  an unavailable status; a verified incompatibility bypasses this grace period.
- Require two consecutive usable validation cycles for recovery, with no intervening failure. Keep stale state
  separate from compatible; do not count cached data or successful reconnect alone as recovery.
- Silence repeated tray toasts for the same incident, including across app restart. Re-arm after verified recovery
  followed by a new failure, or a materially different incompatibility. Persistent UI remains while unresolved.

## Warning experience

Example, with affected features filled from health state:

> CodexMeter can't read task counts from this Codex version.
> Check for a CodexMeter update. Other available readings will continue working.

Only claim other readings are available when their current health supports it. For multiple failures, summarize
all affected features in one notification and list their individual states in the dialog.

The dialog provides:

- A plain-language explanation and affected/unaffected readings.
- Check for updates, using the existing update dialog/checker; never automatic installation.
- Details: Codex/CodexMeter versions, detected format, supported formats, reason and last successful reading.
- Copy diagnostics: an allowlisted local report without transcripts, notification bodies, chat/account IDs,
  credentials, authentication/session tokens, raw messages, SQL rows or personal filesystem paths.

Respect disabled automatic update checks: opening a compatibility warning must not contact GitHub. An explicit
Check for updates action may use the existing manual-check behavior. Do not merge this warning with the separate
pricing-page-change warning or mislabel missing model pricing as a Codex format failure.

## Implementation phases

### Phase 1 — contracts, inventory and state model

1. Inventory actual data readers and consumers: chat_activity.py, ipc_projection.py, app_server.py, provider.py,
   local_usage.py, daemon.py and payload builders. Record the required fields/schema for each metric and its
   current freshness/retry behavior. Avoid reading or retaining transcript content for this investigation.
2. Map failures to affected metrics and explicit reason codes; define how partial availability is represented.
3. Identify the relevant Codex process/CLI version through supported local metadata, off the UI thread with bounded
   calls. Record unknown/ambiguous results without failing otherwise working telemetry.
4. Implement a small testable health model with injected clock and incident/recovery transitions. Keep notification
   persistence separate from volatile observations and avoid stale health being trusted after restart.
5. Freeze timing choices and the schema before reader integration; document any justified adjustment to defaults.

Exit: tests cover independent components, startup, stale/unavailable/incompatible states, incident identity,
restart deduplication and recovery. No runtime dependency on a physical display or Bluetooth.

### Phase 2 — reader validation and health reporting

1. Extend the existing 11/13 guard with structured safe details and snapshot/patch validation at the metadata
   projection boundary. Preserve bounded streaming and memory use for oversized messages; never buffer transcripts.
2. Add read-only SQLite schema checks and distinct outcomes for missing schema, missing files, locks and corruption.
   Validate unread-account selection separately. Corruption is not automatically a format-change diagnosis.
3. Validate quota and token-event structures, including numbers, units, timestamps and required discriminators.
   Skip unrelated event types without declaring failure; distinguish no usage history from an unreadable format.
4. Feed the shared monitor from normal reader operations. Keep existing backoff/cancellation and failure isolation;
   no extra provider requests or repeated full-database scans just to establish health.
5. Add bounded, transition-based diagnostics and preserve enough safe evidence to explain a failure.

Exit: known formats and harmless extensions succeed; unknown versions, invalid required fields and schema changes
produce the right component status. Idle, offline, locked and unauthenticated cases are not false compatibility alerts.

### Phase 3 — partial data, IPC and consistent display behavior

1. Extend status IPC additively with component health and affected metrics, using the privacy-safe projection.
2. Prevent invalid/stale readings from being sent as current values. Preserve existing quota/token cache policies
   only when their age and unavailable/stale status remain explicit.
3. Audit C6 and Ball availability rendering. In the incident, C6 showed dashes while Ball showed a fallback zero;
   an unknown running-chat count must not masquerade as zero. Preserve any genuinely known fallback metric only
   when its scope/availability can be distinguished clearly.
4. Use existing payload availability flags where sufficient. If partial availability needs a protocol extension,
   make it additive, document old/new desktop/firmware behavior and include the smallest necessary firmware change.
   Do not silently require a firmware update without compatibility handling.
5. Keep the monitor independent of future MCP and keep-awake implementations. They can later consume these health
   records; neither is implemented here and neither is a prerequisite.

Exit: failure of one data source leaves other valid values intact; both display models agree on unknown versus zero;
old supported clients remain usable, and exported status contains no private data.

### Phase 4 — persistent warning and notification dialog

1. Integrate with windows_tray.py, windows_app.py and the existing notification/update-dialog paths. Keep widget
   changes on the UI thread and data collection off it; avoid competing native notification-click handlers.
2. Provide the persistent warning, accessible click target and shared dialog with the actions described above.
3. Coalesce simultaneous failures, deduplicate by incident and preserve warning state across control-panel close/open.
4. Clear warnings on verified recovery. Dismissing a toast does not dismiss the persistent incompatibility status.
5. Extend native tray and packaged self-tests to exercise click routing, dialog reuse, recovery, copy-diagnostics
   redaction and interaction with pricing/update warnings without changing live user data.

Exit: each warning explains what stopped working and what to do; repeated reconnects do not spam notifications;
opening the warning makes no network request when automatic update checks are disabled.

### Phase 5 — regression, packaged validation and documentation

1. Add sanitized/synthetic fixtures for supported versions 11/13, unknown 14, malformed version types, snapshots and
   patches, missing fields/columns, harmless additions, SQLite locks, missing files, connection loss and idle streams.
2. Test partial failures and recovery, app restart with unresolved incidents, changing installed Codex versions,
   concurrent providers, both displays and operation without a display. Add bounded-memory and cancellation coverage.
3. Run the full regression suite and native firmware tests if firmware changed. Build on D: with explicit caches and
   temporary paths after checking headroom; retain candidate artifacts/evidence on E:.
4. Test the exact standalone outside the checkout without external Python. Verify actual current-profile telemetry
   read-only, then exercise incompatibility/recovery in an isolated fixture; do not mutate Codex's production files
   or install an incompatible Codex build to manufacture a test.
5. Verify actual warning/click behavior and display availability on both models where affected. Use fixed synthetic
   cases for expected failures and real-profile checks for healthy behavior, clearly distinguishing their provenance.
6. Update README/Windows guidance and changelog with warning meanings, supported contracts and limits. Preserve
   rollback artifacts and record tests, deviations and outstanding work in post-implementation notes.

Exit: exact-artifact tests pass, failures remain isolated and actionable, and neither compatibility nor recovery is
claimed from a version string or connection flag alone. Implementation, local installation, commits and publication
remain separate actions from this planning request.

## Acceptance matrix

| Situation | Expected result |
| --- | --- |
| Valid version 11 or 13, required data present | Compatible; current values shown |
| Valid message declares unknown version | Affected counts unknown; one warning; safe observed-version details |
| Extra irrelevant field/column | Continue working without warning |
| Required field/schema absent | Affected source incompatible after defined confirmation |
| Codex closed, pipe down, database locked or authentication fails | Accurate unavailable reason, no false format warning |
| Connected but required observation expires | Stale/unknown values; no fabricated zeros or false recovery |
| Legitimately idle stream with valid liveness evidence | Remains healthy without requiring chat activity |
| Only unread/history data fails | Done unknown; independently verified running/waiting remain usable |
| Quotas fail while local token data works | Quota unavailable; valid token/cost readings continue |
| Reconnect/restart repeats same incompatibility | Persistent warning, no repeated tray spam |
| Two successful current validation cycles after failure | Warning clears; normal readings resume |
| Copy diagnostics / open warning with auto-update checks disabled | Redacted report / no unsolicited network request |

## Dependencies and limits

Build on the current 3.12.3.3 correction and preserve the in-progress USB feature's delivery/ownership behavior.
Its pending second-PC acceptance is a separate concern, not proof of this monitor's compatibility. There is no
existing dependency graph to update. This feature can be prepared independently of the two new feature explorations.

No claim of compatibility with every future Codex version is possible. The monitor detects explicit version and
contract failures and loss of usable data; it does not validate arbitrary changed semantics automatically.

## Consistency review — 18 November 2026

These requirements resolve gaps found in the current source and override less-specific phase wording above.
Notification policy accepted by the user: the sustained-outage behavior below is required. No user questions remain.

- Phase 2 must split root inventory from unread identity/history reads. Currently read_inventory raises for either,
  disabling all counts. Unread failure must not terminate the stream or invalidate valid running/waiting counts.
- Phase 2 must decouple local token collection from quota-fetch success. Currently fetch requests quotas first and
  never reaches local usage on quota failure. Reuse one incremental local reader; do not duplicate scans or polls.
- Phase 1 must specify authoritative snapshot coverage and idle liveness. The existing three-second startup and
  two-second publication timers prove neither. Inventory success does not prove stream completeness. Do not require
  snapshots for all historical chats unless the protocol guarantees them. If completeness cannot be established,
  report unknown/checking rather than a fabricated zero or compatibility success.
- Unknown runtime status/active flags that affect classification are contract failures. Unrelated event types and
  harmless fields remain ignorable. Revision gaps first trigger resynchronization, not a format-change diagnosis.
- Incomplete final JSONL records are pending writes. Malformed relevant completed records cannot be silently skipped
  while showing a complete aggregate. Distinguish no history, zero usage, partial coverage and incompatible usage.
  Preserve valid totals separately from unavailable breakdown/cost; retain historical pricing and attribution rules.
- Define independent validation cycles per reader. UI refreshes and republishing caches never count toward recovery.
  Independent source reads may return unchanged valid values. Historical usage does not expire merely through idle
  time; validate source accessibility and date-window rollover. Freeze per-reader freshness limits in phase 1.
- Separate unresolved incompatibility evidence from current reachability. Closing Codex after a confirmed failure
  cannot clear/rearm that incident. Label persisted evidence as previous-run evidence until current validation.
- Ignore results from superseded reader generations/connections/accounts. Rebinding invalidates live observations.
  Do not conflate quota identity with ambiguous chat identity.
- Fingerprints use component/reason/safe contract evidence, never timestamps or arbitrary exception text. Persist
  at most 32 incident/notification/recovery records atomically in existing app data. Persistence failure is nonfatal.
- Coalesce concurrent failures over two seconds. Route notification clicks by category. If the backend cannot
  distinguish pricing/update/compatibility notifications, open a shared overview listing outstanding notices.
  OS-suppressed toasts must not hide the persistent warning or its accessible dialog action.
- Diagnostics allow only known field names and bounded primitive versions. Arbitrary upstream strings can contain
  private text. No raw exceptions, automatic uploads or transcript capture; copy only on explicit user action.
- Display scope is normal-layout unknown values, not a new warning page/full-screen overlay or completion alert.
  Define validity semantics and the old/new desktop/firmware matrix before phase 3. Old firmware unable to express
  partial validity must conservatively mark the group unknown. If it cannot, require a firmware update and explain
  the limitation in desktop device status; do not claim that pairing satisfies per-metric acceptance.
- Firmware changes are limited to required validity semantics on both models. Test identical semantics on USB/BLE,
  reconnect and cached-state replay. Keep the pending second-PC USB acceptance separate from this feature.
- Version discovery is bounded, best effort and cached by executable/process identity. Add no network-based version
  allowlist or extra update check. Monitor errors cannot stop transport delivery, collection or UI.
- Add regression tests for the above, including source independence, partial aggregates, stale-generation results,
  stream completeness, date rollover, notification routing, persistence failure and monitor cancellation/exceptions.
- This review changes planning documents only; implementation/deployment/publication await subsequent instructions.

## Accepted sustained-outage notification policy

User accepted the recommendation on 18 November 2026. Apply this alongside confirmed-incompatibility warnings:

- Notify once when a monitored reading remains unavailable or stale for five minutes of awake, eligible monitoring
  time without confirmed format incompatibility. Say which readings are affected and that the cause is unknown;
  do not claim that Codex changed its format or that installing an update will fix it.
- Suppress this outage notification when Codex is known to be closed or not installed. This suppression does not
  clear an already established incompatibility incident. Keep accurate per-source status visible in the panel.
- Pause the outage timer during host sleep. After resume, allow 30 seconds for reconnection before continuing the
  timer and reassess the source before notifying. Sleep and resume grace do not count toward the five minutes.
- Codex-closed/not-installed periods likewise do not count. A new eligible connection attempt starts a fresh
  five-minute window after startup grace; unknown process state alone must not suppress monitoring indefinitely.
- Deduplicate per outage, including app restart. Preserve incident/notification identity, but do not carry unverified
  elapsed downtime across restart: begin timing from fresh observations after startup grace. Rearm only after the
  same verified recovery rules used by the health service, followed by a new outage.
- Coalesce affected components and open the same diagnostic dialog from the toast and persistent status. If an
  outage becomes confirmed incompatibility, allow one updated notification explaining the newly confirmed cause;
  do not emit both notices for the same component in the same notification batch.
- Persistent unavailable/stale status appears according to the normal health/grace rules; it does not wait five
  minutes. Other valid readings continue normally. No automatic restart, installation or remediation is added.

Phase 4 includes these timers, notification wording and routing. Phase 5 must test the five-minute boundary with
an injected clock, brief failures, known-closed suppression, sleep/resume grace, restart deduplication, verified
recovery, multiple simultaneous outages and escalation to confirmed incompatibility. No physical sleep test is
required; use simulated lifecycle events so the pending USB acceptance scope remains unchanged.

Planning review is complete with no outstanding user decisions. Phase 1 still includes the specified technical
contract inventory and reader-specific freshness definitions; implementation has not started.
