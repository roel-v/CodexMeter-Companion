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
