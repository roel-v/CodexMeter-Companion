# Keep the computer awake while jobs are running

## Request and status

Requested on 18 November 2026: add a way for CodexMeter to prevent the computer from sleeping while jobs are
still running. Created directly in the in-progress lane at the user's request. Exploration only; not implemented.

## Intended outcome

The companion can keep the host computer awake while it reports running jobs, then release its sleep inhibition
when those jobs finish. This should use the same job-state information as the display so the two do not disagree.

## Proposed scope to refine

- Provide a clear user setting and show whether CodexMeter is currently keeping the computer awake and why.
- Manage one host-wide sleep request, independent of the number, model or connection status of physical displays.
- Acquire and release the request as the running-job count changes; clean up on disable and normal app exit.
- Keep the screen's power policy separate from the computer's sleep policy. Do not change global power-plan settings.
- Use an OS-owned request whose lifetime ends with the process, avoiding persistent inhibition after a crash.
- Initially target the Windows companion; determine macOS support explicitly before implementation.

## Decisions still to resolve

- Default setting and whether the user can override it temporarily.
- Whether waiting for input/approval should keep the computer awake. The initial proposal is running jobs only;
  completed unread chats should not keep it awake merely because they remain unread.
- Behavior on battery power, explicit Sleep commands, lid closure and critical-battery actions. The initial proposal
  is to inhibit automatic idle sleep while respecting deliberate user actions and system safety behavior.
- How long to retain an existing request when job telemetry becomes stale or unavailable, and how to communicate
  uncertainty without either allowing an active job to sleep immediately or keeping the PC awake indefinitely.

## Investigation and validation

Inspect the existing job-state aggregation, freshness indicators, settings UI and application shutdown lifecycle.
Evaluate the supported native power-request mechanism before choosing an implementation. Test running-to-idle
transitions, unavailable telemetry, setting changes, process exit/crash and multiple displays without duplicate
requests. Plan any physical sleep/lid tests explicitly; this feature does not authorize those actions by itself.

## Relationship to existing work

Reuse the companion's shared job state rather than creating another chat watcher. USB/Bluetooth transport selection
is independent of the sleep decision. Review integration with the in-progress USB fallback work when implementation
starts; neither a connected display nor Bluetooth hardware should be required to keep the host awake.
