# Keep-awake implementation and verification

## Where the work landed

- The [original feature request][request] was recorded on 18 November 2026. Implementation began in the local Codex
  chat **Set up computer to sleep when unused**. Review, release and installed-app verification continued in
  **Set up Waveshare for CodexMeter**.
- [Implementation commit `6b39569`][implementation] added [the Windows power request][guard], connected it to the
  [daemon's existing chat observer and status response][daemon], and added [lifetime and expiry tests][tests].
  The OS handle belongs to the companion process. Only a system power request is acquired.
- [Release commit `d82d2b0`][release-commit] shipped the standalone executable in [Windows 3.12.3.6][release].
  The [Windows guide][guide] documents the default and opt-out. The C6 and Ball continued using firmware 3.12.3.5.

## Verification on 19 November 2026

- With two real local turns running, the installed executable reported `preventing_sleep=true` and Windows
  reported `ES_SYSTEM_REQUIRED`.
- A second instance of that same executable, using an isolated test profile, went from two running turns to zero
  and reported `preventing_sleep=false`. The live profile still had active work during this check.
- The automated tests cover one shared handle across multiple turns, zero running turns, loss of the desktop,
  expiry after silent telemetry, reacquisition on fresh activity and observer cleanup. Both platform jobs passed
  in the [follow-up CI run][ci]. The automated guard tests use simulated Windows calls.
- Verification exercised request acquisition and release. Physical sleep, lid closure, critical-battery behavior
  and forced process termination were not exercised.

[request]: https://github.com/roel-v/CodexMeter-Companion/commit/266e6b8a2574895441520020473e9a6124df56d0
[implementation]: https://github.com/roel-v/CodexMeter-Companion/commit/6b39569500a8f2d75c14d16415a9683bfd0e5a65
[guard]: ../../../codexmeter/sleep_guard.py
[daemon]: ../../../codexmeter/daemon.py
[tests]: ../../../tests/test_sleep_guard.py
[release-commit]: https://github.com/roel-v/CodexMeter-Companion/commit/d82d2b06b774db993bc3e628e7831076e62a9a6b
[release]: https://github.com/roel-v/CodexMeter-Companion/releases/tag/windows-c6-2026.11.19.1
[guide]: ../../../README.windows.md#automatic-windows-sleep
[ci]: https://github.com/roel-v/CodexMeter-Companion/actions/runs/44531650353
