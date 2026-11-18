# Code structure

CodexMeter reads Codex data once and sends it to independently managed displays. A display's identity,
settings and delivery history survive transport changes; a USB port or Bluetooth connection does not own them.

## Desktop

- `provider.py`, `chat_activity.py` and `compatibility_readers.py` read and validate Codex metadata.
  Reader leases fence delayed results after reconnects or account changes. `compatibility.py` records source
  health; `power_events.py` connects Windows suspend/resume events to that lifecycle. Elapsed-time detection
  remains a fallback when native notifications are unavailable.
- `device_manager.py` owns logical devices and registry operations; `device_slot.py` holds each device's
  queue and `DeliveryState`. `device_coordinator.py` selects and fences transport owners.
- `delivery.py` and `delivery_pump.py` own freshness, replay, explicit settings and completion delivery.
  One `LockScreenPolicy` instance supplies periodic lock handling and reconnect reconciliation.
- `companion_protocol.py` parses the bounded wire format. `companion_session.py` handles claims, leases,
  sequences, acknowledgements and maintenance. Known-identity tools ask the manager to pause discovery before
  opening a port. Bluetooth-to-maintenance transfer claims USB ownership before releasing BLE so the display
  retains same-host telemetry. `UsbSession` and `BleSession` are sibling adapters.
  Serial port discovery and I/O stay in `usb_transport.py`; BLE discovery, workers and fragmentation
  stay in their BLE modules. The legacy JSON/ACK path remains in `ble.py` for older firmware and rollback.
- `device_identity.py` and `device_metadata.py` interpret identity consistently across transports. Models
  and capabilities are metadata, not separate desktop display implementations. Local status uses `devices`;
  repository tools no longer rely on the former duplicate `ble` key.

## Firmware

USB line framing and BLE fragments feed a common protocol/session owner. `board_profile.h` supplies model,
dimensions and capabilities. `orientation.h` is implemented by the sensor-backed driver or Ball's manual
orientation module. Absent power/settings services are compiled out instead of implemented as dummy functions.

`dashboard_view_model` and `token_view_model.h` determine freshness, partial task validity, token availability,
checked cost sums and partial-cost flags. Round and square renderers own geometry, typography and formatting.
C6 themes remain supported. The original S3 target remains buildable with its own identity; it is not physically
tested in this development setup.

## Constants and builds

`codexmeter/__init__.py` is the release-version source. Setuptools reads it directly; `scripts/release_version.py`
validates it without importing the app. Nuitka uses the validated value for file/product metadata and PlatformIO
writes a generated firmware header under its configured build directory. Test firmware can append `-mtu23`.
Release versions and wire protocol versions are independent.

`companion_protocol.py` and `protocol_limits.h` own host/firmware wire bounds; a cross-language test checks agreement.
The 512-byte ATT limit is distinct from the 512-byte application limit. Host alert backlog is eight entries for
60 seconds; firmware retains 32 deduplication entries for 65 seconds to cover reconnect timing. Explicit setting
intent has its own 60-second lifetime. These values describe different responsibilities.

Windows build scripts configure active output, compiler scratch and caches on D:. Retained bundles and validation
artifacts belong on E: and stay out of Git. Runtime/user-data locations are unchanged.

## Verification

Run the Python suite and `tools/test_firmware_usb.ps1`, then build all three PlatformIO targets and the onefile app.
The executable's `--self-test OUTPUT.json` checks Tk, the external panel's polling/recovery, native tray actions,
settings persistence, packaged child commands, WinRT imports and DPAPI. Use an isolated profile and a PATH without
Python. Test physical transport handovers and captures under maintenance leases; restore each device's settings.

The [audit](code-audit-2026-11-18.md) records the original findings and their disposition. Physical sleep/resume,
the separate computer without Bluetooth, and capacity beyond two displays need separate acceptance; passing
simulations does not establish those hardware results.

The [original upstream architecture notes (Chinese)](architecture.upstream.md) are retained as historical reference.
They describe the earlier macOS/S3 design, not the current implementation.

Manual screen commands: `screen-on` / `screen-off` broadcast to registered displays, or accept `--device-id FULL_ID`.
They return per-device admission results; disabled, disconnected or maintenance targets are rejected. Partial failure
returns a nonzero exit status. A queued response is not an application acknowledgement. Only `--reason manual` is
accepted; automatic OS lock policy is internal and remains independent of manual screen state.

### Audit follow-up verification (18 November 2026)

The companion admits manual controls per device, preserving separate manual and automatic policy state.
Negotiated explicit commands carry their original 60-second deadline to the serialized first write. Legacy
telemetry replay uses producer freshness, including refresh and health paths. Workers perform one attempt;
the coordinator owns retries and fencing. Maintenance acquisition and close serialize through a session lifecycle
lock. A definitely-unsent stale session permits fresh verified USB acquisition; an uncertain sent request retains
its durable maintenance pause. The operation deadline is 12 seconds; maintenance IPC allows 20 seconds.

For synthetic capture, start a disposable profile with `.codexmeter/.validation-profile` and `--validation-mode`.
This is a startup option, not a production IPC toggle. `validation_payload` accepts version-1 usage/activity only;
normal usage IPC also checks its wire kind. Live telemetry and network monitors are disabled in validation mode.
Status reports validation_mode and independent accepted_hashes for usage/activity (at most two hashes).
The raw `validation_state` diagnostic follows existing maintenance ownership rules and refreshes the UI before
reporting its model, validity and page. It contains no chat text. Model readback does not prove raster content.

`validate_architecture_cleanup.py` records expected values and ACK hashes; `capture_validation_pages.py --expected`
checks UI values/page and writes capture hashes in sidecars. `validation_capture.compare_crops` compares explicit
metric regions against separately reviewed reference images. Captures are marked visual_review=pending until
visually reviewed; never treat a successful transfer or model readback as completed pixel acceptance.
