# Audit reliability cleanup implementation notes

Baseline: 0abefe3. Implementation authorized; primary agent only. Live deployment remains separate.

## Phase 1

Replaced the partial runner with pytest forwarding, added the test extra and updated contributor/PR/CI instructions.
Regression failed on the old runner with missing monkeypatch/capsys; it now passes, including failure exit status.
Canonical/wrapper collection matched. Fresh D: environment installed .[test] and passed all 424 cases in 27.85s.
