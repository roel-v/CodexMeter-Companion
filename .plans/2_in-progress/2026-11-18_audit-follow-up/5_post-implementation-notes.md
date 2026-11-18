# Audit follow-up implementation notes

Baseline commit: 2bb9d90 (audit and approved plan). Implementation is in progress, primary agent only.

## Phase 1

Manual screen IPC/CLI uses per-device admission with partial-result reporting and an optional full device selector.
Disconnected targets are rejected; queued is not reported as applied. Manual/policy queue keys and desired state
are distinct; queue eviction removes replay intents. The session checks explicit intent deadlines after send-lock
acquisition, preserving bounded resolution for an already-written transaction.

Validation: initial three regressions failed on the baseline. Focused transport/events suite: 58 passed;
expanded follow-up tests: 8 passed. No live hardware or process changes yet.

## Phase 2

Legacy GATT writes now enforce the shared producer-observation freshness predicate for reconnect, queued, refresh
and health-check telemetry. Refresh handles usage/activity independently; health checks choose a fresh sample or
send no synthetic telemetry. Legacy reconnect restores manual and policy state independently.
Validation: three real connection-path fake-GATT regressions failed before the fix; 34 focused tests now pass.

## Phase 3

Maintenance now uses a coordinator-owned operation and a small typed maintenance-session/worker contract.
The session serializes close against acquisition (DATA lock then lifecycle lock; close takes lifecycle only).
Definitely-unsent closed/failing sessions are fenced before fresh verified USB acquisition. Sent/uncertain failures
still retain the durable pause. BLE exposes its negotiated session through the same worker boundary.
Operations have a 12-second deadline; maintenance IPC allows 20 seconds for bounded cancellation cleanup.
Validation: closed-session regression failed before the fix; 61 ownership/maintenance/USB tests and 18 additional
follow-up/BLE tests pass, including barrier-controlled native cleanup and an uncertain write.

## Phase 4

Both workers now execute one attempt; DeviceCoordinator alone owns retry/selection. Removed single_attempt switches,
standalone backoff/jitter and their unused imports. Candidate disappearance ends an attempt. Bluetooth availability
is in ble_availability.py; USB cleanup uses public discovery invalidation.
Validation: 60 coordinator/discovery/recovery/follow-up tests passed; no references to removed retry modes remain.

## Phase 5

Parser frame/payload checks and its local buffer now use protocol_limits.h. A native test compiles the actual parser
against production limits and a copied, isolated reduced-limit header (320/128) on D:. The reduced variant failed
before the fix; both variants now pass, including oversize/no-effect, UTF-8, truncation and transaction replay checks.
All three production firmware targets build successfully. Midpoint full Python suite: 409 passed in 25.47 seconds.
D: had approximately 98 GB free; existing build/profile directories were inventoried and no data was moved.

## Phase 6 (implementation; hardware acceptance pending)

Validation IPC now checks payload version and semantic kind before enqueueing. An explicit --validation-mode
requires a disposable profile marker; it disables quota, chat, transcript, activity TTL, compatibility, pricing and
update producers. Normal startup remains live. Typed fixture injection preserves independent usage/activity records.
Per-kind ACK hashes and a maintenance-only UI model/page diagnostic gate capture; expected values and image hashes
are retained in sidecars. Wrong values/pages, missing activity and valid PNGs with changed metric pixels have
negative tests. Captures remain marked visual_review=pending until independently reviewed; CRC is not content proof.
Restoration errors survive production reconnection checks. The fixture retains immutable timestamps while feeding.

Validation: full Python suite before final negative tests: 411 passed. Focused content/capture/follow-up suite: 27
passed. Firmware and standalone builds are in progress. No live app shutdown, installation or flashing performed.
Read-only diagnostic reports UI model inputs after forcing refresh; it does not claim to verify raster pixels.
Pixel comparison requires explicit crops and a separately reviewed reference. Live capture/review is phase 7's
separately authorized deployment gate, not a completed acceptance claim.

## Phase 7 — Build/package verification; deployment gate open

- Full Python suite: **419 passed** (33.32 seconds), using D: test scratch.
- Native firmware core/protocol and real parser boundary tests: passed at 640/512 and 320/128 limits.
- Production firmware: C6 and Ball passed; original S3 passed on recheck after correcting the Ball-only guard
  around the new diagnostic. The first failing build log is preserved, not presented as a passing build.
- Standalone Nuitka onefile built successfully with pinned dependencies. Isolated profile on D:, no Python/source
  on child PATH: compiled runtime, real Tk panels/workers, tray icon/menu/click/quit, DPAPI, WinRT, child CLI passed.
  CLI missing-daemon and policy-spoof rejection paths passed. Help forwarding initially needed --foreground;
  corrected test passed. No installed app or device settings were changed.
- Retained evidence: dist/windows/validation/audit-follow-up-20261118 (ignored).
  CodexMeter.exe; C6/Ball app + factory binaries; original-S3 app binary; SHA256 manifest; test/build logs;
  runtime-self-test.json and isolated-cli-checks.json. Build source includes phase 6 commit 342497f.
- Versus phase 5, C6 static RAM +16 bytes / flash +3242 bytes; Ball static RAM unchanged / flash +4328 bytes.
  No dependency additions or protocol version change. Original S3 remains compile-only.

Remaining required gate: install candidate app and flash C6/Ball under the plan's separate local deployment
permission; run the real USB/BLE fixture, packaged validation-mode startup, positive manual controls, freshness,
maintenance, waiting/recovery/completion, native-size content review and explicit crop/reference comparisons;
restore settings and real telemetry. No screenshots from the older run are reused as proof of this candidate.
Legacy hardware behavior is simulated; physical sleep, the user's Bluetooth-less PC and longer soak are not
claimed. Do not move this item to done until required live acceptance passes. No push or release was requested.

Commits: baseline plan 2bb9d90; phase 1 91998d9; phase 2 07fe481; phase 3 5de6216;
phase 4 b5393c5; phase 5 26bad4a; phase 6 342497f. Final build/documentation commit follows.
