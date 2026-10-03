# Current handoff

Repository code is authoritative. This file records the current state and next requested work.

## Repository state

- Branch: `main`; completed work is pushed to `origin/main`.
- TODO-012 is complete: one application supports independent profiles with neutral shipped
  defaults. The existing roadmap revision is retained; no later TODO was executed.
- The TODO-012 clean-profile startup regression is fixed: empty Twitch identity and absent
  credentials permit desktop launch; complete setup is required before creating a Twitch session.
- Source launch: Windows `run.bat`; all platforms `python -m app.main` or installed `twitch-bot`.
  Build the frontend before production source launch. Native bundles/installers remain future work.

## Current application state

- Python owns domain behavior, persistence, Twitch/Gemini, and lifecycle. React/pywebview is
  presentation; one backend host owns one asyncio loop, composed application, and bot runtime.
- Normal launches guard the selected profile before reading data. `--check` bypasses the guard
  and performs no migration or directory creation. Shutdown is shared and idempotent.
- `app/runtime_paths.py` selects platform app-data by default. `--data-dir <path>` takes priority
  over `TWITCH_BOT_DATA_DIR`. Config, filters, SQLite, OAuth cache, and the instance guard use
  that profile. Alternate profiles never automatically import checkout state.
- The normal profile retains the original keyring service. Alternate roots get independent,
  stable keyring namespaces and use `<profile>/.env` instead of checkout `.env`.
  Explicit process environment variables still override deployment settings.
- Shipped starters: one neutral personality, empty filters/reactions/custom commands/Twitch
  presets, a neutral forecast, and a community-link configuration reminder. Personal style
  and named-person instructions are local data. Shared prompt safety remains application code.
- The owner's former shipped personalities, named-person style rules, fun-command responses,
  filters, and reactions were preserved in the normal local profile before defaults changed.
  Existing local overrides were retained. No profile values or credentials were committed.
- User personalities (including retired shipped IDs) survive through local overrides. Built-in
  Reset restores the shipped prompt; local-only Reset clears its text and retains its ID.
- Missing configs recover neutral starters; existing files are never overwritten by seeding.
  `.legacy-migration-v1` remains outside config, preventing config reset from reimporting state.
  Database, OAuth cache, and keyring credentials survive deletion of only `config/`.
- `config/fun_settings.json` optionally stores version-1 `tg_message` and `forecasts` for existing
  built-ins; edits take effect after restart. No alternate owner build exists.
- Command policy, filter editing, Twitch recovery, Gemini client ownership, tray behavior and
  branding remain as documented in `.agent/ARCHITECTURE.md`.

## Next requested work

- **TODO-013 — Perform one global pre-packaging codebase review**. Start only when requested.

## Open risks and validation

- Fresh profiles open stopped/disconnected and retain the dashboard's Configure Twitch guidance.
  Missing client secrets are `None`. Start/reconnect validate complete connection setup and return
  safe field-name errors; incomplete automatic startup is skipped while the UI remains usable.
  Twitch identity/client ID still use profile deployment settings; credential edits require restart.
- macOS/Linux source startup has not been run natively. Linux requires a pywebview backend/system
  libraries; credential backend availability depends on the desktop environment.
- No standalone executable exists yet; TODO-012 validates the shared source runtime's profile semantics.
- TODO-012: 116 focused profile/migration/reset/personality/credential/command/desktop/filter tests
  passed. Python compilation and whitespace validation passed. No frontend source changed.
- Startup regression: 88 focused settings/profile/runtime/Twitch-client/desktop/credential tests
  passed, including actual backend startup with no deployment values and both auto-start settings.
  Python compile checks passed. The native window was not opened by automated tests.
- The sandbox cannot launch the venv's base interpreter; checks used the same project venv
  with approved execution outside the sandbox. This is an agent environment limitation.
