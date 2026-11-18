# Phase 2: firmware transport support on C6 and Ball

Depends on phase 1 contract. Covers R5-R11, R14 and R17.

## Work

- Introduce explicit message source/session context around handle_json(); route ACK/NACK to that source only.
- Add bounded serial protocol parsing, heartbeat/lease expiry, ownership arbitration and explicit USB capability
  metadata on both models. Preserve existing identity IDs and legacy BLE wire payloads.
- Replace the BLE-specific waiting policy with active-companion freshness. Screen-off must not disable transport.
  Preserve page, rotation, brightness and completion behaviour; handle initial session before first telemetry.
- Reject writes from a non-owning source while another session is active; release stale ownership automatically.
  Discard queued messages from an expired owner. Ensure an abandoned USB session cannot block BLE indefinitely.
- Keep diagnostic commands usable under maintenance ownership, and preserve firmware serial identity tooling.
  Make oversized/incomplete data recoverable without applying a truncated payload or starving rendering/touch.
- Preserve alert IDs/deduplication across a transport switch while powered. Document the power-loss boundary.

## Verification and exit

Run parser/session tests, build both targets on D:, review memory headroom and retain ignored artifacts on E:.
After deployment is authorized, use identity-checked application updates preserving settings/backups. Exercise
USB-only fixtures on each board with no BLE connection, ACK/error paths, stale heartbeat waiting and legacy BLE.
Verify serial-origin messages never create BLE ACKs. Record exact source/build/device identities and results.

Use a bounded development serial fixture implementing the phase 1 contract for this phase's USB-only checks;
the production desktop USB transport does not exist until phase 3. Keep the fixture isolated from the running
companion and retain its input/expected-response cases for later host interoperability tests.

## Ordered implementation tasks for Sol

1. Freeze phase 1 contract/examples. Add framing/session modules under firmware/src with Arduino-independent core
   logic where feasible. Keep fixed capacities and no heap growth on repeated malformed input.
2. Replace handle_serial()'s truncate-and-parse behaviour with incremental bounded framing. A budget per loop limits
   bytes/frames processed so USB floods cannot starve LVGL/touch. Reject overflow as one frame and resynchronize.
3. Change dispatch to carry source/session context. Validate ownership and frame fully before mutating model state.
   A rejected stale/non-owner command must not refresh last_host_payload_ms or hide the waiting view.
4. Split response routing from application handling. USB receives correlated accepted/rejected responses; BLE uses
   its compatible format. ACK only after acceptance/application as specified; unsupported control gets NACK.
5. Implement claim/preemption/release/lease and maintenance states. Check leases every loop, not only when bytes
   arrive. Fence pending BLE queue entries on USB takeover; gate legacy writes at dispatch as well as ingress.
6. Add capability/USB protocol/ownership metadata without changing existing IDs or BLE service UUIDs. Implement the
   BLE busy-status extension agreed in phase 1. Retain non-mutating identity query for tools and discovery.
7. Rework the waiting policy to use current owner's valid data freshness, independent of transport. Track manual
   power intent separately from policy-off. Expose state/revision needed for R8 reconciliation. Do not reset page.
8. Keep serial logs outside protocol reply framing; diagnostic raw binary mode requires maintenance ownership.
   Bound writes/timeouts when the host stops reading. A full USB TX buffer must not freeze rendering or BLE.
9. Update Ball's explicit platformio build_src_filter for every new shared module; verify C6 includes the same logic.
   Build both targets and compare RAM/flash headroom with baseline, especially the non-PSRAM C6.
10. Add an isolated tools/validate_usb_protocol.py fixture runner with explicit port+expected full identity and
    bounded timeout. It must refuse ambiguous devices, avoid resetting boards and output structured pass/fail results.
    This runner precedes the production USB host and must not run alongside an active application owner.

### Tests to implement before physical acceptance

- Split every valid frame at several byte boundaries; coalesce two frames in one read; CRLF/empty line handling.
- Maximum-size UTF-8 payload, one byte over limit, invalid JSON, missing/wrong-type fields, unknown protocol/op.
- Stale session, duplicate message ID, expiry/wrap-safe elapsed time, lost reply/retry without repeated alert.
- BLE writes queued before USB takeover, commands after expiry and maintenance rejection with no state mutation.
- USB payload ACK cannot reach BLE tracker; heartbeat cannot fabricate telemetry freshness.
- Brightness/rotation/page/manual-off preserved across claim; valid later explicit control still works.
- Exercise extracted C++ core via a native test target or existing host C++ test conventions, not Python reimplementation.

### Exit checklist

- [x] Firmware parser/session tests pass; both PlatformIO targets build with recorded memory usage.
- [x] Authorized per-board deployment uses verified full identity and preserves NVS/artwork and rollback files.
- [x] USB-only fixture matrix passes on each physical board; legacy BLE works with USB unowned.
- [x] No serial-origin ACK leaks to BLE; waiting/manual-off and bounded loop/render behavior verified.
  Physical finger-touch was not personally retested and remains a later acceptance observation.
- [x] Contract deviations are reconciled before host development starts (bounded WNR plus matched application ACK).

Coordinating-agent firmware gate accepted 2026-11-18; exact final normal binaries are 3.12.3.0-usb.4.
See 5_post-implementation-notes.md for retained failures, actual MTU23 variant evidence, final production C6
freshness regression, private rollback hashes and restored original companion state.
