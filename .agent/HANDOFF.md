# Current handoff

Replace outdated statements in this file when project state changes. Do not append a session
transcript.

## Repository state

- Branch: `main`.
- Remote target: `origin/main`.
- Latest completed product task before agent-context initialization:
  `cafb873 docs: audit configuration ownership`.
- Working application path: `run.bat`, `python -m app.main`, or installed `twitch-bot`.
- No active partially completed task exists.

## Current application state

- The desktop application is React/TypeScript/Vite hosted by pywebview; Tkinter is removed.
- Python remains the application/domain core behind an explicit `WebUIBridge`.
- Dashboard, editable command settings, AI/personality controls, live logs, window/tray
  settings, and a single system tray icon are implemented.
- One background asyncio loop owns the composed application and Twitch session.
- Normal window close, Tray Exit, and host teardown converge on the orderly shutdown path.
- Commands use registry defaults, optional local overrides, and canonical `RuntimeState`
  effective values.
- Personality-specific overrides and active selection are local data; shared AI instructions
  remain protected source code.

## TODO position

- Latest completed TODO: **TODO-002 — Audit and classify all user-configurable values**.
- Expected next TODO: **TODO-003 — Consolidate ordinary local application settings**.
- `docs/configuration-audit.md` is the source document for TODO-003 planning.
- Do not start TODO-003 unless it is explicitly requested.
- A deferred **TODO-R1 architecture and reliability checkpoint** belongs after the current
  configuration/settings/UX work and before custom commands/triggers. It has not been run.

## Known issues and unfinished work

- Ordinary non-secret settings are split across `.env`, root `config.py`, and
  `data/app_settings.json`.
- `.env` currently mixes secrets with non-secret account, model, logging, database, and
  command-parser settings.
- AI-memory enablement changed in the UI is runtime-only and returns to the code default after
  restart.
- AI enablement has one canonical owner (`ask` command settings) but different persistence UX
  between AI and Commands pages.
- Tracked filter defaults are also the current manual customization surface.
- Built-in personality text remains embedded in Python pending TODO-004.
- Gemini model selection is read-only in the UI and no fallback model is configured.
- Secure OS-backed credential storage, Twitch/AI settings UX, filters UI, custom commands,
  triggers, standalone packaging, and releases remain unfinished TODO work.

## Recent validation

- TODO-001 lifecycle work: `python -m compileall -q app tests` passed and
  `pytest -q tests/test_webview_host.py` passed with 19 tests.
- The last full Phase 3 suite passed with 119 tests; frontend typecheck/build and
  `python -m app.main --check` also passed at that milestone.
- TODO-002 and the agent-context initialization are documentation-only; no executable behavior
  was changed and no broad test suite is required.

## Migration state

- The legacy desktop migration is complete: pywebview is the only GUI path.
- Local command, personality, and desktop-setting JSON files intentionally remain separate
  today. TODO-003 may consolidate ordinary app settings but must preserve command/personality
  domain boundaries and backward-compatible behavior.
- Local runtime files, databases, logs, frontend build output, `.env`, and tokens are ignored.
