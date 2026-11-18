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

## Phase 4 â€” backend

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

### Phase 8 final-review corrections
A terminal ACK/result can arrive at the panel before settings readback finishes. Added readback_pending to keep polling
that supplemental result without downgrading the proven ACK. Actual widget diagnostic now waits across this race.
An added adapter regression reproduced four malformed BLE ownership declarations reaching subscription/legacy handling.
The adapter now routes any negotiation declaration through strict support validation, including rejecting boolean owners.
The four red cases passed after the fix; focused BLE/policy suite: 59 passed. Added lazy/cached host identity coverage
through actual initial/adopted/reloaded workers. Final full Python run: 497 passed, one inapplicable roots/account case
skipped. The first successful candidate build predates the BLE correction; it is not the final tested candidate.

## Phase 8 — integrated verification

- Final Python suite: 497 passed, 1 skipped in 64.28 seconds. The skip is the inapplicable roots/account test combination.
- Canonical pytest and historical wrapper collect exactly the same 498 node IDs; wrapper exit-code regression passes.
- Native firmware protocol/model tests, parser limits (640/512 and 320/128), and real theme-header helper tests passed.
- All three firmware builds passed. Relative to the previous capture-fix build:

| Board | RAM bytes | Flash bytes | RAM delta | Flash delta |
| --- | ---: | ---: | ---: | ---: |
| Original S3 | 127304 | 1644887 | 0 | -228 |
| C6 | 54620 | 2416660 | 0 | -324 |
| Ball | 190784 | 1216686 | 0 | 0 |

- Final Nuitka 4.3.1 onefile candidate built from production source at a4b15e7. Version remains 3.12.3.4 as planned.
- Isolated packaged self-test passed with Python removed from PATH: actual Tk command outcomes/retry/readback,
  compatibility recovery, pricing/update panels, DPAPI, WinRT imports, CLI subprocess, native tray and clean quit.
- PowerShell initially returned before the GUI executable completed; its subsequently written JSON confirms compiled=true
  and ok=true. The test process exited naturally. No production daemon was started, stopped or reconfigured.
- No pytest/_pytest module is included in the compilation report. Runtime dependencies remain separate from the test extra.
- Final reference search finds no removed wait_any/exclusive_delivery/used_successfully/discovery-event scaffolding;
  label/font helper definitions occur only in the shared header.
- Active build/cache/compiler outputs stayed on D:, with 97.3 GB free before and 96.5 GB after the builds.
  Inventoried old test profiles and build directories; sufficient space meant no cold-data relocation was necessary.
- Retained artifacts/logs/compilation report/manifest are ignored under
  dist/windows/validation/audit-reliability-cleanup-20261118. The manifest hashes every retained executable/bin artifact.
  Final executable SHA-256: 70c7c9a4fbae853c1231c6d6d6da26dc8f67fa4e3f74d3b53f81d13dfb5402bd.

## Scope and remaining acceptance

All implementation and software/build checks were performed personally, without agents. CHANGELOG and architecture,
contributor and audit-disposition documentation are updated. Tests exercise fake transport/OS boundaries on Windows;
macOS runtime behavior and fresh physical USB/BLE acceptance are not claimed. Original S3 remains compile-only.
Installation, flashing, live five-minute freshness checks and visual captures belong to a separately authorized
hardware-acceptance step. The work item stays in progress to retain that explicit pending gate; prior deployment
acceptance is not reused for this candidate. No push or release was requested or performed.
