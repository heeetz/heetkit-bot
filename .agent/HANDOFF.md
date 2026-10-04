# Current handoff

Repository code is authoritative. This file records current state and next requested work.

## Repository state

- Branch: `main`; completed work is pushed to `origin/main`.
- TODO-013's pre-packaging review and TODO-013A–013C are complete. Do not repeat the broad review.
- TODO-013A removed personal name rules from shared AI policy; desired protection remains only
  in local profile filters. Shared prompt, credential and content safeguards remain intact.
- TODO-013B declares root `config.py` and required package resources explicitly, makes resource
  and deployment discovery independent of cwd, and supplies complete profile-owned Twitch setup.
- TODO-013C pins and verifies `google-genai==1.75.0`, adds transport/total deadlines and uses
  supported provider cleanup. The former Requests-worker/process-exit blocker is resolved.
- TODO.md retains TODO-013A–013D outcomes and the user's final-checkpoint instructions. Preserve
  those records until the remaining outcomes can be assessed. No standalone artifacts were built.

## Current application state

- Python owns behavior, persistence, providers and lifecycle; React/pywebview presents backend
  state and explicit actions. One backend thread/asyncio loop owns Application and BotRuntime.
- Source launch: `run.bat`, `python -m app.main`, or `twitch-bot`. Production frontend discovery
  prefers `app/resources/frontend/index.html`, then `frontend/dist/index.html` only in a recognized
  checkout. `--dev-url` bypasses build discovery. Non-editable distributions require prebuilt
  frontend staging; automatic staging/freezing remains TODO-014. Generated/staged output is ignored.
- Setuptools includes `config`, `app*` and declared `app.resources` data, with implicit data
  disabled. Filter starters now live in `app/resources/filters`; legacy checkout `data/` is private
  migration input. Installed sibling directories never become default or migration sources.
- `RuntimePaths` selects platform app-data; `--data-dir` overrides `TWITCH_BOT_DATA_DIR`. Config,
  SQLite, OAuth cache and instance guard belong to that profile. Normal launches lock before
  migration; read-only `--check` creates no profile state. Shutdown remains idempotent and bounded.
- Every profile loads its own `.env`. Only the normal source profile retains recognized checkout
  `.env` as a lower-priority fallback; process environment overrides deployment files. The normal
  keyring service remains `twitch-bot`; alternate roots retain hashed namespaces and skip imports.
- Settings saves non-secret client ID, bot login/numeric ID, target login/numeric ID and named
  target presets in the existing version-1 app-settings store. Old target-only files preserve
  deployment identity. Preset and unrelated saves preserve identity. Saved values apply before
  composition; identity/client-ID changes require restart and pending changes block reconnect.
  Target-only reconnect retains the current identity. Twitch secret changes still require restart.
- Secrets remain in OS keyring/private `.env`; OAuth tokens remain under profile `auth/`. No
  ordinary JSON or bridge response contains secret values. UI setup guidance covers client ID,
  identity, target, secret, restart and the existing local Twitch authorization flow.
- Clean profiles open stopped/disconnected. Start requires complete Twitch setup. Gemini remains
  optional; unavailable AI requests consume no policy, memory, cooldown or provider work. Gemini
  credentials apply live without losing saved enabled preferences.
- Gemini uses native HTTPX/aiohttp async I/O with `retry_options.attempts=1`. Generation transport/total
  limits are 45/60 seconds (total includes fallback); discovery limits are 10/15 seconds (total
  includes pagination). Clients are reused by credential; retired leases close on release.
  Async close is bounded to five seconds and sync close always runs. Shutdown retires all clients
  before waiting, preserving lease cleanup if the host cancels the shutdown waiter.
- Neutral starters remain one personality, forecasts/link reminder, and empty commands, triggers,
  filters and presets. Seeding copies missing files only. Config reset preserves SQLite, OAuth
  cache, keyring credentials and migration marker. Forecast editing preserves other local fields.

## Remaining TODO-013 findings

- **TODO-013D must precede packaging freeze:** ordinary Save can replace unrecovered/future-version
  app/custom-command settings; command/personality read failures have a similar preservation risk.
  Startup recovery and atomic writes do not alone prevent this loss. Fun settings already block it.
- **TODO-013E is safe to defer:** bound long-session cooldown bookkeeping. Native platform and
  actual clean-machine artifact checks remain distribution work under TODO-014–019.

## Validation and next requested work

- **144 focused Python tests pass**: 37 Gemini contract/model tests and 107 related AI policy,
  optional-AI, credential, command, bridge and bot-lifecycle regressions. Real installed SDK
  loopback tests exercise both HTTPX and aiohttp, finite stalled/trickling requests, whole-page
  traversal deadlines, cancellation, rotation, normal/cancelled shutdown and subprocess exit.
  Provider calls use only synthetic credentials and a local HTTP server; no live API calls occur.
- The existing project venv was upgraded to the declared SDK pin and editable metadata refreshed.
  Python 3.14 dependency deprecation warnings remain. Frontend code did not change, so no frontend
  checks were repeated. TODO-013B's resource/setup validation remains recorded in TODO.md.
- One final focused diff review completed. Native WebView/tray rendering, real Twitch OAuth,
  live provider calls, actual wheel/frozen artifacts and clean-machine execution remain unexercised.
  No broad codebase audit or standalone packaging was performed.
- Next only when requested: **TODO-013D**. It remains required before packaging freeze.
  After TODO-013A–013D outcomes are available, apply the retained checkpoint instructions without
  another broad review. The application is not cleared for packaging. Stop after TODO-013C.
