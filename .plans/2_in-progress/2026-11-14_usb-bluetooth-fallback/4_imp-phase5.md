# Phase 5: packaged and physical validation

Depends on phase 4. Covers R14-R20 and the functional requirements end to end.

## Candidate preparation

Build the Windows onefile and both firmware candidates before running this matrix, with explicit D: output/cache/temp
paths and E: retained evidence. Record source revision, version and hashes. Test these exact artifacts; any later
source or packaging change requires proportionate retesting and fresh recorded hashes.

## Matrix

- Fresh Windows configuration on a PC with no Bluetooth hardware: both devices discovered/registered over USB,
  telemetry, task counts, costs, completion alerts, supported controls, startup/restart and unplug/reconnect.
- Current PC: both USB; both BLE; C6 USB/Ball BLE; C6 BLE/Ball USB. Repeat using only one device.
- Old firmware BLE compatibility, unsupported USB capability/version, duplicate names and changing COM numbers.
- Cable removal with device power retained; cable removal causing reboot tested separately. Wall-charger or
  power-only cable uses BLE if available and permitted by the configured mode, otherwise waiting; it must not
  be labelled USB data connected.
- Busy port, absent Bluetooth, disabled adapter, stalled USB/ACK timeout, app quit/restart and device restart.
- Maintenance screenshot and flashing ownership without the companion reacquiring the port mid-operation.
- At least ten powered handover cycles per board. The 30-minute mixed run is optional and non-blocking;
  record the outcome if performed, otherwise mark it not run.
- No physical sleep/resume testing: explicitly excluded by the user on 2026-11-16. Record it as unverified,
  not a failed release gate; retain simulated suspend/resume and elapsed-time/session-expiry tests.


## Evidence

Run regression and packaged self-tests from the standalone executable without external Python/source dependencies.
Record per-device transition timestamps, latest ACK, duplicates/dropped alerts, control/page preservation and peer
responsiveness. Measure R20 targets. Verify no unexpected reset, UI hang, escalating memory or recovery loop.
Keep logs/captures local under ignored dist/windows/validation; omit chat content and secrets from reports.

The user confirmed a machine without Bluetooth is available. Arrange access at validation;
a fake backend or disabled adapter is supporting evidence only. Stop and report any release-blocking failures rather
than weakening requirements silently. Ask for physical user actions only when needed, then await the answer.


Test all three persisted connection modes, including changes while connected, missing forced transports and restart.
Test PC A sending via BLE while PC B claims USB, then USB loss/lease expiry and BLE restoration. Confirm that only the
current owner's telemetry and alerts are accepted, page/local settings survive and ownership contention causes no
Bluetooth recovery cycle. Use independent test identities/data so the active source can be established from evidence.


If retaining power during unplug is not possible, record that limitation. A USB data-path interruption with power
retained can exercise transport handover; do not label reboot/reconnect tests as powered handover tests.
Legacy companion tests verify firmware rejection during USB ownership and restored BLE functionality afterwards;
they do not assert updated ownership status or radio-recovery suppression in old companion executables.


Cross-PC settings test: give PC B saved settings that differ from the physical display. Verify takeover changes
telemetry but not page/brightness/rotation/manual power. Repeat with manual-off and host-policy-off separately;
verify subsequent explicit controls and lock/unlock policy, then test returning ownership to PC A. Exercise a local
setting change during disconnect to ensure same-companion replay cannot restore stale cached values.


## Ordered execution checklist for Sol

1. Verify current source/tests and D: capacity. Build both firmware targets and Windows onefile; create an ignored
   candidate manifest with source revision, dirty-tree status, versions, board targets, byte counts and SHA-256 hashes.
   Use unique evidence folders; do not overwrite baseline rollback binaries or prior observations.
2. Run packaged --self-test with external Python paths removed. Verify included USB modules, serial enumeration and
   mode/status/maintenance UI construction. Preserve existing tray/pricing/updates self-tests. Launch from a directory
   outside the repository to expose accidental source imports or relative-path dependencies.
3. Record fresh physical device identity before each authorized flash. Use the existing identity-checked upload path
   with the correct target, not a generic S3 image. Verify application settings and C6 artwork after flashing.
