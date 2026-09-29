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
  mode can load a Vite URL with `--dev-url`. `--stopped` suppresses automatic bot connection;
  `--check` validates configuration/build availability without opening the UI.
- Tkinter has been removed. There is no legacy GUI or alternate application lifecycle.

## Frontend

Responsibility: presentation and explicit user actions only.

- Stack: React 19, TypeScript, and Vite under `frontend/`.
- Pages: Dashboard, Commands, AI, Logs, and Settings.
- `frontend/src/bridge.ts` defines the typed pywebview API surface. React does not import
  Python internals or implement command permissions, persistence, AI policy, or Twitch logic.
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
  app settings, and recent logs.
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
  owns start-minimized, minimize-to-tray, and close-to-tray behavior. Start minimized controls
  only initial window visibility.

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
   conditionally enables Google Search grounding, calls the configured Gemini model, filters
   the response, and applies the configured response-length limit.
5. A successfully delivered response is saved to memory only if memory remains enabled.

Gemini API key/model currently come from typed environment `Settings`. Provider failures do
not disable unrelated commands.

## Personalities and AI memory

- Protected shared instructions and built-in personality definitions currently live in
  `app/config/personalities.py`; the active source default is in root `config.py`.
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
- OAuth tokens are stored in the configured local TwitchIO token file. They are secrets and
  are ignored by Git.

## Logging

- Standard Python `logging` remains authoritative.
- `app/utils/logging.py` attaches a thread-safe `RecentLogHandler` backed by a bounded
  500-entry deque.
- `WebUIBridge.get_recent_logs()` exposes validated cursor/limit reads. The frontend keeps a
  separate bounded view; Clear affects only that view and does not delete persistent logs.
- Secrets and authorization values must never be added to log messages.

## Configuration and persistence boundaries

| Data | Source of truth / location | Git status |
| --- | --- | --- |
| Typed deployment settings | `app/config/settings.py`, loaded from `.env` | `.env` ignored; `.env.example` tracked |
| Behavioral defaults and paths | root `config.py` | Tracked |
| Built-in personalities/shared instructions | `app/config/personalities.py` | Tracked |
| Ordinary application preferences | Versioned `data/app_settings.json` (`window`, `ai`) | Ignored local state |
| Command overrides | `data/command_settings.json` | Ignored local state |
| Personality selection/overrides | `data/personality_settings.json` | Ignored local state |
| Twitch OAuth tokens | `data/twitchio_tokens.json` or configured path | Ignored secret state |
| Users and AI memory | `data/twitch_bot.db` by default | Ignored local data |
| Global filter resources | `data/filters/*.txt` | Tracked |
| Frontend source / generated build | `frontend/src`, `frontend/dist` | Source tracked; build ignored |

See `docs/configuration-audit.md` for the current ownership audit and recommended future
configuration direction.
