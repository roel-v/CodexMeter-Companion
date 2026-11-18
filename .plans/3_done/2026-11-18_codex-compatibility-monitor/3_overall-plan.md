# Implementation contracts and validation

Implementation authorized 18 November 2026. Phases are executed in order; no commit or publication requested.

## Phase 1: health model
- Components: stream, root inventory, unread history, quota, local tokens.
- Inventory/unread expire after 20 s; quota/tokens after 120 s; stream coverage after 90 s.
- The normal inventory read interval is 5 s, quota/local scan 60 s, source publishing 2 s.
- Startup/resume grace 30 s; unknown-cause outage notification after 300 awake eligible seconds; toast coalescing 2 s.
- Two independent successful observations clear a failed incident. Initial healthy validation may succeed once.
- Incidents persist locally, at most 32 notification fingerprints. A current reachability failure does not clear
  earlier incompatibility evidence. Local storage failure does not stop the bridge.
- Executable versions are local metadata, refreshed at most once a minute, with unknown explicitly represented.
- No new network requests, auto-installation, restart machinery or edits to Codex data.

## Phase 2: validated readers
- Required SQLite contracts: state_5.sqlite threads(id, archived, source), thread_spawn_edges(child_thread_id);
  thread_history_1.sqlite thread_turns(thread_id, status, rollout_ordinal).
- Root inventory and unread-account/history failures are isolated. Multiple unread identities are unavailable,
  not a guessed account or a format-change diagnosis.
- Stream versions 11/13 are supported. Known relevant status and flag types are validated; harmless additions ignored.
- The initial timer was not authoritative coverage. Installed Codex application code confirms read-only
  thread-owner-discovery v1 returns success with owner ID or explicit no-client-found.
  The existing observer loop now uses at most 16 outstanding discovery requests, 10 s local request deadline,
  60 s coverage validity and refresh beginning 10 s before expiry. No start/read/approval action is requested.
  Owned roots require metadata snapshots; unowned roots use explicit negative coverage. Failed/incomplete coverage
  gives unknown counts. This is local IPC validation, not a second quota poll or a transcript scan.
- Source success, rather than repeating cached publications, advances recovery.
- Quotas and tokens run concurrently with one local reader. Quota failure cannot skip local token collection.
- JSONL scanning uses bounded line chunks and preserves unfinished trailing records for a later read.
  Invalid complete usage records cannot silently yield a complete-looking aggregate.
- Pricing history and attribution are unchanged. Unknown breakdown/cost remains separate from valid totals.

## Phase 3: display semantics
- Existing v1 fields carry JSON null for unknown run/wait/done; individual valid fields retain numbers.
- Both 3.12.3.4 firmware images advertise metric_validity and render partial counts correctly.
- New desktop/new firmware: supported partial validity on USB and BLE.
- Old desktop/new firmware: known numeric fields work, missing fields remain unknown.
- New desktop/old firmware: upgrade required for reliable unknown task counts; older firmware can reject null run,
  older C6 cannot express partial count validity and older Ball may show a fallback zero.
  Device status explicitly reports this limitation. USB/BLE ownership protocols are unchanged.

## Phase 4: warning UI
- Persistent control-panel summary and Codex data status / details button.
- Native tray action and shared notifications overview; Windows balloon callbacks have no per-notification ID.
- Dialog shows affected sources, reasons, supported/observed format details and version provenance.
- Copy diagnostics is allowlisted and local; opening details does not initiate update checks.
- Check for updates opens the existing explicit-action update dialog.
- Distinct wording for confirmed incompatibility and five-minute unknown-cause outages.

## Phase 5: verification
- Full Python regression at current checkpoint: 365 passed.
- Native C++ tests pass, including null and partial activity payloads.
- Source Windows self-test passes: actual native notification clicks, panel/dialog reuse, recovery and shutdown.
- Read-only real-profile observer validated current counts (3 running / 0 waiting / 7 completed unread at one sample).
- Exact-artifact build, packaged self-test and hardware evidence are recorded in 5_post-implementation-notes.md.
- No physical host sleep, second-PC USB acceptance, or overnight soak is claimed by this feature.
