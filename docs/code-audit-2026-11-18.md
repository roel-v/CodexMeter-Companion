# Code and architecture audit — 18 November 2026

Scope: current working tree, including uncommitted USB/multi-transport and compatibility-monitor changes.
This is an audit, not an implementation plan or approval to remove support. No application/firmware edits,
flashing, restarts or release actions were performed during the audit.

Method: Serena symbol/reference inspection, scoped source searches, comparison of firmware build branches,
and two isolated Python reproductions. No network requests or live-device operations were needed. Python
references were checked semantically and by text; C++ inspection was textual because this Serena project
has only a Python language server. No claim of exhaustive dead-code proof across external consumers.

## Confirmed behavior defects

### 1. Standalone control panel discards valid compatibility status (P1)

Location: codexmeter/windows_app.py:173, in the non-tray-managed health polling worker.

`reply.get("compatibility", reply.get("status", {}).get("compatibility", {}))` evaluates its default argument
before calling the outer get. A normal ping response contains `status: "running"`, so calling get on that
string raises AttributeError even when compatibility is present. The catch then substitutes an empty
snapshot, leaving the separate control panel at "Checking Codex data compatibility...".

Reproduced with a minimal valid ping-shaped dictionary. The normal tray-managed panel bypasses this path,
which explains why the packaged tray UI test could pass. Remove the unneeded alternate nesting assumption,
or implement explicit typed schema handling, and test the independent control-panel polling route.

### 2. Identical C6 hardware is described differently over Bluetooth and USB (P2)

Locations: firmware/src/identity.cpp:38-53; codexmeter/ble.py:134-165;
codexmeter/usb_protocol.py:75-127; firmware/platformio.ini:1.

Ball identity declares firmware/protocol plus the wire aliases fw/app. The non-Ball branch declares only
fw/app. UsbIdentity normalizes those aliases; BleIdentity feeds the raw object to DeviceMetadata.

Reproduced using the exact C6-shaped identity: BLE metadata reports legacy with no firmware/protocol;
USB metadata reports compatible, firmware 3.12.3.4, protocol 1. A transport change can therefore overwrite
registry metadata with a less complete interpretation of the same board. This does not mean BLE cannot
connect: negotiated session parsing subsequently uses UsbIdentity and does validate the wire version.

There is a second board leak: the non-Ball branch always calls the model waveshare_c6_amoled_216, although
the original ESP32-S3 waveshare_amoled_216 build environment remains in platformio.ini. Building that target
would advertise the wrong model. The C6 branch also omits dimensions and touch from its advertised metadata,
whereas the Ball includes them despite both displays having working touch.

Create a board descriptor and one canonical identity serializer/parser. Define whether the original S3
build remains supported; do not silently relabel it as C6 or delete it merely because it is older.

### 3. Duplicated token/cost rendering has diverged between the two displays (P2)

Locations: firmware/src/classic_theme.cpp:339-374; firmware/src/ball_ui.cpp:49-98;
firmware/src/dashboard_view_model.cpp:94-125.

The C6 details page gates every token row, including the total, on breakdown.valid. The Ball gates its
total on has_today_tokens/has_last_7d_tokens. Thus valid totals with unavailable breakdowns remain visible
on the Ball but become dashes in C6 details, even though the C6 dashboard may still show the total.

Other drift: Ball uses checked addition for the three cost components; C6 sums them unchecked. Ball marks
cost as partial for partial OR unknown; C6 passes only partial to its formatter. Compact cost thresholds
also differ. Width-dependent formatting can be intentional, but validity, overflow and partial-cost rules
must be shared. Put semantic calculation in the dashboard view model; keep layout/precision choices in
each renderer. Add a shared fixture matrix for valid totals + unknown breakdown, partial cost and overflow.

## Incomplete abstractions and obsolete paths

### 4. Bluetooth currently inherits the USB implementation rather than a common session (P2)

Locations: codexmeter/ble_session.py:120-138; codexmeter/ble.py:473-503;
codexmeter/usb_worker.py:18-191; codexmeter/usb_transport.py:566 onward.

