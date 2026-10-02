# Twitch Bot — TODO

This file contains **only unfinished work**.

Completed implementation history lives in Git. Durable architectural decisions belong in
`.agent/ARCHITECTURE.md` / `.agent/DECISIONS.md`, while `.agent/HANDOFF.md` should describe only
the current state and the next task.

Before removing the old TODO from the repository, verify that the agent context still records the
important current boundaries: React/pywebview/Python ownership, settings persistence, credential
storage, Twitch lifecycle, tray/startup behavior, logging semantics, and the current release direction.

## Agent workflow

When asked to execute a TODO:

1. Read `AGENTS.md`, this file, and `.agent/HANDOFF.md`.
2. Work on **one TODO only**.
3. Read architecture/decision notes only when the task changes those boundaries.
4. Do not perform unrelated cleanup or broad re-audits.
5. Use web research only when current external documentation materially affects correctness; prefer official sources.
6. Delegation is optional, not automatic. Prefer at most one bounded implementation subagent when useful.
7. Run focused checks only. Do not repeat reviews/tests after they pass unless code changed or a concrete defect remains.
8. Perform **one** final review, update project context, commit with a semantic prefix, push to `origin/main`, and stop.
9. Preserve unrelated local changes. Never commit secrets/runtime data and never force-push or destructive-clean the repository.

---

# P0 — Reliability still open

## TODO-001 — Make filter loading failure-safe

- [ ] Review startup/reload behavior when blocked-word, blocked-phrase, or regex files are missing, unreadable, malformed, or partially invalid.
- [ ] A failure in one optional rule/file must not silently disable the whole filtering layer.
- [ ] Invalid regex entries should be rejected individually and reported clearly.
- [ ] Preserve current filtering semantics for valid rules.
- [ ] Keep failures visible in logs/diagnostics without crashing the whole app where avoidable.
- [ ] Add focused regression coverage for the real failure cases.

**Acceptance:** one broken filter entry/file cannot silently remove otherwise valid moderation rules.

---

## TODO-002 — Give the Gemini client one clear lifecycle owner

- [ ] Inspect the current Gemini client construction/reuse path.
- [ ] Establish one obvious application/service owner for provider client resources.
- [ ] Reuse the client when the SDK supports it safely instead of recreating expensive resources per request.
- [ ] Ensure credential/model changes still take effect correctly.
- [ ] Preserve request timeout, policy, filtering, search-tool, and fallback behavior.
- [ ] Close/release provider resources cleanly on shutdown where supported.
- [ ] Add focused lifecycle tests where useful.

**Acceptance:** client ownership is obvious, provider configuration still updates correctly, and shutdown does not leak provider resources.

---

## TODO-003 — Improve Twitch disconnect/recovery observability

- [ ] Keep normal reconnect/recovery behavior TwitchIO-owned unless a concrete defect requires otherwise.
- [ ] Make connection loss, reconnecting/recovery, recovered, and terminal auth/config failures distinguishable in application state/logs where TwitchIO exposes enough information.
- [ ] Ensure Dashboard/Settings eventually reflect recovered connection state.
- [ ] Preserve one reconnect mechanism; do not wrap TwitchIO in a competing reconnect loop.
- [ ] Add focused state/observability tests rather than mocking an entire Twitch network stack.

**Acceptance:** a temporary disconnect and a terminal configuration/auth failure no longer look identical to the user.

---

# P1 — Runtime data, portability, and desktop polish

## TODO-004 — Consolidate mutable runtime data into one platform app-data root

Goal: no user-mutated state should depend on writing beside the source tree or packaged executable.

- [ ] Inventory every mutable runtime artifact:
  - app settings;
  - command overrides/custom-command data;
  - personality overrides;
  - SQLite database;
  - TwitchIO OAuth/token cache;
  - any generated filter/user data;
  - persistent logs/cache if they exist.
- [ ] Introduce one platform-aware application data root using a standard solution such as `platformdirs`.
- [ ] Keep a small number of cohesive subdirectories/files instead of scattering config across the repository.
- [ ] Prefer a layout conceptually similar to:

