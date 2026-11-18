# Phase 1: protocol contract and hardware feasibility

Depends on: approved requirements. Covers R3-R7, R9, R14 and R20.

## Work

- Confirm both physical units and USB identifiers without relying on historical COM numbers. Record the Ball's
  current data-cable/port availability. Use existing identity tooling after reviewing its control-line behaviour.
- Review Serial/HWCDC read/write behaviour in the pinned Arduino core, native USB sleep limits and safe opening.
  Measure identity response and non-resetting open/close on both units before choosing timeout values.
- Specify a versioned wire contract: discovery identity/capability response, session claim/release, bounded lease,
  heartbeat, message IDs, ACK/NACK/error framing, limits, newline/partial-frame handling and overflow resynchronization.
- Define how read-only probing differs from owning delivery; how stale sessions/late ACKs are rejected; and how new
  USB ownership interacts with legacy BLE writers and both transports being connected simultaneously.
- Define payload/envelope byte budgets, including maximum UTF-8 content, without expanding beyond C6 memory limits.
  Specify that log lines cannot be interpreted as ACKs and binary diagnostics require released maintenance ownership.
- Fix and document proposed timing constants: heartbeat/failure timeout, USB promotion delay, backoff and BLE retry.
  Check these against R20. Explicitly bound per-loop serial processing and outgoing buffering.

## Verification and exit

Retain identity/open-close observations and a reviewed protocol contract with example frames and transition table.
No live application payload injection while the production BLE sender owns the display. No reset or flash merely
for probing. Record unavailable hardware tests honestly. Later code must implement the contract rather than invent
incompatible host and firmware interpretations independently.

## Contract completeness checks added in review

Specify firmware boot identity versus host session identity; idempotent retried claims/messages; lease expiry using
monotonic device time; and how handover completes when the previous transport cannot acknowledge release.
Separate link liveness from telemetry freshness: heartbeat traffic alone must not make stale data appear fresh.
Define bounded alert replay age/count and deduplication retention together, including overflow and restart behaviour.
Preserve existing alert policy where possible; do not promise unlimited exactly-once delivery using a bounded cache.
Define the USB probe allowlist and exact harmless identity query. VID/PID alone proves only Espressif hardware,
not CodexMeter; exclude known unrelated devices and bound unsuccessful probe frequency.
Specify supported Windows baseline, shutdown timeout and adapter arrival/removal handling. A Bluetooth adapter
appearing later must become available without restarting the companion, subject to the selected connection policy.

USB claims have priority over BLE ownership, including a different PC; use host/session identities to distinguish
owners. Define deterministic preemption, bounded release/expiry, owner-busy replies and old BLE client behaviour.
On cross-PC ownership change, replace usage/task telemetry while preserving the physical page, brightness,
rotation and manual on/off state (R8). Do not replay the new PC's saved display settings. Prevent old queued host messages/alerts from leaking into the new session.

Include current display state and power-intent origin in the session/state reconciliation design. Distinguish
same-companion reconnection from a different PC taking ownership, and manual screen-off from host lock-policy off.
Specify precedence for explicit controls versus stale cached controls so session replay cannot undo a local change.
The new owner's live lock/unlock policy remains effective without treating connection establishment as manual wake.


## Required handoff to phase 2

Produce protocol-contract.md and hardware-verification.md in this feature directory. The former must contain
exact frames, capability/version negotiation, payload/queue limits, timing constants, ownership/state transition
and control-precedence tables, plus accepted/rejected examples for firmware/host fixtures. The latter records
actual board identities, tested serial-open behaviour, pinned core observations and remaining hardware limits.
Resolve engineering choices within confirmed requirements; escalate only if evidence requires changing those
requirements. Hardware presence and no-reset serial access must be verified before claiming phase 1 complete.

## Ordered implementation tasks for Sol

1. Read implementation-guide.md and establish the baseline. Inspect current firmware main/identity/BLE code,
   device_registry, multi_ble, ble, screen_policy and serial tooling. Record current IDs and firmware versions.
2. Read pinned Arduino HWCDC implementation from the D: dependency tree. Record DTR/RTS handling, open detection,
   read/write blocking behaviour and buffer sizes. Do not substitute current upstream APIs for the pinned version.
3. Enumerate ports without opening unrelated devices. For each identity-verified C6/Ball candidate, use the reviewed
   SerialSession path for a bounded identity query. Record reboot counter/uptime evidence before/after repeated
   open-close. If the Ball is not connected, request the physical data connection and stop until answered.
4. Write protocol-contract.md. Separate USB protocol version from existing application/BLE protocol version.
   Specify handshake, claim, heartbeat, payload, ACK/NACK, state query, release and maintenance operations.
   Each operation needs exact field names/types, required/optional fields, valid states and error responses.
5. Add representative frames for usage, task counts, completion, brightness, rotation and screen policy. Establish
   the maximum encoded UTF-8 length for actual payload builders plus envelope; check both firmware budgets.
   Choose an explicit length bound and discard-until-delimiter recovery; do not retain silent truncation.
6. Define host ID persistence (local random ID, no external service), session token/generation, boot generation,
   sequence wrap and duplicate replay rules. A correlated ACK must match the session and pending message.
   IDs are ownership/correlation mechanisms, not authentication claims; do not imply protection against hostile PCs.
7. Complete the state tables below and define exact timeout/backoff constants. Candidate starting values: 2-second
   heartbeat, 3 missed replies, 2-second USB promotion stability and capped retry backoff. These are design inputs,
   not accepted measurements; ensure total expiry/reconnect time satisfies R20 and the current BLE timings.
8. Specify host-neutral state reconciliation: current settings, setting revision and power origin are returned by
   the new firmware so an incoming PC can avoid replaying stale settings. Define legacy fallback conservatively.
9. Specify the new BLE ownership/busy-status extension for updated hosts while preserving legacy application frames.
   Without that extension, a new host cannot reliably distinguish USB ownership from a broken BLE link.
10. Produce a finite fixture list with expected input/output/side effect. Review each requirement against it before
    completing phase 1. Record findings in hardware-verification.md and handoff decisions in the post-notes file.

### Mandatory transition-table rows

| Starting condition | Event | Required result |
| --- | --- | --- |
| No owner | Valid registered USB claimant | USB session; no settings mutation on claim |
| BLE owner, same or other PC | Valid USB claimant | Fence old writes; USB owner; busy status to updated BLE host |
| Live USB owner | BLE payload/claim | Reject application mutation; do not ACK as applied |
| USB owner | Release, disconnect or lease expiry | Clear owner, invalidate queued work; BLE eligible again |
| Any owner | New boot/session with stale ACK in flight | Old callbacks/messages cannot complete new delivery |
| Maintenance owner | Another data sender | No application mutation until maintenance release/defined recovery |
| Active mode Auto | USB fails and BLE is usable | Bounded BLE fallback; retry USB with stability/backoff |
| Forced mode | Selected transport fails | Wait/retry selected transport only |
| Other PC claims USB | Incoming saved settings differ | Replace telemetry only; preserve physical/manual state |
| Link alive, provider stalled | Heartbeats continue | Transport alive; telemetry freshness not falsely refreshed |

### Exit checklist

- [ ] Both hardware identities and safe serial access verified or a specific unresolved hardware blocker recorded.
- [ ] protocol-contract.md has no TBD fields, unbounded buffers, unspecified ownership transitions or timer units.
- [ ] Firmware and host can independently implement every fixture from the contract alone.
- [ ] Legacy BLE compatibility and busy-status limitations are explicit.
- [ ] No application/firmware changes or fabricated physical pass results are hidden in the discovery work.
