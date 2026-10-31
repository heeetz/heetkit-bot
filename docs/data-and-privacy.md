# Data, profiles and privacy

HeetKit keeps settings and chat data on the operator's computer or server, outside
its installation folder.
Twitch and optional AI features communicate with their respective providers.

## Privacy notice for viewers

The operator of the bot in your Twitch channel chooses its settings and handles
privacy requests. Contact that channel's bot operator through their published
contact route for access, correction, deletion, objection or a local storage opt-out.
The HeetKit software developer receives no automatic telemetry, viewer database,
chat history or profile uploads. If the developer operates a bot instance, they are
the operator of that instance. Information you voluntarily send in an issue or
support request is separate; never attach a private profile or unredacted logs.

The bot keeps two distinct personal collections in one database per profile, scoped
by Twitch's stable channel ID and viewer ID. Presence stores the current login and
first/last observation for `!seen` and recent-viewer replies; ordinary chat text is
not archived. First observed means membership in this retained bot database, not
Twitch's first-ever chatter designation. Successful, delivered AI questions and
answers have their own timestamps and are saved when conversation memory is on.
Each AI exchange expires **60 days after creation**, or sooner under the stored-count
cap. Presence expires **60 days after last observed activity**; active metadata can
outlive its original creation date. These are maximum windows, not permission to
retain data that is no longer needed.

The defaults are the last **100 stored exchanges (N)** and **5 model-context exchanges
(M)** per viewer/channel. Valid limits are N = 1–500 and M = 1–50, with M no greater
than N. Writes, startup and saved limit changes enforce the count cap; retrieval
never expands it. Limits are backend settings in `config/app_settings.json` under
`ai.history_max_entries` and `ai.context_max_entries`; stop the application before
manual edits. Invalid limits stop startup. Use **AI > Conversation memory** to save these limits in the panel.
The memory toggle stops subsequent memory reads/writes.

Expiry uses UTC elapsed time. Expired records are excluded from lookups immediately;
physical database cleanup runs at application startup and hourly while the application
process runs, including Desktop in the tray and Headless/Server. It continues when the
Twitch bot is stopped or memory is off. Removal can lag expiry by one cleanup interval;
when the process is stopped, overdue cleanup waits until its next startup. Desktop
source-console diagnostics report cleanup failures. The panel's bounded activity
projection does not expose raw diagnostics or retention-cleanup failures. Backups and older profile copies
require separate operator handling. Deletion is logical removal, not a promise of forensic
erasure from disks, journals or provider systems.

