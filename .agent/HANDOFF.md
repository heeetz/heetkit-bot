# Current handoff

Replace outdated statements when the project changes. This file describes current state, not a
task history; repository code remains authoritative.

## Repository state

- Branch: `main`; remote target: `origin/main`.
- Latest application-code baseline: TODO-001 filter loading hardening (this commit).
- Normal launch paths: `run.bat`, `python -m app.main`, or installed `twitch-bot`.
- No active partially completed implementation task exists.

## Current application state

- React/TypeScript/Vite is the only desktop UI, hosted by pywebview. Python owns the application
  and domain core behind the explicit `WebUIBridge`; Tkinter has been removed.
- One `AsyncioBackendHost` owns one background asyncio loop, composed `Application`, and
  `BotRuntime`. Bot start/stop/reconnect and orderly shutdown stay on that lifecycle. Window
  close, Tray Exit, and host teardown converge on the same idempotent shutdown path.
- One `DesktopController` owns one tray icon. Start-minimized affects initial visibility only;
  minimize-to-tray and close-to-tray change window behavior without creating another tray or
  shutdown path.
- Normal Windows desktop launches hold a named single-instance mutex before local state loads.
  Duplicate launches report the existing process and exit; read-only `--check` bypasses it.
- Bridge calls waiting on backend work have explicit deadlines, request cancellation on timeout,
  and observe uncancelled late completion. AI-memory and Gemini-model persist-and-apply changes
  execute in backend-loop order.
- Commands are registry-driven and use canonical thread-safe `RuntimeState` settings. Apply is
  session-only, Save persists a validated override, and Reset restores registry defaults.
- Ordinary non-secret preferences use versioned `data/app_settings.json`; command and personality
  overrides remain in their dedicated ignored JSON stores. Writes are atomic and malformed or
  stale values fall back safely where defined.
- Built-in personality prompts and Gemini model presets are tracked resources. Shared AI
  instructions remain protected Python-owned policy; only personality-specific local overrides
  are editable.
- Gemini API keys and Twitch client secrets use the OS keyring abstraction (Windows Credential
  Manager on the current target), with private `.env` values retained as startup fallbacks.
  TwitchIO OAuth tokens remain in its ignored local token cache.
- Twitch target-channel settings and named target presets contain no credentials and reconnect
  through the shared bot lifecycle. TwitchIO remains responsible for normal network recovery.
- Standard Python logging feeds a thread-safe bounded backend buffer and bounded React view with
  whitelisted semantic metadata. Log Clear is frontend-local and secrets must never be logged.
- Filter files load independently. Missing/unreadable files keep their previous rules on reload;
  malformed UTF-8 lines and invalid regex entries are skipped with file/line diagnostics. An
  invalid-only file also keeps the last valid rules; an intentionally empty file clears them.
- The application currently runs from source. No standalone bundle, installer, or automated
  release pipeline exists yet; generated frontend/release output remains untracked.

## Active roadmap

- `TODO.md` contains unfinished work only; completed implementation history is in Git.
- Next item: **TODO-002 — Give the Gemini client one clear lifecycle owner**. Start it only when explicitly
  requested.
- Later work covers Gemini client ownership, Twitch recovery observability, platform app-data,
  portability/layout polish, custom commands/triggers/filter UI, and distribution.

## Important open risks

- Gemini clients are constructed per operation without one explicit lifecycle owner.
- Twitch disconnect/recovery and terminal authentication/configuration failures need clearer
  state and focused coverage without adding a competing reconnect loop.
- Mutable runtime data still lives under checkout-relative paths pending the platform app-data
  migration.
- Required Twitch configuration is validated before the UI opens, so first-run recovery still
  depends on external `.env`/credential setup.

## Validation baseline

- TODO-001 compilation and a standard-library filter-loading smoke check passed. Focused pytest
  was unavailable in this agent environment: the project virtualenv could not execute and fallback
  Python lacks pytest.
- The latest full-suite milestone passed 119 tests; frontend typecheck/build and
  `python -m app.main --check` passed at that milestone.

## Workspace note

- Unrelated pre-existing local edits to `AGENTS.md` and `data/filters/blocked_words.txt` are not
  part of this migration and must remain unstaged unless a future user request explicitly owns
  them.
