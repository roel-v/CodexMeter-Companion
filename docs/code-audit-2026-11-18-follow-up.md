# Follow-up code audit — 18 November 2026

Baseline: `c4a89a0` (clean checkout). This repeats the earlier architecture/dead-code audit after remediation.
Audit only: no production source changes, app restart, device connection, firmware flash or release.

## Method and outcome

Scoped source/reference inspection of desktop transport, delivery, device management, compatibility readers,
firmware board/UI and protocol boundaries, plus isolated fake-device reproductions. Serena could not verify its
runtime process identity; its status command also failed, so this pass used scoped source reads and rg.
The existing Python suite passed: **395 tests in 25.78 seconds**. Temporary test output was placed on D:.
No hardware or firmware builds were repeated. Reference locations below belong to the baseline above.

The earlier restructuring is substantial and present: sibling USB/BLE session adapters, common delivery pump,
neutral identity and logical-device state, native power notification wiring, board capabilities, shared token/task
view semantics and generated release versions. However, the first audit's disposition table overstates completion
for legacy freshness, constant ownership and removal of alternative retry paths. Passing tests do not cover all
public command paths or the interleavings below.

## Behavior findings

### 1. P2 — Published screen commands cannot control negotiated firmware

Locations: `codexmeter/cli.py:78,237`; `codexmeter/events.py:351`; `codexmeter/companion_session.py:250`.

`screen-on` and `screen-off` still emit the old broadcast `screen` event. EventServer builds a manual control and
sends it through the generic sink, bypassing DeviceManager.control_device and its boot/revision-bound intent.
CompanionSession correctly rejects that manual control as `stale explicit intent`. The caller receives
`{ok: true, queued: screen}` even though the control cannot be applied to either current display over USB or BLE.
The event test only checks construction/queueing, not delivery through the negotiated session.

Reproduced through the real EventServer and DeliveryPump with a UsbSession/FakeChannel:
`SCREEN {'ok': True, 'queued': 'screen', 'on': False} stale explicit intent`.

Route manual controls through per-device intent creation (including an explicit broadcast fan-out policy), or
remove the obsolete public command deliberately. Keep automatic lock policy distinct from manual controls.

### 2. P2 — Queue coalescing conflates manual power intent and automatic screen policy

Location: `codexmeter/queueing.py:14-29`; producers in `device_manager.py:420` and screen policy.

Controls are coalesced only by `cmd`. Manual screen state and OS lock/unlock policy are separate firmware state
variables, but both use `cmd=screen`. If manual off is queued and an unlock policy arrives before consumption,
the queue drops manual off. Conversely, a manual command can remove a pending lock-policy change. The retained
explicit-intent ledger may then replay the dropped manual request on a later same-host reconnect within its TTL.

Reproduction: enqueue manual off, then policy unlock; the queue contains only the unlock payload.
This is an interleaving defect, not evidence that every manual click fails. Coalesce according to semantic intent:
manual screen state and policy state need separate keys, while repeated brightness values can still coalesce.

### 3. P2 — Legacy BLE bypasses the shared telemetry freshness contract

Locations: `codexmeter/ble.py:270-279,321-336`; `tests/test_transport_delivery.py:108`.

The legacy adapter unconditionally replays last_usage/last_activity on reconnect and resends cached usage for
refresh/health checks. It never checks observed_at against TELEMETRY_REPLAY_TTL_SEC at these write sites. As a
result, old readings can continue looking current on supported legacy firmware after their producer stops.

Reproduced through the real legacy connection method with a fake GATT client: a usage payload observed **3,600
seconds** earlier is written on reconnect. The named legacy freshness test calls negotiated_replay directly;
it does not exercise the legacy adapter that actually writes to the device.

Keep the supported legacy wire protocol, but apply the common freshness decision to reconnect, refresh and
health-check telemetry. A transport health probe must not present expired cached measurements as fresh data.

### 4. P2 — Maintenance treats a closing USB session as a usable session and leaves a sticky pause

Location: `codexmeter/device_manager.py:329-379`, especially `346-350`.

Maintenance chooses the live-session branch based solely on a truthy worker.session and `kind == usb`. The worker
can already be closing or failed while it still exposes that object. The manager persists a maintenance pause,
then sends the request through the unusable session. It fails and retains the pause, so ordinary delivery stops
until the user explicitly resumes. Coordinator.lock does not serialize the worker's own cleanup.

Reproduced with an already closed real UsbSession still attached to the worker:
`Session session unavailable`, with `retained_pause=True`. The previous hardware-validation notes recorded the
same class of race; waiting in the fixture avoids it there but does not fix the public operation.

