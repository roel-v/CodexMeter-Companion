# Post-implementation notes

## Phase 1 — 2026-11-17

Source baseline `a358579882d5c88b953131056383728530e8a1c9`. The feature plan was moved into `2_in-progress`;
no dependency graph exists. Phase 1 adds only the [protocol contract](protocol-contract.md) and
[hardware verification](hardware-verification.md), with this note. No source changes, new build or flash,
commit, push or publication. Baseline test suite run by the coordinating agent passed 254 tests in 13.45 s
using D: pytest cache and temporary directories. D: free space observed as 159,739,768,832 bytes.

The contract chooses a fixed header outside the application JSON, explicit idempotence and an ownership lease,
state revision gating for explicit controls, and separate link and data freshness. Timings are provisional until
physical release-validation measurements. C6 native USB identity and non-resetting repeated open/close were
verified with the existing firmware. No application commands were sent. Ball USB was absent at enumeration.
Phase 1 remains open pending live Ball identity and continuity checks. Phase 2 has not started.


Contract review retained the 5-minute host-stale waiting threshold, 3-minute usage-stale threshold and 60-second
default usage interval. Existing macOS lock/unlock reasons map to negotiated policy controls while legacy payloads
remain readable. Bounded BLE fragmentation preserves the full 512-byte application payload at the minimum ATT MTU
and does not silently downgrade an updated endpoint to legacy ownership. Fragment timing and adapter interoperability
remain untested until the implementation and physical validation phases.

## Phase 1 resumed — 2026-11-18

Live Ball identity confirmed codexmeter-6867f4697090 on COM9, firmware 3.12.3.0-usb.1, app protocol 1.
C6 remained present on COM6. Both completed five identity-only open/close cycles with unchanged volatile log
sequence/uptime markers before/after; identity round trips were 15–16 ms. The first Ball logs request timed out
at 2 seconds, then a retry and the full continuity test passed. Hardware-verification.md retains exact observations.
The physical Phase 1 blocker is resolved. Root contract review remains the handoff check before Phase 2.
The loaded Ball firmware does not advertise the proposed wire protocol. No implementation, flashing, build,
commit or publication occurred during this phase. No new tests were necessary for these document-only updates.

## Phase 2 — implementation and physical trial, 2026-11-18

Source baseline remains `a358579882d5c88b953131056383728530e8a1c9`; firmware and isolated fixtures are dirty/uncommitted.
No host transport implementation, commit, push or publication is included. Evidence is retained under ignored
`dist/windows/validation/usb-2026-11-18/phase2`. Initial D: headroom was 139.56 GiB; old pytest/desktop outputs were
inventoried as possible cold candidates but not moved. Active builds use `D:/build/CodexMeter/usb-phase2-build`;
the baseline `firmware-build` files remain intact. Native tests use `usb-phase2-native`, and caches/TEMP remain on D:.

Firmware now shares fixed-capacity framing/fragment decoding, ownership/retry fencing and the powered alert ledger.
Control and application JSON use a bounded aligned allocator, exact-root/duplicate/type/UTF-8 checks and validation
before effects. USB replies are correlated and source-routed, with 128-byte RX/one-frame and 64-byte TX loop budgets.
Identity IDs/service UUIDs remain unchanged. State revisions cover physical page/brightness/rotation/manual intent;
manual and policy power are separate. Telemetry freshness excludes controls, alerts, duplicate retries and pings.
Raw application JSON on serial is disabled; diagnostic writers are gated away from USB app ownership.

Native verification: `./tools/test_firmware_usb.ps1` compiles actual protocol/session/framing and `model.cpp` with
Visual C++ against pinned ArduinoJson 7.4.3. It passed, including exact 512-byte payloads with both breakout arrays
and uint64 values, malformed/duplicate JSON, overflow/discard, expiry/wrap, retry revision comparison, maintenance,
live-owner duplicate claims and tombstone fencing. MSVC reports only pre-existing demo time_t-to-long conversions.
Root independently ran the harness and the existing Python regression suite: **254 passed in 13.41 s**, using D:
pytest cache/temp. Serena CLI was unavailable due unverifiable runtime PID/lifecycle metadata; bounded C++ reads
were used as explicitly allowed by the implementation guide. No global Serena configuration was changed.

Before application updates, full current private 16 MiB rollback images were captured and independently hashed by
the coordinating agent. They contain NVS/artwork and must never be published:

| Board | Private rollback image | SHA-256 |
| --- | --- | --- |
| C6 `codexmeter-00e216f16e20` | `E:/DeviceBackups/Waveshare-C6-206EF116E200/2026-11-18-usb-phase2-before/current-full-16MiB.bin` | `fa847c9d24c22674005fb11c0e437aebe8086ae53706498ac3a35e61446657b4` |
| Ball `codexmeter-6867f4697090` | `E:/DeviceBackups/Spotpear-Ball-907069f46768/2026-11-18-usb-phase2-before-retry/current-full-16MiB.bin` | `9d8a5d789575577c217c541cab0afe7188732981e6b7e3590bcc4f34a53ffa99` |

