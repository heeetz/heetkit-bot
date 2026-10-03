# Current architecture

Repository code is authoritative if this summary becomes stale. This document records
responsibilities and boundaries, not implementation detail from entire source files.

## Entry points and desktop shell

- `python -m app.main` is the canonical application entry point. The installed `twitch-bot`
  command resolves to the same function.
- Normal Windows desktop launches acquire a named mutex keyed to the resolved platform app-data settings
  path before loading settings or starting the host. A duplicate reports the existing instance
  and exits. The read-only `--check` mode bypasses the guard; `--dev-url` remains guarded.
- Root `run.bat` changes to the repository directory and invokes
  `.venv\Scripts\python.exe -m app.main`; it never falls back to system Python.
- `app/main.py` delegates to `app/webview_host.py`.
- Production mode loads the generated, Git-ignored `frontend/dist/index.html`. Development
  mode can load a Vite URL with `--dev-url`. Normal launch follows the saved
  `startup.auto_start_bot` preference (default off); `--stopped` explicitly overrides it off.
  `--check` validates configuration/build availability without opening the UI.
- Tkinter has been removed. There is no legacy GUI or alternate application lifecycle.

## Frontend

Responsibility: presentation and explicit user actions only.

- Stack: React 19, TypeScript, and Vite under `frontend/`.
- Pages: Dashboard is the daily bot/Twitch/AI control center; Commands owns command behavior;
  AI owns runtime toggles, Gemini model configuration, and personalities; Logs owns diagnostics;
  Settings owns desktop/window behavior, Twitch connection metadata, and secure credentials.
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
  commands and command Apply/Save/Reset, AI status/toggles, personality Apply/Save/Reset,
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
- `Application.startup()` initializes the database and loads tracked filter rules.
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
- `AppSettingsStore` supplies the versioned local application settings. Its `window` section
  owns start-minimized, minimize-to-tray, and close-to-tray behavior. Its `twitch` section may
  override the non-secret target-channel login and numeric user ID. Start minimized controls
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
- Handler-specific behavior remains in handlers; for example, `tg` bypasses the global
  `OutputLimiter` without changing generic command settings.

## Command settings persistence

- Type/validation and JSON persistence live in `app/command_settings.py`.
- Local file: platform app-data `config/command_settings.json`.
- Writes use temporary-file flush/fsync followed by replacement. Missing, malformed, stale,
  and individually invalid overrides fall back safely to registry defaults.
- Apply changes runtime state, Save writes a minimal difference from defaults, and Reset
  removes the override and restores registry defaults.

## AI and Gemini flow

Responsibility: policy and provider work remain in Python.

1. The `ask` command validates non-empty input and applies `AIRequestPolicy`.
2. If enabled, recent per-user AI memory is loaded from SQLite and formatted as untrusted
   context.
3. `TwitchAPIService` supplies the current category as optional untrusted context, cached for
   90 seconds.
4. `GeminiAIService` owns one reusable Gemini SDK client for the effective credential. It
   retires an old client after active calls finish if the credential changes, and the composed
   `Application` closes provider resources during shutdown. The service builds protected shared
   instructions plus the effective personality, conditionally enables Google Search grounding,
   calls the selected Gemini model, and uses
   the configured fallback only for model-not-found/unsupported responses. It then filters the
   response and applies the configured response-length limit.
5. A successfully delivered response is saved to memory only if memory remains enabled.

Gemini selected/fallback model defaults come from typed environment `Settings`; validated local
overrides in platform app-data `config/app_settings.json` are applied before composition and UI changes update the
shared Settings object for the next request. Tracked presets live in
`app/resources/gemini_models.json`, while provider discovery is optional. The Gemini API key is
resolved from Windows Credential Manager first, then the private `.env` fallback. Provider
failures do not disable unrelated commands.

## Personalities and AI memory

- Built-in personality-specific prompts are tracked UTF-8 data in
  `app/resources/personalities.json` and loaded by `app/config/personalities.py`. Protected
  shared instructions remain application code there; the active source default is in root
  `config.py`.
- Only personality-specific text is editable. `RuntimeState` overlays local prompts and active
  selection from platform app-data `config/personality_settings.json`.
- Personality Apply is runtime-only, Save is persistent, and Reset restores the built-in text.
  Shared AI instructions are never sent to the editor.
