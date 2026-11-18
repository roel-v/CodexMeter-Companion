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
