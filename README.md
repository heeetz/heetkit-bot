# Twitch Bot

Created and maintained by **heeetz**. Official repository:
[github.com/heeetz/twitch-bot](https://github.com/heeetz/twitch-bot).
Discord contact: **de.tected**.

Licensed under [Apache License 2.0](LICENSE), with original attribution in [NOTICE](NOTICE).
Dependencies retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

## Overview

This is a single-channel Twitch chatbot with a desktop interface. Windows is the first release target; the source application is designed to use supported macOS/Linux pywebview backends. It receives chat through TwitchIO EventSub, records when users were last seen, applies global and AI-specific filters, and dispatches commands with permission and cooldown checks.

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

- Python 3.12 or newer. Python 3.12 is the recommended baseline.
- Node.js 20.19 or newer for installing and building the frontend.
- A Twitch account for the bot and a Twitch Developer application.
- The numeric Twitch user IDs for the bot account and target channel.
- A Gemini API key only if `!ask` should produce AI responses.
- A renderer supported by pywebview. Windows normally uses the installed Microsoft Edge WebView2 runtime. macOS uses Cocoa/WebKit; Linux requires an installed GTK/WebKit or Qt backend and its system libraries. Linux users must select the matching `pywebview[gtk]` or `pywebview[qt]` extra.
- A working system keyring backend is recommended for credential storage. Advanced deployments can provide process environment overrides when needed.

## Installation

From Windows PowerShell:

```powershell
cd "C:\path\to\Twitch Bot"
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
twitch-bot
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
`app/resources/frontend/`. Generated frontend files remain ignored. Automatic frontend staging,
standalone freezing and release artifacts are future packaging work; no standalone release is available yet.

## Configuration

Configuration responsibilities remain separated:

- The desktop Settings page and profile stores are the normal configuration path. Non-secret Twitch identity, target metadata, command overrides, AI memory/personality/model preferences, and other local settings are stored under the selected profile; credentials are stored in the OS keyring. Advanced deployments and development/CI workflows can use process environment variables as defaults. Saved profile values override those defaults, and keyring credentials override process environment values.
- Non-secret behavioral defaults are defined in `app/config/commands.py` and `app/config/ai.py`. Built-in personality prompts live in the tracked `app/resources/personalities.json` resource; protected shared AI instructions and default personality construction remain application code in `app/config/personalities.py`.
- `config/command_settings.json` under the platform app-data root contains optional local command overrides. Commands without overrides continue to use registry defaults.
- `config/custom_commands.json` under that root contains versioned, local custom commands. Invalid entries are skipped and cannot disable built-in commands.
- `config/message_triggers.json` under that root contains local reactions to ordinary chat messages. It is seeded from `app/resources/default_triggers.json` when missing; edits take effect after restarting the app.
- `config/personality_settings.json` under that root contains the locally selected AI personality and prompt overrides, including user-created personality IDs. Shared AI instructions are not editable.
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

The app-data root is `%LOCALAPPDATA%\TwitchBot` on Windows, `~/Library/Application Support/TwitchBot` on macOS, and `${XDG_DATA_HOME:-~/.local/share}/TwitchBot` on Linux. It contains `config/`, `data/`, `auth/`, and `cache/`.

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
| `TWITCH_BOT_DATA_DIR` | No | Independent profile root; `--data-dir` takes priority. |
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
| `DATABASE_URL` | No | Legacy SQLite URL to import on the first normal launch, or an explicit non-SQLite database URL. Local SQLite uses app-data `data/twitch_bot.db`. |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `COMMAND_PREFIX` | No | Command prefix; defaults to `!`. |
| `COMMAND_MAX_ARGUMENTS_LENGTH` | No | Maximum command-argument length, from 1 to 450. |

`TWITCH_CLIENT_SECRET` must be available from either the OS keyring or the process environment
before starting a Twitch connection.

Gemini is optional. Twitch and non-AI commands work without a Gemini key. Without a configured
key/provider, `!ask` is unavailable, while its enabled preference is retained. Adding a Gemini
key in Settings restores AI availability immediately; a deliberately disabled command stays disabled.
Use the credential Test action to verify the key with the provider.

Global message filters start empty and are copied from shipped `app/resources/filters/` into app-data `config/filters/` on first launch. Manage them on the desktop **Filters** page: Apply changes the running session, while Save keeps validated changes across restarts. The page marks source-default and local rules and highlights invalid entries. You can also edit the app-data copies directly; missing copies are recreated from the shipped defaults:

- `blocked_words.txt` contains whole-word matches;
- `blocked_phrases.txt` contains literal phrase matches;
- `blocked_patterns.txt` contains regular expressions.

Blank lines and lines beginning with `#` are ignored. The tracked files are distributable defaults; local edits in app-data stay outside the source tree. Review custom filter content before sharing it.

These rules filter incoming chat and Gemini response text. Configure name or topic protection
in each profile's local filters; shared AI safeguards contain no personal name rules.

Built-in cooldown values come from `app/config/commands.py`; effective command cooldowns can be applied or saved from the Commands page. Only `neutral` ships. Saved local personality IDs and prompts remain available after upgrades, including IDs removed from shipped resources. Add IDs (1–64 characters) to the local `overrides` object to create additional styles, then restart. Reset restores a built-in prompt or clears a local-only prompt while retaining its ID.


Use the same application with independent profiles:

```powershell
python -m app.main --data-dir C:\BotProfiles\Clean --stopped
```

`TWITCH_BOT_DATA_DIR` is the equivalent environment override; `--data-dir` takes priority.
Alternate profiles can launch before setup. Configure Twitch in Settings; each profile uses its own
config, database, OAuth cache and keyring namespace. Explicit process environment variables remain
available as advanced defaults, while `--data-dir` forces the selected profile's own paths.
Point the override at your normal app-data root to use the existing owner profile.
`--check --data-dir <path>` validates without creating or migrating profile files.

Deleting only a profile's `config/` restores neutral defaults on the next normal launch;
its SQLite database, OAuth cache, migration marker and OS credentials remain intact.
Alternate-profile keyring services use `twitch-bot:<hash of resolved profile path>`;
relocating that profile requires storing its credentials again. The normal profile retains
service `twitch-bot`. The OAuth callback port remains 4343, so avoid simultaneous authorization
flows in multiple profiles.

For built-in `!tg` and `!forecast` responses, optionally create `config/fun_settings.json`:

```json
{"version": 1, "tg_message": "Your community link", "forecasts": ["Tomorrow brings a new opportunity."]}
```

Responses must be non-empty and at most 450 UTF-8 bytes. Expand `!forecast` in Commands to
edit its response pool: Apply changes this session, Save persists it atomically in the selected
profile, and Reset restores neutral shipped responses. These actions preserve `tg_message` and
other fields. Direct file edits, including `tg_message`, require restart. Missing or invalid
files use neutral starters; unreadable/unsupported files must be repaired before saving from the UI.
Existing profiles are never overwritten during seeding.

## Twitch setup

1. Create a Twitch Developer application. Launch the desktop and open **Settings → Twitch connection**.
2. Register this exact OAuth callback URL in the Twitch Developer Console:

   ```text
   http://localhost:4343/oauth/callback
   ```

3. Enter the application client ID, bot account login and numeric user ID, and destination channel login and numeric user ID. Save the setup. These non-secret values belong to this profile. Named presets contain target-channel metadata only.
4. Under **Secure credentials**, replace the Twitch client secret. Restart the application to apply the saved client ID, bot identity and secret. Use **Start Bot**; if authorization is required, Logs shows the local TwitchIO authorization URL served on port `4343`.
5. Authorize the configured bot account. The application requests chat read/write, bot, and follower-read scopes used by the current implementation.

TwitchIO stores generated access and refresh tokens in app-data `auth/twitchio_tokens.json`. Token files contain credentials: never commit, publish, email, or include them in a manually created ZIP. Configure the client secret through Settings; advanced process environment overrides are available for development and deployment workflows. The app never writes setup into its installation directory.

## AI setup

Store the Gemini API key from the Settings page. Advanced deployments can set `GEMINI_API_KEY`
in the process environment as a fallback to enable AI replies. `GEMINI_MODEL` supplies the deployment default. The AI page can
save validated selected and fallback model IDs locally for subsequent requests, using shipped
presets, optional provider discovery, or an explicit custom model ID.

`!ask` applies the local AI request policy before contacting Gemini. Requests involving current, changing, comparison, event, or named-opinion information can enable Google Search grounding. Provider responses then pass through the local response policy and configured response-length limit before delivery.

When AI memory is enabled, up to `AI_MEMORY_MAX_ENTRIES` successful exchanges per Twitch user are stored in SQLite and supplied as untrusted conversation context. The AI page can disable memory without disabling Gemini, and that preference is saved in app-data `config/app_settings.json`. Built-in personality prompts are loaded from `app/resources/personalities.json`; the editor exposes only personality-specific text and always preserves the application-owned shared system and safety instructions.

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

The Commands page also lets you create your own commands with a name, optional aliases, permission level, per-user and global cooldowns, and one or more response templates. Multiple templates are chosen at random. Use `{sender}`, `{target}` (first argument, or sender if absent), `{args}`, `{arg1}` through `{arg9}` (missing arguments become blank), and `{random_user}` (a chatter seen in the last 30 minutes, or sender if none is available). Unknown variables are rejected when saving. Custom commands cannot take a built-in name or alias, and templates never run code. Replies are limited to 450 UTF-8 bytes and use the normal global output limiter.

Ordinary chat can also trigger short, non-AI reactions. Edit app-data `config/message_triggers.json` to add or disable entries, then restart. Each entry needs a unique `id`, `enabled`, `match_mode` (`contains` or `exact`), `text`, `case_sensitive`, `probability` (0 to 1), `cooldown_seconds` (0 to 86400), and 1 to 10 literal `responses`. The starter file has an empty `triggers` list. Matching is in file order; at most one reaction is sent per message. Bot messages and command-prefixed messages do not trigger reactions. Responses have a 450-byte UTF-8 limit and share the global output limiter with commands. Invalid entries are skipped. Deleting the local file restores the empty starter on the next normal launch.

## Desktop control panel

`python -m app.main` opens the React UI in pywebview and controls the single composed Python application. The explicit bridge exposes only application-level lifecycle and settings operations; command rules, AI behavior, persistence, Twitch, and database access remain in Python.

The built-in Commands section is registry-driven, including hidden commands. Cards start collapsed
with enabled/availability, permission, and cooldown summaries; expand a card to edit its settings.
Apply is process-local, Save writes app-data `config/command_settings.json`, and Reset removes the
override and restores registry defaults. Forecast responses have separate Apply / Save / Reset
actions in the expanded editor. Weather and uptime continue to use runtime data. The separate
Custom Commands section saves user-created commands immediately to app-data `config/custom_commands.json`.

The AI page provides a runtime AI-command toggle, a persisted memory toggle, Gemini
selected/fallback model configuration, and the active personality selector. Personality Apply
changes the next AI request without restarting, Save writes the active selection and
personality-specific override to app-data `config/personality_settings.json`, and Reset restores the
built-in prompt. The shared AI instructions are never sent to the editor.

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

The **About** page shows the app version, creator, Discord contact with Copy, project
license and third-party notices. Project/license/notice links open in your external browser.

## Runtime data and privacy

Generated local files include:

| Path | Classification | Share? |
| --- | --- | --- |
| Process environment | Advanced deployment defaults and optional credential fallbacks | Never record or share |
| System keyring entries for service `twitch-bot` | Gemini API key and Twitch client secret | Not repository files |
| App-data `auth/twitchio_tokens.json` | Twitch access/refresh credentials | Never |
| App-data `data/twitch_bot.db` | Local user activity and AI memory | Never |
| App-data `config/command_settings.json` | Local command overrides | Never |
| App-data `config/custom_commands.json` | Local custom commands | Never |
| App-data `config/fun_settings.json` | Local built-in command responses | Never |
| App-data `config/message_triggers.json` | Local message reactions | Never |
| App-data `config/personality_settings.json` | Local personality text and selection | Never |
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
personality instructions, stream category, and recent exchanges when AI memory is enabled
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
.\scripts\package.ps1 -OutputPath .\twitch-bot-source.zip
```

The script packages tracked files from the current working tree, including edits to those files.
Untracked files stay out of the archive. It uses a temporary staging directory and defensively
excludes environment files, tokens, databases, virtual environments, caches, logs, IDE metadata,
build artifacts, private development notes, temporary patch/debug files, and existing archives.
It preserves public source, tests, shipped filter defaults and required notices.

The command refuses to overwrite an existing ZIP. Delete or rename an old archive before rerunning it.

There is no standalone application download yet. A future end-user bundle must explicitly include
only executable/runtime assets, required notices, and intended user documentation; its packaging
spec must exclude private development context, tests, development scripts, and local
state. Before publishing any public source release, review both the current files **and Git
history** for secrets and private data. Archive filtering does not perform that history check.

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
npm run typecheck
npm run build
```

## Troubleshooting

- Missing Twitch setup: the desktop opens disconnected. Enter the client ID, bot login/user ID and target login/user ID in Settings, save the Twitch client secret under Secure credentials, then restart before Start Bot. Advanced deployments can provide process environment defaults; ordinary desktop setup belongs in Settings. `--check` checks desktop configuration and frontend availability; Twitch-required values are checked when connecting.
- Twitch authentication failure: verify the client credentials, numeric account IDs, callback URL, and that the intended bot account completed OAuth. Remove a stale local token file only when you intentionally want to authorize again.
- Import or command not found: activate `.venv` and rerun `python -m pip install -e ".[dev]"`.
- No control panel: verify that the process has access to a graphical desktop and that the Microsoft Edge WebView2 runtime is installed. `python -m app.main --check` intentionally does not open the GUI.
- Web UI build missing: for source launches, run `npm install` and `npm run build` in `frontend/`. Installed distributions must supply the declared prebuilt files under `app/resources/frontend/`.
- Web UI development server unavailable: start `npm run dev` in `frontend/` before using `--dev-url http://localhost:5173`.
- Gemini unavailable: verify `GEMINI_API_KEY`, the selected model, network access, and package installation. Other non-AI commands continue to work without Gemini.