BleSession subclasses UsbSession and manufactures UsbCandidate/UsbDiscovered objects to do so.
BleTransport._negotiated then constructs UsbDeviceWorker with a SimpleNamespace slot and calls its private
_deliver method. UsbDeviceWorker._deliver actually implements shared replay, freshness, conflict, alert
and acknowledgement policy; it even raises UsbError for Bluetooth delivery failure.

This reuse avoids some duplication but puts the dependency in the wrong direction. Extract a common
CompanionSession (claim/lease/sequence/ACK/revision/maintenance) and a shared delivery pump. SerialChannel
and BleWireChannel should supply I/O/framing, without inventing another backend's discovery objects.
Keep BLE MTU fragmentation and serial port/open/line limits in the appropriate channel modules.

### 5. The device manager facade does not establish a transport-neutral boundary (P2)

Locations: codexmeter/device_manager.py:1-5; codexmeter/multi_ble.py:338-803;
codexmeter/screen_policy.py:13,153-190; codexmeter/delivery.py:12-73.

The new device_manager module re-exports the real implementation from multi_ble. That implementation
constructs both transport stacks, owns registry mutations and maintenance leases, interrogates OS lock
state, exposes status and reaches into discovery/session private fields. DeviceSlot uses the BleState
alias, and broadcast/control invoke BleTransport.remember_desired despite delivery.py already owning it.
Screen policy also imports BleState and retains a single-device parameter alongside the manager callback.

Move logical-device types and manager implementation into neutral modules, use DeliveryState directly,
and expose explicit discovery/maintenance APIs instead of mutating internal sets/maps and _send_lock.
Keep selection/fencing in DeviceCoordinator. Separate OS lock observation/policy from transport I/O.
Two LockScreenPolicy instances currently track the same observation stream (screen_policy_loop and
DeviceManager._live_policy); consolidate ownership while retaining fresh reconciliation on reconnect.

### 6. The declared transport interface is unused and incomplete (P2)

Location: codexmeter/transport_types.py:26-29; codexmeter/usb_worker.py:62-67;
codexmeter/usb_transport.py:751 onward.

Serena and text searches find no consumers of TransportSession. Its send(payload) signature omits the
expected_boot/expected_revision arguments required by the real caller. Production code additionally
relies on open, state, identity, failure, generation, maintenance operations and close(release=False),
none of which that interface describes. Consequently it cannot check the interchangeability it suggests.

Define small interfaces around actual consumers (wire channel, negotiated session, discovery and worker),
then use them in type annotations/tests. Avoid one giant interface for every device/transport feature.
Endpoint and DeliveryResult do have real consumers and should not be removed with the unused Protocol.

### 7. Compatibility lifecycle hooks exist only in tests (P2)

Locations: codexmeter/compatibility.py:100-113,167-186;
codexmeter/daemon.py:395-419; codexmeter/chat_activity.py:214-323; codexmeter/provider.py:41-99.

begin()/generation filtering and power() have no production callers; references are confined to tests.
The daemon uses a greater-than-30-second event-loop gap as a resume heuristic. That is not equivalent to
subscribing to real suspend/resume events: shorter sleeps are not recognized, and long event-loop stalls
are treated as sleep. Reader observations never supply generation values, so the generation feature is
not integrated into reconnect/account lifecycle boundaries.

Also, the empty-root stream branch observes success on each publication interval, rather than only on a
new validated inventory read. This is an exception to the stated independent-observation recovery rule.

These are integration gaps, not safe dead-code deletion candidates. Wire the required lifecycle behavior
through production entry points or explicitly narrow the contract. Add integration tests through the
actual service lifecycle. The earlier completion claim was too strong regarding these protections;
unit tests of unused hooks do not establish runtime behavior.

### 8. Firmware's shared UI interface still models the original themed board (P2/P3)

Locations: firmware/src/ui.h:6-40; firmware/src/ball_ui.cpp:155-205;
firmware/src/ball_hardware.cpp:29-55; firmware/src/main.cpp:590-744.

