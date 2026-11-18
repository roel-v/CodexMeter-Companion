# Overall implementation plan

Status: planned, not started. Requirements: [2_requirements.md](2_requirements.md).
All phases are sequential; each leaves the existing BLE workflow usable. No separate project dependency graph
exists, and this feature has no unfinished prerequisite elsewhere in the repository.

## Architecture

Keep one logical device record, delivery queue and desired-state cache per registered hardware ID.
USB/BLE endpoints are attributes of that device, not duplicate registrations. A transport-neutral coordinator
owns replay, pending alerts and active-session selection. Concrete USB and BLE transports own connection and I/O.
Discovery reports endpoints separately from delivery. Failed USB probes do not count as BLE radio failures.
USB discovery/registration must run without starting BLE discovery. Allow a device record with no BLE address;
attach a verified BLE endpoint later if one becomes available. Isolate Bluetooth initialization errors and unavailable
adapters from USB workers, UI startup and telemetry. A no-Bluetooth PC is a normal supported configuration.

Use a versioned, bounded USB protocol alongside the existing BLE protocol. Phase 1 specifies its wire grammar,
maximum encoded frame size, session ownership, heartbeat/lease expiry and acknowledgement correlation before coding.
Reuse existing application payloads; do not add envelope bytes without accounting for firmware memory/size bounds.
Keep legacy BLE clients functional. If an older BLE client lacks ownership negotiation, firmware must explicitly
reject/ignore its application writes while a live USB owner holds the device and permit it after that lease expires.
A new companion must not rely solely on closing its own BLE connection to prevent another sender from writing.

Candidate USB validation must be read-only with respect to display state. Complete handover at a bounded delivery
boundary, invalidate old callbacks, claim the selected session and replay current state. On failure, fence the old
session before starting another sender. Uncertain pending alerts reuse their original IDs; never mint a new alert ID
just because the transport changed. Keep screen/control intent independent of transport lifetime.

Receive serial incrementally with strict limits and timeouts. Distinguish protocol replies from logs and binary
screenshots. Prefer exclusive maintenance ownership for screenshot/flash operations rather than multiplexing binary
captures with live telemetry. Avoid blocking the asyncio/UI loop and close handles on cancellation and shutdown.

## Phases and exit evidence

| Phase | Deliverable | Exit evidence |
| --- | --- | --- |
| 1 | Wire contract and hardware feasibility | Both units identified; safe serial behaviour and ownership design recorded |
| 2 | Firmware USB sessions on both boards | USB-only fixtures acknowledged; waiting/power/UI semantics preserved |
| 3 | Transport-neutral host and USB discovery | Automated routing/replay/cancellation tests; legacy BLE regression pass |
| 4 | Automatic handover, status and maintenance | Deterministic switching tests and usable transport/maintenance controls |
| 5 | Packaged and physical validation | R17-R20 evidence for both units, including no-adapter operation and switching |
| 6 | Documentation and release preparation | Compatibility guidance, artifacts/checksums and rollback evidence |

Start with implementation-guide.md for the verified source map, proposed interfaces, commands and execution rules.
Detailed ordered tasks, tests and exit checklists are in 4_imp-phase1.md through 4_imp-phase6.md.
The plans are written for GPT-6.1 Sol; proposed module names are identified as proposals, not existing code.

## Storage and change boundaries

Use D:\build\CodexMeter for active firmware/Nuitka output, dependencies and compiler temporary files.
Inspect D: headroom and cold-data candidates before large builds; do not move evidence-bound paths automatically.
Retain logs, captures, backups and release bundles in ignored dist subdirectories on E:. Never commit device backups,
credentials or binaries. Keep source/plan changes reviewable by phase; commit/push only when requested.

When implementation is authorized, move this entire feature to 2_in-progress. Record actual results, deviations and
remaining limits in 5_post-implementation-notes.md as work proceeds. Planning alone does not authorize a production
firmware change or release. Do not mark a phase passed using simulations in place of its specified physical checks.


## Confirmed policy — 2026-11-16

USB ownership may preempt Bluetooth from another PC. Connection mode is persisted per registered device on each PC:
Auto, USB only or Bluetooth only. Transport selection must obey forced modes, including on initial registration,
configuration reload and reconnect. Explicitly handle an owner elsewhere without triggering radio recovery.
The no-Bluetooth test PC is available. Physical sleep/resume testing is excluded and is not a release gate;
retain automated recovery tests and disclose the physical validation limitation.

Cross-PC takeover follows R8: preserve physical display settings and manual power intent, and refresh telemetry.
Do not replay the incoming PC's saved brightness/rotation/power settings. Reconcile state before sending controls;
subsequent explicit controls and live lock/unlock policy apply, without waking manual-off merely on connection.