```text
TwitchBot/
├── config/
│   ├── app_settings.json
│   ├── command_settings.json
│   └── personality_settings.json
├── data/
│   └── bot.db
├── auth/
│   └── <library-managed non-keyring auth cache if required>
└── cache/
```

- [ ] Credentials/API secrets remain in the OS keyring and must not be copied into JSON.
- [ ] Preserve safe migration from the current development/runtime paths.
- [ ] Missing files/directories must recreate clean defaults automatically.
- [ ] Add one internal developer/agent reference documenting:
  - exact runtime paths per platform;
  - which files are safe to delete to reset settings;
  - which data is destructive to delete;
  - which secrets live only in the OS credential store.
- [ ] This reference is developer-facing and must not be bundled into the end-user application.

**Acceptance:** deleting the non-secret config files recreates defaults, and mutable user state no longer lives throughout the source tree.

---

## TODO-005 — Remove accidental Windows-only assumptions from application code

Windows remains the first release target, but the application core should not unnecessarily block macOS/Linux.

- [ ] Audit platform-specific assumptions introduced by:
  - named mutex/single-instance behavior;
  - filesystem paths;
  - credential-store wording/behavior;
  - tray/window integration;
  - pywebview startup;
  - launch scripts;
  - packaging-only code.
- [ ] Keep Windows-specific implementations behind small platform boundaries where needed.
- [ ] Use the system keyring abstraction rather than presenting Windows Credential Manager as the universal UI concept.
- [ ] Provide a reasonable non-Windows single-instance strategy or explicitly degrade safely when unavailable.
- [ ] Confirm the Python core/frontend can start on supported pywebview macOS/Linux backends in principle.
- [ ] Do not attempt to create macOS/Linux distributables in this task.
- [ ] Record any unavoidable OS prerequisites/limitations for later packaging work.

**Acceptance:** normal application code is platform-aware rather than Windows-hardcoded, while Windows behavior remains unchanged.

---

## TODO-006 — Finish responsive layout consistency

Fix the remaining desktop-layout inconsistencies without redesigning features.

- [ ] Make Settings sections/cards use available width sensibly on large windows instead of staying as a narrow left column.
- [ ] Use responsive grids/columns where appropriate rather than simply stretching form controls to absurd widths.
- [ ] Keep readable maximum line lengths for explanatory text.
- [ ] Align form actions consistently; credential actions such as Replace/Test/Remove should follow the same visual alignment rules as the rest of the app.
- [ ] Review Commands at smaller desktop widths:
  - no clipped fields;
  - no overlapping labels/controls;
  - actions remain usable;
  - cards may reflow vertically when necessary.
- [ ] Smoke-check Dashboard, AI, Logs, Commands, and Settings at narrow, normal, and maximized desktop widths.
- [ ] Preserve existing semantics, navigation, fixed sidebar, and scrolling behavior.
- [ ] Do not solve this with one-off pixel hacks for the supplied screenshots.

**Acceptance:** Settings makes good use of maximized windows and Commands remains clean at smaller widths.

---

# P2 — Industry-style extensibility

## TODO-007 — Build Custom Commands v1 around a safe template model

Do not model common custom commands as generated Python code or a visual programming language.

Industry baseline: custom command systems normally expose a trigger/name, response template,
permissions, cooldowns, aliases, enable/disable state, and dynamic variables/arguments.

### Data model

- [ ] A custom command has a stable internal ID plus:
  - command name/trigger;
  - enabled state;
  - one or more response templates;
  - permission/user level;
  - per-user cooldown;
  - global cooldown;
  - aliases;
  - response selection mode (`single` or `random`);
  - optional description/notes only if it materially helps the UI.
- [ ] Command matching is case-insensitive and normalized consistently.
- [ ] Validate duplicate names/aliases and collisions with built-in commands before save.
- [ ] Built-in commands remain application-owned; custom commands are local user data.
- [ ] Reuse the existing canonical permission/cooldown machinery rather than building a second dispatcher policy.

### Template variables

Start with a deliberately small allowlist:

