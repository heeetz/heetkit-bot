# Current handoff

Replace outdated statements in this file when project state changes. Do not append a session
transcript.

## Repository state

- Branch: `main`.
- Remote target: `origin/main`.
- Latest completed task: **TODO-R2 — Harden shutdown timeout behavior**
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
  `AsyncioBackendHost` serializes that work through one shutdown future; deadline overruns cancel
  pending asyncio work, use a bounded forced-stop grace period, and cannot keep the process alive
  through the daemon backend worker.
- Commands use registry defaults, optional local overrides, and canonical `RuntimeState`
  effective values.
- `data/app_settings.json` is schema version 1 with `startup`, `window`, `ai`, and `twitch`
  sections. It persists opt-in automatic bot startup, window/tray behavior, AI-memory
  enablement, selected/fallback Gemini models, and optional target-channel overrides while
  accepting the legacy flat window format.
- Personality-specific overrides and active selection are local data; shared AI instructions
  remain protected source code.
- Built-in personality-specific prompts load from tracked
  `app/resources/personalities.json`; all existing IDs and prompt text are preserved.
- Gemini API keys and Twitch client secrets use Windows Credential Manager through `keyring`,
  with private `.env` values retained as startup fallbacks.
- The Settings page exposes Twitch connection/account/OAuth-cache status and named target
  presets. Stable-ID presets persist only display name, channel login, and broadcaster ID in
  ordinary local app settings. Save & reconnect reuses the shared `BotRuntime` lifecycle;
  secure credentials, authenticated bot identity, and TwitchIO tokens retain their stores.
- The Settings page exposes Google Gemini provider/model configuration using tracked backend
  presets, optional provider discovery, and custom IDs. Model changes apply to the next AI
  request; only model-not-found responses use the configured fallback.
- Window/tray toggles auto-save with clear effect timing. Dismissible feedback toasts remain
  visible while the independently scrolling main pane moves; the desktop sidebar stays fixed.
- Normal desktop launch leaves the bot stopped unless the local
  `startup.auto_start_bot` preference is enabled. It is independent of start-minimized, and
  `--stopped` remains an explicit override. Status polling waits for a populated pywebview API.
- Gemini model choices are native selects populated from backend presets/discovery, with a
  separate input shown only for a custom model ID.
- All normal boolean controls use one reusable native-checkbox-backed React switch component,
  including command, AI, window/startup, and log auto-scroll controls. Existing Apply/Save and
  auto-save behavior is unchanged.
- Dashboard is the compact daily control center for bot start/stop, Twitch connection/channel,
  uptime, and AI runtime/model/personality state. Its AI toggles call the same bridge actions as
  the AI page. Gemini model discovery/selection now lives beside personalities on AI; Settings
  retains desktop/window, Twitch connection, and secure credential controls.
- Dashboard derives a first-run checklist from the existing Twitch target, credential, AI-model,
  and personality APIs. Contextual actions scroll to the authoritative Twitch/credential editor
  or open AI; Settings and AI show explicit missing/not-configured states without duplicating
  persistence or introducing a mandatory onboarding flow.
- Live logs retain their bounded standard-logging pipeline and whitelisted semantic metadata for
  chat direction, commands/cooldowns, Twitch lifecycle, Gemini activity, and settings actions.
  React presents important values in reusable priority-aware chips without message regexes:
  cooldown duration, command/user, AI model/duration, and Twitch channel/action are immediately
  scannable while secondary context and raw diagnostics remain available. Severity, raw-message
  search/filtering, auto-scroll, and local Clear remain intact.
- TODO-UX6 found no reproducible application-level scrolling defect in the production
  pywebview/WebView2 host. The fixed sidebar and independently scrolling main pane remain
  unchanged; any recurrence should be captured as a platform/input-specific case before code or
  CSS is changed.

## TODO position

- Latest completed TODO: **TODO-R2 — Harden shutdown timeout behavior**.
- The daily-use UX sequence through TODO-UX7 is complete. The next reliability follow-up is
  **TODO-R3 — Add single-instance / local-state contention protection**, but start it only when
  explicitly requested.
- The completed checkpoint is `docs/architecture-reliability-checkpoint.md`. Its high-priority
  reliability findings should be fixed in focused tasks or explicitly accepted before release.

## Known issues and unfinished work

- Multiple application launches are not prevented and can contend for Twitch, SQLite, tokens,
  OAuth port 4343, and local JSON stores.
- Filter loading catches I/O failures despite startup intending to fail safely, and invalid
  regexes are not validated at load time.
- TwitchIO owns normal reconnect, but reconnect-state restoration and terminal-failure recovery
  lack focused coverage; bridge timeout/late-completion behavior is also untested.
- Gemini clients are created per operation without an explicit lifetime. The installed
  `google-genai 0.8.0` API has no public close method, so the dependency baseline and ownership
  should be addressed together.