4. Install the candidate at the existing local startup target only when authorized; retain rollback and record which
   process/entrypoint is running. Do not confuse the onefile parent/child pair with duplicate companion instances.
5. Establish one-board USB-only baseline for C6, then Ball: identify/register, display current usage/tasks/cost data,
   trigger a controlled completion fixture, exercise each supported control and verify real ACKs. No BLE connection.
6. Test both devices simultaneously with distinct aliases under USB/USB, BLE/BLE, USB/BLE and BLE/USB. Use synthetic
   known snapshots for comparison where needed, then restore live telemetry. Do not claim pixels were verified solely
   from a connection flag; use framebuffer captures or explicit physical observations under maintenance ownership.
7. Execute ten powered USB-to-BLE-to-USB cycles per board. Record initial/final owner and timestamps for each failure
   detection, first ACK and USB promotion. Keep the other display active and record its freshness during each cycle.
   Use data-path interruption without cutting power if possible; otherwise request appropriate hardware and record
   the missing powered test rather than substituting a reboot.
8. Test all modes, port contention, mode changes mid-connect, process restart, changed COM port/hub, malformed reply,
   stale ACK and owner expiry. Fault injection must be isolated in fixtures/adapters, never silently left in production.
9. Prepare the no-Bluetooth-PC handoff: executable hash, both firmware versions, data-cable requirement and short
   USB-only registration/control checklist. Obtain access/instructions from the user when needed and stop for answers.
   Run with a fresh test config without deleting the user's settings. Confirm adapter absence, no external Python,
   successful first registration and both displays' data/controls/alerts/reconnect. Record actual evidence or a user
   report as such; do not describe remote/user-reported checks as personally observed tool results.
10. Use the second PC for the cross-PC test: A sends over BLE; B claims USB; A becomes owned-elsewhere; B releases;
    A resumes. Check different saved settings and manual-off exactly as in R8. No user transcripts in fixture logs.
11. Do NOT put the PC to sleep or wake it for this feature. Run fake-clock expiry/resume tests only. The 30-minute
    mixed run is optional; if skipped, mark not run and proceed without calling it a failed gate.
12. Restore live telemetry and normal mode settings after fixtures. Summarize pass/fail/pending with artifact hashes.
    Investigate any required failure, fix in its owning phase and retest impacted matrix rows before release readiness.

### Result record schema

For each case retain: case ID, requirement IDs, source/build hashes, device full IDs/models, host/config/mode,
precondition, action, expected result, observed result, monotonic elapsed times, pass/fail/not-run, evidence path.
Do not log auth tokens, chat content, raw user config or unrelated Windows information. Use test aliases in reports.

### Exit checklist

- [x] Full suite and packaged self-test pass for the exact candidate binaries.
- [x] Both physical boards pass USB-only and mixed transport/control/alert tests.
- [ ] Ten powered cycles per board meet R20; no false successes based only on port presence.
- [ ] Real no-adapter PC acceptance and cross-PC takeover are recorded.
- [x] No physical sleep test performed; optional endurance outcome is accurately labelled.
- [x] No lingering fixture mode/maintenance pause; live app works; rollback artifacts remain available.


### Local execution status, 2026-11-18

Exact desktop 3.12.3.2 and firmware 3.12.3.0-usb.5 retained under ignored
`dist/windows/validation/usb-2026-11-18/phase5/candidate`; manifests and post-implementation notes hold hashes/provenance.
334 tests and the compiled standalone self-test pass. Root independently inspected real usage/cost/alert/task frames.
Twenty powered explicit-mode handovers pass (ten per board); these are not exact-executable Auto cable-loss tests.
The R20 checkbox therefore remains open: source actual-serial data-boundary Auto recovery supports the targets,
but actual executable physical-interruption/discovery timing and second-PC evidence remain pending.

The original executable/startup target and physical settings were restored; no fixture daemon/pause remains.
See `5_post-implementation-notes.md`, `phase5/local-summary.json` and the candidate's `SECOND-PC-CHECKLIST.md` for the
specific pending physical cases and the no-adapter/cross-PC handoff. Phase 5 is not complete; no Phase 6 claim is made.