The first Ball read exceeded its initial 240 s bound without producing a full image. The failure metadata and
recovery diagnostics remain in the earlier `2026-11-18-usb-phase2-before` folder. A normal read-only flash-ID/reset
diagnostic verified MAC `90:70:69:f4:67:68` and restored the unchanged app; live full identity then succeeded.
The retry used a persistent progress log and 600 s bound informed by measured ~42 KiB/s transfer progress. C6
full read took 98.2 s. Both saved partition tables/OTA seq 1 select app0 at `0x10000`, size `0x300000`.

The production companion was stopped gracefully through its existing IPC shutdown event. Identity-checked
`tools/update_firmware_app.ps1` verified rollback hashes and wrote only app0, preserving NVS/artwork/bootloader/
partition-table regions. Both `3.12.3.0-usb.2` writes passed esptool verification. These intermediate artifacts,
ELFs/maps and logs are retained separately; they are not final acceptance binaries:

| Intermediate board artifact | Static RAM / flash | Application SHA-256 |
| --- | --- | --- |
| C6 | 54,588/327,680; 2,412,778/3,145,728 | `77391572964af853aeebce925587c64153c2a8cdd87d524184d0b3ce5390131d` |
| Ball | 190,768/327,680; 1,213,734/3,145,728 | `6c4ab70252f2bc4e67b41d67a0108924b68efc7ba9d79b965f05384763ed5764` |

Both boards passed the strict isolated USB fixture's 12 cases in `*-usb-fixture-retry.json`. The first one-second
identity query following each update timed out; both failures are retained separately. Subsequent identity and
protocol requests succeeded without additional device reset. Negotiated-MTU handover passed legacy/negotiated
BLE ownership, USB preemption/busy notice, USB ACK isolation, shared alert presentation deduplication, settings and
manual-off preservation, same-connection identity reread/new-token BLE reclaim and seven-second USB lease expiry.
Ball also passed the 302 s healthy-ping/no-new-telemetry waiting check (`ball-handover-mtu.json`, 183 cases).

Two C6 longer runs lost serial replies mid-freshness, then identity/logs recovered on a new handle without reset.
Their failed reports remain `c6-handover-mtu.json` and `c6-handover-wnr.json`; do not count them as freshness passes.
The proposed usb.3 revision instruments RX frames, app-buffer abandons, ring wait loops and bytes queued to the
driver, and explicitly pumps the pinned HWCDC IN_EMPTY interrupt without blocking or overwriting queued bytes.
`tx_queued` is driver-ring acceptance, never evidence of host receipt. Final physical verification is still pending.

### Measured BLE contract adjustment

Acknowledged ATT writes with forced 15-byte logical fragments took **5.047 s** for the initial C6 claim, exceeding
the bounded two-second assembly train and correctly yielding no ACK. With root-reviewed sequential awaited writes
without response, tested trains took **0–32 ms** to queue, and matching application ACKs confirmed device acceptance,
including a full 512-byte application. The measured host was Windows with negotiated MTU 256, not MTU 23.
The contract now requires bounded sequential WNR, no interleaving, matched application ACK, and a whole-frame
identical-sequence retry on unknown outcome. OS queue acceptance is not success. The two-second train and seven-
second lease remain unchanged. Phase 3 must implement this adjusted contract.

Explicit MTU-23 variants identify as `3.12.3.0-usb.3-mtu23` and call NimBLE `setMTU(23)`; they are isolated acceptance
builds, not release artifacts. They must be distinguished by hashes and restored to production configuration.
Real no-Bluetooth-PC acceptance, ten switch cycles per board and mixed production host integration remain later
phases. Physical sleep/resume is excluded; optional 30-minute endurance has not run. Touch responsiveness and
visual presentation must not be claimed from protocol state assertions alone. Phase 2 is not yet marked complete.

### TX recovery and actual minimum-MTU evidence

The reviewed usb.3 driver adapter arms the existing IN_EMPTY interrupt and flushes only the hardware FIFO request,
not the software queue, once per loop while USB is physically plugged. It runs even after the final application
chunk has entered the driver's ring. It never writes beyond `availableForWrite`, waits, calls `Serial.flush`, or
uses USB presence as ownership. This is a mitigation consistent with the pinned HWCDC full-ring/disabled-interrupt
hypothesis; the original transient was not captured with driver-level instrumentation, so its root cause is not proven.

Both isolated `3.12.3.0-usb.3-mtu23` images passed **183 cases**, including actual negotiated MTU **23**, full 512-byte
usage with both breakout arrays, matched application ACK, busy notices, alert presentation deduplication and a
302-second healthy-ping/no-telemetry waiting check. Each run accepted 148 freshness pings. Final C6 health reported
303,936 ms telemetry age, waiting=1, tx_abandon=0, tx_wait=0; Ball reported 303,599 ms, waiting=1. Ball's one app-buffer
abandon/41 wait loops were from the preceding deliberate backpressure trial, which recovered with a clean ping.
WNR logical train queue times were C6 0.015/0.047/0.016/0.015 s and Ball 0.015/0.046/0/0.015 s. Queue time does not
measure air delivery; matching device replies are the acceptance evidence. Reports are in `phase2/usb3`.

