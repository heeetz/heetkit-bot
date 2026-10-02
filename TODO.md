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

- [x] Introduce one cohesive versioned local settings model/file for ordinary non-secret app settings.
- [x] Avoid one JSON file per checkbox.
- [x] Keep command overrides separate if their existing dedicated store remains the cleaner boundary.
- [x] Candidate sections:
  - `window`
  - `twitch`
  - `ai`
  - `general`
- [x] Missing/malformed settings must safely fall back to source defaults.
- [x] Use atomic writes.
- [x] Local settings must be Git-ignored.
- [x] Do not store API keys, OAuth tokens, refresh tokens, or other credentials here.
- [x] Keep source-controlled defaults clearly separated from user overrides.

`data/app_settings.json` schema version 1 now groups `window` preferences and the persisted
AI-memory preference. Legacy flat window settings remain readable; command and personality
overrides remain in their dedicated stores. Twitch/provider/general fields stay deferred to
their focused TODOs.

---

## TODO-004 — Move built-in personalities from Python code to tracked data resources

- [x] Built-in personality text should no longer need to live directly in `.py`.
- [x] Store built-in personalities as tracked application resources, preferably JSON or another simple data format.
- [x] Preserve:
  - personality IDs;
  - current wording;
  - active-personality behaviour;
  - Reset-to-built-in behaviour.
- [x] Keep protected/shared AI instructions application-owned and not casually editable.
- [x] User personality overrides remain local data and Git-ignored.
- [x] Do not turn personality data into executable code.

Conceptual model:

```text
tracked built-in personality resource
              ↓
       optional local override
              ↓
          runtime prompt
```

Built-in personality-specific prompts now load from tracked UTF-8 JSON at
`app/resources/personalities.json`. The loader preserves the existing IDs/order and combines
each prompt with protected shared instructions kept in application code. Local overrides
remain in ignored `data/personality_settings.json`.

---

## TODO-005 — Secure credential storage

- [x] Stop treating plaintext user-editable JSON as an acceptable future home for credentials.
- [x] Add an OS-backed credential abstraction suitable for Windows desktop use.
- [x] Prefer a small established solution such as the system credential store / `keyring`.
- [x] Store sensitive values such as:
  - Gemini/API provider keys;
  - user-entered Twitch secrets where applicable;
  - future provider credentials.
- [x] `.env` may remain a developer/backward-compatible fallback if useful.
- [x] UI must mask stored values.
- [x] Support Replace / Remove / Test where appropriate.
- [x] Never log credential values.

Gemini API keys and Twitch client secrets can now be managed through the masked Settings UI
and are stored through `keyring` in Windows Credential Manager. Secure values override `.env`
on startup; `.env` remains a private fallback. Provider tests and logs never include secret
values. TwitchIO's generated OAuth token cache remains library-managed local secret state.

---

# P1 — Twitch settings UX

## TODO-006 — Add Twitch connection settings to the UI

- [x] Add a clear Twitch section in Settings.
- [x] Expose ordinary non-secret values such as:
  - target channel;
  - bot account identity/status where available.
- [x] Add connection/authentication status.
- [x] Add a safe reconnect/test action if supported cleanly.
- [x] Store non-secret channel configuration in ordinary local settings.
- [x] Store secrets/tokens through the credential/auth system, not ordinary JSON.
- [x] Clearly indicate which changes apply immediately and which require reconnect/restart.
- [x] Preserve the existing Twitch lifecycle and OAuth flow unless a concrete UX improvement requires a targeted change.

The Settings page now shows Twitch connection state, configured bot identity, OAuth-cache
availability, active channel, and editable target-channel login/user ID. Non-secret channel
overrides use `data/app_settings.json`; Save & reconnect reuses the existing `BotRuntime`
lifecycle. Client secrets remain in Windows Credential Manager with `.env` fallback, and
TwitchIO OAuth tokens remain in the ignored token cache.

---

# P1 — AI provider/model UX

## TODO-007 — Add AI provider/model configuration

- [x] Add an AI provider/model section to Settings.
- [x] Start with the currently supported Google Gemini path rather than pretending to support arbitrary providers immediately.
- [x] Show:
  - provider;
  - selected model;
  - fallback model;
  - credential status;
  - Test action.
- [x] Model selection should not be hardcoded only in React.
- [x] Prefer:
  1. provider model discovery where reliable;
  2. shipped known-good model presets as fallback;
  3. optional custom model ID.
- [x] Keep model presets/current availability easy to update.
- [x] Do not silently hide model failures.

Fallback behaviour:
- use fallback for unavailable/unsupported selected model cases where appropriate;
- do **not** blindly retry fallback for invalid credentials, network failure, policy rejection, or generic rate limits;
- log/display when fallback was actually used.

If the selected model becomes invalid, the application should still have a known-good configured fallback where possible.

