# Repeat audit after deployment — 18 November 2026

Baseline: `1398e9a` on `main`. This is a new audit, after the seven-phase follow-up and local deployment.
Production code, running companion, display state and firmware were not changed during this audit.

## Result

The earlier delivery, queue, maintenance and parser fixes are present. The current Python suite passes:
**423 tests in 24.39 seconds**, with D: test scratch and no pytest cache writes. Passing that suite does not
cover the findings below. No new P1 issue was confirmed. Four functional/verification gaps and three cleanup
items remain. Priority P2 means a normal follow-up fix; P3 means lower-priority maintenance.

Navigation used Serena against this exact checkout, scoped source/reference reads and repository searches.
Small reproductions use fake transport channels or disposable databases; they do not use production IPC,
Codex databases, Bluetooth or serial hardware. Reproduction code/results are retained outside Git at
`dist/windows/validation/audit-repeat-20261118/` (`reproduce.py`, `reproduce.json`, `capture-deadline.json`).

## 1. P2 — The display panel reports queue admission as successful application

Locations: `codexmeter/device_dialog.py:124`, `codexmeter/device_manager.py:416`,
`codexmeter/delivery_pump.py:40`, `firmware/src/main.cpp:1009`.

The manager correctly returns `ok: true, queued: brightness` after admission. The panel converts that to
"Applied; refreshing status." before any device acknowledgement. A physical swipe, BOOT page change or automatic
rotation changes the firmware settings revision. The manager retains its earlier revision until reconnect or a
control readback, so the next command can be admitted and then rejected with `conflict`. Two quickly queued
settings can encounter the same mismatch. Queue admission is not the problem; the GUI's success claim is.

Reproduction through the real manager, DeliveryPump and UsbSession with a revision-checking fake wire channel:
IPC returned `ok=true, queued=brightness`, then delivery recorded `conflict`. The GUI message was established
by tracing its response branch, not by operating the live UI. Ordinary telemetry success clears `last_error`,
and panel polling replaces its message, so the existing status row is not a durable command result.

Fix: show "Queued" at admission and retain a per-command terminal result (applied/rejected/unknown/expired)
that the panel can correlate. On conflict, expose refreshed settings and a retry action. Do not blindly rebase
old commands and overwrite physical changes. Test queue success followed by conflict, expiry, disconnect and
success, plus a local page/rotation change before a desktop control and two rapidly submitted settings.

## 2. P2 — Repeated database readers do not close their SQLite connections

Locations: `codexmeter/compatibility_readers.py:22,58`; polling caller `codexmeter/chat_activity.py:219,232`.

`with sqlite3.Connection` manages a transaction; it does not close the connection. Both inventory and unread
readers use this form without a closing context or finally block. They run every five seconds. Connections and
file handles are therefore retained until garbage collection, rather than released when each read completes.
This is especially undesirable when database files must be replaced during a Codex update or account change.

Isolated reproduction with a disposable database: forty calls to the real `read_roots` increased Windows process
handles from **198 to 238**; explicit garbage collection restored **198**. Automatic cyclic collection was disabled
only for this probe to make the lifetime visible. This establishes delayed cleanup, not an unbounded permanent
leak, and does not establish the cause of any historical crash.

Fix: give `open_database` a closing context-manager contract, or wrap each connection in `contextlib.closing`.
Test closure on normal results, invalid schemas and query exceptions for both readers, independent of GC timing.

## 3. P2 — Full-frame screenshot header waiting has no total deadline

Location: `tools/capture_screenshot.py:42–53`.

Every unrelated log line restarts `read_line(line_timeout)`. If the screenshot command fails to produce a header
but the device keeps logging, capture can wait indefinitely. `raw_timeout` applies only after a valid header.
The later end-marker helper already uses an overall deadline; the initial header search does not.

A fake serial stream emitted an unrelated log every seven seconds. With an eight-second line timeout, the real
capture function was still requesting another full eight seconds after 35 simulated seconds. The harness stopped
the probe after five reads; the capture function had not enforced any total deadline. No physical device was used.

Fix: bound the entire header search with monotonic time and pass the remaining budget into reads. Recognize
explicit failure markers promptly. Add noisy-stream, empty-line and missing-header tests, preserving the existing
full-frame CRC and older-header compatibility tests.

## 4. P2 — The documented contribution test command is obsolete and cannot run the current suite

Locations: `tests/run_tests.py:15,44–48`, `CONTRIBUTING.md:22,51`, `.github/PULL_REQUEST_TEMPLATE.md:9`.

The hand-written runner lists **16 of 45** current Python test modules and directly calls test functions.
It cannot provide pytest fixtures or expand parametrization. Signature checking found two calls that fail:
`test_usb_registration_requires_verified_full_id_without_bluetooth` needs `monkeypatch` and `capsys`, and
`test_full_frame_capture_checksum_and_legacy_header` needs `monkeypatch` and its parametrized checksum.
The runner enumerates 148 functions, which is not equivalent to the 423 pytest cases. Its description as a
runner for environments without pytest is also outdated: listed modules now import pytest.

