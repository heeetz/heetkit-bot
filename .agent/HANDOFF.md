# Current handoff

Repository code is authoritative. This file records the current state and next requested work.

## Repository state

- Branch: `main`; completed work is pushed to `origin/main`.
- TODO-013 is complete: the one global pre-packaging review is finished. Every known finding
  has a priority and follow-up. Packaging was not started; no build/release artifacts were made.
- Only the isolated empty-target `!erase` error, a stale desktop-settings test expectation,
  and README accuracy were changed. Empty or `@`-only targets now leave memory untouched
  without logging an exception; the bridge test includes its existing `tray_available` field.
- TODO.md contains unfinished follow-ups; do not run another generic review or start the next
  task automatically. No architecture/ownership boundary or durable decision changed.

## Current application state

- Python owns behavior, persistence, Twitch/Gemini and lifecycle; React/pywebview is presentation.
  One backend thread owns the application and asyncio loop. Shared runtime/store snapshots use
  locks; async bridge operations submit to that loop with bounded UI waits.
- Source launch: Windows `run.bat`, or `python -m app.main` / installed `twitch-bot` from the
  checkout. Production source launch needs a built `frontend/dist/`. Standalone bundles are future work.
- `RuntimePaths` selects platform app-data; `--data-dir` overrides `TWITCH_BOT_DATA_DIR`.
  Config, SQLite, OAuth cache and instance guard belong to that profile. Alternate profiles skip
  legacy imports and use their own `.env`/hashed keyring service. The normal profile retains
  service `twitch-bot` and currently reads working-directory `.env`.
- Normal launches acquire the profile guard before reading/migrating state. `--check` neither
  locks nor creates/migrates files. Shared shutdown is idempotent with a bounded degraded path.
- Clean profiles launch stopped/disconnected without credentials. Start requires complete Twitch
  setup. Settings edits target channels/presets and secrets; client ID and bot identity still
  require deployment configuration. Twitch secret edits require restart; Gemini edits apply live.
- Gemini is optional; unavailable `ask` requests consume no cooldown/policy/memory/provider work.
  Enabled preferences survive key changes. Existing stores own local command/personality/filter/
  forecast overrides; seeding does not overwrite existing files. Config reset preserves SQLite,
  OAuth cache, keyring credentials and the migration marker.
- Shipped starters are neutral personality/forecast/link reminder and empty commands/triggers/
  filters/presets. Remaining owner-specific AI policy is a classified release blocker below.
- Built-in command cards start collapsed. Forecast Apply/Save/Reset uses its profile store and
  preserves other fields. Non-AI commands and memory erasure work without Gemini.

## TODO-013 prioritized report — 2026-10-04

**Release blockers, resolve before TODO-014:**

1. **TODO-013A:** request/response policy still embeds the original owner's name rules
   (`app/services/ai_request_policy.py`, `app/services/gemini_ai_service.py`). Neutral local
   defaults do not remove this personal behavior from a distributed runtime.
2. **TODO-013B:** installation/setup assumes the checkout. Runtime imports need root `config.py`,
   but setuptools declares only `app*`; frontend/default filters use sibling paths. Default-profile
   `.env` discovery depends on working directory, and the GUI cannot configure client ID/bot identity.
3. **TODO-013C:** declared/installed `google-genai` 0.8.0 uses Requests in `asyncio.to_thread`
   with no HTTP timeout unless supplied. Coroutine deadlines cannot stop a stalled network worker;
   that worker can survive backend shutdown and hold process exit. Lifetime mocks expose close
   methods absent from this installed SDK, so passing mock tests do not establish transport cleanup.

**Should fix before v1:** **TODO-013D** protects unrecovered profile files. App/custom-command
load failures fall back to defaults, then ordinary Save can replace the original/future-version
file. Command/personality read failures have the same preservation risk. Atomic writes alone
prevent partial writes, not loss of unrecovered data; the fun-settings store already blocks this.

**Safe to defer:** **TODO-013E** bounds lifetime cooldown entries for very large/long-lived
channels. Native macOS/Linux verification remains **TODO-019**. Reproducible runtime dependencies,
version/icon/WebView2 handling, and actual clean-machine artifact verification
remain the scoped distribution work in **TODO-014–018**, without another architecture audit.

The pass covered module ownership/obsolete-file risk, paths/resources, tracked privacy,
credential boundaries, storage/migration, first run, lifecycle/single instance, thread/async
ownership, Twitch/Gemini lifetimes, bridge signatures/payload consumers, dependencies, README
and release-relevant tests. Existing audit docs/developer scripts are intentional source material;
exclude them from runtime artifacts. All declared runtime dependencies have consumers; Pillow is
currently supplied transitively by pystray. No file-count refactor or unrelated cleanup was done.
Current tracked-file inventory and a redacted credential-pattern scan found no credentials,
OAuth caches, databases, local profiles or private absolute user paths. This was a current-tree
review, not Git-history sanitization or a dependency-vulnerability audit.

## Validation and next requested work

- Full automated suite ran once: **250 passed, 1 failed**. The sole failure was an obsolete
  expected bridge response missing `tray_available`; its isolated correction passed the one
  targeted rerun (**1 passed**). No second full-suite run or generic review was performed.
- Read-only validation passed: syntax for all **79 tracked Python files**, parsing of all
  **8 tracked JSON files**, and **38 public bridge method names/argument signatures**.
  The three new empty-target erasure cases passed in the full run. Dependency deprecation
  warnings on Python 3.14 remain; no dependency changes/installations were made.
- Existing automated coverage protects empty-profile launch/isolation, migration/reset survival,
  credential redaction, instance guard, bounded host/bridge waits, tray fallback, Twitch auth/
  reconnect, SDK lease rotation, atomic saves and frontend-entrypoint presence.
- Frontend sources were unchanged; no frontend build/typecheck or packaging was run.
- Actual native WebView/tray UI, real provider authorization, a Python 3.12 environment and
  clean-machine artifacts were not exercised by this checkpoint. The available venv uses Python
  3.14; sandbox execution of its base interpreter is restricted, so checks require approved
  execution of the same project venv outside the sandbox.
- Next only when requested: **TODO-013A**, followed by the remaining classified follow-ups.
  TODO-014 is gated on TODO-013A–013C. The review checkpoint is complete; the app is not yet
  cleared for packaging. Stop here.