Google Gemini model selection now uses tracked backend presets, optional provider discovery,
and validated custom IDs. Selected/fallback IDs persist in the ordinary local app-settings
file and apply to the next AI request. Fallback is attempted only for provider model-not-found
responses; authentication, policy, rate-limit, and network errors remain visible. Credentials
remain in Windows Credential Manager with the private `.env` fallback.

---

# P1 — Settings UX polish

## TODO-008 — Make settings behaviour obvious to users

- [x] Clearly communicate whether each setting:
  - applies immediately;
  - applies to the next AI request;
  - requires Twitch reconnect;
  - requires application restart.
- [x] Prefer auto-save for simple app settings such as tray/window toggles.
- [x] Keep `Apply / Save / Reset` where runtime-vs-persistent distinction is genuinely useful, such as command settings and personality editing.
- [x] Add concise success/error feedback (toast/status).
- [x] Avoid fake controls or settings that are not wired.
- [x] Keep Settings grouped into understandable sections rather than one long undifferentiated page.

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

Window/tray toggles now auto-save with explicit immediate-versus-next-launch guidance. Action
feedback uses dismissible viewport-fixed toasts, so it stays visible while content scrolls.
Gemini presets/discovered models use real select controls with a separate custom-ID path. The
desktop sidebar remains fixed while the main content pane scrolls; command/personality
Apply/Save/Reset semantics remain unchanged.

---

# P1.5 — Architecture & reliability checkpoint

## TODO-R1 — Review project structure and reliability

- [x] Re-evaluate the current folder/file structure after the configuration/UI work settles.
- [x] Identify files/modules that are:
  - obsolete;
  - unused;
  - duplicated;
  - unnecessarily fragmented;
  - in an unclear package/location.
- [x] Review whether responsibilities still have obvious homes.
- [x] Check for unnecessary wrappers/forwarding layers.
- [x] Check for circular or awkward dependency direction.
- [x] Check lifecycle reliability:
  - startup;
  - shutdown;
  - reconnect;
  - tray/window lifecycle;
  - background threads;
  - asyncio boundaries.
- [x] Review persistence robustness:
  - malformed local settings;
  - atomic writes;
  - stale overrides;
  - reset behavior;
  - missing files.
- [x] Review external-service failure behavior:
  - Twitch;
  - Gemini;
  - weather/other APIs.
- [x] Review logging/error handling.
- [x] Review security boundaries and accidental secret exposure.
- [x] Review whether tests cover important failure/lifecycle paths.
- [x] Review dead dependencies and package declarations.
- [x] Produce concrete cleanup recommendations before modifying architecture.
- [x] Implement only high-confidence cleanup in separate commits after the audit.

Important:

Do not optimize for minimum file count. A cohesive larger module is preferable to multiple
useless forwarding files, but unrelated responsibilities must not be merged merely to reduce
file count.

The purpose is reliability, understandable structure, lower maintenance cost, and fewer
unnecessary indirections.

Do not perform this review until the preceding configuration/settings work is substantially
complete.

Audit completed in `docs/architecture-reliability-checkpoint.md`. The report records prioritized
lifecycle, filter-loading, reconnect, concurrency, provider-lifetime, packaging, and
regression-coverage follow-ups, plus boundaries that should remain unchanged. Resolve or
explicitly accept those findings before release work. One isolated cleanup removed the duplicate
tray-menu refresh; all broader findings remain deferred to focused tasks.

---


# P1.6 — Daily-use UX & runtime polish

These tasks come from real daily-use testing of the current desktop UI.

Complete the blocking/runtime items first. Do not mix unrelated UX changes into one task.

## TODO-UX1 — Fix startup bridge readiness and make bot startup explicit

- [x] Reproduce and fix the user-facing startup error around `get_app_status` / bridge availability.
- [x] Treat normal pywebview bridge initialization as an expected lifecycle state, not an error.
- [x] Prefer waiting for the bridge-ready event / deterministic readiness path over blind repeated retries.
- [x] Opening the desktop application must **not** start/connect the bot by default.
- [x] Add a persisted local setting such as `startup.auto_start_bot`, defaulting to `false`.
- [x] Add a clear **Start bot automatically** toggle in the desktop/startup settings.
- [x] The toggle takes effect on the next application launch.
- [x] `Start minimized` and `Start bot automatically` must remain independent.
- [x] Preserve an explicit CLI/testing override if the current host already has one, but normal GUI launch follows the saved setting.
- [x] No expected red error/toast should appear during a healthy application startup.
- [x] Add focused bridge/startup regression coverage.

**Acceptance check:** normal `run.bat` launch opens the application with the bot stopped by default and no `get_app_status` startup error.

The frontend now waits for a fully populated pywebview API before status polling. Normal desktop
launch follows the persisted `startup.auto_start_bot` preference, which defaults off; `--stopped`
remains an explicit override, and start-minimized remains independent.