- `AIMemoryService` uses repository-backed SQLite storage and retains the configured number of
  successful exchanges per Twitch user. AI memory enablement starts from the source default
  overlaid by platform app-data `config/app_settings.json`; UI changes persist there before updating RuntimeState.

## Twitch boundary

- `app/twitch/client.py` owns TwitchIO lifecycle, OAuth adapter/scopes, token load/save, chat
  subscription, incoming-message mapping, and connection-state updates.
- `app/services/twitch.py` is the command/service-facing API boundary. It is bound to the
  authenticated TwitchIO client and exposes category and followage lookups.
- `.env` supplies initial Twitch identity/channel defaults. A validated local target-channel
  override is applied before application composition. Named stable-ID connection presets in
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

- `app/credentials.py` wraps `keyring`; on Windows its supported backend is Windows Credential
  Manager. It owns masked status, Replace/Remove, and provider-specific credential tests.
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
| User-entered provider credentials | Windows Credential Manager via `app/credentials.py`; `.env` fallback | OS-backed/private, never ordinary JSON |
| Behavioral defaults and paths | root `config.py` | Tracked |
| Built-in personality prompts | `app/resources/personalities.json` | Tracked package data |
| Protected shared AI instructions | `app/config/personalities.py` | Tracked application code |
| Gemini model presets | `app/resources/gemini_models.json` | Tracked package data |
| Ordinary application preferences | App-data `config/app_settings.json` (`startup`, `window`, AI memory/models, non-secret `twitch` target and named target presets) | Outside repository |
| Command overrides | App-data `config/command_settings.json` | Outside repository |
| Personality selection/overrides | App-data `config/personality_settings.json` | Outside repository |
| Twitch OAuth tokens | App-data `auth/twitchio_tokens.json` | Outside repository; secret |
| Users and AI memory | App-data `data/twitch_bot.db` | Outside repository; private |
| Locally editable filters | App-data `config/filters/*.txt` | Outside repository |
| Distributed filter defaults | `data/filters/*.txt` | Tracked, read-only at runtime |
| Frontend source / generated build | `frontend/src`, `frontend/dist` | Source tracked; build ignored |

See `docs/configuration-audit.md` for the current ownership audit and recommended future
configuration direction.

### Runtime data reference

`platformdirs.user_data_path("TwitchBot", appauthor=False)` selects the root: Windows
`%LOCALAPPDATA%\TwitchBot`, macOS `~/Library/Application Support/TwitchBot`, and Linux
`${XDG_DATA_HOME:-~/.local/share}/TwitchBot`. Platform directory overrides may change these
exact locations. `app/runtime_paths.py` owns the paths and first-launch migration. Before
opening local state, a normal desktop launch copies missing legacy checkout JSON, SQLite,
TwitchIO tokens, and filter files to the new root. SQLite is copied through its backup API.
Old files are retained; the `.legacy-migration-v1` marker prevents a later reset from
reimporting them. Missing filter files are reseeded from tracked source defaults. `--check`
does not create directories or migrate data.

Delete `config/app_settings.json`, `config/command_settings.json`, or
`config/personality_settings.json` to reset those non-secret preferences and overrides.
Deleting a file in `config/filters/` restores its distributed default on the next launch.
Deleting `data/twitch_bot.db` destroys saved users and AI memory. Deleting
`auth/twitchio_tokens.json` removes Twitch OAuth access/refresh tokens and requires
reauthorization. The Gemini API key and Twitch client secret live in the OS keyring, with
private `.env` fallbacks; they are never stored in ordinary JSON. There are no persistent
application logs or other cache files at present; `cache/` is reserved for future use.

## Current source and release boundary

- The supported current workflow runs from the source checkout through `run.bat`,
  `python -m app.main`, or the installed `twitch-bot` entry point. There is no standalone
  end-user bundle or installer yet.
- Vite output under `frontend/dist` is generated and ignored. Standalone packaging must rebuild
  it and include the Python runtime plus required tracked resources; it must not require Python,
  Node.js, or the development virtual environment on the target machine.
- Root behavior configuration, packaged personality/model resources, frontend assets, and
  tracked filter defaults are runtime inputs that a future build must include explicitly.
- Local settings, keyring credentials, Twitch tokens, SQLite data, logs, caches, tests, agent
  context, and other development-only material must not be bundled as user data or committed as
  generated release output.
- Windows x64 is the first distribution target. Any later macOS/Linux artifacts must be built
  and validated natively for their pywebview and keyring backends rather than treated as
  cross-compiled variants of a Windows bundle.