- [ ] `{sender}` — user invoking the command.
- [ ] `{target}` — first target/username argument, with defined fallback behavior.
- [ ] `{args}` — full argument tail after the command.
- [ ] `{arg1}`, `{arg2}`, etc. — bounded positional arguments.
- [ ] `{random_user}` — recent eligible chatter from the existing recent-user source.

Rules:

- [ ] Unknown variables fail validation or remain clearly literal; never execute code.
- [ ] No Python eval, arbitrary expressions, arbitrary HTTP calls, nested scripting, or user-supplied executable logic.
- [ ] Define safe missing-argument behavior.
- [ ] Enforce Twitch/output length limits through the existing output path.

### UI

- [ ] Commands page clearly separates built-in and custom commands.
- [ ] Support create, edit, enable/disable, save, and delete.
- [ ] Show response templates and available variables without requiring the user to memorize syntax.
- [ ] Multiple response templates imply random selection instead of creating a separate “random command type”.
- [ ] Target-user and random-user behaviors come from variables, not separate hardcoded command classes.
- [ ] Keep advanced features such as chat-based `!command add`, counters, timers, API variables, scripting, imports, and command costs out of v1.

### Persistence and tests

- [ ] Persist custom commands in the consolidated runtime config/data location from TODO-004.
- [ ] Use versioned validation and atomic writes.
- [ ] Malformed custom-command data must not break built-in commands.
- [ ] Add focused tests for matching, aliases, collisions, variables, permissions, cooldowns, persistence, malformed input, and random response selection.

**Acceptance:** a non-programmer can create commands comparable to the basic Nightbot/StreamElements custom-command workflow without being able to execute arbitrary code.

---

## TODO-008 — Add lightweight non-command message triggers

- [ ] Add local data-driven triggers for simple chat reactions that do not require Gemini.
- [ ] Initial fields:
  - enabled;
  - match mode (`contains`, `exact`, or another deliberately small set);
  - case sensitivity if genuinely useful;
  - probability;
  - cooldown;
  - one or more responses.
- [ ] Prevent bot/self-feedback loops.
- [ ] Reuse existing output limiting/spam protections.
- [ ] Keep trigger matching cheap and predictable.
- [ ] First real use case can remain `вась` → probabilistic response.
- [ ] No arbitrary regex unless there is a clear reason and validation story.
- [ ] Persist alongside other user-defined behavior in the consolidated runtime data location.

---

## TODO-009 — Add a Filters management UI

- [ ] Manage blocked words, blocked phrases, and regex patterns from the desktop UI.
- [ ] Preserve existing moderation semantics exactly.
- [ ] Validate regex before Apply/Save.
- [ ] Clearly show invalid entries without disabling valid rules.
- [ ] Reuse the failure-safe loading behavior from TODO-001.
- [ ] Keep source defaults and local user modifications distinguishable if both exist.
- [ ] Do not weaken existing moderation behavior during the UI migration.

---

# P3 — Source/release boundary and branding

## TODO-010 — Clean the source-vs-release boundary

Do not confuse “files useful to developers/agents” with “files shipped to end users”.

- [ ] Audit tracked project-only material such as:
  - `.agent/`;
  - `AGENTS.md`;
  - `TODO.md`;
  - `docs/`;
  - tests;
  - development scripts;
  - temporary patch/debug artifacts.
- [ ] Remove accidental temporary files from Git.
- [ ] Do **not** add tracked development documentation to `.gitignore` merely to hide it.
- [ ] Decide which developer/agent files remain useful in the source repository.
- [ ] End-user packages/releases must contain only runtime-required assets, licenses/notices, and intended user documentation.
- [ ] Packaging manifests/specs must explicitly exclude development-only material.
- [ ] Before any public source release, perform a secret/history hygiene check separately from normal build packaging.
- [ ] Preserve durable project/architecture knowledge before deleting or relocating any agent-context file.

**Acceptance:** the source repository may remain developer-friendly, while the downloadable app contains none of the agent/TODO/test clutter.

---

## TODO-011 — Establish final branding and icon assets

- [ ] Inventory existing icon/logo assets and where they are used.
- [ ] Use one master application identity across:
  - pywebview window/taskbar;
  - system tray;
  - packaged executable;
  - installer;
  - shortcuts;
  - future macOS/Linux bundles.
