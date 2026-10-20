# Contributing

HeetKit is maintained by **heeetz** at
[heeetz/heetkit-bot](https://github.com/heeetz/heetkit-bot).
Small fixes, documentation improvements, and focused feature proposals are welcome.

- Use the [issue forms](https://github.com/heeetz/heetkit-bot/issues/new/choose) for bugs
  and feature requests. Include your version/commit and OS for bugs.
- Report vulnerabilities privately using [SECURITY.md](SECURITY.md).
- Discuss substantial changes in an issue before building them. A small fix can go
  straight to a pull request; no CLA or special commit format is required.

## Development

Follow [development setup](docs/development.md#source-setup), including the frontend build.
Create a branch and keep the pull request focused. Python owns behavior, validation,
providers, persistence, and lifecycle; React uses the shared typed desktop/browser
operations described in the [architecture boundaries](docs/development.md#development-boundaries-and-checks).
Reuse the existing application/profile boundaries. Keep settings and
credentials out of the installation directory and use synthetic fixtures in tests.

Update the [guide owning the changed contract](docs/development.md#documentation-ownership).
Use [impact-based validation](docs/development.md#validation-by-impact): prose needs
content/link/anchor review, machine-consumed docs need focused input checks, and shared
core/API/transport changes may require integration and browser-contract coverage.
For a Python subsystem change, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_affected_subsystem.py
git diff --check
```

For frontend code/type/asset changes, also run focused browser tests, `npm run typecheck`
and `npm run build` in `frontend/`.
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
