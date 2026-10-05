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
location, so moving it requires entering them again. Avoid simultaneous Twitch
authorization flows across profiles because they share the callback port.

The portable build keeps its profile in app-data too; copying the application folder
does not transfer settings or credentials. Upgrades, same-version reinstalls and
uninstall retain the profile and OS-stored credentials. Quit using **tray Exit** before
upgrading, uninstalling or making a backup.

Older default `TwitchBot` profiles are imported once into HeetKit, with existing HeetKit
files taking priority. The old profile is retained. Alternate profiles do not import
the old default profile. If migration fails, keep both profiles backed up and resolve
the reported conflict with the application stopped.

## Credentials and local data

- Gemini keys and Twitch client secrets entered in Settings use the OS keyring
  (Windows Credential Manager on Windows). They are separate from profile backups.
- Twitch access and refresh tokens are stored in the profile's `auth/` directory.
- The local database contains Twitch user IDs, usernames, last-seen timestamps and
  recent successful AI exchanges when memory is enabled.
- Settings, personality prompts, profile instructions, custom replies, filters and
  recovery copies can contain private community information.
- The Logs page can contain chat and diagnostic details. Clearing its displayed entries
  does not delete stored activity or other application state.

Advanced deployments can provide process environment credentials; stored keyring
values take priority. HeetKit does not load `.env` files. See
[development configuration](development.md#advanced-process-configuration).

## AI processing and memory

AI requests send the chatter's prompt, protected shared instructions, profile
instructions, the selected personality prompt and stream category to Google. When
memory is enabled, recent exchanges for that chatter are included too. Requests needing
current information may use Google Search grounding. Credential **Test** and **Discover
models** also contact Google. Google's terms and data handling apply; see the live
[Gemini pricing and data-use information](https://ai.google.dev/gemini-api/docs/pricing).

The `!weather` command sends the supplied place query to Open-Meteo's geocoding
service, then sends the returned coordinates to its forecast service.

Turning memory off stops stored context being included in later requests; it does not
erase existing exchanges. The broadcaster-only `!erase <username>` command deletes
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
