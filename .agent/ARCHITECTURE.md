# Current architecture

Repository code is authoritative if this summary becomes stale. This document records
responsibilities and boundaries, not implementation detail from entire source files.

## Entry points and desktop shell

- `python -m app.main` is the canonical application entry point. The installed `twitch-bot`
  command resolves to the same function.
- Normal desktop launches guard the resolved platform app-data settings path before loading state:
  Windows uses a named mutex; macOS/Linux use a nonblocking advisory file lock in app-data
  `config/`. A duplicate reports the existing instance and exits. The read-only `--check`
  mode bypasses the guard; `--dev-url` remains guarded.
- Root `run.bat` changes to the repository directory and invokes
  `.venv\Scripts\python.exe -m app.main`; it never falls back to system Python.
- macOS/Linux source launches use `python -m app.main`; the PowerShell share-archive script is
  development packaging tooling, not an application runtime dependency.
- `app/main.py` delegates to `app/webview_host.py`.
- Production mode prefers packaged `app/resources/frontend/index.html`; a recognized source
  checkout falls back to generated, Git-ignored `frontend/dist/index.html`. Development
  mode can load a Vite URL with `--dev-url`. Normal launch follows the saved
  `startup.auto_start_bot` preference (default off); `--stopped` explicitly overrides it off.
  `--check` validates configuration/build availability without opening the UI.
- Tkinter has been removed. There is no legacy GUI or alternate application lifecycle.

## Frontend

Responsibility: presentation and explicit user actions only.

- Stack: React 19, TypeScript, and Vite under `frontend/`.
- Pages: Dashboard is the daily bot/Twitch/AI control center; Commands owns command behavior;
  Filters edits global message-filter rules; AI owns runtime toggles, Gemini model configuration,
  and personalities; Logs owns diagnostics; Settings owns desktop/window behavior, Twitch
  connection metadata, and secure credentials.
- `frontend/src/bridge.ts` defines the typed pywebview API surface. React does not import
  Python internals or implement command permissions, persistence, AI policy, or Twitch logic.
- Frontend startup waits for the `pywebviewready` lifecycle event and a populated
  `get_app_status` bridge method before beginning status polling.
- Status polling is approximately 1.5 seconds. Logs poll every second and keep at most 500
  entries in frontend state.
- Commands and personality editors may hold dirty form drafts, but backend state remains
  authoritative.

Boundary: React calls only methods exposed by `WebUIBridge`; it does not own a server or a
second backend.

## Desktop host and frontend bridge

Responsibility: compose the native window with the existing Python application safely.

- `app/webview_host.py` owns `AsyncioBackendHost`, `WebUIBridge`, `DesktopController`, and
  desktop startup.
- `AsyncioBackendHost` creates one daemon background thread with one asyncio loop, builds one
  `Application`, and owns one `BotRuntime`. Close requests are serialized and share one shutdown
  future: orderly cleanup is awaited first, then a deadline overrun cancels pending asyncio work
  and uses a bounded forced-stop grace period. A still-unresponsive backend thread cannot keep
  the desktop process alive after the window and tray exit.
- `WebUIBridge` exposes narrow application operations: status, bot start/stop, registered
  commands and command Apply/Save/Reset, custom-command CRUD, filter inspect/Apply/Save,
  AI status/toggles, personality Apply/Save/Reset,
  app settings, Twitch target/status/reconnect, Gemini model settings/discovery, masked
  credential status/actions, and recent logs.
- Async bot operations are submitted to the owning loop with
  `asyncio.run_coroutine_threadsafe`. Bridge waits have operation-specific deadlines, request
  cancellation at timeout, and observe any uncancelled late completion. AI-memory and Gemini
  model persist-and-apply operations execute in backend-loop order so effective runtime values
  cannot race their persisted values. Raw Twitch, database, Gemini, and `RuntimeState` objects
  are not exposed to React.

## Application composition and lifecycle

Responsibility: one application truth and one orderly lifecycle.

