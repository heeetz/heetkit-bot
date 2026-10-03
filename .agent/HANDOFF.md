# Current handoff

Repository code is authoritative. This file records the current state and next requested work.

## Repository state

- Branch: `main`; completed work is pushed to `origin/main`.
- Latest application-code baseline: TODO-009 desktop Filters management. TODO-010 clarified
  source sharing and the future end-user release boundary without changing application behavior.
- Normal source launch: Windows `run.bat`; all platforms `python -m app.main` or installed
  `twitch-bot` after installing dependencies and building the frontend.

## Current application state

- React/TypeScript/Vite is the desktop presentation layer hosted by pywebview. Python owns the
  application and domain core behind `WebUIBridge`.
- One `AsyncioBackendHost` owns one asyncio loop, composed `Application`, and `BotRuntime`.
  Window close, Tray Exit, and host teardown share an idempotent shutdown path.
- Normal desktop launches guard the app-data settings path: Windows uses a named mutex;
  macOS/Linux use a nonblocking advisory file lock. Read-only `--check` bypasses the guard.
- `app/runtime_paths.py` owns the platformdirs app-data root and first-launch migration of
  legacy checkout settings, SQLite, OAuth tokens, and filters. Old files remain. The migration
  marker prevents reset state from being reimported; missing filters reseed from source defaults.
- Preferences and command/personality overrides live under app-data `config/`; SQLite users
  and AI memory under `data/`; TwitchIO OAuth tokens under `auth/`. The system keyring owns
  user-entered Gemini and Twitch client secrets, with private `.env` fallback.
- Windows uses one pystray tray icon. macOS/Linux source launches keep the pywebview window
  visible and close normally; saved tray/start-minimized options are unavailable there. If the
  Windows tray fails to start, the window remains reachable.
- Commands remain registry-driven with canonical thread-safe `RuntimeState` settings. Apply is
  session-only, Save persists a validated override, and Reset restores registry defaults.
- Custom commands are separate versioned app-data templates with stable IDs, aliases, permission,
  cooldowns, and one or more random-selected responses. The Commands page manages them; the
  existing dispatcher applies policy and ignores malformed local entries safely.
- Ordinary chat reactions load from versioned app-data `config/message_triggers.json`, seeded
  from a tracked `вась` example. Matching supports contains/exact and case sensitivity, with
  probability, global cooldown, literal responses, and one reply at most per message. Bot and
  command messages are excluded; the existing output limiter applies. Edits require restart.
- Twitch connection state distinguishes stopped, connecting, connected, reconnecting,
  authorization required, and terminal failure. TwitchIO owns ordinary network recovery.
- Standard Python logging feeds a bounded backend buffer and bounded React view. Log Clear is
  frontend-local. The Filters page edits local blocked words, phrases, and Python regex rules.
  Apply changes active rules for the session; Save persists the validated rules in app-data text
  files. It identifies source-default and local rules and shows invalid entries. Loader failures
  and invalid-only files retain prior active rules.
- Settings uses responsive grids and a wider bounded layout; explanatory copy retains readable
  line lengths. Commands cards reflow controls and actions at narrow desktop widths.
- The application runs from source. `scripts/package.ps1` creates a tracked-files developer
  source archive, including agent notes, docs, and tests. It is not an end-user app or public
  source release. No native distributable, installer, or automated release pipeline exists yet.
  A future app packaging spec must explicitly include runtime assets and exclude development
  material; public source publication needs a separate current-tree and Git-history secret check.

## Active roadmap

- `TODO.md` contains unfinished work only; completed history is in Git.
- Next item: **TODO-011 — Establish final branding and icon assets**. Start only when requested.

## Important open risks

- TwitchIO does not emit an immediate application event for every transport interruption;
  state changes when its WebSocket close/welcome or subscription events are dispatched.
- Required Twitch configuration is validated before the UI opens, so first-run recovery still
  depends on external `.env`/credential setup.
- macOS/Linux source startup was reviewed against supported pywebview backends but has not
  been run natively. Linux needs a GTK/WebKit or Qt backend and system libraries; keyring and
  tray availability depend on the desktop environment. Native packaging remains future work.

## Validation baseline

- TODO-010 source ZIP was generated and inspected: expected developer files were present and
  excluded private/build/patch artifacts were absent. No tracked temporary artifacts were found.
