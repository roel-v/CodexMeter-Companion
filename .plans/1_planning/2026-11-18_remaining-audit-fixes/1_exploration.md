# Remaining audit fixes

Baseline: 9c9ce33. User-authorized planning and sequential implementation, personally, without agents.
Standing staged-commit instructions apply. No deployment, flashing, publication or version bump in this scope.

## Requirements

Pricing publication and acceptance preserve newer candidates and append-only rate history. Desktop token reports
identify observation time and unavailable/stale state, including legacy reports. Failed registry saves never put
uncommitted settings into recovery backups. Hardware fixtures accept valid serial execution and preserve their inputs.
Versions share the package version, with release tags kept distinct. Session contracts describe consumer requirements.
Remove small duplication/dead statements without deleting supported compatibility behavior.

## Sequential phases and commits

1. Coordinate pricing-store publication and acceptance across instances. Network work stays outside the short shared
   lock. Fence superseded fetches and validate exact pending/status hashes. Test both race orderings and delayed checks.
2. Add a versioned usage-report envelope with timestamp/day window and explicit unavailable status. Publish failures
   from the provider and render current/stale/legacy reports honestly through a tested pure presenter.
3. Define primary replacement as the save commit point; backups contain committed data only. Post-commit backup errors
   must not claim rollback. Test actual replacement failures and recovery; share manager registry rollback logic.
4. Separate rapid-command outcomes from deterministic stale-revision coverage. Accept valid sequential ACKs and record
   unobserved conflicts honestly. Retain deterministic protocol/ledger conflict tests; test fixture classification.
5. Give USB fault injection a disposable registry copy with explicit D: scratch on Windows. Reject paused inputs before
   hardware work; clean up copies on all paths. Test byte-preservation of inputs on success and failure.
6. Use canonical package version in update UI; extend version consistency tests.
7. Complete the worker/session interfaces for maintenance and state refresh; test actual adapter conformance.
8. Extract shared test support from test modules, remove redundant rethrows/unused locals, run the full Python suite
   and wrapper collection parity, update changelog/architecture and acceptance notes.

Each phase has a focused commit and regressions before the next. Final acceptance covers their combination.

## Scope and acceptance

Tests use synthetic state and fake I/O. Active caches/temp stay on D:, retained evidence on E:. No private transcripts,
installed settings, running app or boards are touched. Firmware behavior/geometry are unchanged; no firmware rebuild
or physical test is required. There are no unresolved product decisions or dependency graph. Move the whole plan to
3_done after software acceptance. Record actual results, failures and limits in 5_post-implementation-notes.md.