| Isolated tested image | SHA-256 |
| --- | --- |
| C6 MTU23 | `bc88a59e81018bf77fdcca58f67942ccf787653369ff8f9d15279c457822c76d` |
| Ball MTU23 | `d40d142e9e5c9fe56afea5f7864a9dbf2f4fa6d99db2e08e965c336204c39634` |

Runtime headroom after bounded malformed/backpressure fixtures: C6 internal free 216,128 B, largest 196,596 B,
minimum 212,420 B; Ball internal free 37,208 B, largest 28,660 B, minimum 35,712 B, plus 7,688,084 B free PSRAM.
The aligned 8 KiB wire allocator fits observed largest internal blocks. These are observed post-fixture snapshots,
not a proof against arbitrary future allocator pressure. Both targets passed 13 USB cases including backpressure.

### Final normal configuration — usb.4

A final source-aware power correction confines mac_locked/mac_unlocked and on-only ble_restored policy aliases to
legacy BLE. Negotiated requests use only lock/unlock for policy; a revisioned mac_locked request is manual intent.
The pure classifier is covered by native tests and the final physical R8 fixture uses that negotiated manual case.
The correction and version text are the only differences from the tested usb.3 transport behavior; MTU23 variants
were not rebuilt for this power-only change. Future source-built test variants identify as usb.4-mtu23; the retained
physically tested usb.3 variant hashes above remain the actual minimum-MTU evidence.

Normal `3.12.3.0-usb.4` images, ELF/maps, source snapshot and build/native logs are retained in `phase2/usb4`:

| Final normal image | Static RAM / flash | Application SHA-256 |
| --- | --- | --- |
| C6 | 54,604/327,680; 2,413,204/3,145,728 | `53e635b9e58610b0e7be7429dfcc4e78d040d8bd7a29103229aba3656bb58205` |
| Ball | 190,784/327,680; 1,214,066/3,145,728 | `9909a4e057d069e6cc5d05dcee466b1da55a79d67b662e2c4b1dc43b8975985d` |

Both normal images were restored with app-only writes and esptool hash verification. Each passed **18** strict USB
cases, including maintenance claim/renew, blocked application DATA, diagnostics, maint_end and fenced-token reuse,
as well as backpressure recovery. Ball passed **32** normal-MTU-256 handover/R8 cases and five read-only open/close
cycles with unchanged boot `9634568c6cb52a20`. Its 240x240 waiting framebuffer was captured with the existing serial
tool and visually inspected. The first one-second query following each app update still timed out and is retained;
these cold post-update observations are distinct from the previously observed mid-session C6 failure.
The exact normal C6 usb.4 regression passed **183 cases at MTU256**, including 148 accepted freshness pings,
303,954 ms telemetry age with waiting=1, tx_abandon=0 and tx_wait=0. This specifically reran the conditions of the
earlier normal-MTU failure. Five subsequent C6 read-only open/closes retained boot `e2dcdd4800be2c5c`; its 480x480
tiled framebuffer passed CRC/coverage checks and was visually inspected. The normal Ball R8 run passed 32 cases.

The original retained companion executable was restored once, hidden, with TEMP on D:, after all fixtures closed.
`companion-restored.json` records launcher PID **84864**, executable SHA-256
`2fc2e2c1bf7e5286315f566095af5c8ccee598f7d66953e38efba1d61f2b2de8` and startup UTC
`2026-11-18T11:07:22.1495706Z`. Authenticated IPC then reported running, configured_count=2, connected_count=2,
both exact board IDs connected over the original legacy BLE path, no per-device last_error, and last ACK age 4.8 s.
USB and maintenance ownership are released. No test MTU23 image remains installed. No commit/push/publication ran.

The coordinating agent accepted the Phase 2 firmware gate after independently reviewing the native/physical
reports and framebuffers. Physical finger-touch was not personally retested; preserve that later acceptance note.
Cold first-query misses, real no-Bluetooth-PC validation, ten powered switch cycles, production-host integration,
excluded physical sleep/resume and optional unperformed endurance remain accurately distinguished above.
Phase 3 must follow the adjusted WNR contract and include `tools/update_firmware_app.ps1` in its later maintenance-
consumer audit. The powered alert ledger clears on reboot; replay across power loss can present an alert again.

## Phase 3 — desktop transport implementation (2026-11-18)

Source baseline remains `a358579`; phase 2 firmware and planning edits remain uncommitted and were preserved.
No commit, push, publication, firmware flash or production-companion restart was performed in this phase.
Serena CLI succeeded against the exact E: checkout (session 59d401b8); Python source navigation used its symbols.

### Implemented boundaries

- `delivery.py` owns desired snapshots, accepted state, monotonic producer-observation times, explicit intents and
  an eight-entry/60-second pending alert ledger. `BleState` remains a compatibility alias. Legacy ACK/replay behavior
  is characterized; accepted/retried/replayed payloads do not refresh producer observation time.
- `transport_types.py` defines endpoint/session/result contracts. `usb_protocol.py` is a hardware-free bounded codec;
  duplicate keys, nesting, UTF-8, frame/application limits, invalid reply correlations and incompatible identity fail
  explicitly. Timeout/overflow discards through LF, never promoting a suffix to a new frame.