AI prompts, instructions and optional context go to the selected provider; bot replies
go to Twitch. Type `!optout` (using the operator's configured prefix) to disable local
storage for your authenticated Twitch account. Extra text never selects another person.
The request runs before normal command restrictions, filters and cooldowns, and
deletes your presence and AI history across all channels in that profile. It prevents
future identifying writes, including pending AI results and renamed accounts.
It retains your Twitch ID plus available verified/stored username and the actual
opt-out date (unknown for historical entries) as a suppression record until the
operator confirms withdrawal or retires the profile. It does
not disable chat commands, Twitch processing or fresh AI provider requests. Ask the
operator to also use **Commands → User restrictions** if you want your `!ask` requests ignored.
Opted-out requests are excluded from HeetKit's session log buffer and configured
console handlers, including later diagnostics from requests already in progress;
earlier logs need operator handling. Access blocks/notes and other safety configuration
remain in place. Necessary transient command state is described below.
Local requests cannot delete Twitch's chat or provider copies.

Operators should publish their identity and contact route beside this notice,
explain their lawful basis and provider use to their community, and resolve the
provider restrictions in [the legal assessment](#legal-assessment-and-open-questions)
before using AI with viewers. This notice describes software behavior; it does not
certify that any instance complies with data protection law or provider terms.

## Profiles

The default profile location is:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\HeetKit` |
| macOS source launch | `~/Library/Application Support/HeetKit` |
| Linux source launch | `${XDG_DATA_HOME:-~/.local/share}/HeetKit` |

On **Desktop**, use **Settings → Data & diagnostics → Open profile folder** or
**Copy path** to find the active profile. Headless uses its selected `--data-dir` or
environment profile; Docker uses the [mounted profile volume](docker.md#run-and-inspect).
Browser management does not open server folders. Profiles contain private data;
do not attach them to public issues.

Profiles keep separate settings, commands, personalities, profile instructions,
filters, activity databases and Twitch authorization. An alternate profile can be
selected at launch:

```powershell
.\HeetKit.exe --data-dir C:\BotProfiles\Example --stopped
```

For source launches, use `python -m app.main` with the same options. `--stopped` prevents
automatic connection. `--data-dir` takes priority over `HEETKIT_DATA_DIR`; the legacy
`TWITCH_BOT_DATA_DIR` override is used only when the HeetKit variable is absent.
Each alternate profile needs its own setup. Desktop keyring credentials are associated
with its resolved location, so moving it requires entering them again. The local guard
allows only one Desktop or Headless process per profile. Desktop authorization flows
share the OAuth callback port; Headless disables that listener. Copies or separate hosts
are not protected by the local guard; avoid duplicate connections for one Twitch account.

The portable build keeps its profile in app-data too; copying the application folder
does not transfer settings or credentials. Upgrades, same-version reinstalls and
uninstall retain the profile and OS-stored credentials. On Desktop, quit using **tray
Exit** before upgrading, uninstalling or making a backup. For Server, stop the running
process/service or container; see [Docker backup and recovery](docker.md#backup-restore-and-updates).

Older default `TwitchBot` profiles are imported once into HeetKit, with existing HeetKit
files taking priority. The old profile is retained. Alternate profiles do not import
the old default profile. If migration fails, keep both profiles backed up and resolve
the reported conflict with the application stopped.

## Daily local aggregates

**Analytics** on either host shows Today / 7 / 30 / 60 UTC calendar-day totals,
trends and command/provider breakdowns for the configured channel. Its retained-user
card is a current snapshot, not historical daily unique viewers. Playground usage is
separate and excluded from channel totals.

The separate `<database-name>.analytics.sqlite3` file holds daily counters, channel IDs,
bounded command/provider/model dimensions and observation metadata. It contains no
viewer identities, chat bodies, prompts/replies, provider payloads or request IDs.
Rows expire after 60 UTC calendar days, even when collection is disabled. Nothing is
uploaded, and this file is excluded from portable configuration exports.

Attempts, execution starts and terminal outcomes are different facts. Skips are not
execution errors; generated text is not confirmed delivery. Missing usage is unknown,
not zero. Cached/reasoning token breakdowns are subsets, not extra totals to add twice.
Spend is a dated **known USD subtotal**, never an invoice or account balance. The page
marks missing usage/pricing, disabled/disconnected periods, drops and incomplete windows.
It does not infer audience activity during downtime or reconstruct historical users.

Updates are buffered and written in bounded batches off the command loop. Crashes,
full buffers and write failures can lose updates; coverage is not exactly-once billing.
Opt-outs exclude pending/late identifying work and usage, but fresh provider calls may
still cost money. Anonymous totals have no per-viewer contribution ledger. Small buckets
can still identify someone when combined with other information: keep them private and
reset the collection if necessary when handling a request.

**Collect analytics** saves immediately. **Reset all profile analytics** requires
confirmation and clears every channel plus Playground, including pending updates.
It does not erase personal history, opt-outs, credentials or settings. Backups need
separate review: restoring an old aggregate file restores its old totals.

The operator may also remove only the identified analytics file and its matching
`-wal`/`-shm` sidecars with the whole application stopped. Startup creates an empty store.
Do not delete the personal database to reset Analytics; that would also lose opt-outs.

## Credentials and local data

| Location | What it contains |
| --- | --- |
| `config/` | Settings, commands, personalities, instructions, restrictions and filters |
| `data/heetkit.db` | Channel-scoped presence/AI history, profile-wide opt-outs and migration metadata |
| `auth/twitchio_tokens.json` | Twitch access/refresh tokens |
| `auth/server_credentials.json` | Server browser-managed secrets and provider keys |
| OS keyring | Desktop client secret/provider keys; separate from profile backups |

These files and their recovery copies are private. Linux Server credential writes use
owner-only directories/private files, but are **not encryption at rest**. Protect the
host, volume and backups. Desktop keyring values take priority over intentional process
environment fallbacks. Server nonempty environment/`_FILE` credentials take priority over
browser-managed values and cannot be replaced through the panel. HeetKit does not load
`.env` files. See [process configuration](development.md#advanced-process-configuration).

Logs on Desktop and authenticated Server show permitted command input/reply attempts,
outcomes and fixed lifecycle events. Ordinary chat text, provider payloads, reasoning,
rejected AI output and raw exception prose are excluded. Opt-outs suppress later
request diagnostics too; already captured logs need separate operator handling.

The live feed is memory-only: at most 500 entries / 1 MiB, with bounded text/excerpt
markers. Clear view clears the display, not the backend buffer or saved history.
Confirmed export creates a private JSON snapshot outside automatic retention; review
it before sharing and delete it separately. Console/service/Docker logs also need
an operator retention policy. HeetKit creates no application log files.

Temporary cooldown/correlation state uses bounded account/message-ID caches, not a
chat archive. Correlation tracks replay/echo/uncertain-send decisions and automatically
reports pause expiry. Sanitized client/socket/session references and readiness flags
help diagnosis without raw Twitch IDs or chat text. Duplicate counts alone do not
prove lost commands. Only a transport-confirmed AI reply becomes delivered memory.

Browser/native UI drafts and Playground results stay in memory. The app does not use
cookies, localStorage, sessionStorage or IndexedDB for its application state; browser
engines and external OAuth pages may keep their own data. Close the UI to clear drafts.

Credentials, saved channels, access rules, notes and custom text do not receive the
personal database's 60-day expiry. Review these, old profiles, exports and recovery
copies separately when handling privacy requests. Portable configuration excludes
credentials, authorization, personal history, opt-outs and private access policy.

## Private command restrictions

`config/command_restrictions.json` is a separate version-2 private policy store in the
active profile. It stores numeric user/channel IDs, a creation-time login label, stable
command IDs, absolute UTC expiry (or permanent), and an optional 200-character note.
Version-1 rules load with channel scope and upgrade on the next save, preserving notes,
expiry and identities. This policy remains separate from SQLite privacy suppression.

Rules enforce access within their saved channel/profile, except explicit global AI-only
rules, which cover stable `ask` identity across profile channels. Legacy AI blocks migrate
to permanent channel `ask` rules using deterministic IDs, making interrupted moves
repeatable without duplicate rules or loss of existing notes. Username-only blocks remain
explicit unresolved rows; login compatibility denies AI until verified through authenticated
Twitch lookup/recent observation or matching authenticated chat identity. Once bound, only
the numeric ID matches, protecting against login reuse. Missing configured channel is a
visible pending state retaining old profile-wide AI protection until configuration permits
binding. Operators can inspect, retry verification and remove these rows in User restrictions.
Old portable archives' AI blocks merge through this migration during the existing import
transaction; existing private rules are preserved. Consolidated rules are never exported.

Expired rules stop matching
at the expiry boundary even before physical cleanup. Startup, management reads and saved
changes remove expired entries and their notes from the active file; removing a rule
takes effect immediately after a successful save. No queued request is replayed.
Malformed/unsupported policy stops startup without dropping rules or overwriting the
file; back up and repair it while stopped. Saves are atomic and publish only after
replacement succeeds. Limits are 1000 active rules and 1 MiB of policy data.

Private notes never enter chat, AI requests, public help or portable command presets.
Portable configuration export omits all personal command restrictions; imports preserve
the destination's policy and reject an injected restriction section. A stopped whole-profile
backup or move includes this file and retains its numeric channel scopes. Treat it and
any manually retained/recovery copies as private operator policy. Expiry/removal cannot
erase external copies. Self-service data opt-out does not remove access rules/notes;
operators manage those separately. Existing profile-wide storage/log suppression and
self-only `!optout` access remain in force.

## AI processing and memory

AI chat sends the current question, shared/profile/personality instructions and
available stream category to the selected Gemini, DeepSeek or OpenAI provider. If
memory is enabled, up to M recent successful exchanges for that viewer/channel are
included. A configured cross-provider fallback may receive the same permitted context
only after explicit consent. Search can also send context to the provider's tools.

HeetKit does not attach a separate Twitch viewer-ID/username identity field, but the
text itself can identify people. The provider receives its key and ordinary network
connection information. Provider retention/terms are independent of local deletion.
OpenAI requests use `store: false` and no server conversation history; that is not a
promise about every provider's retention. Thinking/tool continuations are not saved
as chat or memory. Required source attribution is preserved or the answer is withheld.
See [AI setup](ai-setup.md#thinking-search-and-fallback-boundaries).

Playground works on Desktop and authenticated Server. It makes real provider requests
with the applied instructions/filters, but no viewer memory, stream category or chat
activity; results are not saved as test cases. It consumes provider quota and proves
no Twitch delivery. Filter Tester runs locally without a provider request.

Twitch receives authorization/refresh, account/channel/category/follower lookups and
outgoing messages; incoming chat arrives through EventSub. Role/follower checks are
transient, not a stored viewer-role profile. Weather sends the place query to
Open-Meteo geocoding, then coordinates to its forecast service. Desktop's manual
update check contacts GitHub's public release API without profile/chat credentials.

Turning memory off stops subsequent reads/writes, while older pairs remain subject
to count limits, 60-day expiry and deletion. `!erase <username>` clears a known
viewer's AI memory in the current channel; it does not remove presence or suppress
future storage. Use `!optout` or the operator privacy procedure for that broader scope.

Do not put secrets or unnecessary personal information in prompts, instructions or
chat. Keep profile folders, databases, tokens, recovery copies and unredacted logs
private. Local deletion does not send a Twitch/provider deletion request.

## Manual privacy requests

Viewers can use the self-only `!optout` command. The operator handles access, correction,
deletion without suppression, verified withdrawal and requests covering other copies.
Verify control of the Twitch account through an authenticated message from that
account, and resolve its stable numeric ID using Twitch's authenticated account
lookup or an already verified record. A supplied display name or screenshot alone
is insufficient: names can change or be reused. Collect only the verification
information needed, keep any request record private, and assess applicable response
deadlines and exceptions using the [ICO individual-rights guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/).

1. Identify every profile used for this viewer. On **Desktop**, find the active path
   in **Settings → Data & diagnostics** and quit fully with **tray Exit** (or exit
   the application on platforms without a tray). On **Headless/Server**, locate the
   selected private profile or mounted volume and stop its process/service/container,
   preventing automatic restart during maintenance. Follow the [Docker storage and
   recovery procedure](docker.md#backup-restore-and-updates) for volume access.
   Close every process using the database; stopping only the Twitch bot leaves SQLite
   and retention active. Process exit clears backend session logs/pending requests;
   close the desktop/browser interface to clear its drafts and displayed logs too.
   Review separately captured console/container output.
2. Use `scripts/privacy_request.py` from the matching source version with Python
   3.12 or later against that stopped profile's actual SQLite file. It needs only
   Python's standard library. Desktop example, after
   replacing the path and synthetic ID below with the verified target:

   ```powershell
   python scripts/privacy_request.py --database "C:\BotProfiles\Example\data\heetkit.db" --user-id 123456 --action opt-out
   ```

   `opt-out` atomically adds the minimal ID suppression record and deletes matching
   rows from **both** `users` and `ai_memory_entries`. `delete` deletes those rows
   without adding an opt-out; later activity may be stored again. It preserves an
   existing opt-out. `opt-in` removes only the suppression record after verified
   withdrawal; it does not restore deleted history. Repeating an action is safe.
   The tool requires an existing, initialized privacy-enabled database and refuses
   an invalid/non-numeric ID, missing path, unsupported version or running database.
   Legacy upgrades may first require the explicit channel mapping below.
   The tool also applies the request to this database's migration recovery snapshot;
   it creates no backup. Other copies still require separate handling.
   Server/Docker paths refer to the selected profile's `data/heetkit.db`; do not use
   the Desktop example path. Preserve mounted-file ownership/permissions. Advanced
   desktop `DATABASE_URL` deployments must supply their actual SQLite file.
3. Verify privately in a SQLite client, using parameterized queries for that ID:
   `SELECT COUNT(*) FROM users WHERE twitch_user_id = ?` and
   `SELECT COUNT(*) FROM ai_memory_entries WHERE twitch_user_id = ?` must both be
   zero. After `opt-out`, the corresponding count in `privacy_opt_outs` must be one.
   Retain this suppression record; deleting the whole database removes opt-outs.
4. Review configuration text/blocks, recovery files, old `TwitchBot` profiles,
   backups and console captures for the same person. Remove unnecessary personal
   data there and handle Google/Twitch requests separately. Expiry and the tool do
   not edit these copies. Before restoring any backup, reapply current deletions
   and suppression records **before restarting the bot**, so old data or opt-outs
   cannot be resurrected. Do not create an indefinite undeleted backup merely to
   process a deletion.
5. Restart and confirm the outcome to the verified requester privately. Explain
   the local scope, the minimal retained suppression ID and any unresolved provider
   deletion. The `!erase` command remains AI-memory-only and is insufficient for
   a full privacy request.

## Legal assessment and open questions

For each instance, record an operator LIA outline using the ICO's
[purpose, necessity and balancing tests](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/legitimate-interests/what-is-the-legitimate-interests-basis/)
(link checked 2026-10-29):

1. **Purpose:** identify the operator, contact/notice location, specific benefit and
   separate purposes of presence and AI memory; assess provider disclosure separately.
2. **Necessity:** explain why stable IDs, each field, N/M and the chosen windows are
   needed; consider less data, shorter retention or disabling memory.
3. **Balancing:** consider viewer expectations, children, sensitive text, provider
   access and harms; document safeguards, `!optout`, objection/deletion handling,
   the decision and when it will be reviewed. Publish the operator's contact and
   a link to this notice in channel information or a chat notice.

This outline grants no blanket legitimate-interest approval. The maximum 60-day
policy does not establish necessity; the ICO's
[storage-limitation guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/storage-limitation/)
requires an operator-specific retention justification.

Reviewed against the linked primary guidance/terms on **2026-10-13**. This is an
engineering assessment; instance-specific legal clearance remains open.

- **UK GDPR:** The operator ordinarily determines purposes and means and should
  assess their controller obligations. Public or commercial streaming should not
  assume a household exemption. Legitimate interests may support necessary chat
  operation, subject to a recorded purpose, necessity and balancing assessment,
  including reasonable expectations and children. It is not automatic permission
  for sending viewer text to AI. Consent, where chosen, needs a valid withdrawal
  process. Resolve the basis for each use and any sensitive data before processing.
  See [ICO legitimate interests](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/legitimate-interests/what-is-the-legitimate-interests-basis/).
- **Retention:** 60-day AI age and 60-day presence inactivity are product choices,
  not statutory periods. Only M exchanges are used at a time, so retaining older AI
  history under N requires operator justification. Document why these windows
  are proportionate for the actual community, delete sooner when unnecessary,
  and review backups and suppression IDs. The software has no shorter-window UI;
  operators can disable memory or manually delete data. See
  [ICO storage limitation](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/storage-limitation/).
- **ICO fee:** A UK operator must complete the [fee self-assessment](https://ico.org.uk/fee-checker)
  and pay/register if required. Free software, local storage and small channels do
  not establish an exemption. Eligibility depends on the operator's processing;
  review [ICO exemptions](https://ico.org.uk/for-organisations/data-protection-fee/data-protection-fee/exemptions/).
- **Twitch permissions:** The [Developer Services Agreement](https://legal.twitch.com/en/legal/developer-agreement/)
  restricts third-party sharing without prior written permission and requires
  end-user-data deletion on specified requests/authorization changes, including
  downstream copies. Treat transmitting API-derived chat/history/category to
  Gemini as potentially covered; a viewer's `!ask` or bot OAuth is not proof of
  Twitch's permission. No such written approval was verified. Confirm applicable
  storage/caching limits, including Schedule 1's application to these 60-day
  records, and any exceptions with Twitch. The current page's full body was not
  readable in the research tool; indexed current sharing/deletion clauses were
  checked, but retention permissions remain unresolved. Local suppression-ID
  retention and provider deletion also require resolution; automatic revocation
  cleanup is not implemented. Disable AI use until required permissions are settled.
- **Google:** [Gemini terms](https://ai.google.dev/gemini-api/terms) require adult
  API users and prohibit clients likely accessed by under-18s. Regional end-user
  availability in the UK/EEA/Switzerland requires Paid Services. Unpaid input/output
  may improve Google products and receive human review; UK/EEA/Swiss account data
  has the terms' paid-data-treatment exception. Paid input/output is not used for
  product improvement, but limited abuse logs and international processing remain.
  Confirm billing status, audience eligibility, the incorporated
  [processor addendum](https://business.safety.google/processorterms/), transfer
  safeguards and deletion assistance. Search grounding separately retains
  prompt/context/output for 30 days and imposes display/storage restrictions;
  the current truncated chat output and stored history have not been cleared
  against those restrictions. These unresolved checks can preclude public AI use.

## Portable configuration transfer

Use **Settings → Configuration transfer → Export Configuration** on Desktop or
Server to save the same versioned ZIP (Desktop opens a native Save dialog; the
browser downloads it). It contains the currently applied
built-in command settings and response pools, custom commands, personality prompts
and selection, profile instructions, AI memory/model/language preferences, filters,
message triggers and saved ordinary-chat announcements. Applied session-only edits are included;
unfinished editor drafts are not. Import saves these values on the destination.

Built-in settings include their primary chat names and aliases, keyed by stable
factory command IDs. Renaming does not change which implementation or permission
floor the imported settings control. Older archives without primary names restore
factory triggers while retaining their other command settings. Invalid or conflicting
names reject the import before any replacement.

Server exports include per-command stream availability. Desktop exports omit this
Server-only preference. When an older or Desktop ZIP omits availability, import
preserves the destination's policy for each matching built-in or custom command
(custom ID first, then canonical name); new commands default to Anytime. An
explicit policy in a Server ZIP replaces that value, including explicit Anytime.
Desktop can retain imported policies but never enforces them.

Announcements carry their stream availability on both hosts. Their saved text,
intervals and activity thresholds transfer; deadlines, activity counters and send
status do not. Import restarts enabled schedules with a full interval. Older ZIPs
without an announcements section preserve the destination's schedules; an explicit
empty collection in a new ZIP removes them. Announcement activity uses only a
transient count of eligible events, with no additional viewer/message archive.

Select the ZIP in Settings on the other instance, review the included names/counts,
replacement scope and preserved settings, then explicitly confirm the import.
Each included collection replaces its destination collection, including deletions.
The preview expires after ten minutes and must be repeated if the ZIP, active
configuration or affected files change. A successful import refreshes the interface
to discard old editor drafts. Subsequent bot processing uses the imported settings
immediately; in-flight replies may finish using earlier values. None of the supported
transfer settings requires reconnection or restart.

Provider/API keys, OAuth tokens, management credentials, SQLite history and storage
opt-outs, machine paths, Twitch identity/channel/presets, headless operation mode,
desktop startup/window preferences and operator cooldown-bypass policy are excluded and preserved on the
destination. Set up authorization and secrets separately. Text you enter in prompts,
commands or filters can still be private: review and protect the ZIP before sharing it.
Legacy archives can include AI blocks with usernames/account IDs; these merge into
the destination's private channel restrictions. New consolidated restrictions and
their private notes are excluded; existing destination rules are preserved. This is portable configuration,
not a full private profile backup or an account migration.

AI transfer includes the selected provider and separate primary/fallback choices for
Gemini and DeepSeek. Legacy Gemini archives select Gemini explicitly and preserve
the destination's DeepSeek choices. A model in the wrong provider's namespace is
rejected rather than reinterpreted. No provider key is included.

The ZIP is limited to 1 MiB and contains only `manifest.json` and
`configuration.json` (at most 768 KiB). Unsupported schemas, unexpected files,
duplicate names/keys, invalid values, linked entries, traversal paths, excessive
compression and oversized content are rejected before changing configuration.
Contents are read in memory; archive paths are never extracted into the profile.

Import retains exact copies of affected configuration under
`config/import-backups/configuration-<unique-id>/`, with a generated manifest recording
relative destination paths and which files were previously absent. Existing recovery
preflight still refuses malformed/unreadable/future-version local files. All replacement
files are staged before writes, and live state publishes after successful replacement.
On an ordinary write/publication failure, import attempts to restore original files
and active settings, including prior session-only changes. A process/power failure
between file replacements or a storage failure during rollback can require manual
recovery: stop the application, preserve current files, and restore the affected files
listed in the backup manifest (remove only those recorded as previously absent), then
restart. Multi-file replacement is not a filesystem-wide crash-atomic transaction.
Keep these private backups until satisfied with the import, then delete unwanted
copies according to your retention/deletion policy; they are not automatically removed.

## Backups and settings recovery

### Versioned database upgrade and recovery

Desktop and Server run the same versioned SQLite upgrade before Twitch, requests or
cleanup workers start. Fresh databases start at schema version 2. Version 1 upgrades
transactionally by adding nullable opt-out username/date metadata, without changing
existing suppression IDs or inventing historical dates. A verified `schema-1.sqlite3`
snapshot supports recovery under the same seven-day/privacy rules as schema 0.
New chat/operator opt-outs store authenticated/resolved usernames and actual UTC dates;
repeated requests preserve the original date, including unknown historical dates.
The management list formats dates in the operator's local time and marks unavailable
historical usernames honestly. Confirmed withdrawal permits only future storage;
captured requests retain invalidated storage/log tickets after withdrawal.
Existing unversioned
presence/AI tables require an explicit mapping for their unscoped rows; the selected
startup channel is never used as a guess. **Desktop** opens a one-time confirmation
form only when recognized legacy history needs a mapping and the input file is absent.
The configured target is offered as a suggestion; it requires an explicit acknowledgement
and confirmation, or you can enter another numeric channel ID verified with Twitch.
**Confirm channel and continue** saves the private profile-local choice and resumes
the normal verified upgrade. **Cancel and exit** leaves the choice unsaved. Normal
controls, Twitch and cleanup workers remain blocked until startup succeeds. Existing
invalid mappings, backup failures and other migration errors show actionable guidance;
they do not trigger an inferred mapping or overwrite an existing choice.

**Server**, or optional manual Desktop preparation: with all profile processes stopped,
create `data/legacy-channel-mapping.json` beside the actual database, for example:

```json
{"version": 1, "channel_id": "123456"}
```

Use the channel's verified numeric Twitch ID and keep this input private. A historical
attribution approximation must be an explicit operator decision. Already-scoped rows
keep their channels. The upgrade preserves original timestamps/text/IDs, retains every
suppression ID, excludes opted-out/expired/over-count rows with separate aggregate
counts, checks fields/uniqueness/relationships, and commits data plus version together.
It does not fabricate command executions or analytics. Unsupported/corrupt schemas,
unexplained loss or failed backups stop startup without resetting the database.

Before transformation, SQLite's backup API creates one verified recovery database
under `data/<database-name>.recovery/schema-0.sqlite3`, with private JSON counts,
checksum and fixed expiry. WAL contents are included. Failed transactions roll back;
the verified backup remains available. Successful restarts do not remigrate or make
another migration backup. Resolve any incomplete/unverifiable recovery copy while
stopped before retrying; never delete the profile database to bypass a failed upgrade.

This recovery copy has a **seven-day acceptance window**, fixed from creation and
never extended by startup, use or a privacy request. Startup/hourly cleanup removes
it at expiry (catch-up after downtime); do not restore/use an expired snapshot.
The same cleanup also handles an expired verified snapshot when retrying an interrupted
upgrade. Only the owned, manifest-verified `schema-0`/`schema-1` SQLite/JSON pairs are
removed; unrelated files and unverifiable copies are retained for operator review.
`!optout` and the offline privacy tool scrub applicable personal rows in that copy;
opt-out preserves suppression, deletion alone adds no suppression, and verified
opt-in removes only the marker. A failed recovery scrub leaves live suppression in
place; hourly cleanup retries opt-outs. Other backups, exported logs and copied
profiles require operator handling, with a fixed expiry no later than 60 days from
creation and earlier deletion where required. They are restricted recovery copies,
not extra model history.

Do not run an older binary against the upgraded database. Rollback across this schema
change requires the matching pre-upgrade snapshot and a compatible binary, with all
writers stopped. Preserve the current database first; account for post-upgrade writes
and reapply current deletions/suppression before any connection. Do not overwrite
unrelated settings, credentials or token rotations with an old whole-profile copy.
These steps describe a controlled recovery operation, not an automatic downgrade.

### Whole-profile and settings copies

Stop every process using the profile before copying it. Desktop uses **tray Exit**
or application exit; Server uses service/container shutdown. A management **Stop bot**
does not close the database. Protect backups like the original; Desktop keyring
credentials and Server injected secrets are outside the profile copy; Server
browser-managed credentials and OAuth tokens are inside it. Keep a backup
before manual edits, moving profiles or restoring old settings. Use the
[Docker guide](docker.md#backup-restore-and-updates) for volume backup/restore,
ownership, secret backup and rollback procedures.

Unreadable, malformed or unsupported settings files are left intact; UI saves, resets
and deletes refuse to replace them. To repair one, stop the app, back up the named file,
then repair it or move only that file aside and restart to restore its defaults.
Leave unrelated settings, database and authentication data in place.

When a save cannot retain every original setting, HeetKit preserves the exact original
beside it as `<filename>.<unique-id>.recovery`; Logs reports the path. These copies are
private and are not automatically deleted. To restore one, exit, back up the current
settings file, copy the recovery file over its original filename, then restart.

For suspected credential exposure, revoke or rotate the credential at the provider and
follow [SECURITY.md](../SECURITY.md).

[Back to README](../README.md#documentation).