Retaining the pause after uncertain device ownership is safe. The gap is distinguishing a session already closing
before a request from an uncertain maintenance result. Expose lifecycle/readiness and acquire maintenance through
a serialized worker/coordinator operation; do not merely clear pauses after arbitrary failures.

### 5. P2 — Explicit control expiry is enforced only during reconnect replay

Locations: `codexmeter/delivery.py:177-186`; `codexmeter/delivery_pump.py:29-40`.

Explicit intents record their creation time and have a 60-second lifetime. negotiated_replay checks the age,
but ordinary DeliveryPump.deliver ignores the timestamp and forwards the boot/revision indefinitely. A queued
control delayed past the TTL can therefore execute if its boot and revision remain valid. Delayed event loops
or suspend/resume without a completed reconnect are relevant cases; this is not a normal fast-delivery failure.

Reproduced with the real session and fake channel: a **120-second-old** brightness intent is sent and accepted.
Enforce intent age at the common delivery boundary, immediately before sending, for both transports.

## Remaining architecture and validation findings

### 6. P3 — Protocol constants are declared centrally but the parser still has independent limits

Locations: `firmware/src/companion_protocol.cpp:50,64-65`; `firmware/src/protocol_limits.h:4-5`;
`tests/test_protocol_agreement.py:9-11`.

The parser still uses literal 640, 512 and a 513-byte local payload array. Other buffers now use frame_limit and
payload_limit. The cross-language test checks the header values against Python, not these parser consumers.
The limits agree today, so there is no current size mismatch. A future change can pass the agreement test while
leaving the parser on the previous limits (or allowing a larger local payload than the session ledger supports).
Use the owned constants at all semantic consumers; keep the separate ATT limit separate.

### 7. P3 — Transport ownership is cleaner, but redundant worker modes and backend leaks remain

Locations: `codexmeter/ble_worker.py:36-92`; `codexmeter/usb_worker.py:29-131`;
`codexmeter/device_coordinator.py:100`; `codexmeter/usb_transport.py:564`;
`codexmeter/device_manager.py:143,346`; `codexmeter/transport_types.py:27`.

All production workers are started by the coordinator with single_attempt=True. Both workers nevertheless retain
standalone retry/backoff modes; BLE also retains jitter for this unused production mode. Thus the claim that all
retry decisions live in the coordinator is not true of the source structure, even though it is true of the active
production path. Remove the obsolete mode after migrating any tests that rely on it.

Bluetooth adapter availability is still implemented in usb_transport and imported by the neutral manager.
Move it to the BLE backend. The manager still discovers a session through getattr on a backend-specific worker;
BLE keeps its negotiated session as a local variable whereas USB exposes it. TransportSession is now genuinely
used by DeliveryPump, but there is no typed maintenance/lifecycle boundary for the manager. Add a small explicit
contract for that responsibility rather than expanding DeliveryPump's interface into an all-purpose abstraction.

These are maintenance issues, not justification for a new class hierarchy per display model. The current
metadata-based desktop display abstraction is appropriate.

### 8. P2 (validation gap) — Screenshot transport success does not prove the intended fixture was displayed

Locations: `tools/validate_architecture_cleanup.py:29-55,69-87`; `codexmeter/events.py:360-364`;
previous cleanup post-implementation notes.

The fixture feeds both usage and activity dictionaries through a `usage` event. EventServer wraps either one as
Payload(kind='usage'), although its wire `k` may be `activity`. Queueing/freshness follow the Python kind while
firmware follows the JSON kind. Alternating fixture messages can replace one another, and the normal chat observer
can overwrite the synthetic activity independently. The fixture checks connectivity/capture success but not that
the expected values reached the rendered model before capture. CRC proves image transfer integrity, not content.

The earlier notes already disclose partial-count captures affected by observer interleaving. That remains a test
limitation, not proof of a production display-count defect. Provide deterministic producer isolation and correctly
typed fixture injection; verify expected state/content as well as successful image transfer. Validate the usage
IPC payload's semantic kind rather than relying on callers to keep the outer and inner types aligned.

## Priority and retained support

First fix the public manual-control path and queue semantics, then maintenance lifecycle and final-send expiry.
Bring supported legacy replay under the same freshness policy, tighten the hardware fixture, and finish the small
constant/worker/backend cleanup. Add tests through the real affected consumer, not only its helper.

No new defect was established in the shared token-row arithmetic, identity normalization, board capability split,
release-version generation or native power registration during this pass. This is not an exhaustive proof of
absence of defects. Physical sleep/resume, original S3 hardware, a Bluetooth-less PC and larger device fleets were
not tested here. Legacy BLE/rollback support and existing C6 themes remain intentional supported functionality.

No fixes or commits were made. This report is the only repository addition from the audit.
