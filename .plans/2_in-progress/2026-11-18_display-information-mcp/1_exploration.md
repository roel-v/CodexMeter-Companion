# Expose display information through MCP

## Request and status

Requested on 18 November 2026: add an MCP interface exposing all information visible on CodexMeter displays to
other agents. Created directly in the in-progress lane at the user's request. Exploration only; not implemented.

## Intended outcome

An MCP client can retrieve the companion's current display information as structured data, without reading pixels
or requiring a physical display to be connected. Values should agree with what the companion sends to its displays.

## Initial information inventory to verify

- Remaining usage quotas and reset timestamps/countdowns for the windows shown by the active display views.
- Today and seven-day token totals and the new-input, cached-input and output breakdowns.
- Estimated API costs corresponding to those token breakdowns, including currency and estimate/availability status.
- Running jobs, jobs awaiting input or approval, and completed unread chats, with availability and freshness.
- Completion-notification information shown on the display, with an explicit privacy boundary for notification text.
- Per-display status visible to users: model/identity or alias, connection and active transport, waiting state,
  selected page, power/battery indication and supported settings where the companion actually knows them.

Audit both the C6 and Ball pages before defining the schema. Distinguish companion-derived data from firmware-only
information; unavailable battery or physical UI state must be reported as unknown rather than inferred from USB.
Do not promise data the current protocol cannot retrieve without first identifying the required extension.

## Proposed interface direction

- Begin with read-only access. Control commands, settings changes and other mutations are separate scope decisions.
- Reuse a consistent companion snapshot, retaining timestamps, units, source and missing/stale states.
- Expose data even when no display is connected. Avoid independent quota polling, pricing calculations or chat
  watchers that could disagree with the desktop app or increase provider traffic.
- Keep credentials, authentication/session tokens and raw conversation transcripts out of MCP responses.
- Preserve the standalone Windows executable: agents should not require a full Python installation to use the MCP.
- Document client setup, schema/version compatibility and behavior when the companion is stopped or unavailable.

## Decisions still to resolve

- Local stdio versus another local MCP transport, and the supported client configuration/discovery experience.
- Whether MCP starts a companion, connects only to an already-running instance, or supports an explicit choice.
- Snapshot tools/resources versus subscriptions for updates, and the minimum useful polling cadence.
- Whether notification titles/bodies are exposed, omitted or separately opted in; aggregate task counts do not
  imply permission to expose chat content.
- Whether historical values or model-level detail belong in a later extension beyond the information on the display.

## Investigation and validation

Map every displayed value to its source and existing IPC projection. Choose a stable schema after that inventory.
Test agreement with the display payloads, stale/unavailable data, multiple models and displays, no connected display,
companion shutdown/restart, concurrent MCP clients, privacy filtering and standalone packaging/client setup.

## Relationship to existing work

Build on shared telemetry and generic per-display status from the USB/Bluetooth feature without coupling MCP clients
to a transport. Keep-awake and MCP can share the existing job snapshot; neither new feature requires the other.
