# Audit follow-up implementation notes

Baseline commit: 2bb9d90 (audit and approved plan). Implementation is in progress, primary agent only.

## Phase 1

Manual screen IPC/CLI uses per-device admission with partial-result reporting and an optional full device selector.
Disconnected targets are rejected; queued is not reported as applied. Manual/policy queue keys and desired state
are distinct; queue eviction removes replay intents. The session checks explicit intent deadlines after send-lock
acquisition, preserving bounded resolution for an already-written transaction.

Validation: initial three regressions failed on the baseline. Focused transport/events suite: 58 passed;
expanded follow-up tests: 8 passed. No live hardware or process changes yet.