- `app/container.py` is the composition root. `build_application()` wires Settings, database,
  shared HTTP client, repositories, services, `RuntimeState`, command registry, and dispatcher.
- `Application.startup()` initializes the database and loads local filter rules, seeded from
  tracked defaults when missing. Each filter file retains prior active rules on read failure or
  invalid-only content. The Filters UI validates Python regex before session Apply or persistent
  Save; it keeps the existing word, phrase, and regex matching semantics.
  `Application.shutdown()` closes the Gemini service's provider client, shared HTTP client,
  and database engine.
- `app/bot_runtime.py` owns Twitch-session start/stop on the asyncio loop. Its lifecycle lock
  prevents overlapping session transitions; shutdown stops the bot before closing the
  application.
- `DesktopController.exit_application()` is the idempotent desktop shutdown path used by Tray
  Exit and host shutdown. It closes the backend, stops the tray, and destroys a live window.
  Graceful backend timeout/failure is logged before the tray/window teardown continues.
- With close-to-tray enabled, the closing event hides and preserves the process. Otherwise the
  window closes and its `closed` event enters the same orderly exit path.

## Tray and window ownership

Responsibility: one tray icon and window behavior per application process.

- One `DesktopController` owns one `SystemTray` from `app/system_tray.py`.
- Tray startup is guarded by the controller lifecycle lock and by `SystemTray`'s icon guard,
  so repeated starts do not create another icon.
- Tray actions are Open, Start Bot/Stop Bot, and Exit. Start/Stop delegates to `WebUIBridge`;
  Exit reuses the orderly desktop shutdown path.
- Tray hosting is currently Windows-only. macOS/Linux keep the window visible and close normally;
  saved start-minimized and tray options are shown as unavailable there. If the Windows tray
  backend fails to start, the host shows the window and does not hide it on close/minimize.
- `AppSettingsStore` supplies the versioned local application settings. Its `window` section
  owns start-minimized, minimize-to-tray, and close-to-tray behavior. Its `twitch` section may
  override non-secret client ID, bot login/user ID, and target-channel login/user ID. Identity
  changes are saved for restart; target-only reconnect preserves them. Start minimized controls
  only initial window visibility. Its `startup.auto_start_bot` setting independently controls
  whether the bot connection starts on the next normal desktop launch and defaults to false.

## RuntimeState

Responsibility: thread-safe effective runtime state shared by commands, services, and UI.

- `app/runtime_state.py` owns effective command settings, persisted-command metadata, AI
  enablement (the canonical `ask` command state), effective AI-memory enablement, personality
  selection/prompts, bot running state, Twitch connection state, and uptime/session timestamps.
- It uses an `RLock` for cross-thread reads and updates.
- Runtime-only Apply changes are distinct from saved overrides. React is never an independent
  source of domain state.

## Commands

Responsibility: registry-driven definitions and centralized dispatch.

- `CommandRegistry` in `app/commands/registry.py` is authoritative for command existence,
  aliases, help/hidden metadata, handler, default enabled state, permission, and cooldown.
- Command modules register built-ins during application composition. There is no separate
  hard-coded UI command list.
- `RuntimeState.configure_commands()` derives defaults from registry definitions and overlays
  valid local overrides.
- `CommandDispatcher` consumes effective settings, validates arguments/pre-checks before
  recording cooldown where designed, checks permissions centrally, and invokes handlers.
- `CustomCommandStore` owns validated, immutable user command snapshots. The dispatcher resolves
  these after built-ins and applies the same permission, cooldown, and output policy. Templates
  use a fixed variable allowlist and cannot execute code; recent users come from the existing
  SQLite user repository.
- `MessageTriggerStore` loads bounded, validated local reactions at composition. The dispatcher
  checks ordinary non-command messages in file order, excludes the bot account, and shares the
  command cooldown manager and global output limiter. Reactions are literal text, never code or AI.
- Handler-specific behavior remains in handlers; for example, `tg` bypasses the global
  `OutputLimiter` without changing generic command settings.