- `serial_backend.py` opens 115200 8N1 with DTR/RTS false before open and no flow control. Existing serial tooling
  reuses this primitive. The packaged transport never imports development-only tools.
- `usb_transport.py` verifies present Windows PnP USB interface00, usbser and Ports class before probing; COM ports
  are hints only. Two probes run concurrently; identity must match the full device ID and boot before claim. Known
  incompatible identities retain an upgrade reason without receiving a claim or application payload.
- One bounded managed reader per serial channel routes protocol lines. Native open/write/close/enumeration use
  capped daemon operations outside asyncio's default executor; repeated hangs are single-flight per port/operation
  and cannot consume every slot. Cancellation fences callbacks/waiters, closes the handle and joins the reader.
  A permanently stuck OS driver operation cannot be forcibly terminated by Python; it remains quarantined in a
  bounded daemon slot until the native call returns, with late handle disposal off the event loop.
- `UsbSession` negotiates claim/state, correlates boot/token/q/seq, sends fixed-cadence two-second heartbeats and
  retries unknown DATA exactly once with identical bytes/sequence. An OS write is never delivery acceptance.
- `ble_session.py` adapts updated `ble_owner:1` peers to the same session contract. It uses ordered awaited WNR
  fragments with a two-second train bound and actual MTU sizing; legacy firmware keeps its weaker original ACK path.
  Callback generation fencing prevents a disconnected adapter's events from completing a replacement session.
- The generic manager facade preserves `multi_ble` imports and a documented `ble` IPC projection; the canonical
  status key is `devices`. Recovery reads only Bluetooth-eligible rows. USB-only operation does not start BLE scans.
- Frozen registry records add validated `connection_mode` (`auto`, `usb_only`, `bluetooth_only`), defaulting old
  entries to Auto. Aliases, metadata, full identity and address-free USB records survive save/reload/rebinding.
  CLI scan/adopt/mode and GUI registration accept verified USB full IDs. Fresh Windows registries do not activate
  the implicit legacy fallback before explicit registration. Initial Auto retries USB after a cold first query.

### Explicit phase boundary and compatibility

Initial transport selection is implemented; an established transport remains selected for that run. Dynamic USB
promotion/Bluetooth fallback, mode-change fencing while running, persisted maintenance pause/resume and fresh OS
policy recomputation after reconciliation belong to phase 4. `UsbDeviceWorker.on_reconciled` is the explicit fresh
policy hook; cached `ble_restored` is dropped. Same-host explicit replay requires its original boot/revision and
unexpired intent; cross-host reconciliation drops queued explicit settings/alerts. No saved physical preset is
blindly replayed on claim. Phase 4 must connect the hook for both negotiated transport adapters.

The registry remains version 1 and additive. The previous reader ignores `connection_mode`, can load the new
address-free records, and retains hardware IDs/aliases. **Rollback limitation:** the old executable does not enforce
USB-only/Bluetooth-only preferences, cannot use USB, and may attempt its old BLE behavior. Running an old writer
can remove the new mode field. Do not describe this as preserving connection policy under rollback.

Nuitka explicitly includes `serial`; existing platform markers retain pyserial on Windows and lazy CoreBluetooth
imports on macOS. Full standalone compilation/self-test and actual no-Bluetooth-PC validation remain phase 5 gates.
Maintenance consumers audited: `capture_screenshot.py`, `capture_c6_screen.py`, `read_device_logs.py`,
`preserve_device_firmware.py`, `update_firmware_app.ps1`, and flash scripts. Their shared serial primitive is retained;
phase 4 must add maintenance pause/ownership integration rather than treating exclusive-open errors as recovery.

### Verification and retained evidence

All test/cache/temp paths were configured through `scripts/windows-env.ps1` on D:/build/CodexMeter. An isolated
Black tool invocation used D: uv cache/temp and formatted only new modules/tests; no project dependency was added.

- Before extraction: 29 BLE/delivery/multi-device tests passed; the same 29 passed after extraction.
- Full intermediate regression: 283 passed in 15.85 s, then 296 passed in 15.94 s as coverage expanded.
- Final test report: `dist/windows/validation/usb-2026-11-18/phase3/pytest.xml` (final count/time below).
- New cases cover missing Bluetooth imports, unavailable adapter, first USB registration/retry, exact full identity,
  registry roundtrip/rollback, incompatible known rows, malformed streams, stale/wrong ACKs, partial line timeout,
  identical retry, unknown delivery, cancellation/reader shutdown, hung open/cleanup/enumeration, repeated operation
  isolation, four workers with one unanswered ACK, unregistered probes with no CM1 traffic, atomic host-ID creation,
  stale legacy replay freshness and negotiated BLE full 512-byte payload at simulated MTU23.
- Physical `physical-usb.json`: COM6/codexmeter-00e216f16e20 and COM9/codexmeter-6867f4697090 on unchanged normal
  `3.12.3.0-usb.4`; compatible identity/claim/state/activity ACK passed, all physical settings/revision preserved,
  reader and heartbeat tasks finished and serial reader threads were gone after release. Boot IDs remained
  `e2dcdd4800be2c5c` / `9634568c6cb52a20`, matching phase 2.
