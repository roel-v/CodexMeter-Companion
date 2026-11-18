# CodexMeter USB and ownership contract

USB wire version 1 is independent of existing application v1. USB is supported on the repository's Windows 10/11 x64
desktop baseline with native usbser. Keep USB imports lazy/platform-scoped. Bluetooth starts independently if an
eligible device needs it and an adapter exists, and is re-evaluated every 5 s and on adapter-change notification.
On removal, cancel BLE workers, preserve delivery state and mark BLE unavailable. Never radio-recover owner-busy
or absent adapters. Local mode is per hardware ID: auto, usb_only, bluetooth_only.

## Discovery and framing

Enumerate present USB Ports-class interfaces with VID 303A, PID 1001, interface 00 and usbser. Exclude known unrelated
PnP instances (denylist takes precedence), ACPI, Bluetooth SPP and other VID/PID. An unrecognized tuple is never probed.
COM and USB serial are hints for probe scheduling, not identity. At most one probe per PnP instance at a time and two
concurrent globally. Start with exact ASCII `identity\n`, no leading bytes, at 115200 8N1, DTR/RTS false before open,
no flow control or reset tricks. Accept only `IDENTITY ` followed by a valid JSON object, then LF or CRLF. Verify the
full lowercase `codexmeter-` plus 12 lowercase hex digits (eFuse identity). USB/BLE equality uses that full value only.
Existing short_id/name may be displayed; neither serves as evidence. If legacy or incompatible, report upgrade/
unsupported; never send a USB application frame. A compatible unregistered device is offered for explicit registration
only. Read-only probe may run beside BLE. Duplicate endpoints with the same full ID are ambiguous until one disappears.

Updated identity retains legacy keys and adds `usb:1`, `app:1`, `fw` (ASCII version, 1–24 bytes), `model`
(`waveshare_c6_amoled_216` or `spotpear_ball_v2`), `boot` (16 lowercase hex digits from boot RNG), and
`capabilities` (array containing `brightness`, `rotation`, `screen`, plus any existing optional flags).
Firmware boot change invalidates every USB/BLE session, all setting revisions and the alert ledger. An optional unknown
identity field/capability is ignored. An unknown model, missing mandatory capability or wrong version is incompatible.

All v1 requests are LF-terminated byte lines: ASCII `CM1 ` + compact UTF-8 JSON object (control requests) or
ASCII `CM1 DATA ` + boot + SP + token + SP + seq + SP + revision + SP + exact application UTF-8 JSON.
Replies are always `CM1 ` + compact JSON + LF. No BOM. A single terminal CR before LF is accepted, other raw control
bytes are invalid. At most 640 bytes before LF, including CR if present; application bytes at most 512. In DATA,
revision is decimal uint32 or `-`; seq is decimal uint32 1–4294967295 (no leading zeros). The prefix/maximum header
is 81 bytes before the application, leaving room for CR. Host writes never interleave. Initialize idle, accumulate
one line, timeout at 1000 ms from its first byte, and on overflow/timeout discard through the next LF without
dispatch. A decoder never treats a suffix of a discarded frame as a new frame. Host ignores all lines outside
the correct prefix and expected schema, including log/identity lines and unsolicited replies. A lost prefix never
becomes an acceptance. Raw JSON diagnostics from old firmware are never consumed as v1 ACKs.

Use one 641-byte receive buffer and one 641-byte outgoing reply buffer (each includes a byte for terminator or use
length-delimited access), no full frame queue. Read at most 128 bytes and dispatch at most one complete line per loop.
Service one TX chunk up to 64 bytes and no larger than availableForWrite; set HWCDC TX timeout to zero for protocol
traffic, avoid flush, retain unsent tail, abandon stalled reply after 500 ms. On partial abort prepend LF to next
output (include in bounded accounting); serialize logs through the same boundary or route them to the existing
RAM ring only while v1/maintenance replies are pending. Maintenance binary output has an exclusive writer.
Retain ArduinoJson 7 for payload parsing with explicit input bounds, maximum nesting 4, and a bounded allocator
for wire parsing (at most 8 KiB peak including pool allocations); reject allocation failure. Validate before effect.
Use the existing payload cap and builders, including 47-byte/16-character title and 210-byte/64-character body.
Escaping is counted after UTF-8 serialization; builder trims alerts and rejects oversize other payloads.
A raw 512-byte application fits with the worst header; do not wrap it in a JSON string. Retain existing
target control capability checks. No raw payload/chat text in protocol logs.

