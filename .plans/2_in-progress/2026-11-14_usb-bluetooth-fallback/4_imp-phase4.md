# Phase 4: automatic selection, maintenance and user-visible status

Depends on phase 3. Covers R2, R6, R8-R13, R16 and R17.

## Work

- Implement per-device states: disconnected, probing, USB active, BLE active, switching and maintenance.
  The phase 1 contract owns timeout values; keep them configurable internally and deterministic under test.
- In Auto mode, probe USB without disrupting working BLE, then fence the old sender, claim USB and reconcile
  current state according to R8. USB-only and Bluetooth-only modes never start a disallowed transport.
  On USB failure, invalidate callbacks/session; in Auto mode attempt BLE if available and retry USB with backoff.
  In USB-only mode retry USB only. In Bluetooth-only mode retry BLE only.
  On a no-adapter PC, stay disconnected/retrying USB without pairing prompts or radio-reset attempts.
- Preserve current data/control intent and pending alert IDs at uncertain-delivery boundaries. Promote stable USB
  only once; do not launch a second application sender or duplicate registrations during discovery races.
- Update Displays, tray aggregation, IPC status and local logs with transport/health/fallback information.
  Distinguish unavailable Bluetooth from a failed active connection; retain usable legacy status where required.
- Add explicit per-device pause/release for maintenance tools and resume. Integrate existing flash/screenshot tools
  with ownership release; flashing suppresses all delivery, screenshots use their defined exclusive serial session.
  A timeout or tool failure must leave a clear recoverable state, never steal a port from an active tool.
- Scope Bluetooth recovery to relevant BLE failures; a USB-connected or maintenance-paused device is not a BLE fault.

## Verification and exit

Test USB promotion/failure/return, simultaneous endpoint discovery, stale callbacks, lost ACKs, duplicate alerts,
unavailable BLE, two independent devices, busy ports and maintenance acquire/release/crash cases. Verify UI status
from test data and the packaged self-test. No new automatic app restart or installer behaviour is introduced.

## Maintenance lifecycle

Distinguish explicit maintenance pause from an accidentally busy port: maintenance suppresses both senders, while a
busy port can use BLE only in Auto mode. Define manual resume and tool-owned completion/failure handling, including companion restart.
Do not automatically expire a maintenance pause into a serial probe while a flasher could still be running.
Unrelated displays remain active. Provide status and a recovery action if a tool exits without releasing its pause.

## Confirmed connection controls

Expose Auto / USB only / Bluetooth only per device, persisted on this PC. Apply changes without restarting the app,
using the same fenced handover path. Cancel disallowed candidates and do not silently override a forced setting.
Cover mixed settings across devices, new USB-only registration, reload/restart and an unavailable forced transport.
USB takeover across PCs is supported: updated companions show the non-owner as in use elsewhere and suppress retries/radio
recovery, and permit BLE ownership again when the USB owner releases or expires. Reconcile each PC's current snapshot.

## Cross-PC maintenance and compatibility

A local maintenance pause alone cannot silence a companion on another PC. Specify device-side maintenance ownership
for running-firmware diagnostic operations so a released USB port does not permit BLE writes during a screenshot.
For flashing, coordinate local discovery suppression, device quiescence and reboot boundaries; document limitations
when the firmware is not running. Do not promise that a legacy companion understands busy/maintenance state.
Test updated companions separately from legacy-client compatibility; retain legacy BLE data/control functionality
when no USB/maintenance owner exists, without claiming new ownership UI or recovery behaviour in old executables.


For takeover and reconnect, reconcile physical settings with R8 before replaying controls. Never overwrite the
current display with another PC's cached brightness, rotation or power setting. Preserve page and manual power
intent; apply explicit new actions and live lock/unlock policy with the defined power-origin precedence.


## Ordered implementation tasks for Sol

1. Implement a deterministic per-device coordinator with explicit states: disconnected, probing, USB active,
   BLE active, switching, owned elsewhere and maintenance. Inject clock and retry scheduler; no UI-owned timers.
2. In Auto, validate candidate USB identity/capability and stability while BLE remains usable. Stop dequeuing new
   application messages, bound any in-flight send, invalidate old callback generation, claim USB and reconcile state.
   Resume the single delivery loop only after ownership confirmation. If a claim fails, retain/restore a permitted
   healthy path; do not mark USB active just because Serial.open succeeded.
