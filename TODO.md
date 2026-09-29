# Twitch Bot — TODO

This file is the short source of truth for the next product/UX work.

The current application already has:
- Python application core
- React + TypeScript + Vite desktop UI
- pywebview host
- canonical runtime command settings with persistence
- command editor
- AI personality editor
- live logs
- tray support
- legacy Tkinter removed
- `python -m app.main` as the canonical Python entry point
- root `run.bat` launcher

## Agent execution rules

When asked to work from this file:

1. Read the current repository state first. The repository is authoritative.
2. Work on **one TODO item only** unless the user explicitly asks for more.
3. Do not re-audit the whole project for every task.
4. Do not repeatedly inspect the same files once the required dependency flow is understood.
5. Do not perform unrelated cleanup or refactors.
6. Do not create new abstraction layers unless the task genuinely requires them.
7. Prefer modifying the existing implementation over replacing it.
8. Run focused validation only:
   - `python -m compileall -q app tests`
   - relevant focused tests
   - `npm run typecheck` / `npm run build` only when frontend code changes
9. Do **one** final code-review pass before commit. Do not enter iterative review loops unless that pass finds a concrete defect.
10. If blocked by environment/tooling, report the blocker and stop instead of repeatedly retrying equivalent actions.
11. Preserve unrelated user changes.
12. Never use `git reset --hard`, `git clean -fd`, or force push.
13. Never commit secrets, tokens, local databases, runtime logs, local user configuration, `node_modules`, or generated build artifacts.
14. After a task is complete:
    - update its checkbox in this file to `[x]`;
    - add a short implementation note if useful;
    - commit with a semantic prefix (`feat:`, `fix:`, `refactor:`, `chore:`, etc.);
    - push to `origin/main`.
15. Stop after the requested TODO item is complete. Do not continue into the next item because time/context remains.

---

# P0 — Immediate fixes

## TODO-001 — Fix tray singleton and window-close semantics

- [x] Ensure exactly **one** tray icon exists per application process.
- [x] `Start minimized` must only control initial window visibility; it must not create another tray icon.
- [x] `Minimize to tray = true`:
  - minimizing hides the window;
  - bot keeps running;
  - the existing single tray icon remains available.
- [x] `Minimize to tray = false`:
  - minimizing behaves like a normal Windows minimize to taskbar;
  - bot keeps running.
- [x] `Close to tray = true`:
  - clicking `X` hides the window;
  - bot keeps running;
  - existing tray icon remains available.
- [x] `Close to tray = false`:
  - clicking `X` performs the existing orderly bot/application shutdown;
  - application exits completely.
- [x] Tray `Exit` must reuse the same orderly shutdown path.
- [x] Do not introduce a second tray controller or shutdown path.
- [x] Add/update focused tests for the above combinations.
- [x] No broad settings refactor in this task.

**Acceptance check:** enabling both `Minimize to tray` and `Close to tray` still results in one tray icon only.

---

# P1 — Configuration architecture / UX

## TODO-002 — Audit and classify all user-configurable values

- [x] Inventory current configurable values and where each one lives.
- [x] Classify each value as:
  - source-controlled default;
  - local non-secret user setting;
  - local secret/credential;
  - runtime-only state.
- [x] Identify duplicated/scattered configuration ownership.
- [x] Produce a short proposed target map before changing storage.
- [x] Do not perform the migration in the same task.

Audit recorded in `docs/configuration-audit.md`; no storage or runtime migration was made.

Target principle:

```text
source defaults
    ↓
local non-secret overrides
    ↓
runtime effective state
```

Secrets are separate and must not live in normal JSON configuration.

---

## TODO-003 — Consolidate ordinary local application settings

- [ ] Introduce one cohesive versioned local settings model/file for ordinary non-secret app settings.
- [ ] Avoid one JSON file per checkbox.
- [ ] Keep command overrides separate if their existing dedicated store remains the cleaner boundary.
- [ ] Candidate sections:
  - `window`
  - `twitch`
  - `ai`
  - `general`
- [ ] Missing/malformed settings must safely fall back to source defaults.
- [ ] Use atomic writes.
- [ ] Local settings must be Git-ignored.
- [ ] Do not store API keys, OAuth tokens, refresh tokens, or other credentials here.
- [ ] Keep source-controlled defaults clearly separated from user overrides.

---

## TODO-004 — Move built-in personalities from Python code to tracked data resources

- [ ] Built-in personality text should no longer need to live directly in `.py`.
- [ ] Store built-in personalities as tracked application resources, preferably JSON or another simple data format.
- [ ] Preserve:
  - personality IDs;
  - current wording;
  - active-personality behaviour;
  - Reset-to-built-in behaviour.
- [ ] Keep protected/shared AI instructions application-owned and not casually editable.
- [ ] User personality overrides remain local data and Git-ignored.
- [ ] Do not turn personality data into executable code.

Conceptual model:

```text
tracked built-in personality resource
              ↓
       optional local override
              ↓
          runtime prompt
```

---

## TODO-005 — Secure credential storage

- [ ] Stop treating plaintext user-editable JSON as an acceptable future home for credentials.
- [ ] Add an OS-backed credential abstraction suitable for Windows desktop use.
- [ ] Prefer a small established solution such as the system credential store / `keyring`.
- [ ] Store sensitive values such as:
  - Gemini/API provider keys;
  - user-entered Twitch secrets where applicable;
  - future provider credentials.