- Definitions mark AI generation dependencies (`ask` only). Provider availability is separate
  from configured enabled state; unavailable commands exit before policy, memory and cooldown work.
  Non-AI commands and memory erasure do not require Gemini. The bridge reports availability
  alongside canonical settings; React starts built-in cards collapsed and retains form drafts.

## Command settings persistence

- Type/validation and JSON persistence live in `app/command_settings.py`.
- Local file: platform app-data `config/command_settings.json`.
- Writes use temporary-file flush/fsync followed by replacement. Missing, malformed, stale,
  and individually invalid overrides fall back safely to registry defaults.
- Apply changes runtime state, Save writes a minimal difference from defaults, and Reset
  removes the override and restores registry defaults.
- Custom commands use a separate versioned app-data `config/custom_commands.json` store with
  atomic writes. Invalid entries and unsupported versions are ignored without affecting built-ins.
- App/custom-command, command-override and personality writes call the narrow file preflight
  in `app/settings_recovery.py` under their existing locks. Unreadable/malformed JSON (including
  duplicate keys) and unsupported app/custom-command versions refuse replacement. Unknown fields,
  skipped entries or data absent from the session's recovered snapshot get a unique exact-byte
  `<filename>.<unique-id>.recovery` copy beside the source before atomic replacement. Copy failure
  aborts publication; fully recovered data needs no copy. Reset/Delete use the same write paths.
  Manual repair/reset requires quitting, backing up and repairing/moving aside the named JSON,
  then restarting. Legacy flat app settings remain readable and upgrade on save.
- Message triggers use versioned app-data `config/message_triggers.json`, seeded when missing from
  tracked `app/resources/default_triggers.json`. Local edits take effect on restart; invalid
  entries are skipped.
- `FunSettingsStore` in `app/fun_settings.py` owns the existing version-1 profile file
  `config/fun_settings.json`. Forecast handlers read its locked immutable pool each invocation.
  Apply is session-only; Save uses flush/fsync + atomic replacement; Reset removes only the
  forecast override. Existing `tg_message` and other fields survive saves/resets. Unreadable or
  unsupported files fall back to neutral responses but cannot be overwritten by editor actions.

## AI and Gemini flow

Responsibility: policy and provider work remain in Python.

1. The `ask` command validates non-empty input and applies `AIRequestPolicy`.
2. If enabled, recent per-user AI memory is loaded from SQLite and formatted as untrusted
   context.
3. `TwitchAPIService` supplies the current category as optional untrusted context, cached for
   90 seconds.
4. `GeminiAIService` owns one reusable Gemini SDK client for the effective credential. It
   retires an old client after active calls finish if the credential changes, and the composed
   `Application` retires all clients and waits for active leases during shutdown. Retired leases
   close on release even if the shutdown waiter is cancelled. The service builds protected shared
   instructions plus the effective personality, conditionally enables Google Search grounding,
   calls the selected Gemini model, and uses
   the configured fallback only for model-not-found/unsupported responses. It then filters the
   response and applies the configured response-length limit.
5. A successfully delivered response is saved to memory only if memory remains enabled.

The SDK contract is pinned to `google-genai==1.75.0`: native HTTPX/aiohttp async transport,
`client.aio.aclose()` and `client.close()`. Gemini Developer API mode is explicit. Client HTTP
timeout is 45 seconds with `retry_options.attempts=1`; generation's 60-second total deadline includes
fallback. Discovery overrides HTTP timeout to 10 seconds and bounds all pages to 15 seconds.
Async client close is bounded to five seconds and sync cleanup runs in `finally`. Real SDK
loopback tests exercise both native transports and subprocess exit without live credentials.

