# Twitch Bot — TODO

This file contains **only unfinished work**.

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

---

# P3 — Branding

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
branding
→ Windows standalone + installer + releases
→ macOS/Linux release builds
```

Do not add advanced chatbot features merely because competitors have them. Match the proven basics first,
keep the execution model safe, and expand only after real usage demonstrates the need.