- [ ] Generate platform-specific icon formats from one high-quality source asset.
- [ ] Avoid shipping placeholder `TB` artwork if a final asset exists.
- [ ] If no suitable master asset exists, **stop and ask the user for/propose a 1024×1024 transparent PNG or SVG master icon before continuing**.
- [ ] Verify the icon at small tray/taskbar sizes, not only at full resolution.

---

# P4 — Windows distribution first

## TODO-012 — Build a reproducible standalone Windows application

Recommended first target: Windows x64.

- [ ] Build the React/Vite frontend automatically as part of packaging.
- [ ] Freeze Python + runtime dependencies + built frontend/resources into a repeatable Windows build.
- [ ] Prefer a predictable `onedir` application bundle first; optimize to `onefile` only if testing shows a real benefit.
- [ ] The packaged app must not depend on the development virtualenv, Node.js, or a locally installed Python.
- [ ] Keep mutable config/database/auth data outside the install directory using TODO-004.
- [ ] Include only runtime-required resources.
- [ ] Add version metadata and final application icon.
- [ ] Detect/report a missing WebView2 Runtime cleanly.
- [ ] Produce an optional portable ZIP from the same application bundle for testing/power users.
- [ ] Validate on a clean Windows environment/user profile.

**Acceptance:** extracting the portable ZIP on a clean Windows machine is enough to run the application once required OS runtime prerequisites are present.

---

## TODO-013 — Add a normal Windows installer

The polished default distribution should be an installer; the portable ZIP may remain an alternate asset.

- [ ] Build an installer around the tested standalone bundle.
- [ ] Install to an appropriate per-user or per-machine application directory.
- [ ] Create Start Menu shortcut and optional desktop shortcut.
- [ ] Preserve user data/config across upgrades and uninstall unless the user explicitly chooses to remove it.
- [ ] Detect WebView2 Runtime and bootstrap/install the Evergreen Runtime when missing using Microsoft's supported deployment flow.
- [ ] Add application icon/version/publisher metadata.
- [ ] Support clean uninstall without deleting user data by surprise.
- [ ] Keep installer generation scripted/reproducible.

---

## TODO-014 — Add versioned release automation

- [ ] Define application versioning and where the canonical version lives.
- [ ] Build/test the Windows frontend + standalone application in CI.
- [ ] Build the Windows installer and portable ZIP as release artifacts.
- [ ] Publish versioned GitHub Releases from tags.
- [ ] Do not commit generated binaries/build directories to normal source history.
- [ ] Include checksums for downloadable artifacts.
- [ ] Keep release notes concise and user-facing.

---

# P5 — Cross-platform release expansion

## TODO-015 — Produce native macOS and Linux release builds

Do this only after the Windows packaging/storage model is stable.

- [ ] Build each OS artifact **on that OS**; do not assume one PyInstaller build is cross-platform.
- [ ] macOS:
  - create a proper `.app` bundle;
  - use the system WebKit path supported by pywebview;
  - integrate macOS Keychain through the existing keyring abstraction;
  - evaluate signing/notarization before calling it a normal public release.
- [ ] Linux:
  - choose and document the supported pywebview backend/runtime prerequisites (GTK or Qt);
  - integrate Secret Service/KWallet through keyring where available;
  - choose one practical initial distribution format after testing rather than promising every distro.
- [ ] Reuse the same platform app-data layout semantics from TODO-004.
- [ ] Extend CI/release workflows per OS only after local/native builds are proven.
- [ ] Document unavoidable system prerequisites clearly.

**Acceptance:** Windows, macOS, and the explicitly supported Linux target can each run a native packaged build without installing Python/Node development tooling.

---

# Product direction

Near-term sequence:

```text
remaining reliability
→ runtime storage + cross-platform-safe core
→ responsive desktop polish
→ custom commands / triggers / filters
→ source/release cleanup + branding
→ Windows standalone + installer + releases
→ macOS/Linux release builds
```

Do not add advanced chatbot features merely because competitors have them. Match the proven basics first,
keep the execution model safe, and expand only after real usage demonstrates the need.