Gemini selected/fallback model defaults come from typed environment `Settings`; validated local
overrides in platform app-data `config/app_settings.json` are applied before composition and UI changes update the
shared Settings object for the next request. Tracked presets live in
`app/resources/gemini_models.json`, while provider discovery is optional. The Gemini API key is
resolved from the system keyring first, then the private `.env` fallback. Provider
failures do not disable unrelated commands.
Gemini is optional. Service availability requires a non-blank key, an SDK provider, and an open
service, independently of the user's saved command preference. Credential Replace/Remove refreshes
the effective key on the backend loop for the next request; existing client retirement handles
rotation. Credential tests verify provider acceptance without exposing values. Twitch-secret
changes still require restart.

## Personalities and AI memory

- Built-in personality-specific prompts are tracked UTF-8 data in
  `app/resources/personalities.json` and loaded by `app/config/personalities.py`. Protected
  shared instructions remain application code there; the active source default is in root
  `config.py`.
- Only personality-specific text is editable. `RuntimeState` overlays local prompts and active
  selection from platform app-data `config/personality_settings.json`.
- Personality Apply is runtime-only, Save is persistent, and Reset restores the built-in text.
  Only `neutral` ships. Local IDs and retired shipped IDs remain available through saved overrides;
  local-only Reset clears text while retaining the ID. Shared AI instructions are never sent to the editor.
- `AIMemoryService` uses repository-backed SQLite storage and retains the configured number of
  successful exchanges per Twitch user. AI memory enablement starts from the source default
  overlaid by platform app-data `config/app_settings.json`; UI changes persist there before updating RuntimeState.

## Twitch boundary

- Desktop `Settings` supports blank Twitch identity fields and an absent (`None`) client secret.
  `Settings.validate_twitch_configuration()` requires all connection fields before session creation;
  the runtime validates starts and active reconnects, and the Twitch adapter guards direct entry.
  Incomplete automatic startup leaves the desktop open and stopped; manual starts return a safe
  Configure Twitch error. Existing bridge values preserve first-run dashboard setup guidance.
- `app/twitch/client.py` owns TwitchIO lifecycle, OAuth adapter/scopes, token load/save, chat
  subscription, incoming-message mapping, and connection-state updates.
- `app/services/twitch.py` is the command/service-facing API boundary. It is bound to the
  authenticated TwitchIO client and exposes category and followage lookups.
- Environment/profile `.env` supplies initial Twitch identity/channel defaults. Validated local
  identity and target overrides are applied before composition; old target-only files retain
  deployment identity. Settings exposes complete setup and pending identity changes; reconnect
  refuses a pending identity change until restart. Named stable-ID connection presets in
  the local app-settings `twitch` section contain only a display name, target login, and numeric
  broadcaster ID; selection updates the same target override. Save & reconnect uses the
  existing `BotRuntime` stop/start lifecycle on its owning asyncio loop.
- Presets do not represent authenticated bot accounts. The configured bot identity and
  TwitchIO OAuth cache remain process-wide; future multi-account authentication would need an
  explicit profile reference and credential/token ownership model.
- OAuth tokens are stored in platform app-data `auth/twitchio_tokens.json`. They are secrets.

## Logging

- Standard Python `logging` remains authoritative.
- `app/utils/logging.py` attaches a thread-safe `RecentLogHandler` backed by a bounded
  500-entry deque. Producers may attach an explicit semantic `event_kind` plus a small
  whitelist of safe display fields; arbitrary record attributes are not exposed to React.
- `WebUIBridge.get_recent_logs()` exposes validated cursor/limit reads. The frontend keeps a
  separate bounded view and presents event metadata without parsing message text. Severity and
  the raw formatted message remain available; Clear affects only the frontend view and does not
  delete persistent logs.
- Secrets and authorization values must never be added to log messages.

## Credential boundary

- `app/credentials.py` wraps the OS `keyring` backend (Windows Credential Manager, macOS
  Keychain, or a Linux keyring where available). It owns masked status, Replace/Remove, and
  provider-specific credential tests.
- Supported secure entries are the Gemini API key and Twitch client secret. Secure values
  overlay private `.env` fallbacks during startup and require restart after UI changes.