3. On USB loss, close handle, resolve uncertain deliveries, and select BLE only if Auto permits and a verified BLE
   endpoint exists. On USB-only, retry USB with capped backoff. On Bluetooth-only, do not claim USB. Recheck mode
   after every awaited discovery/connect result so a late completion cannot violate a newer user setting.
4. Handle owner-busy distinctly from connection failure. Updated BLE hosts may monitor owner state at a bounded rate,
   but do not enqueue writes/recover the radio while another PC owns USB. When the owner releases/expires, replay
   the returning PC's current telemetry, not a queue of old snapshots or expired completion notifications.
5. Implement R8 state reconciliation for both same-host and cross-host transitions. Use firmware state/revision;
   physical current settings win over stale saved values. Manual-off and host-policy-off remain distinct. Do not
   apply a synthetic reconnect screen-on before learning current power origin. New explicit user controls still work.
6. Add connection-mode IPC/CLI operations with ID/value validation and atomic registry persistence. Apply mode changes
   live; retain disabled status and aliases. Extend device_dialog.show_devices with mode selector and Apply action,
   transport/owner/status/last-ACK columns and maintenance Pause/Resume. Handle failure without falsely showing saved.
7. Update windows_tray and windows_app connectivity aggregation using generic device status. Missing optional BLE is
   not an app warning while USB is healthy. Log transition/reason/latency once; avoid per-poll spam and raw payloads.
8. Decouple BluetoothRecovery from USB state and generic failure counters. Feed it only genuine eligible BLE health
   evidence; ignore owned-elsewhere, forced USB, maintenance and missing/disabled adapter. Add regression tests for
   a mixed setup where one USB device is healthy and a separate BLE device genuinely fails.
9. Define maintenance IPC acquire/release with a token and full device ID. Pause delivery/probing locally, obtain
   device-side quiescence where firmware is running, then close serial and acknowledge release to the tool.
   Update flash-windows.ps1 and screenshot/log tools to use try/finally release and preserve their existing identity
   checks. Do not launch a daemon if none is running merely to request maintenance; safely use direct tooling then.
10. Persist manual maintenance state across app restart; show Resume explicitly. For tool-owned operations verify
    completion/token before resuming, never a timer that can interrupt flashing. If the tool crashes, show a clear
    stale-maintenance state with manual recovery; do not kill or steal another process's serial handle.
11. Run the full deterministic matrix, then the full regression suite. Freeze behaviour and candidate versions for
    phase 5; leave production flashing/publication to the authorized validation/deployment scope.

### Deterministic test schedule

| Test | Controlled events | Assertions |
| --- | --- | --- |
| Auto promotion | BLE ACK; USB detected; handshake; stable interval | One active sender; no duplicate device/alert |
| USB loss | USB ACK lost; timeout; BLE available | Unknown delivery retained; same alert ID retry; bounded fallback |
| Cable flaps | Repeated USB appear/disappear | Capped retries; healthy BLE continues; no rapid owner oscillation |
| Mode race | Switch mode during USB probe/connect | Late result discarded; selected mode persisted and obeyed |
| Cross-PC claim | A BLE active; B USB claim; A writes | A rejected without mutation; B data only; A busy, no recovery |
| Owner release | B release/crash/lease expiry | A eligible again; fresh snapshot; stale work remains fenced |
| Settings | B cached values differ; device manually off | No flash/reset; page/settings preserved; explicit control works |
| Maintenance | Acquire; tool opens port; app restart | No probe/write race; unrelated display remains active |
| Missing BLE | No adapter, USB loses/reappears | Waiting then USB reconnect; no pairing/radio-reset loop |
| Recovery isolation | Real BLE failure plus healthy USB peer | USB health correct; recovery eligibility specific to BLE |

### Exit checklist

- [ ] Tests prove ownership, retry/cancellation and settings precedence across same-PC and cross-PC transitions.
- [ ] Mode, status and maintenance controls function without a source-only dependency.
- [ ] Flash/screenshot/log tools release/reacquire safely, including tool failure and app restart.
- [ ] Legacy client behaviour is documented accurately; only updated clients get the new busy/recovery guarantees.
