# Contributing

HeetKit is maintained by **heeetz** at
[heeetz/twitch-bot](https://github.com/heeetz/twitch-bot).
Small fixes, documentation improvements, and focused feature proposals are welcome.

- Use the [issue forms](https://github.com/heeetz/twitch-bot/issues/new/choose) for bugs
  and feature requests. Include your version/commit and OS for bugs.
- Report vulnerabilities privately using [SECURITY.md](SECURITY.md).
- Discuss substantial changes in an issue before building them. A small fix can go
  straight to a pull request; no CLA or special commit format is required.

## Development

Follow [README setup](README.md#installation), including the frontend build.
Create a branch and keep the pull request focused. Python owns behavior, validation,
providers, persistence, and lifecycle; React presents backend state through the typed
`WebUIBridge`. Reuse the existing application/profile boundaries. Keep settings and
credentials out of the installation directory and use synthetic fixtures in tests.

Run checks appropriate to the change:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_affected_subsystem.py
git diff --check
```

For frontend changes, also run `npm run typecheck` and `npm run build` in `frontend/`.
The full Python suite is `python -m pytest -q`. Describe what changed, why, and the
checks you ran in the PR; mention checks you could not run. Native window/tray/OAuth
behavior may need manual validation on the affected platform.

Never submit credentials, local profiles, OAuth caches, databases, recovery files,
or private chat content. Review screenshots/logs before attaching them. Keep tests
public and exclude generated frontend/build output and local development context.

Contributions are accepted under [Apache-2.0](LICENSE). Preserve existing attribution.
Dependency changes must update [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and
the corresponding license texts. Every distributable must recheck its actual Python,
frontend, native-library, and OS-runtime contents; a development environment inventory
does not establish that a frozen bundle is ready to redistribute.
