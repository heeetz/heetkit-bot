# Current architecture

Repository code is authoritative if this summary becomes stale. This document records
responsibilities and boundaries, not implementation detail from entire source files.

## Entry points and desktop shell

- `python -m app.main` is the canonical application entry point. The installed `twitch-bot`
  command resolves to the same function.
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
- `AsyncioBackendHost` creates one background thread with one asyncio loop, builds one
  `Application`, and owns one `BotRuntime`.
- `WebUIBridge` exposes narrow application operations: status, bot start/stop, registered
  commands and command Apply/Save/Reset, AI status/toggles, personality Apply/Save/Reset,
  app settings, Twitch target/status/reconnect, Gemini model settings/discovery, masked
  credential status/actions, and recent logs.
- Async bot operations are submitted to the owning loop with
  `asyncio.run_coroutine_threadsafe`; raw Twitch, database, Gemini, and `RuntimeState` objects
  are not exposed to React.

## Application composition and lifecycle

Responsibility: one application truth and one orderly lifecycle.

- `app/container.py` is the composition root. `build_application()` wires Settings, database,
  shared HTTP client, repositories, services, `RuntimeState`, command registry, and dispatcher.
- `Application.startup()` initializes the database and loads tracked filter rules.
  `Application.shutdown()` closes the HTTP client and database engine.
- `app/bot_runtime.py` owns Twitch-session start/stop on the asyncio loop. Its lifecycle lock
  prevents overlapping session transitions; shutdown stops the bot before closing the
  application.
- `DesktopController.exit_application()` is the idempotent desktop shutdown path used by Tray
  Exit and host shutdown. It closes the backend, stops the tray, and destroys a live window.
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
- Local file: `data/command_settings.json` (Git-ignored).
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
4. `GeminiAIService` builds protected shared instructions plus the effective personality,
   conditionally enables Google Search grounding, calls the selected Gemini model, and uses
   the configured fallback only for model-not-found/unsupported responses. It then filters the
   response and applies the configured response-length limit.
5. A successfully delivered response is saved to memory only if memory remains enabled.

Gemini selected/fallback model defaults come from typed environment `Settings`; validated local
overrides in `data/app_settings.json` are applied before composition and UI changes update the
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
  selection from `data/personality_settings.json` (Git-ignored).
- Personality Apply is runtime-only, Save is persistent, and Reset restores the built-in text.
  Shared AI instructions are never sent to the editor.
- `AIMemoryService` uses repository-backed SQLite storage and retains the configured number of
  successful exchanges per Twitch user. AI memory enablement starts from the source default
  overlaid by `data/app_settings.json`; UI changes persist there before updating RuntimeState.

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
- OAuth tokens are stored in the configured local TwitchIO token file. They are secrets and
  are ignored by Git.

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
| Ordinary application preferences | Versioned `data/app_settings.json` (`startup`, `window`, AI memory/models, non-secret `twitch` target and named target presets) | Ignored local state |
| Command overrides | `data/command_settings.json` | Ignored local state |
| Personality selection/overrides | `data/personality_settings.json` | Ignored local state |
| Twitch OAuth tokens | `data/twitchio_tokens.json` or configured path | Ignored secret state |
| Users and AI memory | `data/twitch_bot.db` by default | Ignored local data |
| Global filter resources | `data/filters/*.txt` | Tracked |
| Frontend source / generated build | `frontend/src`, `frontend/dist` | Source tracked; build ignored |

See `docs/configuration-audit.md` for the current ownership audit and recommended future
configuration direction.
