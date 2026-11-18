# Independent verification

Current status: phases 1 and 2 accepted. A fresh GPT-6.1 Sol agent is implementing phase 3.
The root reviews each phase and independently verifies results before the next phase starts.
No commits, pushes or publication have been performed for this feature.

## Baseline

- Repository HEAD: a358579882d5c88b953131056383728530e8a1c9; desktop version 3.12.3.1.
- Initial working changes were only the untracked planning documents.
- Existing Python suite: 254 passed in 13.45 seconds before implementation; 254 passed in 13.41 seconds after phase 2.
- Tests used scripts/windows-env.ps1, with pytest cache and temporary files on D:.
- D: initially had 159,739,768,832 bytes free. Capacity was checked again before firmware builds.
- The whole feature directory moved into 2_in-progress. No feature_dependencies.dot exists in this checkout.

## Phase 1: contract and hardware probes

The initial review required four corrections: Ball's full ID byte order, freshness deadlines consistent with the
existing polling cadence, legacy lock/unlock reason mapping, and BLE fragmentation that retains the full application
payload. These corrections are in protocol-contract.md.

Ball was initially absent from USB. After the user connected it on 18 November, both boards passed five identity-only
open/close cycles with DTR/RTS disabled. Unchanged volatile log markers and uptime supported non-resetting continuity.
C6 is codexmeter-00e216f16e20 on COM6; Ball is codexmeter-6867f4697090 on COM9. Hardware-verification.md records details.
Phase 1 was accepted as a contract/probe gate; protocol timings remained subject to implementation measurements.

## Phase 2: independent source and test review

The root returned and rechecked these issues before acceptance:

- Release tombstones and fenced-token reuse after ownership changes.
- Complete JSON parsing, duplicate keys, escaped NULs, field bounds and validation before model mutation.
- Allocator alignment, bounded allocation accounting and prevention of partial successful responses.
- Revision-aware retries, BLE connection/queue fencing and source-specific acknowledgement routing.
- USB receive capacity for a complete frame and bounded transmit handling when the host stops reading.
- Manual power intent versus host policy, including source-specific handling of legacy reason names.

The native harness compiles the actual framing, session, protocol and model sources against pinned ArduinoJson.
The root ran it independently before and after the final power-state correction; all runs passed. Native MSVC output
retains only the existing demo time_t-to-long conversion warnings. git diff --check passed at review checkpoints.

### Rollback preservation

The installed Ball reported 3.12.3.0-usb.1, different from the source baseline. It did not advertise the new USB wire
protocol. Both current full flash images were therefore preserved before application updates. The root independently
verified each 16,777,216-byte image and its SHA-256 hash:

| Board | Private backup | SHA-256 |
| --- | --- | --- |
| C6 | E:/DeviceBackups/Waveshare-C6-206EF116E200/2026-11-18-usb-phase2-before/current-full-16MiB.bin | fa847c9d24c22674005fb11c0e437aebe8086ae53706498ac3a35e61446657b4 |
| Ball | E:/DeviceBackups/Spotpear-Ball-907069f46768/2026-11-18-usb-phase2-before-retry/current-full-16MiB.bin | 9d8a5d789575577c217c541cab0afe7188732981e6b7e3590bcc4f34a53ffa99 |

The first Ball read exceeded its 240-second timeout without producing a full image. A verified bootloader reset
restored the unchanged application, then the retry completed within a rate-informed 600-second bound. No flash write
preceded preservation. Partition tables and OTA selection identified app0 at 0x10000, size 0x300000, on both boards.
Updates wrote only that application partition, preserving NVS, artwork, bootloader and partition tables.
Private backups must never become public release assets.

### Hardware findings and corrections

Intermediate usb.2 builds passed the short USB and handover tests. Ball also passed the five-minute freshness test.
C6 twice lost a serial reply during the longer test, then recovered on a new handle without a reset. Both failed
reports remain in the evidence folder; they are not counted as passes.

