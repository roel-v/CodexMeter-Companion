# Keep the computer awake while jobs are running

Requested on 18 November 2026. Shipped on 19 November in CodexMeter Companion 3.12.3.6 for Windows.
[Implementation, release and verification](5_post-implementation-notes.md).

## Intended outcome

Keep the PC awake while local Codex turns are running so unattended work can finish. Use the same running-job
count the companion sends to its displays. Once all turns finish or are waiting for input, allow normal idle sleep.

## Shipped behavior

- One Windows system power request covers all running turns. The number of displays and their USB or Bluetooth
  connections have no bearing on it. The screen can turn off while work continues.
- A confirmed count of zero releases the request immediately. Waiting for input or approval and completed unread
  chats do not count as running work.
- During a gap in telemetry, an existing request expires five minutes after the last confirmed positive count.
  The observer releases it on shutdown. Fresh running work can acquire it again.
- Keep-awake defaults to on. Start the daemon with `--no-prevent-sleep` to opt out for that launch.
  The companion reports whether it holds the request in `chat_activity.preventing_sleep`.

The feature uses the Windows idle-sleep mechanism on AC and battery, subject to Windows power policy.
It makes no changes to the power plan, lid settings or screen timeout. The released controls are the daemon flag
and IPC status. A tray checkbox and a macOS implementation were outside the shipped scope.
