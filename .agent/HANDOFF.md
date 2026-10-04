# Current handoff

Repository code is authoritative. This file records current state and next requested work.

## Repository state

- Branch: `main`; completed work is pushed to `origin/main`.
- TODO-013's pre-packaging review, TODO-013A–013E and the final A–D checkpoint are complete.
  Do not repeat the broad review. No classified TODO-013 release blocker remains unresolved.
- TODO-013A removed personal name rules from shared AI policy; desired protection remains only
  in local profile filters. Shared prompt, credential and content safeguards remain intact.
- TODO-013B declares root `config.py` and required package resources explicitly, makes resource
  and deployment discovery independent of cwd, and supplies complete profile-owned Twitch setup.
- TODO-013C pins and verifies `google-genai==1.75.0`, adds transport/total deadlines and uses
  supported provider cleanup. The former Requests-worker/process-exit blocker is resolved.
- TODO-013D preserves settings originals before lossy recovery saves and refuses unreadable or
  unsupported files. TODO.md retains TODO-013A–013E outcomes and the completed checkpoint.
- TODO-013E bounds cooldown history and cleanup work within the existing utility. No standalone
  artifacts were built.

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
- `CooldownManager` records only positive global/per-user windows. Each check rotates through
  at most 64 uses, reclaiming expired entries and unreferenced command-policy metadata without
  accumulating expiration records. Rejected and zero-cooldown requests also advance cleanup.
  Active windows are never evicted for capacity. The latest effective command policy applies to
  all retained uses; later overrides cannot revive expired history already reclaimed. Cleanup
  is lazy during dispatch and adds no service, background task or lifecycle owner.
- Gemini uses native HTTPX/aiohttp async I/O with `retry_options.attempts=1`. Generation transport/total
  limits are 45/60 seconds (total includes fallback); discovery limits are 10/15 seconds (total
  includes pagination). Clients are reused by credential; retired leases close on release.
  Async close is bounded to five seconds and sync close always runs. Shutdown retires all clients
  before waiting, preserving lease cleanup if the host cancels the shutdown waiter.
- Neutral starters remain one personality, forecasts/link reminder, and empty commands, triggers,
  filters and presets. Seeding copies missing files only. Config reset preserves SQLite, OAuth
  cache, keyring credentials and migration marker. Forecast editing preserves other local fields.
- App/custom-command, command-override and personality Save/Reset/Delete re-read their source
  before atomic replacement. Unreadable/malformed JSON (including duplicate keys) and unsupported
  app/custom-command versions refuse writes. Supported data absent from the recovered snapshot
  gets a unique exact-byte `<filename>.<unique-id>.recovery` copy beside the original; copy failure
  aborts publication. Unknown fields and skipped entries survive in those private copies, not the
  rewritten schema. Ordinary fully recovered data needs no copy. Manual repair/reset/restoration
  uses a backed-up named config file with the app stopped, followed by restart; README explains it.

## Retained TODO-013 checkpoint

- Reviewed the recorded TODO-013A–013D outcomes against TODO-013's original findings: owner-specific
  shared policy, checkout-dependent runtime/setup, provider transport/process lifetime and settings
  preservation are resolved. No additional codebase audit was performed. TODO-014 can be requested.
- TODO-013E was deferred at that checkpoint and is now complete. Native platform and actual
  clean-machine artifact checks remain distribution work under TODO-014–019.

## Validation and next requested work

- **75 focused Python tests pass** for TODO-013E: cooldowns, command dispatch/settings, custom
  commands, message triggers and optional AI. Checks cover 40,000 distinct chatters across 20
  elapsed windows, zero/global-only policies, bounded idle cleanup, removed command metadata,
  preservation of long active windows, repeated successes, live overrides and alias dispatch.
- Checks used the existing project venv with approved execution outside the sandbox; sandbox
  interpreter access was denied and no default Python was available. Python 3.14 dependency
  deprecation warnings remain. Frontend code did not change, so frontend checks were not run.
  TODO-013A–013D's completed validation remains recorded in TODO.md; no live API calls occurred.
- One final focused diff review completed. Native WebView/tray rendering, real Twitch OAuth,
  live provider calls, actual wheel/frozen artifacts and clean-machine execution remain unexercised.
  No broad codebase audit or standalone packaging was performed.
- Next only when requested: **TODO-014**, reproducible standalone Windows packaging. The
  classified pre-packaging blockers are resolved; release-artifact/clean-machine validation
  remains future distribution work. Stop after TODO-013E; do not start packaging.