GitHub's Python workflow already runs pytest correctly; this finding concerns the published contributor/PR path.
The same contribution guide still directs issue reports to the upstream repository and describes only the older
macOS/S3 workflow.

Fix: remove the obsolete runner or make it a thin pytest entry point, document/install development test dependencies,
and align the contribution guide and PR checklist with the actual supported targets and build/storage policy.
Do not implement another partial fixture engine. Verify the documented command itself from a clean dev environment.

## 5. P3 — Negotiated connection orchestration is still duplicated, with an ownership injection mismatch

Locations: `codexmeter/usb_worker.py:30–107`, `codexmeter/ble.py:340–372`,
`codexmeter/device_manager.py:65,106`, `codexmeter/companion_protocol.py:94–126`.

USB and negotiated BLE separately initialize logical state, drain the queue, select replay, reconcile screen
policy, send replay, consume queued data and clean up the session. DeliveryPump shares individual delivery but
not this lifecycle. Future reconciliation or cancellation fixes still need two implementations.
There is already a concrete mismatch: DeviceManager's injected host_id reaches USB workers, while the BLE path
calls load_host_id directly. Normal production uses the same persisted default, so this is not evidence that the
currently installed app claims different identities. It does break the coordinator's explicit injection contract.

The common negotiated identity parser also remains USB-shaped: it requires usb=1 and mandatory brightness/rotation/
screen capabilities, hardcodes the three model names, and emits USB-specific errors even when used by BleSession.
This works for today's supported models but is inconsistent with the architecture note that models/capabilities
are metadata. New model support still requires desktop protocol edits, even with compatible wire semantics.

Fix: share the negotiated session lifecycle while leaving discovery, framing, GATT and serial handles in adapters.
Pass one coordinator-owned host identity to both. Separate wire validation from supported-device policy; retain an
explicit supported-model policy if deliberate, but locate and document it as such. Test the same lifecycle scenarios
and injected identity through both adapters. Do not remove the supported legacy BLE implementation.

## 6. P3 — Obsolete discovery/retry-era scaffolding remains

Locations: `codexmeter/ble_discovery.py:115–131,232`, `codexmeter/usb_transport.py:368,483`,
`codexmeter/ble.py:219–338`, `codexmeter/companion_session.py:214`.

Serena found no references to DiscoveryService.wait_for. The coordinator now uses find; the old method retains the
BLE change event and the sole production reference to async_utils.wait_any. USB discovery creates/sets its own
_changed event without any waiter. ble_discovery additionally imports an unused _sleep_or_stop alias.
Legacy BLE still calculates/returns used_successfully, but DeviceWorker ignores that return value now that retry
ownership lives in the coordinator.

exclusive_delivery has one test caller and no production caller after maintenance moved to try_maintenance.
This is a test seam, not automatically a defect: either keep and document the intentional test API or replace it
with an appropriate synchronization fixture. Do not delete it without updating that test.

Fix: remove the reference-proven obsolete paths and bookkeeping; keep intentional test seams explicit. Check source,
tests and tools before deletion, including string-based consumers. These are cleanup findings, not observed outages.

## 7. P3 — Small shared policies and theme helpers are still copied

Locations: `codexmeter/device_coordinator.py:10`, `codexmeter/ble_worker.py:67`,
`codexmeter/device_manager.py:277`; `codexmeter/device_metadata.py:12`,
`codexmeter/companion_protocol.py:97`; theme files below.

The identical busy-reason set is copied into retry selection, failure accounting and Bluetooth recovery filtering.
Application protocol support is declared as SUPPORTED_PROTOCOL but separately hardcoded in negotiated identity
validation. Wire-version and application-version constants must stay distinct even though both currently equal 1.

Firmware duplicates the identical set_label_text_if_changed helper across nine theme files (for example
animal_crossing_theme.cpp:124 and cyberpunk_theme.cpp:107) and the simple font_or helper across ten. These do not
represent different layouts; they can share a small LVGL utility header. Geometry, fonts and theme-specific rendering
should remain separate. Desktop initial/reloaded worker construction also repeats the same transport option mapping.

Fix: consolidate identical policy/helper definitions at their natural owners and reuse _transport_options for both
initial and added workers. Avoid merging unrelated constants merely because their numeric values match. Verify all
three firmware targets if shared theme headers change, and test busy-error classification at all three consumers.

## Assessment and limits

The abstract logical-device/delivery split, sibling session adapters, board profile and shared dashboard/token
semantics are useful and functioning. Supported old-wire BLE handling and older screenshot headers are deliberate
compatibility, not dead shims. Board-specific rendering, power and orientation implementations are also legitimate.
The remaining main duplication is connection orchestration and small utilities, rather than a need for another
architecture rewrite.

This audit did not rebuild/install/flash, run live controls, access private chat content or repeat hardware acceptance.
The previous deployment evidence remains separate. New reproductions are isolated. No implementation, plan, commit,
push or release was made; only this report was added to tracked-source territory, with ignored audit evidence retained.
