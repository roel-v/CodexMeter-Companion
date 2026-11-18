# Phase 3: desktop USB transport and device coordination

Depends on phase 2 protocol implementation and fixtures. Covers R1-R8, R10, R15 and R17.

## Work

- Extract transport-independent delivery queue, desired-state replay, pending alert and health state from BLE code.
  Preserve existing BLE behaviour through an adapter and focused regression tests.
- Add USB candidate discovery and bounded non-resetting identity probes; reconcile endpoints by full device ID.
  Move reusable serial code into the packaged module rather than importing development-only tools at runtime.
- Implement asynchronous/bounded serial I/O, parser limits, session negotiation, ACK correlation, cancellation,
  shutdown and reconnect. Keep a failed/busy serial port isolated from other devices and the UI.
- Support USB-first discovery and registration with no Bluetooth adapter and no existing BLE address/configuration.
  Make BLE discovery optional and independently supervised. Lazy initialization/import failures must not abort USB.
- Preserve stable aliases/settings, support multiple same-model devices, reject identity changes on a reused port,
  and retain BLE-only handling for older firmware lacking the new USB capability.
- Audit Nuitka inclusion, serial backend/dependency paths and existing macOS BLE imports.

## Verification and exit

Use fake serial streams and BLE adapters to test fresh USB-only registration, missing/disabled/failed Bluetooth,
partial/interleaved input, disconnect mid-write, stale ACK, incompatible firmware, cancellation and multiple peers.
Existing tests pass. A USB worker must operate with every Bluetooth API mocked unavailable, not merely disconnected.
No automatic switching is enabled in production until phase 4 coordinates session ownership end to end.

## Configuration and compatibility

Specify a backward-compatible device-registry migration, preserving aliases, hardware IDs and legacy entries.
Keep new USB-only records valid without inventing Bluetooth addresses. Test config reload, duplicate reconciliation
and rollback with the previous executable; document any rollback limitation before changing persisted schema.
Audit IPC consumers, tray aggregation and Bluetooth recovery together, not only the per-device worker.

## Ordered implementation tasks for Sol

1. Add characterization tests around DeviceManager broadcast/control/status and BleTransport replay before extraction.
   Preserve queueing.put_latest coalescing and alert semantics. Identify which fields currently live in BleState.
2. Introduce shared endpoint/result/state types per implementation-guide.md. Extract delivery state from the BLE
   connection so one DeviceSlot retains snapshots and pending alerts across disconnects. Keep facade imports working.
3. Adapt BleTransport incrementally to the common session interface. Test existing BLE paths before adding USB.
   Do not falsely upgrade legacy ACK guarantees. Attach generation to asynchronous callbacks at the adapter boundary.
4. Add connection_mode to frozen DeviceConfig with default auto. Validate values at configuration boundaries;
   absent old fields default safely, unknown values produce an actionable error rather than an unwanted connection.
   Preserve metadata in daemon identity-observer reconstruction; otherwise it can silently reset the selected mode.
5. Implement pure USB codec using phase 1 fixtures. Add streaming limits, timeouts and tolerant skipping of ordinary
   log lines, but reject protocol-shaped invalid replies. No Serial imports in codec or generic registry modules.
6. Move/reuse serial-open primitives in a packaged module and adapt tools/serial_device.py to use them. Preserve
   existing CLI behaviour. USB discovery uses candidate metadata, bounded probes and full-ID verification.
   Known unregistered devices are shown for registration; they receive no application payloads.
7. Implement serial session reader/writer with finite read/write timeouts, cancellation and exclusive port ownership.
   Use a managed thread for blocking serial reads if needed; close wakes reads and join has a bounded timeout.
   A single reader routes heartbeat/ACK/status. Serialize application sends, register ACK waiter before writing,
   and resolve unknown-delivery separately from explicit rejection. Do not use sleeps to guess ACK completion.
8. Supervise USB discovery independently of optional BLE discovery. No adapter, permissions errors or BLE import
   failures may cancel the manager/UI/telemetry. Do not start a radio scan solely for USB-only devices.
9. Add USB-first discovery/registration through CLI and GUI plumbing; a fresh registry must not activate a legacy
   BLE fallback before USB registration can happen. Full-ID matching takes precedence over name/short-ID matching.
10. Wire generic manager status through daemon/events/IPC while retaining a documented compatibility projection for
    existing callers expecting the "ble" key. Do not leave the GUI or recovery consuming contradictory snapshots.

### Proposed tests and fixtures

New tests: test_usb_protocol.py, test_usb_transport.py, test_transport_delivery.py. Extend test_device_registry.py,
test_device_metadata.py, test_multi_ble.py, test_mixed_displays.py, test_daemon.py and test_serial_device_tool.py.
Inject monotonic clock, endpoint discovery and serial factory; do not require real hardware for unit tests.

Required cases: missing BLE backend; adapter absent; first USB registration; two identical names/different IDs;
COM reuse with different identity; duplicate USB/BLE endpoint for one ID; busy port; removal mid-frame/write;
late/wrong ACK; close while read waits; four fake devices with one stalled; registry save/reload preserving mode;
existing registry loads unchanged; protocol version mismatch; unknown device never receives telemetry.

### Exit checklist

- [x] BLE characterization/regression tests pass after extraction.
- [x] USB session works against phase 2 fixture firmware without a BLE dependency or existing BLE registration.
- [x] Cancellation leaves no live reader thread, port handle or unresolved ACK future.
- [x] Shared latest-state/alert ownership is singular; reconnect does not lose pending delivery.
- [x] No production auto-handover is enabled before phase 4 arbitration is tested.
