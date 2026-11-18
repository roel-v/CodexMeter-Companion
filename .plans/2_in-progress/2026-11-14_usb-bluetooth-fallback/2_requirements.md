# Requirements

Status: proposed implementation baseline. Requirements describe the requested behaviour; hardware acceptance is pending.

## Selection and identity

R1. One companion supports both verified display models, multiple units and independent transport selection.
R2. USB-only operation on a PC with no Bluetooth hardware is a primary supported configuration. Startup, USB
    discovery, explicit registration, identity/capability checks, telemetry and all supported controls/alerts must
    work without BLE discovery or a Bluetooth-derived address. Bluetooth initialization must not be a prerequisite.
    Default to automatic selection: prefer a responsive, compatible USB session; otherwise use Bluetooth if available.
    Offer a persisted per-device, per-PC setting: Auto (USB preferred), USB only or Bluetooth only; default Auto.
    Forced modes never fall back to the other transport. USB-only devices do not initiate Bluetooth discovery or
    connections; Bluetooth-only devices do not claim USB sessions. Other devices retain their independent modes.
    Connecting a cable or enumerating a COM port alone does not qualify USB as healthy.
R3. Identify a display by its full stable CodexMeter ID across transports. Preserve registrations, aliases and
    per-device settings when ports, USB hubs or connection type change. Never merge devices by name or model.
R4. Probe only suitable USB candidates, confirm application identity and advertised capability, and send application
    data only to registered devices. Do not open unrelated COM or Bluetooth virtual serial ports indiscriminately.
    An unregistered device may be offered for explicit registration; USB attachment must not register it silently.
R5. Older firmware without USB transport capability remains on BLE in Auto/Bluetooth-only mode.
    USB-only mode reports that a firmware upgrade is needed and does not silently use Bluetooth.
    Unsupported versions or mismatched identities
    are reported per device without affecting healthy peers. Existing BLE operation remains backward compatible.

## Delivery and switching

R6. Have at most one application-data sender per physical display. A candidate connection may be validated while
    the current transport remains active; only the selected session may apply application messages.
    A registered companion on PC B in Auto/USB-only mode takes priority over a BLE sender on PC A when it claims
    a healthy USB session. PC A may resume after USB is released or its lease expires. The updated non-owning companion
    reports the display as in use elsewhere, not a radio fault. Physical USB attachment without a session does
    not take ownership. Each owner supplies its own PC telemetry; this feature does not aggregate across PCs.
    Firmware must reject legacy BLE application writes during USB ownership. Older companion status/recovery
    behaviour cannot be changed by new firmware and is not covered by the in-use-elsewhere guarantee.
R7. Require acknowledgements of accepted application messages on their originating transport/session. Late, unrelated
    or diagnostic messages must not satisfy a pending USB delivery. Reject invalid/oversized frames without applying them.
    Legacy BLE retains its existing uncorrelated ACK format and delivery guarantees; do not claim session/message
    correlation for old firmware. New USB guarantees must not require breaking legacy BLE compatibility.
R8. On a same-companion transport change, restore current usage/tasks and pending explicit control intent without
    resetting page or overriding newer device-local settings. Preserve pending completion delivery without showing
    a duplicate alert on a powered device; document bounded replay/deduplication and the power-loss limitation.
    On cross-PC takeover, replace telemetry with the new owner's snapshot but preserve the physical page,
    brightness, rotation and manual on/off state. Do not apply the new PC's old saved display settings automatically.
    Subsequent explicit controls and the new owner's live lock/unlock policy apply normally, but takeover alone
    must not wake a manually switched-off display. Track manual power intent separately from host policy power.
R9. Detect a silent USB session as well as physical removal. In Auto mode attempt BLE fallback without restarting the app,
    resetting the device or cycling the Bluetooth radio merely because USB failed. Reconsider recovered USB with
    a stability delay and retry backoff so a bad cable does not cause rapid switching.
R10. A stalled device or serial read must not block the UI, telemetry acquisition, shutdown or other displays.
R11. Display waiting state when no healthy companion session supplies data, regardless of transport. Preserve the
     existing waiting view, manual power policy and completion presentation. USB power alone does not hide waiting.

## Operations and visibility

R12. Treat absent, disabled, inaccessible or unsupported Bluetooth as an unavailable optional transport. Do not
     repeatedly prompt for pairing, report healthy USB devices as failed, or attempt radio recovery on a PC with no
     adapter. If the selected connection is lost and no permitted alternative exists, show disconnected/waiting
     and retry only the transports allowed by the configured mode.
     Show selected transport, connection state, last acknowledgement and meaningful failure/fallback reasons per
     display. Tray aggregation and logs must treat a USB-connected display as connected.
R13. Release serial ownership for existing flashing, screenshot and diagnostic tools. Provide a per-device explicit
     maintenance pause/release mechanism and resume behaviour; do not race a flasher to reacquire its port.
     A busy port causes a clear status and BLE fallback in Auto mode where available, without terminating its owner.
R14. Open/close/reconnect without intentionally resetting boards or entering download mode. Recover after COM number
     changes, app restart, USB hub hotplug and host sleep/resume. If a display loses power, recover after it boots.
R15. Continue using a standalone Windows executable without an external Python installation. Preserve the existing
     macOS BLE path; any shared changes must not introduce unconditional Windows-only imports/dependencies.
     This feature's USB release acceptance is Windows-only; do not claim macOS USB certification.
R16. Retain local diagnostics with bounded logging, including transport transitions and failures, without logging
     secrets or chat text. No new network service, tracking or automatic restart machinery is required.

## Acceptance

R17. Automated tests cover identity/compatibility, stream framing, ACK correlation, session arbitration, replay,
     cancellation, maintenance release, and mixed-device failures. Existing regression tests continue to pass.
R18. Test the actual C6 and Ball together over USB, BLE, and mixed transports. On a Windows PC without Bluetooth
     hardware, test a fresh configuration: launch, discover/register both displays via USB, receive telemetry,
     exercise controls/alerts, unplug/reconnect and restart. A disabled adapter test supplements but does not replace
     this no-adapter acceptance. The user confirmed a suitable PC is available; arrange access at validation. Also test
     USB return, busy/missing ports, app restart, controls, waiting state and alerts across handover.
R19. Run at least ten powered transport-switch cycles per physical board. Record latency and failures.
     Physical sleep/resume tests are explicitly excluded by the user (2026-11-16) and do not block delivery.
     Retain recovery implementation and automated coverage, but document physical sleep/resume as unverified.
     The 30-minute mixed-transport run is optional and non-blocking (user decision, 2026-11-16). Record its result
     if performed, otherwise record it as not run; never claim an endurance pass without evidence.
R20. Proposed measurable targets under a healthy available alternative: detect USB failure within 10 seconds,
     restore acknowledged data over BLE within 30 seconds, and adopt stable USB within 10 seconds of discovery.
     Validate these targets in phase 1/5; revise the plan with measured justification before claiming acceptance.
     Measure failure detection from physical disconnect or the first unanswered heartbeat; measure BLE restoration
     from failure detection to acknowledged current data. Measure USB adoption from discovery of a compatible,
     claimable endpoint to acknowledged current data. Busy/incompatible endpoints are not claimable.
     No latency guarantee applies while the PC sleeps, the display lacks power, or neither link works.
R21. Retain rollback executables/firmware and publish a compatibility table and upgrade instructions. Releases must
     accurately distinguish executed tests from pending tests. Building/publishing occurs only when authorized.
