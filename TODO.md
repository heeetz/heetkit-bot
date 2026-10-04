# Twitch Bot — TODO

This file contains unfinished work and the retained TODO-013 follow-up outcomes until
their final checkpoint is complete.

Completed implementation history lives in Git. Durable architectural decisions belong in
`.agent/ARCHITECTURE.md` / `.agent/DECISIONS.md`, while `.agent/HANDOFF.md` should describe only
the current state and the next task.

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
10. Update `README.md` only when the task changes user-facing setup, installation, supported platforms, configuration, commands/features, or important usage workflows.

---

# P5 — Release-readiness checkpoint

TODO-013 is complete. Its single-pass report is in `.agent/HANDOFF.md`; implementation
history is in Git. The checkpoint classified release risks, not approval to package.
TODO-013A–013B are complete. Resolve TODO-013C before beginning TODO-014, and address
TODO-013D before the packaging freeze. Execute follow-ups only when requested.

BEFORE YOU COMPLETE ALL TODO-13 SUBTASKS - DO NOT DELETE RECORDS OF THEM AND FOLLOW:

Review TODO-013A through TODO-013D outcomes.

Confirm whether any release blocker from TODO-013 remains unresolved.

Do not perform another broad codebase review.
Do not modify code unless there is a concrete regression introduced by these fixes.

If clear, update HANDOFF so TODO-014 is next and STOP.

## TODO-013A — Remove owner-specific AI policy from shipped code

**Status: complete — 2026-10-04.**

**Priority: release blocker resolved — neutral-profile/privacy boundary.**

Shared request/response code no longer embeds personal name rules. Protection was preserved
only in the existing owner's local pattern file; shipped starters remain empty.

- [x] Remove personal identifiers from shared request/response policy.
- [x] Preserve any desired owner protection in that owner's local profile through the existing
  filter mechanism; do not put personal values into shared defaults, tests, or project memory.
- [x] Keep shared prompt/credential/content safeguards intact.
- [x] Test that an unrelated clean profile has no owner-specific policy and local filters still work.

**Acceptance met:** runtime code and shipped defaults contain no original-owner moderation
rules. Focused checks cover profile isolation, incoming/response filters, and unchanged safeguards.

---

## TODO-013B — Make runtime resources and first-run setup independent of the checkout

**Status: complete — 2026-10-04.**

**Priority: release blocker resolved — runtime/setup contract.**

Root `config.py` and package-owned resources are explicitly declared. Installed frontend assets
resolve under `app/resources/frontend`; a recognized source checkout retains `frontend/dist`.
Neutral filter starters are separate from legacy migration inputs. Every profile owns its
deployment `.env`, with only the normal source profile retaining a checkout fallback. Settings
now saves client ID, bot login/user ID and target metadata locally; identity changes require
restart, and secrets remain in the existing credential boundary.

- [x] Declare the runtime behavior module and required resources explicitly; keep source-only
  material outside the runtime distribution. Do not build standalone artifacts in this task.
- [x] Make default-filter/trigger/frontend discovery deterministic outside the checkout;
  distinguish shipped starters from legacy migration sources.
- [x] Provide profile-owned Twitch identity/client-ID setup and accurate first-run guidance;
  keep secrets in the existing credential boundary and preserve source/profile compatibility.
- [x] Add focused checks for launch from an unrelated working directory, declared runtime
  resources, and clean setup without checkout files or writing into the install directory.

**Acceptance met:** 147 focused tests pass, including temporary installed-tree `--check`,
normal clean-profile startup/setup, unrelated-working-directory and migration-decoy checks,
and unchanged install-file contents. TypeScript/Vite build passes. Temporary frontend fixtures
are synthetic; generated frontend output stays ignored. Freezing, frontend build/staging
automation, standalone artifacts and clean-machine verification remain TODO-014 onward.

---

## TODO-013C — Bound Gemini transport work and verify the real SDK contract

**Priority: release blocker — provider lifetime and process exit.**

The installed, declared `google-genai` 0.8.0 dispatches Requests work with `asyncio.to_thread`
and defaults its HTTP timeout to `None`. The application's coroutine/bridge timeouts cannot
stop that worker. A stalled generation/discovery can outlive shutdown and prevent process
exit. Existing lifetime tests use fake SDK clients with close methods absent in this SDK.