- Physical `physical-control-noop.json`: revision-bound no-op brightness accepted on both boards with unchanged
  full state. These tests temporarily claimed USB beside the original running companion and released ownership.
- `companion-recovery.json`: original retained companion returned 2/2 connected, no device errors, fresh ACKs.
  No physical sleep/resume, actual no-adapter-PC test, new packaged build, switch-cycle or optional endurance test
  was performed or claimed in this phase. Simulated BLE MTU coverage is distinct from phase 2 physical evidence.

Root independently reviews this phase before phase 4. Final source/evidence manifest and test result follow.

Final phase 3 full suite: **298 passed in 15.67 s**; `git diff --check` passed. The coordinating root independently
observed 298 passed in 15.89 s. One additional connection-notice regression was added afterward (result below).

Owner notices deliberately omit token/q/seq in contract and firmware (`ble_service.cpp` pending_busy serializer).
They are scoped to the subscribed BLE connection adapter. Closed adapter callbacks are fenced before assembly;
regression tests prove an old adapter's notice cannot fence a replacement session. A notice received by the current
adapter fails closed even without a token. Same-connection delayed notices cannot be cryptographically/generationally
distinguished on this wire format; phase 4 must treat them conservatively as owner-busy and reconnect/re-discover,
never invoke Bluetooth radio recovery or claim successful delivery. No stronger token correlation is claimed.

The production process left running throughout is the **original legacy BLE 3.12.3.1 executable**, not this new source
coordinator. `companion-recovery-final.json` confirms both displays connected without errors after the final no-op
control checks. Phase 4 maintenance integration must include the new `tools/update_firmware_app.ps1` consumer.

Final retained suite after owner-notice regression: **299 passed** (see phase3/pytest.xml for duration).
Four negotiated-BLE adapter tests passed in 0.44 s; final `git diff --check` passed. `source-manifest.json` records
exact phase 3 file hashes and baseline HEAD; `git-status.txt` records preserved dirty work. Root accepted phase 3
following independent full/affected verification. Phase 4 remains unimplemented and may now begin sequentially.

## Phase 4 — live selection, maintenance and status (2026-11-18)

Source baseline remains `a358579`; preceding phases' uncommitted firmware/source work was preserved. No commit,
push, publication, firmware flash, large build, production process restart or physical transport test ran in this phase.
Serena verified the exact E: checkout and located DeviceManager before source changes. Root reviews this phase separately.

### Implemented behavior

- Each logical device has one coordinator and at most one worker task. It owns selection, cancellation and bounded
  retry decisions with an injected monotonic clock/wait. States include probing, switching, USB/BLE active, owned
  elsewhere, maintenance and disconnected. Transition logs contain ID/reason/elapsed time, never payloads or lease tokens.
- USB promotion requires a second successful identity with the same full ID/boot after at least two seconds. Probes
  remain read-only beside BLE. Before claim, the old worker is cancelled, callbacks/waiters fenced and cleanup awaited.
  USB failure immediately permits an eligible BLE attempt; USB retries back off to 16 seconds, BLE to eight seconds.
  Owner-busy retries every two seconds and does not become radio-failure evidence. Forced modes exclude the other worker.
- Optional adapter availability is reevaluated at most five seconds apart. Missing/inaccessible/disabled Bluetooth
  clears cached candidates and cancels BLE workers; USB-only needs no Bluetooth imports or scans. Genuine BLE failure
  evidence is tracked separately from generic USB errors. A healthy USB peer cannot suppress another BLE device's
  recovery, and USB failures alone cannot trigger recovery.
- Negotiated USB and BLE reconcile firmware state before clearing old queued work, bounded replay and a fresh OS lock
  read. The fresh result respects the current lock timeout, learned from actual policy-loop observations. Policy uses
  lock/unlock origin and cannot change manual intent. Saved physical presets and synthetic reconnect-on are not replayed.
  Same-host explicit intents retain original boot/revision/TTL; cross-host claims drop queued old controls/alerts.
- Mode changes, registration, aliases and enable changes route through authenticated daemon IPC when it is running.
  The daemon owns registry read/modify/save; offline CLI use remains available. Atomic persistence failures leave the
  current mode/configuration unchanged. Live adoption adds one coordinator while unchanged IDs retain delivery state;
  reload fences disabled/removed records and preserves a pending maintenance pause. Verified full IDs never merge by short ID.
- Displays exposes mode/Apply, transport, owner/reason, last ACK/result and Pause/Resume. Disabled records remain visible.
  Generic tray aggregation counts healthy USB, excludes disabled peers, and names maintenance/owned-elsewhere states.
  Source self-test constructs and checks these controls without invoking them. Destroyed dialogs cancel their callbacks.

### Maintenance and tool boundaries

