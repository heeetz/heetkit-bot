# Data, profiles and privacy

HeetKit keeps settings and chat data on the operator's computer or server, outside
its installation folder.
Twitch and optional Gemini features communicate with their respective providers.

## Privacy notice for viewers

The operator of the bot in your Twitch channel chooses its settings and handles
privacy requests. Contact that channel's bot operator through their published
contact route for access, correction, deletion, objection or a local storage opt-out.
The HeetKit software developer receives no automatic telemetry, viewer database,
chat history or profile uploads. If the developer operates a bot instance, they are
the operator of that instance. Information you voluntarily send in an issue or
support request is separate; never attach a private profile or unredacted logs.

The bot uses Twitch account IDs, usernames and first/last-seen times for chat
features such as last-seen lookup and recent-viewer replies. Successful, delivered
AI questions and answers are saved locally when conversation memory is on. That
history expires after **90 days**; only the **five most recent unexpired exchanges
per viewer** are sent as Gemini context. Viewer records expire **180 days after
their last recorded activity**. These are maximum application retention windows,
not permission to retain data that is no longer needed.

Expiry uses UTC elapsed time. Expired records are excluded from lookups immediately;
physical database cleanup runs at application startup and hourly while the application
process runs, including Desktop in the tray and Headless/Server. It continues when the
Twitch bot is stopped or memory is off. Removal can lag expiry by one cleanup interval;
when the process is stopped, overdue cleanup waits until its next startup. Desktop
cleanup failures appear in Logs. Headless/browser diagnostics are filtered to lifecycle
events and do not expose retention-cleanup failures. Backups and older profile copies
require separate operator handling. Deletion is logical removal, not a promise of forensic
erasure from disks, journals or provider systems.

AI prompts, instructions and optional context go to Google; bot replies go to the
Twitch channel. A storage opt-out deletes that viewer's local activity and AI history
and prevents future writes to both database collections, including after a rename
or restart. It retains only their Twitch ID as a suppression record until the
verified viewer withdraws the opt-out or the operator retires the profile. It does
not disable chat commands, Twitch processing or fresh Gemini requests. Ask the
operator to also use **AI → AI access** if you want your `!ask` requests ignored.
Opted-out requests are excluded from HeetKit's session log buffer and configured
console handlers; necessary transient command state is described below.
Local requests cannot delete Twitch's chat or Google's copies.

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

## Credentials and local data

Within the profile, `config/` holds JSON settings, commands, personalities, AI blocks
and reactions, plus editable filter text in `config/filters/`. Activity and AI memory
use `data/heetkit.db`; Twitch authorization uses `auth/twitchio_tokens.json`.

- On Desktop, Gemini keys and Twitch client secrets entered in Settings use the OS keyring
  (Windows Credential Manager on Windows). They are separate from profile backups.
- Twitch access and refresh tokens are stored in the profile's `auth/` directory.
- The local database contains Twitch user IDs, usernames, first/last-seen timestamps,
  successful AI exchanges when memory is enabled, and minimal storage opt-out IDs.
  `users`, `ai_memory_entries` and `privacy_opt_outs` are separate tables.
- Blocked AI users are saved as normalized logins and, when available, verified
  Twitch account IDs in this profile's `config/ai_user_blocks.json`.
- Settings, personality prompts, profile instructions, custom replies, filters and
  recovery copies can contain private community information.
- Desktop Logs can contain chat and diagnostic details. Recent logs stay in memory;
  desktop source launches also write console diagnostics. Headless stderr and browser
  logs expose filtered lifecycle diagnostics; captured service/container logs need their
  own access and retention policy. HeetKit does not create application
  log files. Clear affects only the displayed entries, leaving the backend buffer and
  stored activity intact.
- Cooldowns temporarily use account IDs in memory, and stream-category lookup has a
  90-second memory cache. Frontend drafts, Playground results and up to 500 displayed
  log entries live in React memory. The backend log buffer also holds at most 500
  entries until displaced or process exit. No application use of localStorage,
  sessionStorage, IndexedDB or cookies was found. The embedded browser and an external
  browser used for OAuth or links may maintain their own engine data.
  Opted-out requests suppress application diagnostics for that asynchronous request,
  including its command replies/errors, while other viewers' diagnostics continue.
  External logging integrations and already captured output require operator review.
