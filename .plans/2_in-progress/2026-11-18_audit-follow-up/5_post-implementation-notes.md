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
