# Data, profiles and privacy

HeetKit keeps settings and chat data locally, outside its installation folder.
Twitch and optional Gemini features communicate with their respective providers.

## Profiles

The default profile location is:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\HeetKit` |
| macOS source launch | `~/Library/Application Support/HeetKit` |
| Linux source launch | `${XDG_DATA_HOME:-~/.local/share}/HeetKit` |

In **Settings → Data & diagnostics**, use **Open profile folder** or **Copy path** to
find the active profile. It contains private data; do not attach it to public issues.

Profiles keep separate settings, commands, personalities, profile instructions,
filters, activity databases and Twitch authorization. An alternate profile can be
selected at launch:

```powershell
.\HeetKit.exe --data-dir C:\BotProfiles\Example --stopped
```

For source launches, use `python -m app.main` with the same options. `--stopped` prevents
automatic connection. `--data-dir` takes priority over `HEETKIT_DATA_DIR`; the legacy
`TWITCH_BOT_DATA_DIR` override is used only when the HeetKit variable is absent.
Each alternate profile needs its own setup. Credentials are associated with its resolved
location, so moving it requires entering them again. Only one desktop instance can open
the same profile at a time. Separate profiles share the OAuth callback port and can use
the same Twitch account; avoid simultaneous authorization flows or duplicate bot connections.

The portable build keeps its profile in app-data too; copying the application folder
does not transfer settings or credentials. Upgrades, same-version reinstalls and
uninstall retain the profile and OS-stored credentials. Quit using **tray Exit** before
upgrading, uninstalling or making a backup.

Older default `TwitchBot` profiles are imported once into HeetKit, with existing HeetKit
files taking priority. The old profile is retained. Alternate profiles do not import
the old default profile. If migration fails, keep both profiles backed up and resolve
the reported conflict with the application stopped.

## Credentials and local data

Within the profile, `config/` holds JSON settings, commands, personalities, AI blocks
and reactions, plus editable filter text in `config/filters/`. Activity and AI memory
use `data/heetkit.db`; Twitch authorization uses `auth/twitchio_tokens.json`.

- Gemini keys and Twitch client secrets entered in Settings use the OS keyring
  (Windows Credential Manager on Windows). They are separate from profile backups.
- Twitch access and refresh tokens are stored in the profile's `auth/` directory.
- The local database contains Twitch user IDs, usernames, last-seen timestamps and
  recent successful AI exchanges when memory is enabled.
- Blocked AI users are saved as normalized logins and, when available, verified
  Twitch account IDs in this profile's `config/ai_user_blocks.json`.
- Settings, personality prompts, profile instructions, custom replies, filters and
  recovery copies can contain private community information.
- The Logs page can contain chat and diagnostic details. Recent logs stay in memory;
  source launches also write console diagnostics. HeetKit does not create application
  log files. Clear affects only the displayed entries, leaving the backend buffer and
  stored activity intact.

Advanced deployments can provide process environment credentials; stored keyring
values take priority. HeetKit does not load `.env` files. See
[development configuration](development.md#advanced-process-configuration).

## AI processing and memory

Twitch AI requests send the chatter's prompt, protected shared instructions, profile
instructions and the selected personality prompt to Google, with the current stream
category when available. When memory is enabled, up to five recent successful exchanges
for that chatter are included too. Requests needing current information may use Google
Search grounding. Credential **Test** and **Discover
models** also contact Google. Google's terms and data handling apply; see the live
[Gemini pricing and data-use information](https://ai.google.dev/gemini-api/docs/pricing).

The **AI Playground** makes real Gemini requests with the same instructions and output
checks, but sends no viewer memory or stream category and writes no chat activity or AI
memory. Prompts and results are not saved as test cases. **Filter Tester** runs locally
without contacting Twitch or Google. See [AI setup](ai-setup.md#test-locally-with-ai-playground)
and [filter testing](commands.md#test-filters-locally).

The `!weather` command sends the supplied place query to Open-Meteo's geocoding
service, then sends the returned coordinates to its forecast service.

**About → Updates → Check for updates** contacts GitHub's public release API only when clicked.
It sends a standard request for HeetKit's latest stable release, without GitHub
authentication, chat content, profile paths or provider credentials. The version
comparison happens locally, check results are not saved to the profile, and saved
settings and profile data remain unchanged. GitHub
receives ordinary connection information such as your IP address. **Open release /
downloads** opens the official release page in your browser; browser privacy settings
apply there. See [update checking](release-process.md#check-for-updates).

Turning memory off stops using and saving exchanges for subsequent requests; existing
exchanges remain stored. The broadcaster-only `!erase <username>` command deletes
stored AI memory for a known user. It does not remove that user's activity record.
See [commands](commands.md) and [AI setup](ai-setup.md).

Do not put secrets or private information into AI prompts or chat sent to Google.
Avoid sharing profile folders, database files, tokens, recovery copies or unredacted logs.

## Backups and settings recovery

Exit HeetKit fully before copying the profile. Protect backups like the original;
OS keyring credentials are not included in a folder copy. Keep a backup before manual
edits, moving profiles or restoring old settings.

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
