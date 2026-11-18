# Consistency review — 2026-11-16

Scope: exploration, R1-R21, overall plan and all six implementation phases. No implementation performed.

## Findings resolved in the plan

- Clarified that a new in-app firmware updater is out of scope, while existing USB flashing remains supported.
- Distinguished new correlated USB ACKs from the legacy BLE acknowledgement protocol.
- Moved candidate builds before packaged/physical tests; release packaging must use the validated artifact hashes.
- Defined latency measurement boundaries rather than leaving the 10/30-second targets ambiguous.
- Added explicit protocol-design checks for stale ownership, failed release, boot/session identity, bounded alert
  replay/deduplication, telemetry freshness and safe candidate probing.
- Added registry migration/rollback, optional-adapter arrival/removal and maintenance restart/failure checks.

## Confirmed decisions — 2026-11-16

- A registered companion on another PC can take over via USB; BLE may resume after USB release/expiry.
- Per-device, per-PC modes: Auto (USB preferred), USB only and Bluetooth only.
- The user has a PC without Bluetooth for required physical USB-only acceptance.
- Physical sleep/resume tests are excluded, non-blocking and must be disclosed as unverified.
- The 30-minute mixed-transport run is optional/non-blocking; record not run unless actually performed.

All user decisions are incorporated, including screen-setting precedence confirmed on 2026-11-17.
No unresolved user questions remain.

## Readiness

Ready to begin phase 1 when requested. Wire grammar, bounded leases and timing constants are
intentional phase 1 engineering deliverables; complete that contract before phase 2 implementation.
Requirements map to the six phases, with USB-only first registration and operation explicitly covered.
This is a document review, not renewed source/hardware verification; recheck the recorded baseline and current
devices when implementation begins. Files remain in planning; no implementation, deployment or publication performed.

## Follow-up review — 2026-11-17

Reviewed the complete current document set; no code/device changes made.
- Qualified ownership status/recovery guarantees to updated companions; old apps cannot inherit new UI behaviour.
- Corrected unavailable-transport retry wording to obey USB-only and Bluetooth-only settings.
- Added cross-PC maintenance ownership, since local host pause alone cannot silence a remote BLE sender.
- Distinguished powered data-path interruption from device reboot during handover validation.
- Resolved takeover precedence: preserve physical settings/manual power; do not replay incoming PC saved settings.
  Subsequent explicit controls and live lock/unlock policy apply as specified in R8.

Phase 1 remains responsible for exact wire grammar, buffer budgets and timeout constants. Its exit requires a
complete transition table covering all three modes, USB/BLE/maintenance owners, failed claims, owner expiry,
late ACKs, same-host versus cross-host replay and legacy clients. These are engineering outputs, not additional
user preference questions. The confirmed R8 policy is covered by phases 1, 4 and 5.


## Final readiness pass — 2026-11-17

Rechecked all current planning files against the complete set of user answers. No further user decisions are needed.
Clarified Auto-only fallback in the detailed phases and removed obsolete wording implying physical sleep testing
was still required. Added the isolated phase 2 serial fixture to avoid depending on the later desktop transport.
Specified the phase 1 handoff documents and their completeness checks.

| Requirements | Implementation responsibility | Verification |
| --- | --- | --- |
| R1-R4: mixed devices, modes, USB-only registration and identity | 1, 3, 4 | 3 unit tests; 5 physical matrix |
| R5-R7: compatibility, single owner, acknowledgements | 1, 2, 3, 4 | 2 fixtures; 3/4 tests; 5 old/new matrix |
| R8-R11: replay, controls, fallback, isolation and waiting | 1, 2, 3, 4 | 2 fixtures; 3/4 tests; 5 handover/settings |
| R12-R13: status, optional Bluetooth and maintenance | 1, 3, 4 | 4 tests; 5 packaged/tool checks |
| R14-R16: reconnect, packaging/platform scope and diagnostics | 1, 2, 3, 4 | 3 tests; 5 packaged/physical checks |
| R17-R20: acceptance and latency | 1 defines contract; 2-4 tests; 5 acceptance | Recorded results and explicit limits |
| R21: documentation, compatibility and rollback | 6 | Validated hashes, notes and rollback evidence |

Ready for phase 1, not a claim that the wire protocol is already implemented or hardware acceptance is complete.
Phase 1 intentionally completes the technical contract before firmware implementation. The no-Bluetooth PC test
remains required at phase 5. Physical sleep/resume is excluded; the 30-minute run is non-blocking. No source,
firmware, installed app or GitHub release was changed by this review. The planning files remain uncommitted.

## Sol implementation detail pass — 2026-11-17

Added implementation-guide.md and ordered substeps/test/exit checklists to all six phase plans, grounded in current
Python symbol inspection and build script interfaces. DeviceConfig already allows no Bluetooth address; migration
adds connection mode rather than inventing an address requirement. Explicitly covered daemon reconstruction losing
new fields, existing ble status projections, recovery after_scan coupling, Ball build_src_filter, isolated phase 2
fixtures, maintenance tool failure and exact-artifact release verification. No implementation or hardware tests run.
Existing requirements and user decisions are unchanged; exact wire fields and constants are phase 1 deliverables.