The Ball implements numerous no-op theme, volume, settings, battery and theme_registry functions to link
against the common application. ball_hardware similarly implements manual rotation through imu_* names
and combines touch, power stubs and rotation in one module. This makes absent capabilities resemble
supported operations with no effect, and raw serial tools expose irrelevant commands.

Use a small common dashboard interface (update/render/page/alert/waiting), optional UI capabilities,
and a board-facing interface for power, orientation and touch. Keep manual rotation separate from an IMU.
Compile-time board adapters are appropriate here; this does not require heap-allocated polymorphism or
forcing round and square layouts into identical coordinates. Existing themes are still used by the C6
build and are not automatically dead simply because the Ball has only one layout.

### 9. Specific obsolete entry points and compatibility wrappers (P3)

- codexmeter/multi_ble.py:452 DeviceManager._initial_worker: no references found.
- codexmeter/ble.py:222 BleTransport.run: old single-display discovery/retry loop; no references found.
  Inspect its exclusively owned helpers before removal; do not delete the still-used connection routines.
- codexmeter/multi_ble.py:96 DiscoveryService.run: superseded in production by manager._ble_discovery;
  the old loop duplicates scan/error/after_scan handling. Consolidate after checking tests/external imports.
- codexmeter/chat_activity.py:44 read_inventory: wrapper used only by an old test; production separately
  reads roots and unread history. Update the test to exercise the actual readers, then remove the wrapper.
- codexmeter/ble.py:196 BleState and remember_desired/_remember_payload/_should_write_payload wrappers:
  still referenced internally and by tests. Migrate those callers to delivery.py before removal.
- codexmeter/ble.py:641 and codexmeter/multi_ble.py:865: identical _sleep_or_stop helpers.
- firmware/src/main.cpp:938 handle_ble_screen_policy now checks generic companion-session freshness;
  rename it to reflect transport-neutral behavior rather than retaining the old BLE-specific name.

These are repository-level findings, not proof that third-party imports do not exist. There is no need
for indefinite internal compatibility aliases when all internal consumers can be migrated together.

### 10. Duplicate constants need named ownership, not one miscellaneous constants file (P3)

- Release version: codexmeter/__init__.py:5, build-standalone.ps1:22-23,
  firmware/src/identity.cpp:16-18. Generate packaging/firmware values from one release manifest, with an
  explicit test-build suffix. Keep protocol versions independent of release version.
- Supported Codex stream versions: chat_activity.py:27 versus compatibility_dialog.py:43.
  Diagnostics must derive the list from the validator rather than maintain a separate list.
- Wire frame/payload limits: usb_protocol.py:10-11 (640/512), ble_session.py:20-95 literals,
  serial_protocol.h:6-7, model.cpp:28, companion_protocol.h reply buffer, companion_session.h payload buffer.
  Share constants within each language and check cross-language agreement with protocol fixtures/schema.
  BLE ATT write size is a different concept from application payload size even where both happen to be 512.
- Delivery freshness: delivery.py:167 and usb_worker.py:42 repeat 300 seconds.
- Alert/intent lifetime and capacities: delivery.py has repeated 60s and an 8-item queue, while the firmware
  ledger uses 65s/32 entries. Some differences are intentional safety margins; name and document them rather
  than blindly replacing equal-looking numbers with one constant.
- Activity freshness: dashboard_view_model.cpp:117 and ball_ui.cpp:70 repeat 15 seconds and duplicate
  validity decisions. Compute per-metric validity once in the shared view model.

### 11. Legacy support should be isolated, not indiscriminately deleted (P3)

Locations: codexmeter/ble.py:325-503; codexmeter/device_registry.py:186;
codexmeter/daemon.py:386; codexmeter/usb_worker.py:52-59;
firmware/src/companion_session.cpp:9-12; tools/observe_mixed_soak.py:97.

The daemon still publishes both devices and ble status keys. Older validation tools actively consume ble,
so it is not unused. Migrate repository tools to the canonical schema before deleting the alias.
The screen policy still emits mac_locked/mac_unlocked/ble_restored reasons, then negotiated delivery
translates/discards them. Emit neutral policy reasons internally and translate only at a legacy adapter.