## Requests and replies

JSON keys are case-sensitive. Required keys are shown below. Reject duplicate keys, invalid UTF-8, wrong type, range,
or extra keys on control requests. For control requests `q` is a host-generated uint32 request ID in [1,4294967295].
`host` and `token` are 32 lowercase hex digits from a cryptographic RNG. Persist host ID per local installation
through restarts (atomically, generated once); generate a fresh token each logical claim and each new connection
generation. IDs are correlation/ownership fields, with no authentication guarantee. Every request supplies the
discovered `boot`. BLE extensions below use the same names. Replies echo boot and q for control requests, and echo
boot, token and seq for DATA. Every successful control reply includes `ok:true`. Every error has `ok:false` and one
`err` value from the table. Never accept an ACK from a different transport instance, generation, token, boot,
or missing/mismatched sequence. Accept DATA only for the single pending seq. Device always echoes its actual boot
on boot mismatch; host ignores that as completion and starts discovery on detection. Do not reuse q while a waiter
can exist. Host wraps q by opening a new generation; sequence starts at 1 and uses no arithmetic wrap. Reclaim before
exhaustion. `token` is echoed on claim/ping/state/release/maintenance responses that have a token in the request.

| Request object | Successful response additions and effect |
| --- | --- |
| `{"op":"claim","q":1,"boot":B,"host":H,"token":T}` | `"state":S`; owner becomes this session; claim changes no physical settings |
| `{"op":"ping","q":2,"boot":B,"token":T}` | No additions; renew owner's lease |
| `{"op":"state","q":3,"boot":B,"token":T}` | `"state":S`; read current state, no renewal |
| `{"op":"release","q":4,"boot":B,"token":T}` | No additions; fence and clear owner |
| `{"op":"maint","q":5,"boot":B,"host":H,"token":T}` | USB only; see maintenance rules |
| `{"op":"maint_end","q":6,"boot":B,"token":T}` | USB only; clear matching maintenance lease |
| `CM1 DATA B T 1 - {"v":1,"k":"activity","src":"codex","run":1,"t":1784000000}` | `{"boot":B,"token":T,"seq":1,"ok":true}`; apply once |

