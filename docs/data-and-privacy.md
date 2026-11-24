# Data, profiles and privacy

HeetKit stores settings and chat data in the operator's profile on their computer
or server. Twitch and optional AI features communicate with external providers.
The developer receives no automatic telemetry, profile uploads or chat history.

## Privacy notice for viewers

Your channel's bot operator chooses the settings and handles access, correction,
deletion and storage opt-out requests. Use their published contact route.
Operators should publish their identity, contact route and AI use beside this notice.
This document describes software behavior; operators remain responsible for their
legal basis, provider permissions and retention decisions for their instance.

Ordinary chat messages are not archived. Presence records, delivered AI exchanges
when memory is enabled, and leaderboard counts are stored as described below.
Messages sent to Twitch or an AI provider have separate provider retention rules.

Send `!optout` with the configured command prefix to stop identifying local storage
for your authenticated account. It deletes your presence, AI memory and leaderboard
counts across the profile, including pending identifying writes. Extra text cannot
select someone else. The request precedes normal restrictions and cooldowns.

An opt-out retains your stable Twitch ID, available verified/stored username and
actual request date (unknown for historical entries) until withdrawal or profile
retirement. It prevents recollection after an account rename. It also suppresses
later request logs; previously captured logs require operator handling.

Opt-out does not stop chat commands or new AI requests. Ask the operator to add an
AI command restriction if you also want `!ask` ignored. Local requests cannot erase
Twitch or provider copies. Deletion is logical removal, not forensic disk erasure.

## Profiles