- `WebUIBridge` exposes identifiers/status/results only. Credential values are accepted for
  replacement but are never returned to React or included in application logs.
- TwitchIO-generated OAuth access/refresh tokens remain in its configured ignored token file;
  they are not ordinary settings or user-entered provider credentials.

## Configuration and persistence boundaries

| Data | Source of truth / location | Git status |
| --- | --- | --- |
| Typed deployment settings | `app/config/settings.py`, loaded from environment/`.env` | `.env` ignored; `.env.example` tracked |
| User-entered provider credentials | System keyring via `app/credentials.py`; `.env` fallback | OS-backed/private, never ordinary JSON |
| Behavioral defaults | root `config.py` | Tracked |
| Profile path selection | `app/runtime_paths.py`, CLI/environment override | Tracked code, local root |
| Built-in personality prompts | `app/resources/personalities.json` | Tracked package data |
| Protected shared AI instructions | `app/config/personalities.py` | Tracked application code |
| Gemini model presets | `app/resources/gemini_models.json` | Tracked package data |
| Ordinary application preferences | App-data `config/app_settings.json` (`startup`, `window`, AI memory/models, non-secret Twitch identity/target and named target presets) | Outside repository |
| Command overrides | App-data `config/command_settings.json` | Outside repository |
| Custom commands | App-data `config/custom_commands.json` | Outside repository |
| Built-in fun-command responses | App-data `config/fun_settings.json`; neutral code fallbacks | Outside repository |
| Message triggers | App-data `config/message_triggers.json`; tracked `app/resources/default_triggers.json` seed | Local file outside repository |
| Personality selection/overrides | App-data `config/personality_settings.json` | Outside repository |
| Settings recovery originals | App-data `config/*.recovery`; unique exact-byte copies, never automatically removed | Outside repository; private |
| Twitch OAuth tokens | App-data `auth/twitchio_tokens.json` | Outside repository; secret |
| Users and AI memory | App-data `data/twitch_bot.db` | Outside repository; private |
| Locally editable filters | App-data `config/filters/*.txt` | Outside repository |
| Distributed filter defaults | `app/resources/filters/*.txt` | Tracked, read-only at runtime |
| Frontend source / generated build | `frontend/src`, `frontend/dist`; staged installed assets in `app/resources/frontend` | Source tracked; generated/staged builds ignored |

### Shipped-default inventory (TODO-012)

- Required application behavior: registry definitions/permissions/cooldowns, dispatch limits,
  typed settings/schema validation, shared AI safety/request/response policy, OAuth scopes,
  memory limits, desktop defaults, logging, branding and frontend assets. These remain shared code.
- Safe public starters: `.env.example` placeholders, Gemini model presets, one `neutral` personality,
  empty filter text files and message-trigger seed, empty custom commands and Twitch presets,
  neutral forecast and community-link configuration reminder. No personal account is configured.
- Owner-specific data removed from shipped defaults: additional personality prompts/selection,
  named-person comparison/meme rules, moderation vocabulary, reaction text, Telegram link and
  forecast responses. These were preserved only in the owner's existing local profile.
- All saved settings, personalities, commands, filters, presets and responses are mutable profile
  data. Runtime preparation copies only missing files; application upgrades never overwrite them.

### Runtime data reference

`platformdirs.user_data_path("TwitchBot", appauthor=False)` selects the root: Windows
`%LOCALAPPDATA%\TwitchBot`, macOS `~/Library/Application Support/TwitchBot`, and Linux
`${XDG_DATA_HOME:-~/.local/share}/TwitchBot`. Platform directory overrides may change these
exact locations. `app/runtime_paths.py` owns the paths and first-launch migration. Before
opening local state, a launch using the default profile copies missing legacy checkout JSON, SQLite,
TwitchIO tokens, and filter files to the new root. SQLite is copied through its backup API.
Legacy discovery is limited to a recognized source checkout (`pyproject.toml` plus
`frontend/package.json`); install-directory siblings never supply migration data. Old files
are retained; the `.legacy-migration-v1` marker prevents a later reset from reimporting them.
Missing filter files are reseeded from package-owned starters. `--check`
does not create directories or migrate data.