Maintenance is a persisted per-device pause, with a private token and retained endpoint/boot information. It never
expires locally. Pause is saved before quiescence or handle release. Own USB transitions to `maint` with the same token
under the app-send lock; other verified USB sessions obtain device-side maintenance after fencing the local worker.
Dedicated port and PnP-instance suppression survives worker cleanup and app restart. Pausing drains an already-running
probe; probes recheck suppression after awaits, and cancelling a child probe does not kill discovery for other devices.

A successful updated-firmware acquire reports `quiescence: device_maintenance` only after the lease is acknowledged and
serial closes. Failure retains the pause and reports recovery. Manual Pause without USB is explicitly local-only and
not tool-ready. Positively identified older firmware reports `unsupported_legacy`: local delivery is paused, but an old
firmware/companion on another PC has no new quiescence or ownership UI guarantee. Malformed updated identity, timeout,
busy, incompatible updated firmware or wrong full ID never downgrade to this legacy path.

Resume/release verifies exclusive access and freshly locates the full ID, including a changed COM number or a rollback
to legacy firmware. Busy/absent/ambiguous/wrong-ID endpoints retain the pause. Updated firmware gets matching-token
`maint_end`; legacy firmware never receives CM1. Tool completion requires its token; manual Resume is explicit recovery
only after the tool closes. A crashed tool or expired device lease never automatically resumes local probes/delivery.

`tools/maintenance.py` supplies shared acquire/release and try/finally guards to screenshot, C6 screenshot and log tools.
It resolves BLE-active registered devices by safe USB identity before requesting a persistent daemon pause. A running
older daemon that lacks maintenance fails actionably instead of being bypassed. It does not start a daemon. Follow-log
mode renews on its existing exclusive handle with a new correlated q for each renewal. Flash scripts retain their
identity/chip/backup checks and release in finally. `flash-windows.ps1` prepares its build before starting the finite
120-second firmware lease, with D: headroom/env checks. Release has three bounded cold-query retries; it never retries
flashing. First-flash/no-running-firmware cannot obtain firmware quiescence: exclusive serial access remains the device
boundary. A failed post-flash release leaves an explicit pause for recovery. No flasher process is killed or port stolen.

### Verification and remaining gates

All active test/cache/temp output used D:/build/CodexMeter via `scripts/windows-env.ps1`; retained evidence is
`dist/windows/validation/usb-2026-11-18/phase4`. Intermediate full runs passed 309 then 321 then 325 tests as coverage grew.
New deterministic tests cover promotion/fallback ordering, mode races, busy backoff, stable identity timing, paused
probe cancellation and service survival, two independent records, durable pause before quiescence, failure retention,
restart/token checks, busy/moved COM Resume, rollback-to-legacy Resume, concurrent adoption/mode/pause persistence,
full-ID collision isolation, USB-only failure/recovery exclusion, fresh lock policy/timeout, tool identity routing,
legacy limits, no direct bypass of an older daemon, unique renewal q and try/finally release.

`source-self-test.json` passed with `compiled:false`, new mode/maintenance/status checks, GUI child command, DPAPI and
native tray diagnostics. A first run exposed a stale Tk callback after dialog destruction; it was corrected and the
clean second run passed without that error. This is source-runtime evidence, not an exact standalone artifact pass.
PowerShell parser checks passed for both flashing consumers; `git diff --check` passed. Final suite count follows.

Firmware remains the accepted normal `3.12.3.0-usb.4` from Phase 2. No firmware or package version changed in Phase 4.
The exact standalone candidate version/build is intentionally chosen once in Phase 5, then retained unchanged through
validation/documentation. The original installed legacy executable was not replaced by this source implementation.
Physical C6/Ball switching, ten powered cycles per board, actual no-Bluetooth-PC/cross-PC acceptance and exact packaged
self-test remain Phase 5. Physical sleep/resume is excluded. Optional endurance was not run and does not block.
Legacy behavior and powered alert-ledger/reboot replay limitations from previous phases remain in force.

Final Phase 4 retained suite: **330 passed in 26.69 s** (`phase4/pytest.xml`). Root independently passed 326 tests in
22.85 s before the final review fixes, then 23 affected coordinator/registry tests in 0.78 s after them. The final fixes
use dataclasses.replace for offline rename/enable/disable so persisted maintenance survives every registry mutation,
and reject mismatched adoption event/config IDs. `source-manifest.json` records the final Phase 4 source hashes;
`git-status.txt` includes all preserved prior-phase dirty work. Final diff whitespace and both PowerShell parser checks
passed. Root accepted Phase 4 source/tests; exact packaged and physical gates remain Phase 5 as stated above.

## Phase 5 candidate and physical validation — in progress (2026-11-18)

Desktop candidate is frozen at **3.12.3.2** after read-only inspection of the latest public Windows 3.12.3.1 release.
No installation, startup-target replacement, commit or publication occurred. The exact executable is retained at
`dist/windows/validation/usb-2026-11-18/phase5/candidate/CodexMeter.exe`, 17,337,344 bytes, SHA-256
`cd6cfd355d240d1db0b7a41b2b43ad7bd96148b314e0776d9703f16cc3389c13`.
Package self-test passed with `compiled:true`, isolated child-only USERPROFILE, sanitized Python environment and an
outside-repository working directory. Native tray, GUI subprocess, pricing/update, DPAPI and mode/maintenance checks
passed. Compilation report confirms USB/coordinator/serial modules are compiled/included. Source manifest and build
logs are retained under ignored `phase5`; active build/cache/compiler temporary output stayed on D:.