- Required Twitch configuration is validated before the desktop UI opens, so first-run recovery
  still depends on `.env`/credential setup outside the UI.
- Filters UI, custom commands, triggers, standalone packaging, and releases remain unfinished.

## Recent validation

- TODO-001 lifecycle work: `python -m compileall -q app tests` passed and
  `pytest -q tests/test_webview_host.py` passed with 19 tests.
- TODO-003: `python -m compileall -q app tests` passed and the focused app-settings and
  desktop-host test selection passed with 32 tests.
- TODO-004: `python -m compileall -q app tests` passed and the focused personality selection
  passed with 14 tests; prompt hashes verify exact preservation of all six built-ins.
- TODO-005: `python -m compileall -q app tests` passed; 29 focused credential/settings/bridge
  tests passed; frontend typecheck and production build passed.
- TODO-006: `python -m compileall -q app tests` passed; 52 focused settings/lifecycle/bridge/
  credential tests passed; frontend typecheck and production build passed.
- TODO-007: `python -m compileall -q app tests` passed; 65 focused settings/Gemini/bridge/
  credential tests passed; frontend typecheck and production build passed.
- TODO-008: frontend typecheck and production build passed. No Python code changed, so Python
  tests were not rerun.
- TODO-R1: source/dependency/security review completed; `pip check` reported no broken
  requirements, all 158 Python tests passed, and `python -m compileall -q app tests` passed.
  The suite emitted dependency deprecation warnings for TwitchIO/aiohttp and `pytest-asyncio`;
  no frontend code changed. A separate focused cleanup removed the duplicate tray-menu refresh
  and its 26 desktop-host tests plus the compile check passed.
- TODO-UX1: 50 focused app-settings/desktop-host tests passed; frontend typecheck and production
  build passed. The project virtual environment required execution outside the restricted agent
  sandbox; no environment workaround was added to the repository.
- TODO-UX2: frontend typecheck and production build passed. No Python or backend behavior changed,
  so Python tests were not rerun.
- TODO-UX3: frontend typecheck and production build passed. No Python or backend behavior changed,
  so Python tests were not rerun.
- TODO-UX4: `python -m compileall -q app tests` passed; 53 focused app-settings/desktop-host
  tests passed; frontend typecheck and production build passed.
- TODO-UX5: `python -m compileall -q app tests` passed; 71 focused logging/command/Twitch/bridge
  tests passed; frontend typecheck and production build passed.
- Logs readability follow-up: representative semantic, generic, warning, and error rows were
  visually verified at 1440x900 and 900x800; frontend typecheck and production build passed.
- TODO-UX6: the real production pywebview/WebView2 host was measured on the 2,127 px Settings
  page across multiple polling intervals. The 6.5-second probe recorded 354 frames (18.41 ms
  average, 19.90 ms p95, 24.60 ms maximum), no frames over 25 ms, no long tasks, and no idle
  scroll-position reset. No application code changed, so frontend/Python suites were not rerun.
- TODO-UX7: first-run Dashboard, Settings, and AI empty states plus contextual setup navigation
  were visually verified at 655 px and 1,180 px viewport widths; frontend typecheck and production
  build passed. No Python code changed, so backend tests were not rerun.
- TODO-R2: `python -m compileall -q app tests` passed and all 31 focused desktop-host tests
  passed, including orderly close, startup failure cleanup, repeated close, and the bounded
  degraded path for an unresponsive shutdown.
- The last full Phase 3 suite passed with 119 tests; frontend typecheck/build and
  `python -m app.main --check` also passed at that milestone.

## Migration state

- The legacy desktop migration is complete: pywebview is the only GUI path.
- Local ordinary settings now use versioned `data/app_settings.json`. Version 1 has independent
  `startup.auto_start_bot` and `window` settings, `ai.memory_enabled`, optional
  selected/fallback Gemini models, and optional non-secret `twitch` target-channel fields and
  named target presets; a
  legacy flat window file is read safely and the next successful save writes the versioned form.
- Command and personality overrides intentionally remain in their dedicated JSON stores.
- Built-in personality prompts are tracked package data; local personality selection and
  overrides remain in ignored `data/personality_settings.json`.
- Windows Credential Manager is the preferred store for user-entered Gemini/Twitch client
  credentials. `.env` remains a private fallback; credential values never enter ordinary JSON.
- Local runtime files, databases, logs, frontend build output, `.env`, and tokens are ignored.
- Twitch presets intentionally do not model authenticated bot profiles. The current process
  continues to use one configured bot identity and OAuth cache; multi-account authentication is
  deferred rather than simulated through channel presets.
- An unrelated local edit to `AGENTS.md` and user roadmap/filter changes predate TODO-R2 and
  remain intentionally uncommitted except for completed TODO-UX1 through TODO-UX7 and TODO-R2
  subsections.