`--data-dir <path>` overrides `TWITCH_BOT_DATA_DIR`; both select the same runtime architecture.
Resolution occurs before credential loading, the instance guard, migration or composition.
Alternate roots never import checkout state and always use their own SQLite/OAuth paths, ignoring
legacy `DATABASE_URL`/`TWITCH_TOKEN_FILE` locations. Every root loads `<profile>/.env`; only the
normal source profile also retains checkout `.env` as a lower-priority compatibility fallback.
Environment discovery never uses cwd. Relative legacy storage inputs resolve against the source
root for the normal source profile, otherwise the selected profile. Explicit process environment
variables override deployment files; saved Twitch identity/target overrides are applied afterward.
The standard profile retains keyring service `twitch-bot`; alternate roots use
`twitch-bot:<SHA-256 of os.path.normcase(str(resolved_root))>`. Entry names are `gemini_api_key` and
`twitch_client_secret`. Moving an alternate root changes its keyring namespace; config reset does not.
Profiles isolate local state, not OS-wide resources: the TwitchIO OAuth callback still uses port 4343.

Delete `config/app_settings.json`, `config/command_settings.json`, `config/custom_commands.json`, or
`config/personality_settings.json` to reset those non-secret preferences and overrides.
Deleting `config/fun_settings.json` restores neutral built-in command responses.
Deleting `config/message_triggers.json` restores its distributed default on the next launch.
Deleting a file in `config/filters/` restores its distributed default on the next launch.
Deleting `data/twitch_bot.db` destroys saved users and AI memory. Deleting
`auth/twitchio_tokens.json` removes Twitch OAuth access/refresh tokens and requires
reauthorization. The Gemini API key and Twitch client secret live in the OS keyring, with
private `.env` fallbacks; they are never stored in ordinary JSON. There are no persistent
application logs or other cache files at present; `cache/` is reserved for future use.

## Current source and release boundary

- Source launch uses `run.bat`, `python -m app.main`, or `twitch-bot`. Runtime declarations
  explicitly include root `config.py`, `app*` packages and required `app.resources` data;
  implicit package data is disabled. A non-editable distribution requires prebuilt frontend
  staging under `app/resources/frontend`. No standalone end-user bundle or installer exists yet.
- `scripts/package.ps1` creates a developer source archive from tracked working-tree files.
  It intentionally retains agent context, TODOs, docs, tests, and development scripts; it is
  not an app release or a substitute for a public-source secret/history review. Untracked files
  and private/generated artifacts are excluded from this archive.
- Vite output under `frontend/dist` and staged `app/resources/frontend` files are generated and
  ignored. Frontend build/staging automation remains TODO-014. Standalone packaging must rebuild
  it and include the Python runtime plus required tracked resources; it must not require Python,
  Node.js, or the development virtual environment on the target machine.
- Root behavior configuration, packaged personality/model resources, frontend assets, and
  tracked filter defaults are runtime inputs that a future build must include explicitly.
- Local settings, keyring credentials, Twitch tokens, SQLite data, logs, caches, tests, agent
  context, `AGENTS.md`, `TODO.md`, `docs/`, and development scripts must not be bundled as user
  data or committed as generated release output. The future application packaging spec must
  explicitly exclude development-only paths and permit only runtime assets, required notices,
  and intended user documentation. A public source release also requires a separate secret and
  Git-history hygiene check; artifact filtering alone cannot establish that history is safe.
- Windows x64 is the first distribution target. Any later macOS/Linux artifacts must be built
  and validated natively for their pywebview and keyring backends rather than treated as
  cross-compiled variants of a Windows bundle.
- Source launches on macOS use the pywebview Cocoa/WebKit backend; Linux needs an installed
  GTK/WebKit or Qt backend and its system libraries. Native tray integration and native
  distributables remain later packaging work.