- [ ] `.env` may remain a developer/backward-compatible fallback if useful.
- [ ] UI must mask stored values.
- [ ] Support Replace / Remove / Test where appropriate.
- [ ] Never log credential values.

---

# P1 — Twitch settings UX

## TODO-006 — Add Twitch connection settings to the UI

- [ ] Add a clear Twitch section in Settings.
- [ ] Expose ordinary non-secret values such as:
  - target channel;
  - bot account identity/status where available.
- [ ] Add connection/authentication status.
- [ ] Add a safe reconnect/test action if supported cleanly.
- [ ] Store non-secret channel configuration in ordinary local settings.
- [ ] Store secrets/tokens through the credential/auth system, not ordinary JSON.
- [ ] Clearly indicate which changes apply immediately and which require reconnect/restart.
- [ ] Preserve the existing Twitch lifecycle and OAuth flow unless a concrete UX improvement requires a targeted change.

---

# P1 — AI provider/model UX

## TODO-007 — Add AI provider/model configuration

- [ ] Add an AI provider/model section to Settings.
- [ ] Start with the currently supported Google Gemini path rather than pretending to support arbitrary providers immediately.
- [ ] Show:
  - provider;
  - selected model;
  - fallback model;
  - credential status;
  - Test action.
- [ ] Model selection should not be hardcoded only in React.
- [ ] Prefer:
  1. provider model discovery where reliable;
  2. shipped known-good model presets as fallback;
  3. optional custom model ID.
- [ ] Keep model presets/current availability easy to update.
- [ ] Do not silently hide model failures.

Fallback behaviour:
- use fallback for unavailable/unsupported selected model cases where appropriate;
- do **not** blindly retry fallback for invalid credentials, network failure, policy rejection, or generic rate limits;
- log/display when fallback was actually used.

If the selected model becomes invalid, the application should still have a known-good configured fallback where possible.

---

# P1 — Settings UX polish

## TODO-008 — Make settings behaviour obvious to users

- [ ] Clearly communicate whether each setting:
  - applies immediately;
  - applies to the next AI request;
  - requires Twitch reconnect;
  - requires application restart.
- [ ] Prefer auto-save for simple app settings such as tray/window toggles.
- [ ] Keep `Apply / Save / Reset` where runtime-vs-persistent distinction is genuinely useful, such as command settings and personality editing.
- [ ] Add concise success/error feedback (toast/status).
- [ ] Avoid fake controls or settings that are not wired.
- [ ] Keep Settings grouped into understandable sections rather than one long undifferentiated page.

Suggested structure:

```text
Settings
├── General
├── Window & Tray
├── Twitch
├── AI
└── Storage / Reset
```

Keep the full personality editor on its own AI/personality page rather than stuffing it into general settings.

---

# P2 — Product extensibility

## TODO-009 — Configurable simple commands

- [ ] Allow creation of simple commands from presets/data, not generated Python code.
- [ ] Initial types:
  - static response;
  - random response;
  - target-user response;
  - random-recent-user response.
- [ ] Candidate placeholders:
  - `{sender}`
  - `{target}`
  - `{random_user}`
- [ ] Reuse canonical command permission/cooldown settings.
- [ ] Keep implementation intentionally limited; do not build a visual programming language.

---

## TODO-010 — Lightweight message triggers

- [ ] Add simple non-command message triggers.
- [ ] First use case may be `вась` → probabilistic `вась`.
- [ ] Support only what is needed initially:
  - enabled;
  - match mode;
  - probability;
  - cooldown;
  - response(s).
- [ ] Do not invoke Gemini for trivial triggers.
- [ ] Protect against spam/feedback loops.

---

## TODO-011 — Filters UI

- [ ] Add UI management for:
  - blocked words;
  - blocked phrases;
  - regex patterns.
- [ ] Preserve existing filtering semantics exactly.
- [ ] Validate regex before save/apply.
- [ ] Do not weaken current moderation behaviour as part of the UI work.

---

# P3 — Distribution

## TODO-012 — Build standalone Windows application

- [ ] Build frontend automatically.
- [ ] Package Python + pywebview + static frontend into a Windows application.
- [ ] Prefer a repeatable scripted build rather than manual commands.
- [ ] Include required runtime assets.
- [ ] Keep local secrets/user state outside the distributable.
- [ ] Validate launch on a machine/process without relying on the development venv.

---

## TODO-013 — Release pipeline

- [ ] Add versioning strategy.
- [ ] Build Windows artifact through GitHub Actions.
- [ ] Publish versioned GitHub Releases.
- [ ] Keep generated release binaries out of normal source commits.
- [ ] Installer/updater can remain a later enhancement.

---

# Product direction

Long-term direction:

Turn the current personal Twitch bot into a configurable desktop Twitch chatbot application without losing the reliable working implementation that already exists.

The progression should remain:

```text
working personal bot
→ clean configurable desktop app
→ configurable commands/triggers
→ secure onboarding/configuration
→ standalone distributable product
```

Do not prematurely generalize everything for hypothetical users. Generalize only the areas that are already proven useful by the current working bot.