Review of pinned Arduino 3.3.8 HWCDC identified a transmit-interrupt servicing path to test. The revised firmware
services it without blocking, resetting or overwriting queued bytes, and exposes diagnostic counters. The final
regression passed; this supports the correction but does not establish the exact cause of every earlier timeout.
Counters for bytes queued to the driver are not evidence of receipt by the host.

An acknowledged-ATT-write train with 15-byte fragments took 5.047 seconds, exceeding the proposed two-second limit.
Sequential awaited writes without response reduced measured queueing time to 0-47 milliseconds; a matching
application acknowledgement remained mandatory. Root approved this measured contract adjustment. The whole-frame
retry, two-second train deadline and seven-second USB lease remain. OS queue acceptance is not delivery success.

### Accepted results

Evidence root: dist/windows/validation/usb-2026-11-18/phase2.

- Both final normal boards passed 18 USB, maintenance and backpressure cases.
- Separate, clearly marked MTU-23 test builds passed 183 cases per board, with actual negotiated MTU 23 and a full
  512-byte application payload. Both entered waiting after approximately 303 seconds without telemetry while
  heartbeats continued. Root independently inspected both reports.
- The exact final normal C6 usb.4 image passed 183 cases at MTU 256, including the previously failing extended test:
  148 healthy pings, waiting after 303,954 milliseconds, zero transmit abandons and zero ring-wait loops.
- The final normal Ball usb.4 image passed 32 affected handover and power-state cases. Its earlier normal and MTU-23
  builds had passed the extended freshness test; the final change was source-specific power classification.
- Five warm identity opens per final board preserved boot identity.
- Root viewed the captured waiting screens: C6 480x480 and Ball 240x240, with the expected layouts. This is framebuffer
  evidence, not a claim that a physical finger swipe was retested.

| Final normal firmware | SHA-256 |
| --- | --- |
| C6 3.12.3.0-usb.4 | 53e635b9e58610b0e7be7429dfcc4e78d040d8bd7a29103229aba3656bb58205 |
| Ball 3.12.3.0-usb.4 | 9909a4e057d069e6cc5d05dcee466b1da55a79d67b662e2c4b1dc43b8975985d |

No MTU-23 test image remains installed. USB and maintenance leases were released and fixture BLE clients disconnected.
The original companion was restored: parent PID 79464 and child PID 73364 remained running when root inspected them.
The retained IPC report showed two configured and connected displays, no device errors and recent acknowledgements.

## Remaining gates

1. Phase 3 accepted; see independent review below.
2. Phase 4 accepted at source/test level; see independent review below.
3. Phase 5: exact standalone artifacts, mixed-display tests, ten powered cycles per board, the actual no-Bluetooth PC
   and cross-PC takeover. Distinguish physical observations from simulated and user-reported evidence.
4. Phase 6: accurate documentation, compatibility and rollback guidance, tested artifact hashes and release readiness.

Physical sleep/resume is excluded by the user. The optional 30-minute endurance test has not run and does not block.
Cold first identity probes immediately after flashing sometimes timed out; later probes succeeded without resetting.
Desktop discovery must handle that with bounded retries rather than permanently classifying the device as incompatible.

## Phase 3 independent verification (18 November 2026)

Root reviewed discovery filtering, full-ID validation, protocol/state parsing, native-operation bounds,
ACK correlation, session shutdown, delivery freshness and first-run host identity creation. Review findings
were corrected before acceptance: repeated hung calls are single-flight, old replay cannot refresh telemetry,
first missed USB discovery retries without Bluetooth, incompatible firmware retains an actionable identity,
and uncertain explicit intent is not silently dropped.

Root independently ran the full suite: 298 passed in 15.89 seconds. After the final tokenless-owner notice
regression was added, the affected BLE/delivery suite passed 9 tests in 0.50 seconds. Owner notices are
intentionally tokenless in the protocol; old connection callbacks are fenced. A delayed notice on a current
connection conservatively requires reconnect/rediscovery, not radio recovery.

Root read both physical USB session reports and companion recovery evidence: both boards completed identity,
claim/state/data ACK/release without changing boot ID, and the original companion recovered both over BLE.
The installed executable is still the original build, not this source implementation. Phase 3 is accepted;
automatic handover, modes and maintenance remain Phase 4, with exact standalone/physical acceptance in Phase 5.