`S` contains `same_host` (bool indicating host matches previous recognized app owner; unknown legacy counts
as different), `rev` (uint32 starting at 1), `page` (nonnegative target UI page enum), `brightness` (integer
0–100, reflecting device's actual supported range), `rotation` (0/90/180/270), `auto_rotation` (bool),
`manual_on` (bool intent), `policy_on` (bool), and `screen_on` (bool actual). Manual intent false always wins
over live policy on. Actual screen also reflects any local temporary presentation/power state. Increment rev on
every change to page, brightness, rotation mode/quadrant or manual intent, including local changes, before dispatching
queued events. On rev wrap, use the same fence and renegotiation as a new boot generation. Policy changes do not
increment revision and do not modify manual intent. New owner does not change policy until a fresh update arrives.

| Error | Meaning |
| --- | --- |
| `bad_request` | Correlatable malformed/unknown request or application schema; uncorrelatable malformed frames are dropped |
| `bad_boot` | Request boot does not match current boot |
| `busy_usb`, `busy_ble`, `busy_maintenance` | Another live owner of indicated type prevents operation |
| `stale_session` | Token absent, fenced, expired, mismatched, or wrong interface |
| `out_of_order` | DATA seq is lower than latest or skips next expected sequence |
| `conflict` | Retry uses same seq with different bytes, or setting revision failed comparison |
| `unsupported` | Known operation/control unsupported by this endpoint or target |

Application v1 unchanged: usage includes v/k/src and existing h5/h5r/d7/d7r/td/t7/st/t/b0/b7 fields;
activity uses v/k/src/run/t plus existing optional counts; alert uses v/k/id/title/body/t and optional run;
controls use v/k/cmd/t, brightness and rotation use `value`, screen uses `on` and `why`. For brightness,
rotation and explicit/manual screen use the observed S.rev. For telemetry/alert and live screen policy use `-`;
policy uses screen with `why:"lock"` or `"unlock"` matching `on:false` or `true`. Revision required for
other screen reasons, which represent explicit manual intent. Accept valid no-op controls. Unknown kinds, wrong
versions, invalid values and unsupported target features never apply or acknowledge success. Reuse existing model
fields and parser compatibility for legacy BLE. Parse into temporaries and commit once only after complete validation.

Process each correctly sequenced DATA once and remember its original bytes (up to 512) and accepted or rejected
outcome. A same-seq identical retry returns that outcome without rendering or updating freshness again. A same-seq
different frame returns conflict; include revision in this comparison. A counted application rejection consumes seq;
busy, bad boot/session and out-of-order do not. Release is idempotent only while the most recent release tombstone
matches boot, originating endpoint and token; clear it at next ownership change. Duplicate claim for the live
same owner/token returns its initial same_host decision and current state, with no reinitialization. A fenced token
cannot reclaim. Generate a new token for each claim attempt and purge old transport requests on fencing. Track one
most recent claim token per USB attachment and BLE connection, with the original q: repeated claims with that token
are eligible only while that owner is live. A new claim token can be staged only on a fresh BLE connection or following
a fresh read-only USB identity exchange. Serialize reads and claims; there is never more than one host claim waiter per
physical endpoint. An updated BLE peer explicitly re-discovers or reconnects after preemption; transport callbacks are
tagged with connection epoch before queueing and rechecked under the same synchronous arbitration boundary as effects.

## Ownership, reconciliation and maintenance

| Starting state and event | Firmware/host transition |
| --- | --- |
| No owner, valid USB claim | Registered host claims after verification; firmware records app owner, resets sequence, no settings change |
| BLE owner, valid USB claim | Atomically fence BLE, discard queued old writes, become USB owner; notify the connected updated BLE peer of busy_usb |
| Live USB, BLE app/claim | No application mutation or legacy ACK; updated BLE receives busy_usb |
| Live USB, another USB token | busy_usb; never displace a live USB session with a different token |
| USB release, transport loss positively known, or 7000 ms lease since claim/valid ping | Fence owner and callbacks; BLE eligible. Do not treat Serial operator bool as a reliable disconnect event |
| BLE release/disconnect or negotiated lease expiry | Fence peer and callbacks; no application owner |
| Legacy BLE application with no owner | First valid accepted payload establishes legacy BLE owner for that connection until disconnect or USB preemption |
| Any stale ACK, old boot or fenced token | No delivery or effect; new host generation has fresh waiters |
| Maintenance lease active | Both app transports denied; same token maint renews; maint_end/expiry restores eligibility |
| Auto USB fails with BLE available | Fence USB writer, close serial after bounded release attempt, start BLE attempt immediately; retry USB with stability/backoff |
| Forced transport fails | Fence and retry only configured transport |
| Other PC takes over | Invalidate prior owner's usage/tasks and queued effects; current telemetry from new owner; preserve page/settings/manual intent |
| Heartbeat continues, no fresh telemetry | Link remains live; waiting after application freshness deadline |

Use device monotonic unsigned elapsed-ms arithmetic. At claim and each successful ping lease is 7000 ms from now;
check expiry before processing any subsequent frame. ACK only after accepting the effect. A failed release has no
authority to bypass device arbitration: local sender fences first regardless of response (try release for at most
500 ms), then waits/retries busy until remote expires. For same-device handover serialize app sends, cancel pending
write/ACK waiter on fence, close old serial handle before local BLE app sends, and verify owner/state before first
new app send. App telemetry freshness changes only on accepted new usage/activity at device receipt time. Use
the existing 300000 ms host-stale waiting threshold, refreshed by actual current provider/activity samples, never resend cached snapshots
periodically solely to stay fresh. Replaying last snapshots after claim is allowed only if observed less than 300000 ms
ago in host monotonic time. Alerts may still present while waiting, but they do not refresh telemetry receipt age. Controls and heartbeats do not refresh it either. Preserve the existing 180000 ms usage-stale threshold and the default 60 s usage polling cadence. Screen-off does not stop I/O.

On same-host transition, re-enqueue only unexpired explicit setting intents from the previous active generation,
and only if the boot and expected revision still match after state reconciliation. Capture expected boot/rev at
explicit action; revision conflict requires reread and status, never blind retry with a substituted rev. A cross-host or
unknown legacy origin drops pre-claim explicit settings/queued alerts from the incoming host and reconciles current
device state. No automatic replay of saved brightness/rotation/power presets on any claim. Live policy is freshly
computed after reconciliation for the current OS state and applies without altering manual intent. The host maps mac_locked (off) to lock and mac_unlocked (on) to unlock for negotiated sessions. The legacy BLE path retains the original reason strings. On updated firmware, legacy mac_locked/mac_unlocked and the legacy on-only ble_restored reason affect policy power only, so a legacy reconnect cannot override manual-off after a USB handover. The negotiated path drops a cached ble_restored control and uses a newly evaluated OS policy after claim.
A manual local or explicit remote off survives unlock; only explicit/manual on changes its intent.

Retain at most 8 pending alerts per logical device, discard oldest on host overflow and expire 60 s after creation
in host monotonic time; log count/reason only. Do not persist pending alerts on restart. Preserve event IDs across
uncertain delivery; use existing 12 lowercase hex ID. Firmware keeps 32 applied event IDs with 65 s monotonic
retention across USB/BLE ownership; key globally by event ID so legacy BLE retry is covered too. After checking
duplicate IDs, reject a novel alert when all 32 slots are live (`conflict` for v1, normal negative ACK for legacy);
avoid premature eviction. Record before presentation in the same dispatch step. A duplicate valid alert succeeds
without presentation. Firmware reboot clears the ledger, so replay across a power loss can duplicate an alert.
No guarantees after expiration, host restart, or on older firmware without the shared ledger.

Maintenance pause is persisted per registered device on the invoking PC until explicit Resume; suppress both app
workers for that device. Stop sends, fence locally, and on USB transition matching own USB token atomically to
maintenance via maint with same host/token. With no owner or a legacy/negotiated BLE app owner, a verified USB
maintenance caller may claim and atomically fence that owner. A different active USB owner returns busy_usb.
Lease duration is 120000 ms, renewed only by same-token maint. Close companion handle and let the tool open it
exclusively. Any active lease blocks app writes even across COM close. Tools renew via same-token maint if needed
or finish before expiry; host Resume first acquires the exclusive handle and sends maint_end using retained token
for current boot, or waits for expiry if the token was lost. Boot clears lease. Exclusive COM ownership protects
a running maintenance tool even after reboot; explicit local pause survives. Do not terminate another port owner.
Updated raw diagnostics including logs/screenshot are blocked during an app USB lease and permitted under maintenance,
or when no owner has claimed USB (legacy tools remain usable alongside BLE for read-only diagnostics). Gate raw
state-mutating serial commands to maintenance or no owner. Disable raw JSON application dispatch on the updated
firmware. Identity and health stay read-only and may run without ownership. Binary screenshot cannot be multiplexed
with v1/control output; reject other input until operation completes and preserve binary exit framing.

## BLE compatibility and timing

Expose negotiated BLE through existing identity/read and RX/TX characteristics: identity adds usb/app/fw/model/boot,
and `ble_owner:1` (support of this extension). Absent flag means legacy. For updated BLE use the same complete CM1 request/reply forms without LF, fragmented over the existing RX/TX
characteristics. A v1 fragment is byte 0x1E, logical total length (uint16 big-endian), offset (uint16 big-endian),
then at least one logical byte. Total is 1–640; the offset is zero on the first fragment and exactly the assembled
byte count thereafter. Fragment size is at most min(512, negotiated ATT MTU minus 3). Send host fragments as
sequential awaited GATT writes without response, with a bounded whole-train deadline and no interleaving.
OS/controller acceptance is never application acceptance: only the matching correlated device reply completes
delivery. On an unknown DATA outcome, retry the complete logical frame once with identical token, seq, revision
and application bytes; do not retry individual fragments or report success merely because writes were queued.
Firmware sends replies as ordered notifications targeted at the originating connection.
One logical frame per direction/connection, with no fragment interleaving except a terminal owner-busy replacement. A new offset-zero fragment replaces any
partial frame. Wrong total, gap, overlap, oversize, wrong connection epoch or timeout discards the partial frame;
ignore further nonzero offsets until a new zero. After completion pass the logical frame once to the same parser and
arbiter as USB. Complete each fragment train within 2000 ms of its first fragment, including local wait/queue time.
Keep one bounded 640-byte assembly per connection and one outbound 640-byte logical frame; queue at most one
pending owner-busy notice, prioritized at the next frame boundary. Reject excess connections using the existing
board connection limit. Purge partial trains and stale callbacks on fence or disconnection. If preemption interrupts
outbound replies, the owner notice begins with offset zero and replaces the host's partial reply.

The standard 23-byte ATT MTU supports 15 logical bytes per fragment; capable adapters may use larger MTU.
Read identity as a normal GATT long read, independently of notification MTU. A complete 512-byte application
always fits a negotiated logical DATA message; preserve both breakout arrays and all existing fields. Keep the
individual legacy GATT characteristic limit and reject truncated/oversized writes. A peer that advertises
ble_owner:1 must use negotiated ownership, including at the minimum ATT MTU. If negotiation, fragmentation or
timing fails, surface the per-device failure and retry as permitted by connection mode. Legacy framing remains
available to existing hosts and to new hosts talking to firmware without the flag. Start ACK waits after sending
the final fragment; allow 2 s per BLE reply/ACK, then one identical retry for DATA. Reserve BLE heartbeat time
by sending any due heartbeat before starting the next application fragment train. A pending application ACK does not prevent a heartbeat send. Heartbeat cadence is 2 s when idle and each fragment train is bounded as above. Recheck lease expiry before any assembled request can take effect.
Send unsolicited exact `CM1 {"op":"owner","boot":B,"err":"busy_usb"}` when BLE is preempted; on maintenance use
busy_maintenance. Negotiated BLE replies are connection-scoped notifications. Ignore uncorrelated legacy ACKs
for negotiated session delivery. Old host writes old JSON, receives existing ACK/NACK when allowed, and receives
no success ACK when fenced. Its status/recovery remains legacy. No application data on either transport until
full verified registration; existing legacy matching remains only for existing legacy BLE records.

| Timing | Value |
| --- | --- |
| Discovery rescan / repeat successful probe during promotion | 2 s / second successful identity and same boot after at least 2 s |
| Identity read / request wait / read polling | 1 s / 1 s / at most 100 ms, off UI thread |
| USB heartbeat / failure / lease | 2000 ms fixed cadence; fail at third unanswered ping deadline; 7000 ms lease |
| DATA ACK retry | One identical retry after 1 s; after another 1 s report unknown and fence |
| Serial write / release / shutdown cleanup | At most 500 ms each write/release; concurrent workers cancel/close within 2 s |
| USB retry after transient failure/busy | 1,2,4,8,16 s capped; incompatible/nonresponders 60 s per PnP instance; clear on topology change |
| BLE retry when available | Immediate, then 1,2,4,8 s capped, 5 s deadline per connection attempt; reset on success |
| BLE owner-busy recovery | Retry owner claim every 2 s on existing eligible connection or reconnect; no adapter recovery |

Heartbeat scheduling starts at claim; reserve writer time for heartbeat even under load. One ping waiter in flight
at a time. A valid matching ping reply clears consecutive misses; late replies do not. With fixed cadence worst-case
silent detection is ~7 s from disappearance and 5 s from the first unanswered send, excluding system suspension.
Promotion budget under responsive conditions is 2 s stability plus bounded old send/release, claim and first DATA
ACK; initial discovery excludes busy/backoff endpoints. BLE restoration goal 30 s includes scanning and BLE
reconnection across lease expiry; these are Phase 5 measurement targets. Health probes, finite retries and unavailable
transport errors are isolated per device. Manual/forced mode and device disable changes fence pending operations that violate the new policy before changing workers.

## Fixture examples

In fixture templates substitute B with `0011223344556677`, H with `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`, and T
with `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`. USB lines end in LF. Prefix these application bodies with
`CM1 DATA B T <next seq> <revision> ` after substitution. All valid examples below return the DATA OK reply.

| Input after claim with rev 4 | Outcome |
| --- | --- |
| `{"v":1,"k":"usage","src":"codex","h5":72,"h5r":1784000100,"d7":51,"d7r":1784090000,"td":55,"t7":88,"st":"ok","t":1784000000}` with - | Replaces current usage, refreshes usage receipt age |
| `{"v":1,"k":"activity","src":"codex","run":2,"t":1784000000}` with - | Two running tasks, refreshes activity receipt age |
| `{"v":1,"k":"alert","id":"112233445566","title":"Task complete!","body":"Résumé ready","t":1784000000,"run":1}` with - | Presents once; retry across BLE with same application ID ACKs without presentation |
| `{"v":1,"k":"control","cmd":"brightness","value":60,"t":1784000000}` with 4 | Changes brightness and increments rev to 5 |
| `{"v":1,"k":"control","cmd":"rotation","value":90,"t":1784000000}` with 5 | Sets manual quadrant and increments rev to 6 |
| `{"v":1,"k":"control","cmd":"screen","on":false,"why":"lock","t":1784000000}` with - | Turns off via policy; manual intent and rev retained |

Additional executable fixture cases: feed a valid frame in one-byte increments and two lines in one read; verify one
effect per line. Feed 641 pre-LF bytes, embedded NUL, CR not immediately before LF, ambiguous duplicate keys,
or a >1-s partial frame followed by a plausible suffix; verify no effect, then a clean valid line succeeds.
Feed exact 512-byte valid application and 513-byte application; first fits USB and negotiated BLE, second rejects. At MTU 23, transmit a 512-byte application with both breakout arrays and verify exact reassembly and effect; exercise a gap, timeout, and USB preemption mid-train, with no partial effect and a complete busy notification. Retry an accepted
seq with same bytes (same ACK) and changed bytes (conflict); skip seq (out_of_order); reject plausible ACK in a log
and late ACK from old token. Claim USB with a legacy BLE sender and with a negotiated peer on a second host; verify
busy notification only on the negotiated path and unchanged settings. Lease expiry, stale release, maintenance
expiry, manual-off/unlock and revision conflict each follow the tables. Advance the test clock by >300000 ms while sending pings without new telemetry;
verify link healthy and display waiting. Boot change clears ownership; a stale ACK never resolves a new write.

### Phase 5 diagnostic-maintenance clarification (2026-11-18)

A same-host transition from a live USB or negotiated BLE application owner into maintenance preserves the current
frame and its original telemetry receive timestamp. It accepts no new application data and never refreshes age.
The existing 300000 ms stale threshold continues to apply during the live maintenance lease. Maintenance end/expiry,
no prior live application owner and cross-host maintenance retain clearing/waiting behaviour. This permits faithful
framebuffer diagnostics without manufacturing freshness. Firmware usb.5 implements this narrow rule.