---

## TODO-UX2 — Replace boolean checkboxes with a reusable switch control

- [x] Create one reusable accessible switch/toggle component for boolean UI settings.
- [x] Use a compact iOS-style track/knob visual rather than native checkbox squares.
- [x] Preserve keyboard/focus/accessibility semantics.
- [x] Replace boolean checkboxes consistently where they represent ON/OFF state, including:
  - command `Enabled`;
  - AI command enabled;
  - conversation memory enabled;
  - startup/window/tray booleans;
  - other equivalent boolean settings.
- [x] Do not replace controls that are not true booleans.
- [x] Preserve existing save/apply semantics; this task changes presentation, not ownership or persistence.
- [x] Keep disabled/loading states visually obvious.

**Acceptance check:** all normal ON/OFF controls use one consistent switch component and still behave exactly as before.

All eight boolean controls now use the shared native-checkbox-backed `Switch` component, with
consistent track/knob styling, keyboard focus, accessible labels, and disabled feedback.

---

## TODO-UX3 — Rebalance Dashboard, AI, and Settings information architecture

The current UI works, but the Dashboard is underused while Settings is vertically dense.

- [x] Re-evaluate placement of **existing** controls before adding new features.
- [x] Keep Commands as the dedicated command-management page; it is already appropriately dense.
- [x] Make Dashboard a useful daily control center rather than mostly empty status cards.
- [x] Prefer a compact responsive dashboard containing existing high-value runtime information such as:
  - bot Start/Stop + running state;
  - Twitch connection + active channel;
  - session uptime;
  - current stream category when available;
  - AI enabled/memory state;
  - selected model;
  - active personality.
- [x] Quick controls on Dashboard must call the same backend state/actions as detailed pages; do not duplicate sources of truth.
- [x] Move detailed Gemini provider/model configuration out of the overloaded general Settings page and into the AI area if that produces a clearer ownership model.
- [x] Keep the personality editor in AI.
- [x] Keep Settings focused on application/startup/window behavior, Twitch connection/account/security configuration, and other true application settings.
- [x] Avoid duplicating the same full editor on two pages.
- [x] Improve use of horizontal space on wide desktop windows without making narrow windows unusable.
- [x] Do not add new backend features in this task; reorganize and present existing functionality only.

**Target mental model:**

```text
Dashboard  = daily status + quick controls
Commands   = command behavior
AI         = AI runtime + model/provider + personalities
Logs       = diagnostics/activity
Settings   = app/window + Twitch/account/security + local app configuration
```

Dashboard now presents responsive bot, Twitch, uptime, and AI runtime cards with shared backend
controls. Gemini model configuration moved to AI beside personalities; Settings now focuses on
desktop behavior, Twitch connection/account details, and secure credentials.

---

## TODO-UX4 — Add named Twitch connection presets

Goal: make switching between test/work target channels convenient without retyping connection metadata.

- [x] Add named non-secret Twitch connection presets such as `Personal test` and `s_chilla`.
- [x] A preset should contain ordinary connection metadata such as:
  - display name;
  - target channel login;
  - broadcaster/user ID where required.
- [x] Persist presets in ordinary local app settings; do not store OAuth tokens/client secrets inside preset JSON.
- [x] Add a clear preset selector in the Twitch settings area and, if useful after TODO-UX3, a compact quick selector on Dashboard.
- [x] Switching preset must clearly indicate whether reconnect is required and provide an explicit Apply/Save & Reconnect flow.
- [x] Show which preset/channel is currently active.
- [x] Design the data model so a future authenticated bot-profile reference could be added cleanly.
- [x] **Do not fake multi-bot-account support.** If the current TwitchIO token cache/auth architecture supports only one authenticated bot identity, keep that identity fixed in this task and document multi-account authentication as a separate future feature.
- [x] Never duplicate secrets into preset data.

Implementation note: presets are stable-ID records inside the local `twitch` app-settings
section and contain only a display name, channel login, and broadcaster ID. The existing
authenticated bot identity and OAuth token cache remain shared and unchanged; multi-account
authentication is explicitly deferred.

---

## TODO-UX5 — Improve logs with semantic event readability

The severity model (`INFO`, `WARNING`, `ERROR`, etc.) must remain intact, but individual events should be easier to scan.

- [x] Preserve log severity as the primary diagnostic level.
- [x] Add lightweight semantic event information for important known events where practical, for example:
  - incoming Twitch chat;
  - outgoing bot message;
  - command invocation;
  - cooldown rejection;
  - Twitch lifecycle/reconnect;
  - AI request/response lifecycle;
  - settings/action events.