| Platform | Default profile location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\HeetKit` |
| macOS source | `~/Library/Application Support/HeetKit` |
| Linux source | `${XDG_DATA_HOME:-~/.local/share}/HeetKit` |

Desktop: **Settings > Data & diagnostics > Open profile folder** or **Copy path**.
Server uses its selected `--data-dir` or environment profile; Docker uses the
[mounted volume](docker.md#run-and-inspect). Browser management cannot open server folders.

`--data-dir` overrides `HEETKIT_DATA_DIR`. Each profile has separate settings,
commands, Twitch authorization and databases. Desktop keyring credentials are tied
to its resolved path; moving a profile requires entering them again. The portable
build also uses app-data. Reinstalling or uninstalling retains profiles and secrets.

Quit Desktop with **tray Exit**, or stop the Server service/container, before
copying, editing or removing profile files. **Stop bot** does not close the database.
The local profile guard does not prevent duplicate bots on separate hosts or copies.

## Credentials and local data

| Location | Stored data | Retention |
| --- | --- | --- |
| `config/config.json` | Commands, settings (including the manual stop and reply interval), prompts, triggers, schedules | Until changed/deleted; review personal text separately |
| `config/` (other files) | Filters, private access policy | Until changed/deleted |
| `data/heetkit.db` | Presence, AI exchanges, leaderboard counts, opt-outs, schema metadata | Personal retention below; opt-outs until withdrawal/retirement |
| `<database-name>.analytics.sqlite3` | Anonymous daily/hourly counters and coverage | 60 UTC calendar days |
| `auth/twitchio_tokens.json` | Twitch access/refresh tokens | Until revoked/replaced/deleted |
| `auth/server_credentials.json` | Browser-managed Server credentials/provider keys | Until removed/replaced |
| `auth/management_sessions.json` | Server only: SHA-256 digests and expiry of remembered panel sessions plus a digest of the management token; no tokens; not exported | 30 days after last use, or until sign-out / token change |
| `auth/ai_safety_salt` | Random secret for the OpenAI viewer safety identifier; not exported | Until deleted (a new one is created) |
| OS keyring | Desktop secrets/provider keys | Separate from profile files |

Server credential file permissions restrict access; they are not encryption at rest.
Protect host access, volumes and backups. Server environment/`_FILE` secrets override
browser-managed values. Desktop keyring values override environment fallbacks.
HeetKit does not load `.env` files. See [process configuration](development.md#advanced-process-configuration).

Logs can show permitted command inputs, reply attempts, outcomes and lifecycle events.
Dashboard **Recent commands** shows the viewer login with each outcome (opted-out viewers leave no entry).
They exclude ordinary chat, provider payloads, reasoning, rejected AI output and raw
exception prose. The live buffer is memory-only, capped at 500 entries / 1 MiB.
**Clear view** clears only the display. Exported JSON and console/service/Docker logs
need separate operator retention and deletion. HeetKit creates no application log files.

UI drafts and Playground results stay in memory. Close the UI to clear drafts.
Application state uses no cookies or IndexedDB. Browser storage holds only the interface
language and, on Server, the panel session token (`sessionStorage`, or `localStorage`
with **Remember me**);
browser engines and OAuth pages may retain their own data. Temporary cooldown and
message-correlation caches are bounded, transient state rather than a chat archive.

## AI processing and memory

AI requests send the question, shared/profile/personality instructions and available
stream category to the selected Gemini, DeepSeek or OpenAI provider. With memory on,
up to M recent successful exchanges for that viewer/channel are included. A configured
cross-provider fallback can receive the same permitted context after explicit consent.
Search tools can also receive context.
A Desktop custom OpenAI-compatible server receives the same context at the address
you enter; its address stays in `config/config.json` on that computer, its optional
key in the OS keyring, and neither is exported.

OpenAI requests from chat carry `safety_identifier`: a hash of the viewer's Twitch
user ID keyed with the profile's `auth/ai_safety_salt`, so OpenAI can attribute
abuse to that viewer instead of your account. It is stable per profile and cannot
be reversed without the salt; the ID and login are never sent. Other providers get
no viewer identity field, but text may identify people. The provider receives its key and normal network connection information.
OpenAI requests use `store: false` without server conversation history. Provider
retention and deletion terms remain independent of local controls.
See [AI setup](ai-setup.md#thinking-search-and-fallback-boundaries).

Only successfully delivered AI exchanges enter memory. Thinking/tool continuations
are not saved. Stored exchanges expire 60 days after creation or sooner under the
count cap. Defaults per viewer/channel are N = 100 stored and M = 5 context exchanges.
N supports 1–500; M supports 1–50 and cannot exceed N. Save limits under
**AI > Conversation memory**. Turning memory off stops subsequent memory reads/writes;
existing exchanges still expire. `!erase <username>` deletes current-channel AI memory
only; it neither removes presence nor prevents future storage.

Playground makes real provider requests with applied instructions and filters, but
without viewer memory, stream category or chat delivery. Results stay in memory.
Filter Tester runs locally. Twitch receives authorization, account/channel lookups
and outgoing replies. Weather sends place queries and coordinates to Open-Meteo.
Desktop's manual update check uses GitHub's release API without profile credentials.
Never include secrets or unnecessary personal information in chat or prompts.

## Chat leaderboards

Presence stores stable channel/viewer IDs, current login and first/last observation
for `!seen` and recent-viewer replies. It expires after 60 days without observed
activity. First observed means first in this retained database, not first ever on Twitch.
Leaderboards store counts by account, channel, UTC month and broadcast, without
ordinary message bodies or individual event IDs. They follow presence retention.

Stream counts require consecutive observations of the same broadcast. Connection gaps,
restarts and the final unconfirmed interval can leave partial coverage. The last
confirmed broadcast remains until another is identified. **Count chat messages** pauses
future leaderboard collection; existing counts remain. Paused messages are not replayed.

Expiry excludes old records from lookups immediately. Physical cleanup runs at startup
and hourly while the application runs, even with the bot stopped or memory off.
Overdue cleanup waits until startup if the whole process is stopped. Backups and
external copies need separate handling; 60 days is a maximum, not a required minimum.

## Daily local aggregates

**Analytics** shows Today / 7 / 30 / 60 UTC calendar-day counts, command/provider
breakdowns and token usage. Today uses hourly observations; older daily records do
not gain invented hourly data. Current retained users are a snapshot. Playground
usage is separate. Missing coverage is unknown rather than zero.

The separate analytics database stores channel IDs, bounded command/provider/model
dimensions, counters and coverage, without viewer IDs, chat, prompts, replies or request
IDs. Rows expire after 60 UTC calendar days, including when collection is paused.
Collection is prospective; crashes, buffers and failed writes can lose updates.

**Collect analytics** controls new collection. **Reset all profile analytics** clears
all channels and Playground totals plus pending updates. It leaves personal data and
opt-outs intact. Alternatively remove only the identified analytics file and matching
`-wal`/`-shm` files with the whole application stopped. Startup creates an empty store.
Small anonymous buckets may still identify people in combination with other data;
keep them private. Totals have no per-viewer contribution ledger.

## Private command restrictions

`config/command_restrictions.json` stores user/channel IDs, a creation-time login label,
command IDs, expiry or permanent status, and optional private notes. Rules stop matching
at expiry; startup, management reads and saves remove expired entries. Global AI-only
rules and unresolved legacy username blocks can also appear in User restrictions.

These rules and notes do not go to chat, AI prompts or portable exports. Storage
opt-out leaves them in place; operators must review/delete them separately.
Malformed policy files stop startup without overwriting them. Repair while stopped.

## Manage a storage opt-out in HeetKit

Verify account control before acting for someone. In **Commands > Storage opt-outs**,
enter their Twitch username and select **Add**. This deletes presence, AI history and
leaderboard counts across the profile and prevents identifying recollection.
**Refresh** shows recent chat opt-outs. **Withdraw** permits future storage without
restoring erased history. The bot attempts one chat confirmation; completed repeats
are silent until withdrawal. Failed recovery cleanup can be retried after a short delay.

## Manual privacy requests

For deletion without suppression or offline administration, stop the entire process
and use `scripts/privacy_request.py` with the actual personal SQLite path, verified
numeric Twitch ID and `--action delete`, `opt-out` or `opt-in`. See `--help` for syntax.
`delete` preserves existing opt-outs; `opt-in` removes suppression only. The tool also
handles managed migration recovery copies and creates no backup.

Review settings, notes, old profiles, logs, exports and other backups separately.
Handle provider/Twitch deletion independently. Before restoring any copy, reapply
current deletions and suppression before restarting. Deleting the personal database
also deletes opt-outs and allows recollection. Confirm the local scope privately.

## Portable configuration transfer

Use **Settings > Configuration transfer** to export a ZIP, preview it on the destination
and confirm import. Included collections replace destination settings. The preview
expires after ten minutes. Commands, response pools, personalities, instructions, AI
settings, filters, triggers and schedules transfer, including applied session edits.

Keys, OAuth, management credentials, personal databases, opt-outs, private restrictions,
machine paths and host preferences are excluded. Text in configuration can still be
private; protect the ZIP. Legacy AI blocks merge into private restrictions on import.
Exact replaced files remain in `config/import-backups/configuration-<unique-id>/` with a
manifest. Remove unneeded copies yourself. Interrupted multi-file replacement can need
manual recovery from that manifest; see [configuration API](management-api.md).

## Backups and settings recovery

Stop the entire application before copying a profile. Protect backups like originals.
OS keyring and injected secrets need separate handling. Other copied credentials and
authorization can be inside the profile. See [Docker backup/restore](docker.md#backup-restore-and-updates).
Operator copies need fixed expiry no later than 60 days after creation and earlier
deletion where required. They are recovery copies, not additional model history.

### Versioned database upgrade and recovery

Both hosts upgrade before connecting or serving requests. Schema 2 upgrades to schema 3
after a verified SQLite recovery backup. Pre-1.5.1 databases must first upgrade through
HeetKit 1.6. Unsupported/corrupt schemas or failed backups stop startup with sources intact.
The managed `data/<database-name>.recovery/` snapshot expires seven days after creation;
startup/hourly cleanup removes it without extending expiry. Privacy actions scrub it.
Never run an older binary against an upgraded database or restore expired snapshots.

Settings live in one `config/config.json`. The first start after 1.6 moves the 1.6
settings files into it and keeps their exact copies in `config/backup-1.6/`; an
unreadable 1.6 file stays only in that backup. HeetKit 1.6 cannot read `config.json`,
so going back to 1.6 means restoring those files.

Unreadable/future settings stay intact and refuse saves/resets. Stop, back up and repair
only the named file. Lossy saves retain exact `<filename>.<unique-id>.recovery` copies;
these, `backup-1.6/` and import backups have no automatic expiry. Review/delete them separately.
Rotate exposed credentials at their provider and follow [SECURITY.md](../SECURITY.md).
