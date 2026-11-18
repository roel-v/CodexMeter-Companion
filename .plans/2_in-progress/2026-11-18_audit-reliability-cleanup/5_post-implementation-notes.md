# Audit reliability cleanup implementation notes

Baseline: 0abefe3. Implementation authorized; primary agent only. Live deployment remains separate.

## Phase 1

Replaced the partial runner with pytest forwarding, added the test extra and updated contributor/PR/CI instructions.
Regression failed on the old runner with missing monkeypatch/capsys; it now passes, including failure exit status.
Canonical/wrapper collection matched. Fresh D: environment installed .[test] and passed all 424 cases in 27.85s.

## Phase 2

Nine close-lifetime regressions failed before the change. open_database now returns a closing context and all callers
retain read-only access. Success, schema/query errors, malformed values and account fencing close before return with
GC disabled. Focused reader/compatibility/chat tests: 50 passed, one inapplicable roots/account combination skipped.

## Phase 3

Five new regressions demonstrated the endless noisy/blank stream and ignored failure markers. Capture now uses one
monotonic header deadline, remaining read budgets and explicit failure handling. Before/exact-boundary, existing CRC,
older headers, optional end marker and maintenance/page cleanup checks pass.

## Phase 4 — backend

Added bounded process-local command IDs/results without changing firmware payloads. Queue admission stays asynchronous.
ACKs establish application; readback failures are separate. Unknown writes cannot replay in a new session. Unsent intents
retain original deadlines, and expiry/supersession/ownership changes are recorded. Legacy ACKs use the same result contract.
The original missing-result regression failed first; 110 focused delivery/IPC/legacy/maintenance tests now pass. New tests
cover send-lock supersession, cancellation before/after dispatch, lost ACKs, durable rejection, retention and capacity.

### Phase 4 panel
Actual Tk widgets exercised with isolated IPC: queued/conflict/explicit retry, acknowledged command with failed readback, unknown outcome and settings check, selection fencing, disconnected retry, older daemon and closure. Focused panel/backend run: 15 passed. Packaged self-test invokes the same widget diagnostic.

### Phase 5
Shared runner owns open/reconciliation/replay/queue consumption and logical disconnect/close. Adapters retain discovery, physical connection and invalidation. Manager resolves one host identity lazily for initial/dynamic BLE, USB and maintenance. Existing transport/coordinator/result suites: 64 passed; new parameterized adapter open/policy failure, normal stop and cancellation checks: 8 passed. No hardware touched.

### Phase 6
Separated structural identity parsing from explicit model/application/transport support. Unsupported identities remain surfaced before claims; no new model is accepted. Shared busy classification and application compatibility. Updated old codec tests to exercise the policy boundary; 85 focused cases passed, including all three models on both transports with empty/partial controls and unsupported declarations. Initial test import error corrected before passing run.

### Phase 7 scaffolding
Removed unconsumed discovery events/wait API and wait_any, ignored legacy success bookkeeping, and test-only exclusive_delivery. The dispatch-expiry test now holds the existing send lock directly. Discovery, legacy, coordinator, maintenance and audit regression suites: 79 passed.

### Phase 7 theme helpers
Compared bodies before extraction: nine label helpers differ only in signature wrapping; ten font helpers are identical.
Shared header preserves unchanged/changed/null-current-text and font fallback behavior; native fake-LVGL checks pass.
All three firmware targets built successfully. S3 RAM 127304, flash 1644887 (-228 versus prior capture-fix build);
C6 RAM 54620, flash 2416660 (-324). Ball figures are recorded in the final verification table below.
No layout, font asset or board behavior was changed. Existing compiler warnings remain in the retained build log.