- [ ] Set finite provider transport deadlines as well as coroutine deadlines for generation
  and discovery; ensure cancellation/shutdown cannot leave indefinite network workers.
- [ ] Select/declare an SDK version whose request/close contract is actually supported, or
  adapt to the existing supported contract without relying on fake-only methods.
- [ ] Add an offline test against the real installed SDK transport for stalled requests,
  credential rotation, and shutdown; never use real credentials for automated checks.

**Acceptance:** declared SDK behavior and tests agree, and provider work has a finite
lifetime after cancellation or application shutdown.

---

## TODO-013D — Preserve unreadable or unsupported profile settings on save

**Priority: should fix before v1; schedule before the packaging freeze.**

Application/custom-command loaders recover with defaults after unreadable, malformed, or
unsupported files, but their next Save rewrites only the recovered snapshot. This can discard
the user's original data or future-schema fields. Command/personality recovery has a similar
read-failure risk. `FunSettingsStore` already refuses saves after a failed/unsupported load.

- [ ] Keep startup recovery, but prevent ordinary Save from silently replacing unrecovered
  settings; provide an explicit repair/reset path or preserved recovery copy.
- [ ] Define handling of unsupported versions and unknown fields for versioned stores.
- [ ] Test that saving an unrelated setting cannot erase unreadable/future-version data,
  and that ordinary supported files still save atomically.

**Acceptance:** recovery never turns an ordinary Save into silent loss of unrecovered user data.

---

## TODO-013E — Bound long-session cooldown bookkeeping

**Priority: safe to defer beyond the packaging checkpoint.**

`CooldownManager` retains every `(command, user)` entry for the process lifetime, including
commands with zero per-user cooldown. Large, long-lived channels can grow this cache indefinitely.

- [ ] Expire inactive cooldown entries with bounded bookkeeping, preserving global/per-user
  cooldown semantics and active overrides.
- [ ] Test many distinct chatters and elapsed cooldown windows without adding a new service layer.

**Acceptance:** historical chatters cannot cause unbounded cooldown-cache growth.

---

# P6 — Windows distribution first

## TODO-014 — Build a reproducible standalone Windows application

Recommended first target: Windows x64.

- [ ] Build the React/Vite frontend automatically as part of packaging.
- [ ] Freeze Python + runtime dependencies + built frontend/resources into a repeatable Windows build.
- [ ] Prefer a predictable `onedir` application bundle first; consider `onefile` only if real testing shows a benefit.
- [ ] The packaged app must not depend on the development virtualenv, Node.js, or a locally installed Python.
- [ ] Keep mutable config/database/auth data outside the install directory.
- [ ] Include only runtime-required resources; exclude `.agent/`, TODO files, tests, development docs/scripts, local profiles, caches, and generated debug artifacts.
- [ ] Add canonical application version metadata.
- [ ] Add the final application icon to the executable/window/taskbar/tray where appropriate.
- [ ] Detect/report a missing WebView2 Runtime cleanly.
- [ ] Produce a portable ZIP from the same tested application bundle for development/power-user testing.
- [ ] Validate both:
  - existing-owner profile;
  - completely clean temporary profile.
- [ ] Validate on a clean Windows user profile or machine/VM without the development environment.

**Acceptance:** extracting the portable ZIP on a clean Windows system is enough to run the application once required OS runtime prerequisites are present, and no owner-specific data is included.

---

## TODO-015 — Add a normal Windows installer

The installer is the primary end-user distribution. The portable ZIP remains an alternate asset.

- [ ] Build a reproducible installer around the tested standalone bundle.
- [ ] Install application binaries to an appropriate application directory.
- [ ] Keep mutable user profile/data outside the install directory.
- [ ] Create a Start Menu shortcut and optional desktop shortcut.
- [ ] Preserve user data/config/database across upgrades.
- [ ] Uninstall must not silently delete user data.
- [ ] Detect WebView2 Runtime and use Microsoft's supported Evergreen deployment/bootstrap flow when it is missing.
- [ ] Add application icon, version, product name, and publisher metadata.
- [ ] Support clean in-place upgrade from an older installed version.
- [ ] Keep installer generation scripted and reproducible.
- [ ] Document where the application is installed and where user data lives.

