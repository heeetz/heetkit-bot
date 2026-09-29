# Current handoff

Replace outdated statements in this file when project state changes. Do not append a session
transcript.

## Repository state

- Branch: `main`.
- Remote target: `origin/main`.
- Latest completed task: **TODO-004 — Move built-in personalities to tracked data resources**
  (committed with this handoff).
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
- `data/app_settings.json` is schema version 1 with `window` and `ai` sections. It persists
  window/tray behavior and AI-memory enablement while accepting the legacy flat window format.
- Personality-specific overrides and active selection are local data; shared AI instructions
  remain protected source code.
- Built-in personality-specific prompts load from tracked
  `app/resources/personalities.json`; all existing IDs and prompt text are preserved.

## TODO position

- Latest completed TODO: **TODO-004 — Move built-in personalities from Python code to tracked data resources**.
- Expected next TODO: **TODO-005 — Secure credential storage**.
- Do not start TODO-005 unless it is explicitly requested.
- A deferred **TODO-R1 architecture and reliability checkpoint** belongs after the current
  configuration/settings/UX work and before custom commands/triggers. It has not been run.

## Known issues and unfinished work

- Twitch identity, provider/model, logging, database, and command-parser settings remain in
  `.env` pending their focused TODOs; `.env` still mixes secrets with these non-secret values.
- AI enablement has one canonical owner (`ask` command settings) but different persistence UX
  between AI and Commands pages.
- Tracked filter defaults are also the current manual customization surface.
- Gemini model selection is read-only in the UI and no fallback model is configured.
- Secure OS-backed credential storage, Twitch/AI settings UX, filters UI, custom commands,
  triggers, standalone packaging, and releases remain unfinished TODO work.

## Recent validation

- TODO-001 lifecycle work: `python -m compileall -q app tests` passed and
  `pytest -q tests/test_webview_host.py` passed with 19 tests.
- TODO-003: `python -m compileall -q app tests` passed and the focused app-settings and
  desktop-host test selection passed with 32 tests.
- TODO-004: `python -m compileall -q app tests` passed and the focused personality selection
  passed with 14 tests; prompt hashes verify exact preservation of all six built-ins.
- The last full Phase 3 suite passed with 119 tests; frontend typecheck/build and
  `python -m app.main --check` also passed at that milestone.

## Migration state

- The legacy desktop migration is complete: pywebview is the only GUI path.
- Local ordinary settings now use versioned `data/app_settings.json`. Version 1 has `window`
  and `ai.memory_enabled`; a legacy flat window file is read safely and the next successful
  save writes the versioned form.
- Command and personality overrides intentionally remain in their dedicated JSON stores.
- Built-in personality prompts are tracked package data; local personality selection and
  overrides remain in ignored `data/personality_settings.json`.
- Local runtime files, databases, logs, frontend build output, `.env`, and tokens are ignored.