The first actual-board run exposed a firmware capture regression: entering same-host maintenance unconditionally
cleared telemetry freshness and displayed WAITING. Screenshot-file creation was successful but these pixels were
**not a data-display pass**. Preserve this initial evidence under `phase5/package-physical`. Connection checks in this
first harness accepted any existing ACK; its twenty explicit powered mode cycles are exploratory, not final latency
acceptance. They are not physical cable unplug tests or Auto failure tests. The original companion was restarted and
both devices acknowledged again. Initial physical settings were restored and read back before firmware updates.

Owning Phase 2 fix: firmware **3.12.3.0-usb.5** preserves the existing visible telemetry and original receive timestamp
only on a same-host live USB/BLE application-owner to Maintenance transition. It accepts no application data and does
not refresh freshness. The normal 300-second stale threshold still applies; maintenance end/expiry and cross-host
changes retain the previous clearing/waiting behaviour. This clarifies that short same-host diagnostic maintenance
can preserve an already-fresh frame, without fabricating a healthy application sample. Root independently reviewed
and passed the exact shared native helper/lease-expiry regression. Full suite after this fix: **330 passed in 25.85 s**.

Both usb.5 normal targets built successfully. C6 application SHA-256
`8a270ad09e15c15cc5ca160babc7850f3e034d7539a45aad6b1ad949a503b966` (2,468,672 bytes); Ball
`f4cb7c35529f97f702f5bbaf92420aea61d56ce4b9fd90fe748f24262d404bdc` (1,214,512 bytes).
`candidate-manifest-usb5.json` freezes these artifacts and source hashes. App-only flashing uses the existing identity,
chip and private rollback-hash checked path; it preserves NVS/artwork. Flash resets are separate from powered cycles.

The strengthened fixture requires fresh telemetry ACKs after transitions, keeps session tokens private, reads back
physical controls and restores the initial physical settings. Cost-page captures use known b0/b7 values delivered
through the exact companion; local page swipes are performed only under maintenance. Successful image creation and
independent pixel validation are recorded separately. A separate source fixture interrupts only its own real serial
data boundary while retaining board power and actual BLE/USB firmware ACKs. This is supporting Auto loss evidence,
not an exact-executable physical cable test. No production fault hooks or driver changes are introduced.

Actual no-Bluetooth-hardware PC and cross-PC takeover remain required, pending access. Physical sleep/resume is
excluded and unverified; optional 30-minute endurance is not run. Phase 5 is not complete and no release readiness
claim is made. Further results and restoration evidence follow below when the corrected physical matrix completes.

### Phase 5 local result (2026-11-18; second-PC/physical gates remain open)

Final suite: **334 passed in 26.91 s** (`phase5/pytest-final.xml`); native firmware core/protocol tests passed.
The exact desktop artifact remains unchanged at the SHA-256 above. Firmware usb.5 and its retained E: copies match
`phase5/candidate/manifest.json` and `SHA256SUMS.txt`. The candidate folder includes the executable, two public-safe
app-only firmware images and `SECOND-PC-CHECKLIST.md`. No private backup/legacy image is included.

| Local case | Observed result / evidence |
| --- | --- |
| Fresh exact-package USB scan/adopt, both full IDs | Pass; `package-physical-usb5/package-results.json` |
| USB/USB, BLE/BLE, USB/BLE, BLE/USB | Pass with new-session fresh usage/activity ACK checks |
| Brightness/rotation controls | Both physically read back at 80%/90 degrees after reclaim; restored afterwards |
| Usage and completion pixels | Both actual boards verified independently by root, exact compiled IPC-to-wire path |
| Token/cost pixels | C6 Today 18.6M/$6; Ball Today and 7-day 236M/$60; b0/b7 sent via exact compiled daemon IPC |
| Task-count pixels | Exact compiled path 0/0/1 from isolated synthetic metadata; source real manager 2/3/4, both verified |
| Ten powered mode handovers per board | 20/20 pass; maximum BLE 14.938 s, USB 5.000 s; boots fixed throughout |
| One enabled board, USB-only startup | Both pass; no Bluetooth prerequisite |
| Manual off across BLE/USB and subsequent explicit on | Both pass with physical state readback |
| Real external exclusive COM holder | Both Auto BLE fallback and subsequent USB recovery pass; holder not terminated |
| Real serial-boundary Auto loss (source fixture) | Both pass, metrics below; no fabricated identity or ACK |
| Old C6 firmware compatibility | Exact package Auto BLE, forced BLE, USB-only no fallback and upgrade notice all pass |
| Package process restart and persisted modes | Pass |
| Physical settings cleanup | First C6 page mismatch found; separate corrected full readback passed for both |
| Final live state | Original 3.12.3.1 executable restored; 2/2 acknowledged, production startup target/config untouched |