## Phase 4 independent verification (18 November 2026)

Root reviewed coordinator fencing, USB stability, runtime modes, fresh lock policy, dedicated Bluetooth failure
accounting, registry ownership and maintenance acquisition/resume/tool integration. Findings corrected during review
included separate persistent discovery suppression, cancellation without ending the discovery service, COM-change
and legacy rollback recovery, safe routing of tools for BLE-active registered displays, and preserving maintenance
through offline rename/enable operations. Long firmware compilation now precedes the maintenance lease.

Root independently ran the full suite: 326 passed in 22.85 seconds. After the final offline-registry preservation
and mismatched adoption-ID fixes, the affected coordinator suite passed 23 tests in 0.78 seconds. Root read the
successful source self-test report covering pricing, Displays mode/maintenance widgets, status projection, updates,
GUI subprocess execution and native tray behavior. It explicitly reports compiled:false; standalone validation is
still Phase 5. Agent source-self-test also found and fixed delayed callbacks after closing Displays.

Phase 4 is accepted at source/test level. No Phase 4 physical firmware update or production companion replacement
was performed. Exact packaged builds, measured physical handovers and the actual no-Bluetooth second PC remain
required; these source tests are not substitutes for those checks.

## Phase 5 local verification and external gates (18 November 2026)

The exact standalone candidate is 3.12.3.2 (17,337,344 bytes), SHA-256
cd6cfd355d240d1db0b7a41b2b43ad7bd96148b314e0776d9703f16cc3389c13.
Root read its successful compiled:true self-test, run outside the checkout with external Python/source paths removed.
Root independently verified the candidate executable and both final firmware byte counts and hashes against the
manifest. Final firmware is 3.12.3.0-usb.5, retained under phase5/candidate:

- C6: 8a270ad09e15c15cc5ca160babc7850f3e034d7539a45aad6b1ad949a503b966.
- Ball: f4cb7c35529f97f702f5bbaf92420aea61d56ce4b9fd90fe748f24262d404bdc.

### Findings and corrections

Root viewed the first captured usage screens and found waiting screens rather than data. Firmware owner_changed
cleared presentation on same-host maintenance entry. The narrowly reviewed fix preserves the current frame and
original freshness timestamp only for same-host USB/BLE-to-maintenance; it grants no writes or artificial freshness.
Cross-host change, release and expiry retain their existing invalidation behavior. Root independently ran the native
protocol/model suite successfully, then reviewed corrected physical pixels after identity-checked application-only
updates. Full private backups, settings and artwork were retained.

An exploratory fixture accepted connection flags with potentially old ACK timestamps; it is not acceptance evidence.
The stronger run requires fresh telemetry acknowledgements and separately recorded physical control readback. Its
final page cleanup failed because the fixture assumed three C6 pages. That fixture-only error was fixed and actual
page/settings restoration subsequently passed on both boards. The twenty valid powered cycles were not relabelled
as failed or rerun unnecessarily because of the later cleanup error.

The real legacy rollback test exposed direct maintenance cleanup sending CM1 to positively identified old firmware.
Compatibility itself passed. The tool-only cleanup correction rechecks full identity and ends without CM1 only for
confirmed legacy firmware. Root reviewed it and independently ran all 11 focused tool tests (0.18 seconds). That
cleanup fix was not physically re-run; no desktop or firmware rebuild was required for a tool-only change.

### Independently checked evidence

- Root viewed both normal quota frames and both completion overlays: correct synthetic values and text.
- Exact compiled companion delivered token/cost payloads through authenticated IPC and real transports. Root viewed
  C6 Today details and Ball Today/7-day details with the expected token and dollar values. C6 page-2 in the first
  capture set wrapped to the overview; it is not evidence of C6 weekly detail pixels.
- Root viewed exact-compiled-app synthetic metadata counts 0/0/1 on both displays, and separately labelled source
  real-transport fixture counts 2/3/4. Neither used user conversations.
