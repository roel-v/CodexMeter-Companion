# Implementation and verification — 18 November 2026

All five phases were implemented in sequence. Desktop and both display firmware versions are 3.12.3.4.
The standalone executable is installed at the existing startup path; both attached displays were updated using
identity-checked, application-only writes with verified rollback metadata. No release, commit or push was made.

## Delivered

- Independent local health observations for stream, inventory, completed-unread history, quota and token data.
- Required-format/schema validation, supported stream versions 11/13, authoritative owner-discovery coverage,
  bounded JSONL parsing, source-specific freshness and two-observation recovery.
- Persistent status and accessible details in the Windows control panel and tray, safe local diagnostic copying,
  deduplicated incompatibility warnings and five-minute eligible-outage warnings with distinct wording.
- Unknown and partially available counts on both display models; older firmware limitations are explicit.
- Local executable/package version provenance; no network compatibility lookup, automatic install or restart.
- README, Windows guide and unreleased changelog updated.

## Verification

- Full final Python regression: 365 passed in 27.64 seconds.
- Native firmware core/protocol tests passed, including null and partially valid task counts.
- Both PlatformIO targets built successfully; standalone Nuitka build succeeded on D:.
- Exact retained executable passed --self-test outside the checkout with an isolated profile and restricted PATH.
  Native Win32 tray click routing, persistent panel, dialog reuse, recovery and bridge shutdown passed.
- Eight actual-device captures passed visual inspection: C6 and Ball, USB and Bluetooth, all unknown and partial
  running=2 / waiting=3 / done=unknown. Actual serial screen captures, not preview renders.
- Original automatic transport modes and display preferences restored. Final normal-screen captures show live
  quota/tokens and task counts on both models. Both have fresh acknowledgements and no maintenance pause.
- All five live source components report compatible with Codex Desktop 26.1111.2228.0. The CLI executable has no
  usable version resource and is correctly reported as unknown; its quota response still validates.
- Git ignores retained artifacts/logs. Existing unrelated USB work remains intact and uncommitted.

## Evidence and rollback

Local evidence directory: `dist/windows/validation/compatibility-20261118/` (ignored by Git).
It contains python-tests.txt, native-tests.txt, packaged-selftest.json, source-selftest.json, build logs,
artifacts.json with SHA-256 hashes, hardware-fixtures.json, flash logs, final-status.json, and actual screen PNGs.
`candidate/` contains the standalone executable and both app-only firmware images.
`rollback/` retains desktop 3.12.3.3 and the previous USB-phase firmware app images. Verified private full-flash
backups remain under E:/DeviceBackups; they were not copied into the repository or prepared for publication.

The first Ball identity probe timed out before writing. It was positively identified, explicitly resumed after
closing the probe, and flashed successfully on retry. One capture raced a serial discovery probe and was retried.
The initial Bluetooth test expected the wrong status spelling (ble versus bluetooth); correcting the harness
completed all four Bluetooth captures. These were validation interruptions, not companion crashes.

## Boundaries

Undocumented semantic changes that preserve every validated contract cannot be guaranteed detectable.
Host power/outage policy is covered by injected-clock tests; runtime long event-loop gaps trigger resume grace.
No physical sleep/resume, overnight soak or second-PC/no-Bluetooth acceptance is claimed. The separate USB feature
retains its own pending acceptance work. No source transcript contents, account identifiers or credentials are
included in the retained compatibility diagnostic report.
