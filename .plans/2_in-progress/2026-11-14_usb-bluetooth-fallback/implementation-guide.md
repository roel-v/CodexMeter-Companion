# Implementation entry guide for GPT-6.1 Sol

This guide is context for implementing the six phase plans, not authorization to start. Read in order:
2_requirements.md, 3_overall-plan.md, this file, the current 4_imp-phaseN.md, and previous phase evidence.
User decisions are settled. Do not reopen them to fill a planning template. Ask only about a new requirement conflict
or a physical action that cannot be completed autonomously; after asking, stop and await an explicit answer.

## Baseline and scope

Source inspected on 2026-11-17 in CodexMeter-Companion. Recheck HEAD, dirty files and applicable instructions first.
Do not overwrite unrelated edits. Move this entire feature into 2_in-progress only when implementation is requested.
This plan does not authorize committing, publishing or changing production devices by itself. Apply authorization
from the active implementation request; do not add redundant permission prompts for already authorized actions.

Support Windows USB-only with no Bluetooth adapter as the primary use case. Preserve macOS BLE import/runtime paths.
Keep Auto / USB only / Bluetooth only per device per PC. USB takes priority across PCs. Preserve physical display
settings/manual power on takeover; live policy and later explicit controls follow R8. No physical sleep/resume tests;
30-minute endurance run is non-blocking. A real no-Bluetooth-PC test remains required.

## Existing code map (verify symbols before editing)

| Concern | Existing locations |
| --- | --- |
| Registry and matching | codexmeter/device_registry.py: DeviceConfig, DeviceRegistry, config_from_short_id |
| Identity/capabilities | codexmeter/device_metadata.py; ble.py: BleIdentity; firmware/src/identity.cpp |
| Worker lifecycle | codexmeter/multi_ble.py: DiscoveryService, DeviceSlot, DeviceWorker, DeviceManager |
| BLE I/O and replay | codexmeter/ble.py: BleTransport, BleState, BleAckTracker |
| Payload construction/coalescing | codexmeter/payloads.py, codexmeter/queueing.py: put_latest |
| Host wiring/status | codexmeter/daemon.py; events.py, ipc.py, ipc_projection.py |
| GUI and tray | codexmeter/device_dialog.py: show_devices, device_row; windows_app.py, windows_tray.py |
| Host screen policy/recovery | codexmeter/screen_policy.py, codexmeter/bluetooth_recovery.py |
| Firmware dispatch | firmware/src/main.cpp: handle_serial, handle_json, handle_ble_screen_policy, loop |
| Firmware BLE and state | firmware/src/ble_service.cpp, model.cpp, device_settings.cpp, identity.cpp |
| Serial tooling | tools/serial_device.py: SerialSession, query_identity, discover_serial_devices |
| Maintenance consumers | tools/capture_screenshot.py, capture_c6_screen.py, read_device_logs.py; flash-windows.ps1 |
| Build/packaging | scripts/windows-env.ps1, build-windows.ps1, build-standalone.ps1, codexmeter/standalone.py |

Serena currently indexes Python. Use its file-scoped symbols for Python; bounded source reads/literal searches for
C++ where semantic navigation is unavailable. Rebind/check the absolute project root before source work.

DeviceConfig currently has device_id, short_id, alias, enabled, name, macos_uuid, legacy and metadata. It does NOT
require a BLE address. Add connection_mode rather than designing a new compulsory BLE-address migration.
Its matches() allows name/short-ID fallback: do not use that permissive path to merge verified USB identities.
The daemon currently exposes manager state under "ble", labels its worker "ble", attaches recovery to after_scan,
and passes manager.control_device and set_connect_control onward. Audit all these integration points together.

## Proposed new boundaries (names are proposals, not existing modules)

- transport_types.py: endpoint, transport-neutral state/result/error types and a bounded transport session interface.
- delivery.py: device-owned desired snapshots and pending alerts, independent of connection lifetime.
- usb_protocol.py: pure bounded encoder/parser with no hardware imports.
- usb_transport.py: Windows serial discovery and cancellable I/O/session management.
- device_manager.py: per-device coordinator; preserve a temporary multi_ble compatibility facade if useful.
- firmware serial_protocol and companion_session modules: hardware-independent framing/session decisions where
  practical, with main.cpp adapting parsed commands to rendering and hardware controls.

Prefer focused extraction over a sweeping rename. Keep tests passing between extractions. Avoid two independently
maintained replay caches: a disconnect must not destroy the logical device's latest snapshots or pending alert.

## Proposed host interface to settle in phase 1

An endpoint carries transport kind, verified full hardware ID, address/port and advertised metadata. A connected
session exposes bounded send(payload), read_state(), close()/release(), plus status notifications. Delivery results
include outcome (accepted/rejected/unknown), transport, session generation, message ID where supported, and reason.
The coordinator owns application sends; a reader may handle ACK/heartbeat concurrently, but never starts a second
application writer. Cancellation must close the serial handle and complete pending waiters exactly once.
Legacy BLE has weaker ACK correlation; represent that explicitly instead of fabricating USB-style ACK IDs.

## Build/test environment

Use repository root as working directory. Set environment before tests/builds:

```powershell
. .\scripts\windows-env.ps1
& $MeterPython -m pytest -q -o cache_dir=D:/build/CodexMeter/pytest-cache --basetemp=D:/build/CodexMeter/tmp/pytest-usb
```

Use targeted tests during each step, then the full suite at integration boundaries. Test counts are observations,
not a fixed expected number. New tests must prove behavioural failure modes rather than mirror private methods.

```powershell
.\build-windows.ps1 -Firmware -Board waveshare_c6_amoled_216
.\build-windows.ps1 -Firmware -Board spotpear_ball_v2
.\build-standalone.ps1
```

Before large builds inspect D: free space and cold-data candidates; never move evidence-bound paths blindly.
Active dependencies, build output and TEMP stay under D:\build\CodexMeter. Retain evidence under ignored
E: checkout dist/windows/validation/usb-<date>/phaseN and artifacts under dist/releases. Do not use C: for caches.
Run packaged self-test via the existing --self-test interface, with an explicit retained report path and sanitized
Python environment. Verify the current command and build output path in the scripts before execution.

## Evidence and stop rules

For each phase record source revision/dirty diff, test commands/results, artifact hashes where applicable, device
identity, unperformed checks and deviations in 5_post-implementation-notes.md. Link bulky logs instead of committing.
A phase is complete only when its exit checks pass or the user explicitly accepts a documented deferral. Missing
hardware is not a successful test. Do not reinterpret excluded physical sleep testing as a requirement to run it.
Do not move to firmware implementation with an incomplete protocol table. Do not silently revise agreed behaviour
because implementing it is awkward; resolve engineering choices in phase 1 and surface actual requirement conflicts.