- Root aggregated the strong packaged mode-cycle report: 20 cycles, zero failed cycles, maximum Bluetooth handover
  14.938 s and USB handover 5.000 s. Boot IDs and selected pages remained stable throughout those powered cycles.
  These are explicit mode switches, not physical cable-failure latency measurements.
- Root read automatic real-serial-boundary fixture results: C6 failure detection 2.438 s, BLE ACK after detection
  5.343 s, USB ACK after boundary restoration 5.047 s; Ball 2.078 s, 5.360 s and 4.765 s respectively. Both preserved
  boot/settings; peer ACK age was 0.1/0.2 s. This was a source fixture using real boards/transports and ACKs, not an
  exact-executable cable interruption. USB timing begins at boundary restoration, not first claimable discovery.
- Root read actual C6 old-firmware compatibility records: Auto BLE, forced BLE and USB-only upgrade notice/no fallback
  passed; usb.5 restored afterward. Root also read final physical settings matching the initial baseline.
- Root inspected final process metadata: only original production parent 25224/child 24992 at the installed path.
  The retained post-restoration status records both displays connected with ACK age 5.3 s and no device errors.
  The new executable remains a separate candidate; startup and installed executable were not replaced.

### Required remaining work

Phase 5 is NOT complete: actual no-Bluetooth-hardware PC and cross-PC ownership/settings/alerts acceptance remain.
Physical changed-port/hub, power-only/wall-charger, cable reboot/reconnect and exact-executable Auto data interruption
observations are also explicitly pending. Memory trend was not measured. Physical sleep is excluded; optional
30-minute endurance was not run and is not a blocker. No publication or Phase 6 completion is claimed.
The exact candidate files and SECOND-PC-CHECKLIST.md form the prepared handoff. No private firmware backup is included.

Final Phase 5 agent regression after the tool-only correction: 334 tests passed in 26.91 seconds. All agents ceased hardware actions before requesting second-PC access; Phase 5 remains in progress and Phase 6 has not started.

The user will perform the second-machine checks themselves. Those acceptance results remain pending; no access to that machine is being requested. A subsequent live-profile report of missing task counts triggered a separate investigation: the restored production companion reports chat_activity.available=false and null chat counts, despite healthy display connections. The earlier isolated synthetic-count tests do not establish availability of the real user profile's chat telemetry.

## Live-profile task-count correction (18 November 2026)

The user's actual displays showed unavailable task counts after the test fixtures were removed. Root independently
confirmed that the installed 3.12.3.1 companion reported chat_activity.available=false with null counts, despite
healthy connections. Inventory reads succeeded; the observer rejected Codex's current stream version 13 because it
only accepted version 11. The different C6/Ball fallback presentations did not establish different live job counts.

The corrected observer explicitly accepts verified versions 11 and 13, rejects other versions/types and reports a
sanitized unavailability reason. The actual version-13 metadata projection was checked before enabling it. Real-profile
source observations recovered available counts without synthetic state or parser monkeypatches. Root reviewed the
change and independently ran 16 focused tests (0.19 seconds); the agent's full regression passed 344 tests.

Standalone 3.12.3.3 passed its compiled isolated-profile self-test and was installed at the existing startup target.
Root independently verified file/product version and SHA-256:
04f7aebb976c32cd758dd50c251e56a3ffce64d901dea4563b45d54e395c75eb (17,339,904 bytes).
Previous installed/candidate builds and private settings backups were retained. Firmware remains usb.5 unchanged.

Root viewed actual normal-dashboard captures from both devices: 2 running, 0 waiting and 8 completed unread,
matching live IPC at capture time. Post-capture independent IPC showed both USB-connected, maintenance=false,
ACK ages 0.5/0.6 seconds and no errors. These are real-profile observations, distinct from prior synthetic fixtures.
The corrected build is left running, rather than restoring the incompatible older companion. The second-PC bundle
has been updated to this same build; prior 3.12.3.2 transport evidence remains historical rather than being relabelled.
Actual second-PC and other pending physical acceptance observations remain pending the user's own checks.
