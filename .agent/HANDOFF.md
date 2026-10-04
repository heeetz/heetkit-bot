# Current handoff

Repository code is authoritative. This file records the current state and next requested work.

## Repository state

- Branch: `main`; completed work is pushed to `origin/main`.
- TODO-013's global pre-packaging review is complete. Do not repeat it or start packaging yet.
- TODO-013A is complete: personal name rules were removed from shared request/response code.
  The existing owner's protection was preserved only in that profile's local pattern file,
  through the existing filter mechanism. No personal values were added to defaults, tests,
  documentation or project memory. Existing local rules were retained.
- Shared prompt, credential and content safeguards are unchanged. Shipped filters remain empty;
  local filters apply to incoming chat and Gemini response text. README documents this behavior.
- TODO.md retains TODO-013A–013D records for the requested final checkpoint. Preserve those
  records and the user's checkpoint instructions until all requested outcomes can be assessed.
- No architecture/ownership boundary or durable decision changed. No standalone artifacts
  or frontend builds were made. Work stopped after TODO-013A.

## Current application state

- Python owns behavior, persistence, Twitch/Gemini and lifecycle; React/pywebview is presentation.
  One backend thread owns the application and asyncio loop. Shared runtime/store snapshots use
  locks; async bridge operations submit to that loop with bounded UI waits.
- Source launch: Windows `run.bat`, or `python -m app.main` / installed `twitch-bot` from the
  checkout. Production source launch needs built `frontend/dist/`. Standalone bundles are future work.
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
  Enabled preferences survive key changes. Stores own local command/personality/filter/forecast
  overrides; seeding does not overwrite existing files. Config reset preserves SQLite, OAuth cache,
  keyring credentials and the migration marker, while resetting local filters and other config.
- Shipped starters are neutral personality/forecast/link reminder and empty commands/triggers/
  filters/presets. Name protection is profile data, with no original-owner rules in shared AI policy.
- Built-in command cards start collapsed. Forecast Apply/Save/Reset uses its profile store and
  preserves other fields. Non-AI commands and memory erasure work without Gemini.

## Remaining TODO-013 findings

**Release blockers before TODO-014:**

1. **TODO-013B:** installation/setup assumes the checkout. Runtime imports need root `config.py`,
   but setuptools declares only `app*`; frontend/default filters use sibling paths. Default-profile
   `.env` discovery depends on working directory, and the GUI cannot configure client ID/bot identity.
2. **TODO-013C:** declared/installed `google-genai` 0.8.0 uses Requests in `asyncio.to_thread`
   with no HTTP timeout unless supplied. Coroutine deadlines cannot stop a stalled network worker;
   that worker can survive backend shutdown and hold process exit. Lifetime mocks expose close
   methods absent from this SDK, so they do not establish real transport cleanup.

**Should fix before v1:** **TODO-013D** protects unrecovered profile files. App/custom-command
load failures fall back to defaults, then ordinary Save can replace the original/future-version
file. Command/personality read failures have the same preservation risk. Atomic writes prevent
partial writes, not loss of unrecovered data; the fun-settings store already blocks this.

**Safe to defer:** **TODO-013E** bounds lifetime cooldown entries for very large/long-lived
channels. Native macOS/Linux verification remains **TODO-019**. Reproducible dependencies,
version/icon/WebView2 handling and actual clean-machine artifact verification remain scoped
distribution work in **TODO-014–018**, without another architecture audit.

## Validation and next requested work

- **92 focused tests passing** across AI request/response safeguards, local filter loading/saving,
  command dispatch, profile isolation, protected personality prompts and optional AI. The new
  15-case module uses only synthetic identities/credentials and an offline provider fake.
- A one-time redacted check confirmed that only the personal request/response rules were removed,
  all other policy code is unchanged, former identifier variants are accepted with empty filters,
  and the existing owner's local filters still protect both incoming chat and Gemini output.
  A targeted scan found no former personal identifiers in runtime, shipped starters or tests.
- One final diff review completed. Frontend sources were unchanged; no frontend checks or broad
  codebase review were run. Python 3.14 dependency deprecation warnings remain. Checks used the
  existing project venv with approved execution outside the sandbox; no dependencies were changed.
- Native WebView/tray UI, real provider authorization, Python 3.12 and clean-machine artifacts
  remain unexercised. The earlier global checkpoint's test/audit history remains in Git.
- Next only when requested: **TODO-013B**. TODO-013C remains a release blocker; TODO-013D must be
  addressed before the packaging freeze. After TODO-013A–013D outcomes are available, apply the
  retained final-checkpoint instructions without a broad review. The app is not cleared for packaging.