The powered cycles above are **explicit mode handovers**, not cable-removal or Auto failure timing. Root independently
aggregated 20 cycles, zero failures and stable physical page/settings/boot evidence. The separate source fixture uses
actual boards and actual USB/BLE ACKs while interrupting only its own serial data boundary. C6 failure detection was
2.438 s and BLE acknowledgement 5.343 s after detection; Ball 2.078 s and 5.360 s. USB ACK after boundary restoration
was 5.047/4.765 s, measured from boundary restoration rather than first claimable discovery. Peer ACK ages were
0.1/0.2 s; both boots and settings were preserved. This supports Auto recovery but is not exact-executable physical
cable-loss R20 acceptance. `source-auto-failure.json` retains these distinctions.

The task fixture distinction matters: Windows intentionally replaces demo-activity counts with the live chat observer.
A fresh empty home reports unavailable counts (`--`). The exact executable was subsequently tested using synthetic
metadata only, yielding available Running 0 / Waiting 0 / Done 1. Independently, the source manager supplied known
2/3/4 over actual transports. No transcript text or production injection hook was used. Root viewed both pairs of
actual framebuffer captures. Cost b0/b7 payloads went through the compiled event server/manager; source tools only
sent authenticated IPC and captured maintenance framebuffers. The USB header icon indicates power, not transport.

C6 has overview/detail navigation with Today/Week tabs; an initial three-swipe capture fixture left page 1 instead of
baseline page 0. This was a fixture cleanup failure, retained honestly in the main run. The capture/restore tools now
use model-specific navigation. `settings-repair/package-results.json` verifies C6 page 0, brightness 70, rotation 0,
auto-rotation true, manual on; Ball page 0, brightness 60, rotation 0, auto-rotation false, manual on. Both same-boot
readbacks passed. After the later legacy app-only rollback/usb.5 restoration, physical settings again matched this
baseline; the expected C6 flash reboot has a new boot ID and is not counted as a powered handover.

The successful legacy rollback exposed a separate Phase 4 direct-tool cleanup warning: an updated maintenance lease
was ended using CM1 after legacy firmware had rebooted in. Firmware writes and all compatibility checks succeeded.
`tools/maintenance.py` now freshly verifies the full identity before direct release and sends no CM1 to positively
identified legacy firmware. Wrong IDs/malformed updated identities fail safely. Eleven focused tests passed (root
independently 11 passed); final full suite passed. This tool-only correction was not physically repeated, as accepted
by root after the actual legacy identity path and compatibility run; no desktop/firmware rebuild was necessary.

Pending actual observations: no-Bluetooth-hardware Windows PC, cross-PC ownership/settings/alerts, exact-executable
Auto physical data interruption and discovery-based R20 timing, changed COM/hub, physical power-only/wall charger,
and cable removal that reboots the display (distinct from verified flashing reboots). Disabled/absent adapter fault
paths have deterministic coverage; a physical disabled-adapter case was not run. Working-set/private-byte memory
trend was not measured. Physical sleep/resume remains excluded and unverified; optional 30-minute endurance was not
run. Existing native/deterministic framing, stale reply/session/expiry/deduplication and maintenance coverage remains
supporting evidence, not a substitute for these physical gates.

No lingering fixture daemon or maintenance pause remains. Final original executable process pair is parent 25224 /
child 24992, original file version 3.12.3.1; exact candidate version is 3.12.3.2. `final-original-status.json` records
2/2 connected with application ACK age 5.3 s. The original companion does not consistently expose new firmware
metadata, so C6 firmware verification uses the preceding exact candidate USB identity/readback, not its legacy status.
No commit, push, publication, production executable replacement or Phase 6 completion claim was made. Phase 5 remains
in progress pending the real second PC and remaining physical evidence; fix forward is the current path. Replan,
restart and supersede remain alternatives if the user chooses to change scope.

## Live task-count fix: 18 November 2026

User-reported missing real-profile counts were traced to Codex chat stream version 13 being rejected by the
version-11-only observer. Metadata projection was verified against the live stream before explicitly enabling
versions 11 and 13; unknown/malformed versions remain rejected, with sanitized availability-reason diagnostics.

Version 3.12.3.3 is installed at the existing startup path and left running. Full regression: 344 passed;
root independent focused tests: 16 passed. Exact compiled self-test passed outside the source checkout. Root
independently verified installed version/hash, both actual dashboard captures (2/0/8 at capture time), and both
USB connections with fresh ACKs, no errors and maintenance released. Firmware stays usb.5 unchanged.

Second-PC candidate/checklist/manifest/checksums now refer to 3.12.3.3. Prior 3.12.3.2 transport evidence and artifacts
remain retained and are not relabelled as having tested this executable. The targeted change was revalidated through
packaging and real-profile delivery; transport code did not change. Evidence and rollback copies are under
 dist/windows/validation/usb-2026-11-18/phase5/live-counts-fix (ignored, private settings excluded from public assets).
Registry normalization added connection-mode defaults and discovered firmware/protocol metadata while preserving
existing configuration values. No firmware flash, commit or publication occurred in this correction.

The user will execute second-machine acceptance themselves. Those results and the previously listed physical
acceptance observations remain pending; Phase 5 and Phase 6 are not declared complete.
