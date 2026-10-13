# Development and building from source

For normal desktop use, download a build from the [Releases page](https://github.com/heeetz/heetkit-bot/releases).
This guide covers source development; Windows distribution builds are covered in
[release process](release-process.md).

## Requirements

- Python 3.12 or newer for source development.
- Node.js 20.19 or newer for the React/Vite frontend, with a version supported by Vite.
- A graphical desktop and a supported pywebview renderer. Windows uses Microsoft Edge
  WebView2; macOS uses Cocoa/WebKit. Linux needs the GTK/WebKit or Qt backend and matching
  system libraries, plus the corresponding `pywebview[gtk]` or `pywebview[qt]` extra.
- A working OS keyring is recommended for secure credential entry.

Windows tray and start-minimized controls are Windows-only. macOS/Linux source launches
keep the window visible and close normally; native distributables are not provided yet.
The current entry point requires a desktop; headless and container operation are not
implemented.

## Source setup

From the repository root in Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Push-Location frontend
npm ci
npm run build
Pop-Location
python -m app.main --check
python -m app.main
```

`run.bat` uses `.venv\Scripts\python.exe`; the installed `heetkit` entry point is also
equivalent to `python -m app.main`. Rerun the editable install after dependency changes.
On macOS/Linux, create and activate a virtual environment with your platform's commands,
install the project and frontend, then use the same Python entry point.

`--check` validates desktop configuration and frontend availability without opening the
window or creating/migrating profile files. Twitch setup is checked when connecting;
the desktop can open before it is configured. `--stopped` forces a disconnected launch
even when automatic startup is saved. Use a separate `--data-dir` for test profiles.
See [Twitch setup](twitch-setup.md), [AI setup](ai-setup.md) and
[data and privacy](data-and-privacy.md).

For frontend development, run `npm run dev` in `frontend/`, then start the Python host
from the repository root in another terminal:

```powershell
python -m app.main --dev-url http://localhost:5173
```

`--dev-url` accepts only HTTP(S) loopback servers from a source checkout. Packaged
applications use their bundled frontend and reject this option.

Normal source launches use `frontend/dist/`. Installed Python distributions load staged
assets from `app/resources/frontend/`; stage the built frontend there before making a
Python distribution. The Windows builder handles this automatically. Generated assets
are ignored and recreated from source.

## Development boundaries and checks

Python owns behavior, validation, providers, persistence and lifecycle. React presents
backend state through the typed `WebUIBridge`. Keep credentials and mutable profile
data outside the application bundle, and use synthetic fixtures in tests.

`app/main.py` enters the pywebview host in `app/webview_host.py`. Its background asyncio
loop owns one composed `Application` (`app/container.py`) and one `BotRuntime`
(`app/bot_runtime.py`). The application wires repositories, Twitch/Gemini/weather services,
filters and the command dispatcher; `BotRuntime` starts and stops Twitch sessions.
One desktop controller owns the window, tray and application shutdown.

The registry defines built-in commands; `RuntimeState` holds their effective settings
and current AI/session state. Profile stores own saved overrides. React calls only
allowlisted bridge operations and holds temporary editor drafts. Stopping the bot
disconnects Twitch while keeping the desktop and local tools available; exiting closes
the backend and its provider, HTTP and database resources.

Documentation-only changes need content/link review and `git diff --check`, without
test suites or builds.

Run focused Python tests for the changed subsystem:

```powershell
python -m pytest -q tests/test_affected_subsystem.py
git diff --check
```

The full Python suite is `python -m pytest -q`. For frontend changes, run `npm test`,
`npm run typecheck` and `npm run build` in `frontend/`. Browser tests use synthetic
setup and mocked external actions. On Windows they use installed Microsoft Edge;
on other development platforms install Chromium with `npx playwright install chromium`.
Native window, tray and OAuth behavior may need platform-specific manual validation.
See [CONTRIBUTING.md](../CONTRIBUTING.md) for pull requests.

### Desktop layout checks

Page headers and content share a centered maximum width of 1280 CSS pixels. Columns
respond to that area's available width after the sidebar, padding and scrollbar:
AI State uses four panels from 1000px, two from 480px, then one. Dashboard keeps
three panels from 720px, two from 480px, then one. Two-field forms stack at 620px.
The existing browser layout at 760px and below keeps its top navigation and single
columns. On desktop, the sidebar menu scrolls independently of the brand and page.

Run the focused viewport matrix in `frontend/`:

```powershell
npm test -- tests/responsive.spec.ts
```

The matrix covers 900×620, 1180×760, 1440×900, 1920×1080 and 2560×1440 CSS-pixel
viewports, plus the 761/760px navigation boundary and 390/320px narrow layouts.
Synthetic fixtures cover fresh setup, configured stopped/connected sessions,
missing Gemini, loading, errors, drafts and long names. Checks include content and
control bounds, form/action order, independent menu scrolling and keyboard help.

Browser viewport checks do not establish Windows DPI acceptance. Separately launch
the native application stopped with an isolated `--data-dir`, keeping the default
1180×760 and minimum 900×620 window sizes. Check restored, minimum and maximized
windows at Windows display scaling of 100%, 125% and 150%. Record each actual
WebView content size (`window.innerWidth`/`innerHeight`), `devicePixelRatio`, and
the main/page client and scroll widths using the development renderer's tools.
Native window dimensions and screenshot pixels can differ from CSS content bounds.
Check actions, navigation, help near edges and keyboard interaction in those actual
bounds; record unavailable scales or scenarios as unverified. Use synthetic profiles
and do not connect Twitch or call Gemini for layout validation.

## Advanced process configuration

Configure ordinary desktop use in Settings. Saved non-secret profile values override
process defaults; OS keyring credentials override process credential fallbacks.
HeetKit never loads dotenv files. Do not record or commit environment contents.
Defaults live under `app/config/`, and shipped starter data lives under `app/resources/`.
For saved settings, profile paths and recovery, see
[data and privacy](data-and-privacy.md#credentials-and-local-data).

| Variable | Purpose |
| --- | --- |
| `HEETKIT_DATA_DIR` | Independent profile root; `--data-dir` takes priority. |
| `TWITCH_BOT_DATA_DIR` | Legacy profile override, used only without `HEETKIT_DATA_DIR`. |
| `TWITCH_CLIENT_ID` | Twitch Developer application client ID. |
| `TWITCH_CLIENT_SECRET` | Client secret fallback when no keyring value exists. |
| `TWITCH_BOT_USERNAME`, `TWITCH_BOT_USER_ID` | Bot login and numeric user ID. |
| `TWITCH_CHANNEL`, `TWITCH_CHANNEL_USER_ID` | Target login and numeric broadcaster ID. |
| `GEMINI_API_KEY` | Optional Gemini credential fallback. |
| `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL` | AI model defaults; saved selections override them. |
| `AI_COOLDOWN_BYPASS_USER_ID` | One numeric user ID allowed to bypass only the Ask cooldown; a saved value takes priority. |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. |
| `COMMAND_PREFIX` | Command prefix, default `!`. |
| `COMMAND_MAX_ARGUMENTS_LENGTH` | Argument limit from 1 to 450, default 300. |
| `TWITCH_TOKEN_FILE` | Legacy OAuth file to import on the first normal launch. |
| `DATABASE_URL` | Legacy SQLite import source or explicit non-SQLite database URL. |

Starting Twitch needs complete identity/channel values and a client secret supplied
through Settings/keyring or the environment. Gemini is optional. Explicit profiles use
their own OAuth/database paths rather than the legacy file/database overrides.

## Sharing source

Use the tracked-file archive tool rather than manually zipping a checkout:

```powershell
.\scripts\package.ps1 -OutputPath .\heetkit-source.zip
```

It packages current tracked-file contents, excludes untracked files and private/generated
state, and refuses to overwrite an existing ZIP. This is a developer source archive,
not a standalone application. Review included contents and Git history before public
sharing; filtering does not detect secrets already committed in tracked source/history.

## Troubleshooting

- Import or entry point missing: activate the virtual environment and rerun
  `python -m pip install -e ".[dev]"`.
- Missing UI: build `frontend/`, confirm a graphical desktop and the required renderer.
  `--check` deliberately does not open a window.
- Dev URL unavailable: start Vite before launching with `--dev-url`.
- Twitch or Gemini failures: use the setup guides and credential Test actions, and
  redact private information before sharing diagnostic logs.

[Back to README](../README.md#documentation).
