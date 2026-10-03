# Current handoff

Repository code is authoritative. This file records the current state and next requested work.

## Repository state

- Branch: `main`; completed work is pushed to `origin/main`.
- Latest application-code baseline: TODO-004 platform app-data migration.
- Normal launch paths: `run.bat`, `python -m app.main`, or installed `twitch-bot`.

## Current application state

- React/TypeScript/Vite is the only desktop UI, hosted by pywebview. Python owns the application
  and domain core behind the explicit `WebUIBridge`.
- One `AsyncioBackendHost` owns one asyncio loop, composed `Application`, and `BotRuntime`.
  Window close, Tray Exit, and host teardown share an idempotent shutdown path.
- Normal Windows desktop launches hold a named mutex keyed to the platform app-data settings
  path. Read-only `--check` bypasses the guard and does not migrate or create runtime files.
- `app/runtime_paths.py` owns `%LOCALAPPDATA%\TwitchBot` on Windows and the matching platformdirs
  root on macOS/Linux. Normal startup copies legacy checkout settings, SQLite, tokens, and
  filter files once before loading state. Old files remain; the migration marker prevents
  deleted settings from being reimported. Filter defaults reseed missing local files.
- Non-secret preferences and command/personality overrides live under app-data `config/`.
  SQLite users and AI memory live under `data/`; TwitchIO OAuth tokens live under `auth/`.
  The OS keyring still owns user-entered Gemini and Twitch client secrets, with private `.env`
  fallback. There are no persistent application logs or cache files.
- Commands remain registry-driven with canonical thread-safe `RuntimeState` settings. Apply is
  session-only, Save persists a validated override, and Reset restores registry defaults.
- Built-in personality prompts and Gemini model presets are tracked resources. Shared AI
  instructions remain protected Python-owned policy; only local personality overrides are editable.
- Twitch connection state distinguishes stopped, connecting, connected, reconnecting,
  authorization required, and terminal failure. TwitchIO owns ordinary network recovery.
- Standard Python logging feeds a bounded backend buffer and bounded React view. Log Clear is
  frontend-local. Filters load independently, retaining prior rules after read failures or
  invalid-only files.
- The application currently runs from source. No standalone bundle, installer, or automated
  release pipeline exists yet.

## Active roadmap

- `TODO.md` contains unfinished work only; completed history is in Git.
- Next item: **TODO-005 — Remove accidental Windows-only assumptions from application code**.
  Start it only when explicitly requested.

## Important open risks

- TwitchIO does not emit an immediate application event for every transport interruption;
  state changes when its WebSocket close/welcome or subscription events are dispatched.
- Required Twitch configuration is validated before the UI opens, so first-run recovery still
  depends on external `.env`/credential setup.

## Validation baseline

- TODO-004 Python files passed static parsing and `git diff --check`. Focused pytest could not
  run in the agent environment: the project `.venv` interpreter was access denied, and the
  available fallback interpreter lacks project packages. Migration tests were added for
  existing state, SQLite rows, reset behavior, and missing files.