- [x] Prefer structured metadata/explicit event kinds at log creation time over fragile frontend regex parsing when changing backend logging is reasonable.
- [x] Visually distinguish incoming vs outgoing chat without turning the entire log into a rainbow.
- [x] Highlight useful fields such as:
  - username;
  - command name;
  - cooldown duration/seconds;
  - channel;
  - model/provider where relevant.
- [x] Keep severity badges/colors unchanged and readable.
- [x] Preserve search, level filter, auto-scroll, bounded history, and local Clear behavior.
- [x] Do not log new secrets, credentials, OAuth data, or full sensitive payloads.
- [x] Keep raw technical information available enough for debugging.

**Acceptance check:** a user can visually distinguish chat, bot output, command/cooldown, and lifecycle events without reading every gray line character-by-character.

Python log producers now attach whitelisted semantic event kinds/context for chat, commands,
Twitch lifecycle, Gemini, and settings actions. The live Logs view renders compact event labels
and context chips while preserving severity, raw messages, filters, search, bounded history,
auto-scroll, and local-only Clear behavior.

---

## TODO-UX6 — Investigate and, if clear, fix scroll jank

This is intentionally lower priority than the functional UX tasks.

- [x] Attempt to reproduce the jerky scrolling on long pages inside the real pywebview/WebView2 desktop host.
- [x] Check for concrete causes such as:
  - whole-page remounts;
  - polling-driven parent rerenders;
  - layout shifts;
  - scroll-position resets;
  - expensive shadows/layout;
  - conflicting CSS smooth-scroll behavior.
- [x] Measure/inspect before changing code.
- [x] If a clear application-level cause exists, make the smallest focused fix.
- [x] Preserve the fixed sidebar and independently scrolling main content.
- [x] Do not replace pywebview or the frontend stack solely for this issue.
- [x] If the issue is WebView2/platform-specific and no reliable app-level fix is identified, document the finding in project context and defer it instead of thrashing through speculative CSS changes.

The reported wheel-scrolling jank was not reproducible as an application-level defect in the
real production pywebview/WebView2 host. A 6.5-second continuous probe of the long Settings page
crossed multiple status-poll intervals with no frames over 25 ms, no long tasks, and no scroll
reset; the scroll position also remained exact while idle across later polls. Inspection found
no remount, layout shift, or smooth-scroll conflict. No speculative code/CSS change was made.
Treat any recurrence as a platform/input-specific symptom and capture a reproducible case before
changing the application.

---

## TODO-UX7 — Review first-run journey and empty states

Treat this as a product UX pass after TODO-UX1 through TODO-UX4 settle.

- [x] Evaluate the application from the perspective of a new user who has no existing local config/token/cache knowledge.
- [x] Ensure Dashboard makes the next useful action obvious.
- [x] Provide useful empty/not-configured states for:
  - Twitch authentication/connection;
  - target channel;
  - Gemini credential;
  - AI model;
  - personalities where relevant.
- [x] Prefer contextual actions/links such as `Configure Twitch`, `Add Gemini key`, or `Open AI settings` over unexplained status text.
- [x] Avoid a mandatory multi-step onboarding wizard unless the actual flow proves complex enough to justify one.
- [x] Ensure technical implementation details (`registry driven`, file paths, internal terminology) are not over-emphasized in normal user-facing UI.
- [x] Keep advanced/debug information available where appropriate without making it the first thing a new user must understand.
- [x] Do not duplicate settings; navigation should lead to the existing authoritative editor.

Dashboard now derives a short setup checklist from the existing Twitch, credential, AI-model,
and personality state and routes each action to the relevant existing editor. Settings and AI
show explicit missing/not-configured states, while advanced details remain available in their
normal pages without introducing a separate onboarding flow or settings store.

---

# P1.7 — Reliability hardening follow-ups from TODO-R1

These items come directly from `docs/architecture-reliability-checkpoint.md`.

Resolve them before release work and preferably before major product extensibility when they touch shared lifecycle/state.

## TODO-R2 — Harden shutdown timeout behavior

- [x] Review the current bounded shutdown/exit timeout path identified by TODO-R1.
- [x] Ensure a stuck Twitch/background operation cannot leave the desktop application hanging indefinitely.
- [x] Preserve orderly cleanup as the normal path.
- [x] Define and test the degraded path when graceful shutdown exceeds its allowed time.
- [x] Log the degraded shutdown clearly without exposing secrets.
- [x] Avoid multiple competing shutdown implementations.

`AsyncioBackendHost` now owns one serialized shutdown future. Normal exit still awaits orderly
`BotRuntime.shutdown()`; a deadline overrun cancels that attempt, requests bounded event-loop
cleanup, and logs the degraded path. The backend worker is daemonized only as the last-resort
process-exit safeguard when uncooperative work cannot be interrupted.

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

Before declaring the project release-ready, resolve the findings from TODO-R1 or explicitly
record which remaining risks are accepted. Do not duplicate the full checkpoint here.

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