Older BLE JSON/ACK handling and firmware LegacyBle ownership remain reachable compatibility paths.
Removing them needs an explicit supported-device/protocol decision and regression coverage for ownership,
maintenance, cross-host handover and reconnect. The legacy maintenance path protects firmware upgrade and
rollback workflows; do not remove it just because both currently attached boards have new firmware.

## Recommended boundaries and order

Desktop direction of dependencies:

Application services -> DeviceManager -> logical device + delivery policy -> DeviceCoordinator
-> transport worker -> common CompanionSession -> SerialChannel / BleWireChannel.

Discovery produces a neutral DeviceIdentity and endpoint. Board model/capabilities are data; the desktop
should not need a C6 subclass and a Ball subclass for the same telemetry/control protocol. Put genuinely
model-specific UI/geometry in firmware board descriptors and renderers.

Firmware: serial and BLE framing -> common protocol/ownership -> shared application/view model -> board UI.
Board drivers supply hardware capabilities; optional theme/audio/power features should be explicit.

Suggested execution order:
1. Fix the reproducible health projection, identity normalization and token-total rendering defects.
2. Close lifecycle integration gaps and add production-path tests before treating them as completed.
3. Extract common session/delivery contracts; make USB and BLE siblings and centralize logical-device state.
4. Consolidate board descriptors, view-model semantics and optional UI capabilities.
5. Migrate status/tool consumers, remove confirmed dead paths, consolidate constants and release metadata.

Do not mix this cleanup with removal of supported boards, changes to transport ownership semantics, a new
release-numbering policy or a visual redesign. Preserve the existing fault/maintenance test coverage and
repeat the USB/BLE matrix on both real boards after implementation.

## Remediation disposition — 18 November 2026

The observations above describe the audit baseline; their old locations are retained for traceability.
See [current code structure](architecture.md) for the resulting boundaries.

| Finding | Disposition |
| --- | --- |
| 1 | Fixed top-level health projection; source and packaged panel acceptance cover worker failure/recovery. |
| 2 | Canonical identity parser/serializer and board descriptors; conflicting legacy aliases are rejected. |
| 3 | Shared token/cost semantics, checked sums and total availability; renderer formatting stays model-specific. |
| 4 | Shared CompanionSession and DeliveryPump; USB and BLE adapters are siblings. |
| 5 | Neutral manager/slot, backend discovery/worker, public maintenance APIs, one screen-policy owner. |
| 6 | TransportSession and WireChannel describe and annotate their actual consumers. |
| 7 | Native power registration, source generations/account contexts, stale-result fencing and fresh inventory evidence wired into production. |
| 8 | Explicit board capabilities, separate manual orientation, no Ball dummy UI/power/IMU subsystem; shared task freshness. |
| 9 | Removed obsolete manager/discovery/run paths, forwarding wrappers and test-only inventory wrapper. Shared waits retained in async_utils. |
| 10 | Shared wire/delivery/view limits, validator-owned stream versions and generated release metadata. Intentional ATT, ledger and timeout differences retained. |
| 11 | Canonical devices status throughout tools/UI; legacy JSON/ACK and maintenance/rollback support retained deliberately. |

Dependency review: Bleak/CoreBluetooth remain required for BLE/macOS, pyserial for Windows USB, pystray/Pillow for
Windows tray/UI, and WinRT radios for the existing Bluetooth recovery feature. None is an obsolete cleanup dependency.
Firmware theme libraries remain required by C6/original S3. This cleanup removes internal shims, not supported devices.

Earlier unit-only evidence did not establish real lifecycle wiring. The cleanup adds production-path tests and native
power registration; physical PC sleep is still not tested. Full test/build/device results and any limits are recorded
in the architecture-cleanup work item's post-implementation notes. Publishing is a separate action.

Follow-up correction (18 November 2026): the subsequent audit reproduced remaining manual-control, freshness,
maintenance and fixture gaps. The disposition above is historical, not proof these were already covered.
See [follow-up findings and disposition](code-audit-2026-11-18-follow-up.md) and the in-progress follow-up plan.
Earlier screenshot CRCs established transfer integrity only; they did not establish the intended synthetic values.