**Acceptance:** installing a newer version replaces application binaries while preserving the user's existing customized profile and data.

---

# P7 — Versioned releases and updates

## TODO-016 — Add versioned GitHub release automation

- [ ] Define one canonical application version source.
- [ ] Build/test the Windows frontend + standalone application in CI.
- [ ] Build the Windows installer and portable ZIP as release artifacts.
- [ ] Publish versioned GitHub Releases from version tags.
- [ ] Do not commit generated binaries/build directories to normal source history.
- [ ] Generate SHA-256 checksums for downloadable artifacts.
- [ ] Keep release notes concise and user-facing.
- [ ] If the source repository remains private, decide on a public release-only repository or another public update feed for end users.
- [ ] Ensure release automation never publishes the owner's local profile, secrets, token cache, database, or private defaults.

**Acceptance:** creating a release tag produces reproducible downloadable artifacts without manually rebuilding them on the developer machine.

---

## TODO-017 — Add safe in-app update checking

Start with a conservative update flow; do not build a custom binary self-patcher.

- [ ] Add a manual `Check for updates` action.
- [ ] Optionally check for updates at startup on a low-frequency/cached basis, with a user setting if appropriate.
- [ ] Compare the running canonical version against the latest stable published release.
- [ ] Show:
  - current version;
  - available version;
  - concise release notes;
  - clear update action.
- [ ] Initial acceptable flow:
  - open the official release/download page.
- [ ] Preferred later flow:
  - download the signed/checksummed installer to a temporary location;
  - verify integrity;
  - ask the user before installation;
  - perform orderly application shutdown;
  - launch the installer;
  - let the installer handle replacement/upgrade.
- [ ] Never let the running executable directly rewrite itself.
- [ ] Handle offline/API failure silently or with non-disruptive status.
- [ ] Do not require GitHub authentication for normal public-user update checks.
- [ ] If releases are hosted separately from the source repository, keep the update endpoint configurable at build time rather than hardcoding private repository assumptions.

**Acceptance:** users can discover a newer stable release from inside the app and follow a safe upgrade path without losing local configuration/data.

---

# P8 — Final Windows release verification

## TODO-018 — Perform a release-artifact audit and clean-profile smoke test

This is **not** another broad architecture review.

- [ ] Test the actual installer/portable artifacts, not the development checkout.
- [ ] Verify:
  - first launch with no prior profile;
  - Twitch setup/auth path;
  - Gemini credential setup;
  - custom commands/personalities/filters persistence;
  - app restart;
  - tray behavior;
  - upgrade from a previous test version;
  - uninstall behavior;
  - no owner-specific defaults/data;
  - no development files bundled;
  - version/icon metadata;
  - update-check behavior.
- [ ] Inspect the packaged file list for accidental source/dev/private artifacts.
- [ ] Run one targeted security/privacy check around credentials, OAuth cache, logs, and user data.
- [ ] Record only concrete blockers; do not reopen solved architecture questions without evidence.

**Acceptance:** the Windows artifact behaves like a clean product installation rather than a packaged development checkout.

---

# P9 — Cross-platform release expansion

## TODO-019 — Produce native macOS and Linux release builds

Do this only after the Windows packaging/storage/update model is stable.

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
- [ ] Reuse the same platform app-data/profile semantics established for Windows.
- [ ] Extend CI/release workflows per OS only after local/native builds are proven.
- [ ] Document unavoidable system prerequisites clearly.

**Acceptance:** Windows, macOS, and the explicitly supported Linux target can each run a native packaged build without installing Python/Node development tooling.

---

# Product direction

The v1 design is considered substantially complete, but it is not immutable.

Change UI/UX when packaging, clean-profile testing, or real usage reveals a concrete problem.
Do not reopen broad design work merely for cosmetic churn.

Near-term sequence:

```text
classified release-readiness follow-ups
→ Windows standalone
→ Windows installer
→ automated releases
→ in-app update checking
→ release-artifact audit
→ macOS/Linux expansion
```

One codebase, one application, many independent user profiles.
Owner-specific presets and moderation/personality data are user data, not product defaults.