- AI blocks, connection presets, optional cooldown-exception IDs and private text in
  settings/recovery copies are operator-managed configuration, with no automatic
  90/180-day expiry. Review them separately when handling a privacy request.

Desktop can use intentional process environment credential fallbacks; stored keyring
values take priority. Headless uses private environment or `_FILE` inputs without
reading the keyring. HeetKit does not load `.env` files. See
[development configuration](development.md#advanced-process-configuration) and
[server secret provisioning](docker.md#prepare-private-storage-and-authorization).

## AI processing and memory

Twitch AI requests send the chatter's prompt, protected shared instructions, profile
instructions and the selected personality prompt to Google, with the current stream
category when available. When memory is enabled, up to five recent successful exchanges
for that chatter are included too. Requests needing current information may use Google
Search grounding. Credential **Test** and **Discover
models** also contact Google. Google's terms and data handling apply; see the live
[Gemini pricing and data-use information](https://ai.google.dev/gemini-api/docs/pricing).
The transport does not attach the viewer's Twitch ID or username as a separate
Gemini identity field, but prompts, history and operator instructions can themselves
identify people. Google receives the API key and ordinary connection information.
Local expiry/deletion does not send a provider deletion request.

Twitch receives OAuth/refresh requests, authorized bot/channel IDs, category,
followage and account-lookup requests, and outgoing messages. Incoming chat is
received through Twitch EventSub. Permissions, VIP/moderator/subscriber flags and
followage results are used transiently rather than saved as viewer profiles.

The Desktop-only **AI Playground** makes real Gemini requests with the same instructions
and output checks, but sends no viewer memory or stream category and writes no chat activity or AI
memory. Prompts and results are not saved as test cases. **Filter Tester** runs locally
without contacting Twitch or Google. See [AI setup](ai-setup.md#test-locally-with-ai-playground)
and [filter testing](commands.md#test-filters-locally).

The `!weather` command sends the supplied place query to Open-Meteo's geocoding
service, then sends the returned coordinates to its forecast service.

On Desktop, **About → Updates → Check for updates** contacts GitHub's public release
API only when clicked.
It sends a standard request for HeetKit's latest stable release, without GitHub
authentication, chat content, profile paths or provider credentials. The version
comparison happens locally, check results are not saved to the profile, and saved
settings and profile data remain unchanged. GitHub
receives ordinary connection information such as your IP address. **Open release /
downloads** opens the official release page in your browser; browser privacy settings
apply there. See [update checking](release-process.md#check-for-updates).

Turning memory off stops using and saving exchanges for subsequent requests; existing
exchanges remain until expiry or deletion. The broadcaster-only `!erase <username>` command deletes
stored AI memory for a known user. It does not remove that user's activity record.
See [commands](commands.md) and [AI setup](ai-setup.md).

Do not put secrets or private information into AI prompts or chat sent to Google.
Avoid sharing profile folders, database files, tokens, recovery copies or unredacted logs.

## Manual privacy requests

Requests are handled by the operator, not by a new chat command or management UI.
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
   an invalid/non-numeric ID or missing path. Launch the updated application once
   to initialize the added table, then stop the process before applying a request.
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
- **Retention:** 90 days supports returning-viewer continuity; 180 days supports
  inactive-viewer last-seen lookup. These are product choices, not statutory
  periods. Only five exchanges are used at a time, so the need to keep older AI
  history for 90 days requires operator justification. Document why these windows
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
  storage/caching limits, including Schedule 1's application to these 90/180-day
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

## Backups and settings recovery

Stop every process using the profile before copying it. Desktop uses **tray Exit**
or application exit; Server uses service/container shutdown. A management **Stop bot**
does not close the database. Protect backups like the original; Desktop keyring
credentials and Server injected secrets are outside the profile copy. Keep a backup
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
