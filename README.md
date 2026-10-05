# HeetKit

Desktop control center for Twitch chat

Created and maintained by **heeetz**. Official repository:
[github.com/heeetz/twitch-bot](https://github.com/heeetz/twitch-bot).
Discord contact: **de.tected**.

Licensed under [Apache License 2.0](LICENSE), with original attribution in [NOTICE](NOTICE).
Dependencies retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

## Overview

HeetKit controls a single-channel Twitch chatbot through a desktop interface. Windows is the first release target; the source application is designed to use supported macOS/Linux pywebview backends. It receives chat through TwitchIO EventSub, records when users were last seen, applies global and AI-specific filters, and dispatches commands with permission and cooldown checks.

Major features include:

- Twitch chat commands, role-based permissions, cooldowns, and output limiting;
- current weather through Open-Meteo;
- followage lookups through the Twitch API;
- optional Gemini responses with conditional Google Search grounding;
- per-user Gemini conversation memory in SQLite;
- configurable blocked words, phrases, and regular expressions;
- a React/TypeScript desktop control panel hosted by pywebview, with dashboard, command, AI, live-log, settings, and tray controls.

Python remains the application core. The web-style desktop shell uses React, TypeScript, Vite, pywebview, and pystray; TwitchIO, asyncio, SQLAlchemy 2 with SQLite, HTTPX, Pydantic Settings, Google Gen AI, and Open-Meteo remain behind the Python UI bridge.

## Requirements

The requirements below apply to source development. Windows installer/portable candidates bundle
Python and the frontend; they need Windows 10/11 x64, .NET Framework 4.6.2 or newer and
[Microsoft Edge WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).

- Python 3.12 or newer. Python 3.12 is the recommended baseline.
- Node.js 20.19 or newer for installing and building the frontend.
- A Twitch account for the bot and a Twitch Developer application.
- The numeric Twitch user IDs for the bot account and target channel.
- A Gemini API key only if `!ask` should produce AI responses.
- A renderer supported by pywebview. Windows normally uses the installed Microsoft Edge WebView2 runtime. macOS uses Cocoa/WebKit; Linux requires an installed GTK/WebKit or Qt backend and its system libraries. Linux users must select the matching `pywebview[gtk]` or `pywebview[qt]` extra.
- A working system keyring backend is recommended for credential storage. Advanced deployments can provide process environment overrides when needed.

## Windows installer candidate

The primary Windows distribution is one `HeetKit-<version>-windows-x64-setup.exe`.
Local installer candidates are available for manual testing; there is no public download yet.
Run setup normally for a per-user installation, without administrator rights. The wizard
shows the Apache-2.0 license and dependency notices, lets you choose a writable application
directory (default `%LOCALAPPDATA%\Programs\HeetKit`), creates Start Menu shortcuts,
offers an optional desktop shortcut, and offers to launch HeetKit when finished.

Setup checks .NET Framework 4.6.2+ and WebView2 Evergreen. When either is missing, it
provides links to Microsoft's supported downloads and waits for installation. For WebView2,
use the **Evergreen Bootstrapper** online or the **x64 Evergreen Standalone Installer**
offline, as described in [Microsoft's deployment guidance](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution).
Complete any required Windows restart before retrying setup. Python, Node.js and a source
checkout are not required on the target machine. These local candidates are unsigned;
Windows may show an unknown-publisher warning.

Application files include `HeetKit.exe`, its adjacent `.exe.config`, `_internal`, notices
and uninstall tooling. Profiles remain under `%LOCALAPPDATA%\HeetKit` and credentials
remain in Windows Credential Manager. A fresh launch seeds only missing neutral defaults
and leaves the bot stopped; existing profiles keep their saved preferences and data.

Quit HeetKit with **tray Exit** before upgrading, reinstalling or uninstalling. Run the
newer setup to upgrade in the existing application directory. Run the same version again
to reinstall its application files; there is no separate Repair command. Downgrades are
refused. To move the installation, uninstall first, then reinstall in the new directory.
Uninstall through **Settings → Apps → Installed apps → HeetKit**. Profiles, OAuth state,
databases and keyring credentials are retained, and Microsoft runtimes are left installed.
Reinstalling uses the retained profile. Setup never offers or performs profile deletion.

## Source installation

From Windows PowerShell:

```powershell
cd "C:\path\to\HeetKit"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Installation includes the tested Gemini SDK pin, `google-genai==1.75.0`. Rerun the install
command when upgrading an existing environment from the older SDK.

Install and build the frontend once:

```powershell
Push-Location frontend
npm install
npm run build
Pop-Location
```

Validate desktop configuration and frontend availability (Twitch setup can be completed after launch):

```powershell
python -m app.main --check
```

On Windows, start the desktop application from the repository root with the one-click launcher:

```powershell
.\run.bat
```

The launcher uses `.venv\Scripts\python.exe` and reports a clear error if the project virtual
environment has not been created. If dependencies change after creating `.venv`, rerun
`.\.venv\Scripts\python.exe -m pip install -e ".[dev]"` before launching. The equivalent Python command is:

```powershell
python -m app.main
```

The installed console entry point is equivalent:

```powershell
heetkit
```

On macOS/Linux, create a virtual environment, install this project, build the frontend with
`npm run build` in `frontend/`, and launch with `python -m app.main`. On Linux, install the
appropriate pywebview backend and system packages for your desktop environment. The tray and
start-minimized options currently apply to Windows; macOS/Linux keep the window visible and
close normally. No macOS/Linux distributables are provided yet.

For frontend development, run Vite in one terminal and point the Python host at it from another:

```powershell
Set-Location frontend
npm run dev
```

```powershell
python -m app.main --dev-url http://localhost:5173
```

Normal desktop launch follows the saved **Start bot automatically** preference, which defaults
off. Use `--stopped` to force the desktop shell to open without connecting even when that saved
preference is enabled. Production mode loads generated `frontend/dist/` assets; the directory
is intentionally ignored and recreated by `npm run build`.

Runtime distribution declarations include the modules under `app/config/` and the resources
under `app/resources/`, including neutral filters, triggers, personalities, models and icons.
Installed launches load prebuilt frontend files from `app/resources/frontend/`; a recognized
source checkout can use `frontend/dist/`. Both paths are independent of the working directory.
Before creating a Python distribution, stage the contents of `frontend/dist/` in
`app/resources/frontend/`. Generated frontend files remain ignored. Automatic frontend staging and
standalone freezing are implemented by the Windows build commands below; public release
automation and downloads remain separate work.

## Configuration

Configuration responsibilities remain separated:

- The desktop Settings page and profile stores are the normal configuration path. Non-secret Twitch identity, target metadata, command overrides, AI memory/personality/model preferences, and other local settings are stored under the selected profile; credentials are stored in the OS keyring. Advanced deployments and development/CI workflows can use process environment variables as defaults. Saved profile values override those defaults, and keyring credentials override process environment values.
- Non-secret behavioral defaults are defined in `app/config/commands.py` and `app/config/ai.py`. Built-in personality prompts live in the tracked `app/resources/personalities.json` resource; protected shared AI instructions and default personality construction remain application code in `app/config/personalities.py`.
- `config/command_settings.json` under the platform app-data root contains optional local command overrides. Commands without overrides continue to use registry defaults.
- `config/custom_commands.json` under that root contains versioned, local custom commands. Invalid entries are skipped and cannot disable built-in commands.
- `config/message_triggers.json` under that root contains local reactions to ordinary chat messages. It is seeded from `app/resources/default_triggers.json` when missing; edits take effect after restarting the app.
- `config/personality_settings.json` under that root contains the locally selected AI personality, prompt overrides (including user-created personality IDs), and optional `profile_instructions`. Profile instructions default to empty and apply to every personality; protected shared instructions remain application-owned and immutable.
- `config/app_settings.json` under that root is a versioned local application-settings file. It contains the
  opt-in automatic-start preference, window/tray preferences, AI memory and selected/fallback
  Gemini models, plus non-secret Twitch client ID, bot login/user ID, target-channel settings and named target
  presets. Legacy flat window settings remain readable and are rewritten in the versioned
  format on the next save.
- Apply actions take effect for the current process; Save persists local overrides; Reset restores source-controlled defaults. On first normal launch, existing checkout data is copied into the platform app-data root; the old files are left in place. Deleting the new config JSON files restores defaults on the next launch.

If upgrading from a source setup that used a `.env` file, enter Twitch identity and target values in
Settings and store Twitch/Gemini secrets through the OS keyring. The application does not migrate
or load dotenv files; advanced overrides belong in the process environment or the existing profile
stores.

The app-data root is `%LOCALAPPDATA%\HeetKit` on Windows, `~/Library/Application Support/HeetKit` on macOS, and `${XDG_DATA_HOME:-~/.local/share}/HeetKit` on Linux. It contains `config/`, `data/`, `auth/`, and `cache/`.

Legacy brand compatibility: on the first normal default-profile launch, the former
`TwitchBot` root is copied in full into HeetKit, including settings, personalities,
instructions, commands, filters, OAuth state and cache. SQLite is backed up to `data/heetkit.db`,
including any committed WAL data. The old root is retained as rollback data and is never deleted.
Existing HeetKit files take precedence; only missing files are recovered. Unsafe links or
file/directory conflicts stop startup with a migration error. Quit both versions before restoring
or repairing a profile. A `.heetkit-migration-v1` marker prevents later deleted state from being
reimported. Existing profiles also migrate their own legacy `data/twitch_bot.db` once; an arbitrary
`--data-dir` never imports the former default profile. A copied default profile skips older
checkout migration so the two imports cannot compete. Keep the markers when resetting settings.

In **Settings → Data & diagnostics**, view the resolved current profile location, choose
**Open profile folder** to open it in the system file manager, or **Copy path** to copy its
location. This uses the selected profile, including `--data-dir` and `HEETKIT_DATA_DIR`
overrides. The folder may contain private authentication and application data; do not share it.

Personality and built-in response settings belong in `config/personality_settings.json` and
`config/fun_settings.json` inside the selected profile. The `.legacy-migration-v1` marker records
a one-time migration attempt; it does not certify that these optional files exist. Missing
files use neutral defaults and are not imported again automatically. To recover customization,
quit the app, back up the profile, restore only the needed settings files into its `config/`,
and restart. Leave the marker, unrelated settings, filters, database, OAuth cache and credentials
in place. Restore editable personality styles rather than old shared/system instructions.

App, command, custom-command and personality settings still recover at startup when a file
cannot be loaded. Save, Reset and Delete refuse to replace unreadable or malformed JSON
(including duplicate keys); versioned app/custom-command files with unsupported versions also
remain untouched. To repair or reset, quit the app, back up the named file under this profile's
`config/`, then repair it or move it aside and restart. Moving aside only that JSON resets its
settings while preserving the original file, database, OAuth cache and credentials.

When a supported file contains unknown fields, skipped entries or customization not recovered
by the current session, a save first preserves its exact original bytes beside it as
`<filename>.<unique-id>.recovery`. Logs report the recovery path. These copies are private
profile data and are never automatically overwritten or deleted. To restore one, quit the app,
back up the current JSON, copy the recovery file over its original filename and restart.
Ordinary fully recovered settings retain atomic saves without creating recovery copies.

The process environment variables supported by the current application are listed below. They are
advanced defaults for development, CI, and purposeful deployments; configure ordinary desktop use
in Settings. Twitch identity and channel values can also be saved in Settings; saved profile values
override process environment defaults.

The optional non-secret `ai.cooldown_bypass_user_id` field in `config/app_settings.json`
preserves a per-user AI cooldown exception. A saved numeric Twitch user ID takes precedence
over `AI_COOLDOWN_BYPASS_USER_ID`; omitting it uses the process default. Internal output,
memory-retention and burst-timing limits remain application-owned.

Values marked required are needed to start Twitch; a fresh desktop profile opens without them and shows
**Configure Twitch**. Missing setup blocks Start Bot with a configuration message. Incomplete
automatic startup leaves the desktop open with Twitch stopped.

| Variable | Required | Purpose |
| --- | --- | --- |
| `HEETKIT_DATA_DIR` | No | Independent profile root; `--data-dir` takes priority. |
| `TWITCH_CLIENT_ID` | Yes | Twitch Developer application client ID. |
| `TWITCH_CLIENT_SECRET` | Yes* | Process environment fallback for the Twitch client secret; an OS keyring value may supply it instead. |
| `TWITCH_BOT_USER_ID` | Yes | Numeric user ID of the bot account. |
| `TWITCH_BOT_USERNAME` | Yes | Login name of the bot account. |
| `TWITCH_CHANNEL_USER_ID` | Yes | Numeric user ID of the channel receiving the bot. |
| `TWITCH_CHANNEL` | Yes | Channel login name. |
| `TWITCH_TOKEN_FILE` | No | Legacy token-file location to import on the first normal launch. New tokens use the app-data `auth/` directory. |
| `GEMINI_API_KEY` | No | Process environment fallback for Gemini; an OS keyring value takes precedence. |
| `GEMINI_MODEL` | No | Gemini model; defaults to `gemini-3.5-flash-lite`. |
| `GEMINI_FALLBACK_MODEL` | No | Model used when the selected model returns 404; defaults to `gemini-3.1-flash-lite`. |
| `AI_COOLDOWN_BYPASS_USER_ID` | No | One Twitch user ID allowed to bypass only the `!ask` cooldown. |
| `DATABASE_URL` | No | Legacy SQLite URL to import on the first normal launch, or an explicit non-SQLite database URL. Local SQLite uses app-data `data/heetkit.db`. |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `COMMAND_PREFIX` | No | Command prefix; defaults to `!`. |
| `COMMAND_MAX_ARGUMENTS_LENGTH` | No | Maximum command-argument length, from 1 to 450. |

`TWITCH_CLIENT_SECRET` must be available from either the OS keyring or the process environment
before starting a Twitch connection.

Gemini is optional. Twitch and non-AI commands work without a Gemini key. Without a configured
key/provider, `!ask` is unavailable, while its enabled preference is retained. Adding a Gemini
key in Settings restores AI availability immediately; a deliberately disabled command stays disabled.
Use the credential Test action to verify the key with the provider.

Global message filters start empty and are copied from shipped `app/resources/filters/` into app-data `config/filters/` on first launch. Manage them on the desktop **Filters** page: expand a category to edit its rules; categories start collapsed and show rule counts. Words and phrases use one non-empty line per rule, with whitespace trimmed and commas kept as text. Regex patterns retain individual editors and validation errors. Apply changes the running session, while Save keeps validated changes across restarts. The page marks source-default and local rules and highlights invalid entries. You can also edit the app-data copies directly; missing copies are recreated from the shipped defaults:

- `blocked_words.txt` contains whole-word matches;
- `blocked_phrases.txt` contains literal phrase matches;
- `blocked_patterns.txt` contains regular expressions.

Blank lines and lines beginning with `#` are ignored. The tracked files are distributable defaults; local edits in app-data stay outside the source tree. Review custom filter content before sharing it.

These rules filter incoming chat and Gemini response text. Configure name or topic protection
in each profile's local filters; shared AI safeguards contain no personal name rules.

Built-in cooldown values come from `app/config/commands.py`; effective command cooldowns can be applied or saved from the Commands page. Only `neutral` ships. Saved local personalities and prompts remain available after upgrades, including IDs removed from shipped resources. Create additional styles with **New personality** in the AI page's Personality Editor. Names are trimmed, must contain 1–64 characters, and cannot duplicate another name (including built-in IDs), regardless of letter case. Custom personalities belong only to the selected profile; clean profiles start with shipped personalities only.


Use the same application with independent profiles:

```powershell
python -m app.main --data-dir C:\BotProfiles\Clean --stopped
```

`HEETKIT_DATA_DIR` is the equivalent environment override; `--data-dir` takes priority.
Legacy compatibility only: `TWITCH_BOT_DATA_DIR` is accepted when `HEETKIT_DATA_DIR` is
not set. The HeetKit variable wins when both are set.
Alternate profiles can launch before setup. Configure Twitch in Settings; each profile uses its own
config, database, OAuth cache and keyring namespace. Explicit process environment variables remain
available as advanced defaults, while `--data-dir` forces the selected profile's own paths.
Point the override at your normal app-data root to use the existing owner profile.
`--check --data-dir <path>` validates without creating or migrating profile files.

Deleting only a profile's `config/` restores neutral defaults on the next normal launch;
its SQLite database, OAuth cache, migration marker and OS credentials remain intact.
Alternate-profile keyring services use `heetkit:<hash of resolved profile path>`;
relocating that profile requires storing its credentials again. The normal profile uses
service `heetkit`. Legacy credential compatibility copies missing Gemini/Twitch entries from
`twitch-bot` (or its matching profile hash) into `heetkit`, retaining the originals. Per-entry
keyring migration markers prevent Remove from restoring old credentials on restart.
The OAuth callback port remains 4343, so avoid simultaneous authorization
flows in multiple profiles.

For built-in `!tg` and `!forecast` responses, optionally create `config/fun_settings.json`:

```json
{"version": 1, "tg_message": "Your community link", "forecasts": ["Tomorrow brings a new opportunity."]}
```

Responses must be non-empty and at most 450 UTF-8 bytes. Expand `!forecast` or `!tg` in Commands to
edit its responses or message/link: Apply changes this session, Save persists it atomically in the selected
profile, and Reset restores neutral shipped responses. Forecast responses use one non-empty line
per response; blank lines are ignored and commas remain part of the text. Each command's actions
preserve the other command and unrelated fields. Direct file edits require restart. Missing or invalid
files use neutral starters; unreadable/unsupported files must be repaired before saving from the UI.
Existing profiles are never overwritten during seeding.

## Twitch setup

1. Launch the desktop and open **Settings → Twitch connection**. Select **Open Twitch Developer Console** in the **Twitch application** section to create a Twitch Developer Application in your external browser. Its Client ID and Client Secret identify the application.
2. Use **Copy** beside the callback URL in Settings and register this exact URL in your Twitch Developer Application:

   ```text
   http://localhost:4343/oauth/callback
   ```

3. Enter the application client ID, bot account login and numeric user ID, and destination channel login and numeric user ID. Save the setup. These non-secret values belong to this profile. Named presets contain target-channel metadata only.
4. Under **Secure credentials**, replace the Twitch client secret. Restart the application to apply the saved client ID, bot identity and secret, then use **Start Bot**.
5. When the connection shows **Authorization required**, select **Authorize Twitch** on Dashboard or in Settings. This opens the existing local TwitchIO authorization page in your external browser; sign in as the configured bot account. Authorization opens only when you choose the action, including after automatic bot startup. The application requests chat read/write, bot, and follower-read scopes used by the current implementation.

TwitchIO stores generated access and refresh tokens in app-data `auth/twitchio_tokens.json`. Token files contain credentials: never commit, publish, email, or include them in a manually created ZIP. Configure the client secret through Settings; advanced process environment overrides are available for development and deployment workflows. The app never writes setup into its installation directory.

## AI setup

Store the Gemini API key from the Settings page. Advanced deployments can set `GEMINI_API_KEY`
in the process environment as a fallback to enable AI replies. `GEMINI_MODEL` supplies the deployment default. The AI page can
save validated selected and fallback model IDs locally for subsequent requests, using shipped
presets, optional provider discovery, or an explicit custom model ID.

`!ask` applies the local AI request policy before contacting Gemini. Requests involving current, changing, comparison, event, or named-opinion information can enable Google Search grounding. Provider responses then pass through the local response policy and configured response-length limit before delivery.

When AI memory is enabled, up to `AI_MEMORY_MAX_ENTRIES` successful exchanges per Twitch user are stored in SQLite and supplied as untrusted conversation context. The AI page can disable memory without disabling Gemini, and that preference is saved in app-data `config/app_settings.json`. Built-in personality prompts are loaded from `app/resources/personalities.json`. Python composes each request's instructions in this order: protected shared instructions, non-empty profile instructions, then the selected personality prompt. User-authored instructions cannot override protected system and safety rules.

## Commands

All commands are configurable from the Commands page. Hidden commands are omitted from public `!help` output but remain available to authorized users when enabled.

| Command | Purpose | Permission | Hidden | Runtime toggle |
| --- | --- | --- | --- | --- |
| `!ask <question>` | Generate a filtered Gemini response and optionally use/save memory. | User | No | Yes |
| `!commands` | List public command help entries. | Moderator | No | Yes |
| `!erase <username>` | Delete stored AI memory for a known Twitch user. | Broadcaster | Yes | Yes |
| `!followage` | Show how long the invoking user has followed the channel. | User | No | Yes |
| `!forecast` | Return a random configured forecast. | User | No | Yes |
| `!help` | List public command help entries. | User | No | Yes |
| `!ping` | Reply with `pong`. | Moderator | No | Yes |
| `!seen <username>` | Show when a known chat user was last seen. | User | No | Yes |
| `!tg <1-10>` | Send the configured Telegram message from one to ten times. | Moderator | No | Yes |
| `!uptime` | Show elapsed time since application composition. | Moderator | No | Yes |
| `!weather <city>` | Show current weather with English, Russian, or Ukrainian localization. | User | No | Yes |

Built-in cooldowns come from `app/config/commands.py`; saved local overrides take precedence at runtime. `!tg` and hidden `!erase` currently have no built-in command cooldown; all other default cooldown values are explicitly configured there. The moderator-only `!tg` burst also bypasses the global output limiter; other outgoing commands and message reactions use it.

The Commands page also lets you create your own commands with a name, optional aliases, permission level, per-user and global cooldowns, and 1 to 10 response templates. The Custom Commands section appears above the built-in commands, with the creator/editor above your existing custom commands. Enter one template per non-empty line; blank lines are ignored and commas remain part of the template. Multiple templates are chosen at random. Use `{sender}`, `{target}` (first argument, or sender if absent), `{args}`, `{arg1}` through `{arg9}` (missing arguments become blank), and `{random_user}` (a chatter seen in the last 30 minutes, or sender if none is available). Unknown variables are rejected when saving. Custom commands cannot take a built-in name or alias, and templates never run code. Replies are limited to 450 UTF-8 bytes and use the normal global output limiter.

Ordinary chat can also trigger short, non-AI reactions. Edit app-data `config/message_triggers.json` to add or disable entries, then restart. Each entry needs a unique `id`, `enabled`, `match_mode` (`contains` or `exact`), `text`, `case_sensitive`, `probability` (0 to 1), `cooldown_seconds` (0 to 86400), and 1 to 10 literal `responses`. The starter file has an empty `triggers` list. Matching is in file order; at most one reaction is sent per message. Bot messages and command-prefixed messages do not trigger reactions. Responses have a 450-byte UTF-8 limit and share the global output limiter with commands. Invalid entries are skipped. Deleting the local file restores the empty starter on the next normal launch.

## Desktop control panel

`python -m app.main` opens the React UI in pywebview and controls the single composed Python application. The explicit bridge exposes only application-level lifecycle and settings operations; command rules, AI behavior, persistence, Twitch, and database access remain in Python.

The built-in Commands section is registry-driven, including hidden commands. Cards start collapsed
with enabled/availability, permission, and cooldown summaries; expand a card to edit its settings.
Apply is process-local, Save writes app-data `config/command_settings.json`, and Reset removes the
override and restores registry defaults. Forecast responses and the `!tg` message have separate Apply / Save / Reset
actions in the expanded editor. Weather and uptime continue to use runtime data. The separate
Custom Commands section saves user-created commands immediately to app-data `config/custom_commands.json`.

The AI page provides a runtime AI-command toggle, a persisted memory toggle, Gemini
selected/fallback model configuration, and the Personality Editor. Choose a personality to edit
its prompt, then **Save** to persist it without changing the active selection. **Set active**
separately saves the selection for the next AI request and future restarts; it does not save prompt
drafts. The active personality stays visible in the status card and editor badge.
**New personality** creates a profile-owned name and prompt without activating it. Custom
personalities have **Rename** and confirmed **Delete** actions. Rename retains the exact prompt
and updates an active selection atomically; deleting the active personality selects and saves
`neutral`. Built-ins cannot be renamed or deleted, but their prompts can be overridden; **Reset**
restores the shipped prompt. All changes use the selected profile's
`config/personality_settings.json` and preserve profile instructions and other settings.
Below the Personality Editor, Profile instructions applies to every personality in the selected
profile. Apply affects this session, Save persists the text in the same personality settings file,
and Reset saves an empty field. These actions preserve personality overrides and selection;
personality actions also preserve profile instructions. New profiles start with an empty field,
and separate `--data-dir` roots keep their instructions independent. The collapsed Protected shared
instructions section displays the current backend policy read-only, with no editing controls.

Live logs use a thread-safe 500-entry backend buffer and a bounded 500-entry frontend view. Clearing the Logs page does not delete persistent logs or application state.

The Settings page controls automatic bot startup, start minimized, minimize to tray, and close
to tray. Its Twitch section shows connection, configured bot identity, OAuth-cache status, and
the active/target channel. Non-secret identity and target settings write to app-data
`config/app_settings.json`; identity/client-ID changes require restart. Named presets store only
display names, target logins and numeric broadcaster IDs. Save & reconnect applies the selected
target through the existing bot lifecycle. The page also shows masked credential status for the
Gemini API key and Twitch client secret, with Replace, Remove, and provider Test actions.
Credential values are never returned to React; changes use the OS keyring. Gemini changes
apply to AI features immediately; removing a stored key uses the process environment fallback
when present. Twitch client-secret changes take effect after restart. The pystray menu provides
Open, dynamic Start Bot / Stop Bot, and Exit.
Tray Exit and normal application shutdown reuse the same orderly backend lifecycle.

The **About** page shows HeetKit, its subtitle and version, creator **heeetz**, Twitch
**@heet_ok**, Discord **de.tected** with Copy, and **Apache-2.0**. The Twitch profile,
repository, license and third-party notice links open in your external browser.
HeetKit is not affiliated with or endorsed by Twitch.

## Runtime data and privacy

Generated local files include:

| Path | Classification | Share? |
| --- | --- | --- |
| Process environment | Advanced deployment defaults and optional credential fallbacks | Never record or share |
| System keyring entries for service `heetkit` | Gemini API key and Twitch client secret | Not repository files |
| App-data `auth/twitchio_tokens.json` | Twitch access/refresh credentials | Never |
| App-data `data/heetkit.db` | Local user activity and AI memory | Never |
| App-data `config/command_settings.json` | Local command overrides | Never |
| App-data `config/custom_commands.json` | Local custom commands | Never |
| App-data `config/fun_settings.json` | Local built-in command responses | Never |
| App-data `config/message_triggers.json` | Local message reactions | Never |
| App-data `config/personality_settings.json` | Local profile instructions, personality text and selection | Never |
| App-data `config/app_settings.json` | Versioned local startup, window/tray, AI memory/model, and non-secret Twitch identity/target/preset preferences | Never |
| App-data `config/*.recovery` | Exact originals preserved before settings recovery saves | Never |
| App-data `config/filters/*.txt` | Locally editable filter rules | Review before sharing |
| `app/resources/filters/*.txt` | Neutral distributed filter starters | Yes |
| Legacy checkout `data/filters/*.txt` | Private migration input | Never |
| `.venv/`, caches, build output, logs, IDE metadata | Generated local development state | No |

The database may contain Twitch user IDs, usernames, last-seen timestamps, and recent AI exchanges. Treat it as private even if it contains no API secrets.

Accidentally created `.env` and `.env.*` files remain ignored by Git and excluded from developer
source archives; the application never loads them.

Gemini is optional. When enabled and requested, AI replies send the prompt, configured
protected shared instructions, profile instructions, selected personality prompt, stream category,
and recent exchanges when AI memory is enabled
to Google. Requests needing current information may use Google Search grounding. Credential
Test and model discovery also contact Google. Google's provider terms and data handling apply
to that external processing; avoid sending private chat content or secrets. Turning AI memory
off prevents conversation context from being added to future requests. Local profiles and
credentials are excluded from the repository and source archives.

## Developer source sharing

Do not ZIP the project directory manually. `.gitignore` protects Git operations but does not
protect a manual archive. The script below creates a **developer source archive**, not a
standalone app or an end-user release. It includes public source, tests, contribution documents,
license texts and development scripts. Private development context stays local.

Create a developer archive from PowerShell:

```powershell
.\scripts\package.ps1 -OutputPath .\heetkit-source.zip
```

The script packages tracked files from the current working tree, including edits to those files.
Untracked files stay out of the archive. It uses a temporary staging directory and defensively
excludes environment files, tokens, databases, virtual environments, caches, logs, IDE metadata,
build artifacts, private development notes, temporary patch/debug files, and existing archives.
It preserves public source, tests, shipped filter defaults and required notices.

The command refuses to overwrite an existing ZIP. Delete or rename an old archive before rerunning it.

There is no public standalone application download yet. Local portable candidates use an
explicit Windows runtime/resource list and exclude private development context, tests,
development scripts and local state. Before publishing any public source release, review
both the current files **and Git
history** for secrets and private data. Archive filtering does not perform that history check.

## Building a Windows portable candidate

Use Windows x64 CPython **3.14.7** and Node.js **20.19+** (or a supported newer Node release):

```powershell
.\scripts\build_windows.ps1
```

The default bootstrap interpreter is `.venv\Scripts\python.exe`; pass `-PythonPath` to
select another matching interpreter. The command creates an isolated environment under
`build/windows/`, installs the exact Python/build pins in `packaging/windows/requirements.txt`,
rebuilds the frontend with `npm ci` and `npm run build`, then creates a PyInstaller onedir
bundle and `dist/HeetKit-<version>-windows-x64.zip` plus a SHA-256 checksum. Internet access
is needed to acquire build dependencies. `app/version.py` owns the application version;
About, Python metadata and executable metadata consume it. Existing ZIPs are never overwritten.

Extract the entire `HeetKit` folder outside the checkout and keep `_internal` and
`HeetKit.exe.config` beside `HeetKit.exe`. Python and Node are not needed on the target machine. License texts and
portable instructions are under `_internal`. User state remains in `%LOCALAPPDATA%\HeetKit`;
portable describes the application files, not moving the user's credentials/profile with them.

Use Explorer **Extract All** for the portable ZIP. `HeetKit.exe.config` enables .NET Framework's process-local
[`loadFromRemoteSources`](https://learn.microsoft.com/en-us/dotnet/framework/configure-apps/file-schema/runtime/loadfromremotesources-element)
setting so the shipped managed assemblies can load while retaining Windows' download
markers. Keep this file beside the executable. HeetKit does not remove those markers
or change global Windows security policy. `--check` tests actual .NET/WebView2 library
loading without opening a window or changing profile files.

If library loading still fails, first verify that the whole folder was extracted,
including `HeetKit.exe.config`. As a last-resort fallback, if you trust the archive,
right-click the ZIP → Properties → **Unblock** → Apply, then extract into a **new**
folder. Unblocking the ZIP does not change files already extracted. For an existing
trusted extraction, quit HeetKit and run PowerShell with the exact application path:

```powershell
Get-ChildItem -LiteralPath 'C:\path\to\HeetKit' -Recurse -File | Unblock-File
```

This removes download markers only from that folder and requires no administrator
rights or system-wide security changes. See [Microsoft's Unblock-File documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/unblock-file).
If it still fails, include the loader detail from the message when reporting the issue.

For a disconnected, isolated smoke test, launch:

```powershell
.\HeetKit.exe --data-dir C:\Temp\HeetKitSmokeProfile --stopped
```

Confirm a neutral first launch, About version/icon, settings persistence after restart,
close/minimize-to-tray, tray Open and tray Exit. Then test the default existing profile and
representative legacy migration with private backups, and test a clean Windows user/VM
without development tooling. Test a transferred/downloaded ZIP as well as a local copy.
For download acceptance, confirm the ZIP and extracted `Python.Runtime.dll` retain
`ZoneId=3`, then verify the native window opens without manually unblocking either.
The frozen process config has passed a controlled outside-checkout load test; the
browser-download/Explorer extraction acceptance test remains pending for this candidate.
`--check` is read-only and does not open the desktop.
These local candidates require manual validation and the artifact-specific redistribution
review in `THIRD_PARTY_NOTICES.md` before publication. Release automation and update checking
remain separate work.

## Building and testing a Windows installer

Install the pinned [Inno Setup **6.7.3** compiler](https://github.com/jrsoftware/issrc/releases/tag/is-6_7_3)
on the build machine. Keep its original license/copyright notices. Build the portable
candidate first, then wrap that exact ZIP (no second freeze or frontend build):

```powershell
.\scripts\build_windows.ps1
.\scripts\build_installer.ps1
```

Use `-InnoCompiler 'C:\path\to\ISCC.exe'` for a non-default compiler location and
`-PythonPath` for a different build interpreter with the pinned PyInstaller installed.
`-PortableZip` selects an existing ZIP; its checksum, manifest hashes, inventory and
canonical version must pass inspection. The compiler version is enforced. Outputs are
`dist/HeetKit-<version>-windows-x64-setup.exe`, `.exe.sha256` and `.exe.build.json`
(input ZIP/manifest/compiler traceability). Existing setup files are never overwritten.
Only source/build instructions are tracked; generated binaries remain ignored.

For the Phase B manual checkpoint, use a disposable Windows user/VM with no Python,
Node or checkout, and keep a private backup before testing an existing profile:

1. Install test build A (0.1.2) normally. Read notices, try the directory chooser and
   optional desktop shortcut; verify Installed apps and both shortcut targets.
2. Launch from a shortcut with a clean profile. Check neutral defaults, stopped bot,
   About version/icon, tray Open/minimize/close/Exit, full exit and relaunch. Verify
   no manual Unblock or DLL movement is needed.
3. Save representative settings, custom commands, filters, personalities and profile
   instructions; exercise database, OAuth and credential persistence where configured.
   Quit fully, install test build B (0.1.3) into the same directory, and launch again.
   Check version 0.1.3 and all retained state; try a same-version reinstall too.
4. Uninstall using Installed apps. Check application files/shortcuts are removed and
   the profile and credentials remain. Reinstall B and confirm the saved state returns.
5. Where possible, test missing .NET/WebView2 in a disposable VM: setup must show the
   Microsoft guidance, permit retry after runtime installation, and leave the profile
   untouched while prerequisites are missing. An offline user can use the supported
   standalone installers.

Automated silent lifecycle checks do not complete this wizard/native/clean-machine
checkpoint. Remaining Phase A fresh browser download, normal Explorer extraction without
Unblock, tray, full exit/relaunch and clean-profile checks require explicit manual results.

## Contributing and reporting

Use the [bug report or feature request forms](https://github.com/heeetz/twitch-bot/issues/new/choose)
and see [CONTRIBUTING.md](CONTRIBUTING.md) for the lightweight development workflow.
Report vulnerabilities privately through [SECURITY.md](SECURITY.md), using GitHub private
reporting when available or Discord **de.tected**. Keep security details and credentials out
of public Issues, logs and screenshots.

## Testing

Install development dependencies with `python -m pip install -e ".[dev]"`, then run:

```powershell
python -m pytest -q
python -m compileall -q app tests
git diff --check
```

Validate and build the frontend from `frontend/`:

```powershell
npm test
npm run typecheck
npm run build
```

The focused browser tests use synthetic setup and mocked external actions. On Windows they
run headless in installed Microsoft Edge. On other development platforms, install the test
browser first with `npx playwright install chromium`.

## Troubleshooting

- Missing Twitch setup: the desktop opens disconnected. Enter the client ID, bot login/user ID and target login/user ID in Settings, save the Twitch client secret under Secure credentials, then restart before Start Bot. Advanced deployments can provide process environment defaults; ordinary desktop setup belongs in Settings. `--check` checks desktop configuration and frontend availability; Twitch-required values are checked when connecting.
- Twitch authentication failure: verify the client credentials, numeric account IDs, callback URL, and that the intended bot account completed OAuth. Remove a stale local token file only when you intentionally want to authorize again.
- Import or command not found: activate `.venv` and rerun `python -m pip install -e ".[dev]"`.
- No control panel: verify that the process has access to a graphical desktop and that the Microsoft Edge WebView2 runtime is installed. `python -m app.main --check` intentionally does not open the GUI.
- Web UI build missing: for source launches, run `npm install` and `npm run build` in `frontend/`. Installed distributions must supply the declared prebuilt files under `app/resources/frontend/`.
- Web UI development server unavailable: start `npm run dev` in `frontend/` before using `--dev-url http://localhost:5173`.
- Gemini unavailable: verify `GEMINI_API_KEY`, the selected model, network access, and package installation. Other non-AI commands continue to work without Gemini.
