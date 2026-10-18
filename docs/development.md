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
The desktop entry point requires a desktop. A separate [headless runtime](#headless-runtime)
can run the same backend in the foreground with previously authorized Twitch accounts.
See [Linux Docker usage](docker.md) for the backend-only container and native checks.

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
The base package installs backend dependencies only; use `.[desktop]` for a desktop
installation or `.[dev]` for the existing full development setup (which includes desktop).
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
`python -m app.headless` instead owns the same application/runtime on its foreground
asyncio loop. Both entry points share saved Twitch/AI settings application; the
headless runner adds authorization supervision and signal-driven cleanup.

The registry defines built-in commands; `RuntimeState` holds their effective settings
and current AI/session state. Profile stores own saved overrides. React calls only
allowlisted bridge operations and holds temporary editor drafts. Stopping the bot
disconnects Twitch while keeping the desktop and local tools available; exiting closes
the backend and its provider, HTTP and database resources.

Documentation-only changes need content/link review and `git diff --check`, without
test suites or builds.

Run focused Python tests for the changed subsystem:

Keep headless supervisor timing checks independent of filesystem/SQLite startup by
using an in-memory application. Real profile/database lifecycle coverage remains in
separate integration checks with time for initialization on shared CI runners.

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
It also checks aligned AI editor/key/access footers. About checks cover compact
manual-update actions and version boxes through loading, results and failures.

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

## Headless runtime

Run one previously authorized bot in the foreground without opening a window, tray,
frontend assets or OAuth callback listener:

```powershell
python -m app.headless --data-dir "C:\private\heetkit-profile"
```

After reinstalling the project, `heetkit-headless` is equivalent. Python and the
current project dependencies are required; Node, a frontend build, WebView2 and a
running desktop/keyring service are unnecessary for this entry point. A base `pip
install .` installs only backend requirements; `.[desktop]` adds the native GUI and
keyring packages. [Linux Docker usage](docker.md) covers the pinned container,
persistent volume, mounted secret files, diagnostics and recovery.

Before first use:

1. Configure and authorize the matching Twitch bot/application through the desktop
   with the selected profile. Grant the channel access described in
   [Twitch setup](twitch-setup.md#give-the-bot-channel-access-then-connect).
2. Stop the desktop. Keep the entire profile in private, writable storage, including
   `auth/twitchio_tokens.json`, `config/`, filters and `data/heetkit.db`. Do not commit
   it, put it in an image, or transfer it through public/shared storage. Back up or
   copy SQLite state only while stopped or through SQLite's backup mechanism.
3. Inject `TWITCH_CLIENT_SECRET` and, for AI, `GEMINI_API_KEY` privately through the
   process/service environment, or supply their `_FILE` paths as described in
   [Docker secret provisioning](docker.md#prepare-private-storage-and-authorization).
   Headless never reads the OS keyring or dotenv files;
   desktop keyring secrets are not part of a copied profile. Do not put secrets in
   command-line arguments, ordinary settings, shell history or logs.

`--data-dir` wins over `HEETKIT_DATA_DIR`, the legacy `TWITCH_BOT_DATA_DIR`, and the
platform default. The existing profile guard is acquired before migration or store
loading and held through cleanup; a desktop or headless process already using that
profile causes exit code 1. This is a local profile lock, not an account-wide or
cross-host lease. Operate only one active instance per Twitch account.

Saved Twitch identity/target and AI model/language/cooldown settings override process
defaults, as on desktop. Headless also applies saved AI-memory enablement, commands,
personalities, filters and SQLite/privacy state; desktop window/auto-start preferences
do not control it. Without saved Twitch identity, supply `TWITCH_CLIENT_ID`,
`TWITCH_BOT_USER_ID`, `TWITCH_BOT_USERNAME`, `TWITCH_CHANNEL_USER_ID` and `TWITCH_CHANNEL`.
Token and SQLite locations always belong to the selected profile; headless ignores
`TWITCH_TOKEN_FILE` and `DATABASE_URL`. No access/refresh-token environment importer exists.

TwitchIO retains token validation, refresh and socket retry ownership. The runner
requires verified bot authorization and a successful initial chat subscription;
missing/rejected authorization, revocation, terminal subscription/listener failures,
unexpected session termination and token write failures stop unattended operation
with exit code 1. Check the private storage, network and account/application settings;
reauthorize through the desktop when requested, then stop it before restarting.
Token saves retain TwitchIO's JSON format, serialize writes, fsync a private temporary
file and atomically replace the cache. Startup rotation is saved after loading; partial
failure retains untouched original records alongside any successfully rotated tokens;
shutdown flushes after refresh work stops and before tokens are cleared. Malformed or
wholly rejected loading preserves original authorization records. Failed replacement preserves the prior
file and reports failure; a failed rotation still needs operator attention.

Use owner-only directory permissions/Windows ACLs, including existing profile files.
New headless POSIX files use umask `077`; token staging files are created with `0600`
before secret bytes are written. Windows inherits the private directory's ACLs.

SIGINT/SIGTERM request graceful cleanup of Twitch, AI/HTTP and SQLite resources,
including after partial startup. Startup defaults to 60 seconds and graceful shutdown
to 20 seconds; `--startup-timeout` and `--shutdown-timeout` accept 0–300 seconds
(exclusive of zero). A missed shutdown deadline cancels work, attempts application
cleanup, and returns failure, with up to three additional seconds of cancellation
grace. Diagnostics go to stderr and show lifecycle/failure guidance; headless suppresses
chat text, account identities, provider responses and tracebacks. It does not write log files.

Focused synthetic Windows checks cover startup, readiness/failure, signal-handler
dispatch, cleanup deadlines, profile locking, SQLite restart persistence and OAuth
cache rotation/write failures with desktop imports rejected. Linux container checks
also exercise native signals and persistent volume recreation with synthetic remote
boundaries; see [Docker validation](docker.md#troubleshooting-and-validation).
Neither establishes live Twitch refresh/reconnect or Gemini behavior. The optional
[private management API](management-api.md) shares application operations with the
desktop, persists live settings and supports bot stop/start without exiting the
process. It is disabled unless `--management-api` and a private administrator token
are configured. Cloud deployment and a browser panel remain separate work.

## Headless readiness audit

Historical baseline audited 2026-10-17 against application revision `29786ce` and
installed TwitchIO 3.3.2. The findings below describe that revision before headless
implementation. The [headless runtime](#headless-runtime) section documents the
subsequent implementation and its validation limits; [Docker packaging](docker.md)
is implemented separately, while cloud deployment remains deferred.

### Reusable core and confirmed gaps

[`Application`](../app/container.py) composes the existing services, repositories,
filters, commands and runtime state. Startup initializes SQLite, retention and filters;
shutdown closes Gemini, the shared HTTP client and database. [`BotRuntime`](../app/bot_runtime.py)
serializes session transitions and stops Twitch before application cleanup. Neither
requires a window, tray or Windows API. A synthetic check exercised the real application
startup/session/shutdown with desktop imports rejected and no provider calls.

| Surface | Confirmed current behavior | Necessary follow-up |
| --- | --- | --- |
| Entry point | `app.main` and `heetkit` enter `webview_host.main`; even `--check` checks frontend assets. Normal launch creates a window. Windows prerequisites and tray calls are confined to desktop paths. | Add a separate foreground runner using the same `Application` and `BotRuntime`, without importing the host or starting its daemon thread. |
| Saved settings | The desktop host alone overlays saved Twitch identity/target, AI models/language/cooldown exception, and AI-memory enablement. Calling `build_application(load_settings())` omits those overlays. | Share the existing profile-settings application logic and apply it before composition; retain memory enablement and all existing stores. Start the service explicitly, independently of the desktop auto-start/window preferences. |
| Authorization | Missing or rejected cached user tokens leave `auth_required` while `Client.start()` keeps waiting. Revocation changes state without ending the session. | Give unattended startup a bounded readiness wait and explicit failure/exit behavior; treat authorization-required and terminal failures as actionable, including after startup. |
| Termination | No application SIGTERM/SIGINT handlers exist. `BotRuntime.shutdown()` awaits the session without a deadline; cancellation or failure during stop can prevent application cleanup. Desktop shutdown deadlines belong to `AsyncioBackendHost`. | Handle both signals in the runner, bound stopping/cancellation, and guarantee application cleanup after partial startup or failed stop. Report failure with a nonzero exit status. |
| Runtime failures | TwitchIO owns socket recovery; no application supervisor observes asynchronous listener/refresh failure. All `twitchio` loggers are silenced above CRITICAL. | Surface safe listener/token-persistence and terminal connection errors through application logging/state. Do not add a competing socket retry loop or repeatedly restart missing authorization. |
| State ownership | The desktop acquires a per-profile Windows named mutex or POSIX nonblocking `flock` before migration/loading; direct core use does not. There is no account-wide or cross-host lease. | Reuse the same guard for the entire headless lifecycle. Require one active owner of the account/profile; separate profiles, machines or container-local locks cannot enforce this across hosts. |

### Linux dependencies

The project requires Python >=3.12. For a concrete compatibility check, the current
backend dependencies, including keyring, resolved to **48 wheel-backed packages for
CPython 3.14, Linux x86-64, glibc 2.28**. Resolution used `pyproject.toml`, omitted only
`pywebview`/`pystray`, and constrained shared versions to the current Windows pins.
Linux-specific additions were SecretStorage 3.5.0 and jeepney 0.9.0. This was metadata
resolution with source builds disabled, not a Linux install or execution test.

| Dependency group | Headless relevance |
| --- | --- |
| TwitchIO/aiohttp, httpx, aiosqlite/SQLAlchemy, Pydantic/settings, platformdirs | Backend requirements; no GUI backend is needed. TwitchIO's existing aiohttp adapter does not require the optional Starlette extra. |
| `google-genai==1.75.0`, `regex==2026.9.29` | Retain existing behavior/pins. Upstream provides a [platform-independent GenAI wheel](https://pypi.org/project/google-genai/1.75.0/#files) and [Linux regex wheels](https://pypi.org/project/regex/2026.9.29/#files), including CPython 3.14 x86-64. |
| `keyring` | Currently imported by settings/credentials even when environment secrets are used. Keep it initially; Linux metadata selects SecretStorage/jeepney instead of Windows credential bindings. A running/unlocked keyring is a separate operational requirement. |
| `pywebview`, `pystray` and GUI-only dependencies | Unneeded for headless operation, but currently unconditional project requirements. Separate desktop installation requirements while preserving desktop setup/build behavior. This removes the renderer/tray stack, including `bottle`, `proxy_tools`, Pillow and Linux `python-xlib`; Windows pythonnet/CLR is also unnecessary. |

The full desktop dependency set at that revision failed the wheel-only check because
`proxy-tools==0.1.0` has no wheel. This is a desktop dependency/source-build issue,
not evidence that the Python backend is incompatible with Linux. Do not install the
entire `packaging/windows/requirements.txt` on Linux: it also includes Windows build
tools and platform-specific packages. The subsequent B3 implementation moves keyring,
pywebview and pystray into the desktop extra and imports credential management only
on desktop settings paths. The base backend needs no keyring package. The canonical
Linux lock/image and native synthetic checks are documented in [Docker usage](docker.md).

### Twitch lifecycle and authorization

[`app/twitch/client.py`](../app/twitch/client.py) validates configuration before creating
the client. TwitchIO obtains an app token using the client ID/secret, loads and
validates/refreshes cached user authorization, then `setup_hook` subscribes to chat
when the configured bot token exists. Valid existing authorization therefore needs no
browser action on restart. A refresh token and the matching Twitch application/identity
are required; a cache file's existence alone establishes nothing.

TwitchIO 3.3.2 skips individual cached tokens that raise `InvalidTokenException`.
The application then reports `auth_required`, just as with an empty cache; the synthetic
rejected-token check confirmed this. The current interactive route requires an explicit
desktop action to create random, single-use OAuth state with a five-minute expiry.
The adapter binds `localhost:4343`, with callback
`http://localhost:4343/oauth/callback`; unsolicited callbacks are rejected. In a remote
browser, localhost refers to that browser's machine. The minimum unattended mode should
use authorization provisioned beforehand with the source instance stopped, disable the
unneeded callback listener, and fail clearly when reauthorization is needed. Do not
publish the desktop bridge or callback to solve initial provisioning.

TwitchIO handles EventSub reconnect URLs, retry/backoff, keepalive loss and resubscription.
Application events update connecting/connected/reconnecting/auth-required/failed state;
recent chat-ID deduplication is in memory and is not shared across instances. A socket
welcome is marked connected before reconnect resubscription finishes, and library
resubscription errors need not end `Client.start()`. Readiness/health must account for
those failures rather than equating a live process or welcome event with chat delivery.
See the [TwitchIO lifecycle reference](https://twitchio.dev/en/stable/references/client.html#twitchio.Client.start)
and the existing [account/channel authorization requirements](twitch-setup.md#give-the-bot-channel-access-then-connect).

OAuth callbacks and bot-token refresh events save tokens. In the inspected library,
save truncates/writes JSON directly; the application chmods it to `0600` afterward.
It is not an atomic replace, and newly created files initially follow the process umask.
Every explicit application close passes `save_tokens=False`, so passing
`save_tokens=True` to start does not provide a final flush on those paths. The headless
follow-up must serialize restrictive, atomic token saves, account for refresh during
loading/shutdown, and report write failures. Preserve TwitchIO's managed token format
and refresh logic. Background refresh can remove an invalid token without an application
failure notification; inherited listener error logging is currently suppressed too.

### Configuration, secrets and persistent state

Select the profile before loading anything: `--data-dir` overrides `HEETKIT_DATA_DIR`,
then the legacy `TWITCH_BOT_DATA_DIR`, then platformdirs' default (normally
`$XDG_DATA_HOME/HeetKit` or `~/.local/share/HeetKit` on Linux). Process settings override
code defaults; saved non-secret profile overrides then win. Keyring values override
`TWITCH_CLIENT_SECRET`/`GEMINI_API_KEY` environment fallbacks. No dotenv file is loaded.
Explicit profiles force their own SQLite/token paths; legacy `DATABASE_URL` and
`TWITCH_TOKEN_FILE` must not be mistaken for portable credential injection. There is
no access/refresh-token environment loader.

Keyring read failures deriving from `KeyringError` are logged safely and permit
environment fallback; keyring writes fail explicitly. Linux Secret Service needs a
D-Bus session and unlocked daemon even without X11, as described in the
[keyring headless guide](https://keyring.readthedocs.io/en/stable/#using-keyring-on-headless-linux-systems).
An environment-only service can select `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`
to avoid interactive keyring discovery, then supply secrets privately through the
process environment. The null backend is not credential storage. Mounted secret-file
loading is not implemented. Retain current precedence; do not introduce plaintext
settings secrets, command-line secret arguments or privileged keyring containers.

| Persistent state under the selected profile | Contents / boundary |
| --- | --- |
| `data/heetkit.db` | Users/activity, AI exchanges and durable privacy opt-out IDs. Retention runs at startup/hourly independently of a Twitch session or memory toggle. Preserve the complete database; use SQLite backup or copy only while stopped, accounting for any journal/WAL sidecars. |
| `auth/twitchio_tokens.json` | Plaintext secret access/refresh tokens managed by TwitchIO; writable private storage is required for rotation. |
| `config/app_settings.json` | Saved Twitch identity/target/presets, AI models/language/memory/cooldown policy and desktop preferences. |
| `config/command_settings.json`, `custom_commands.json`, `fun_settings.json`, `message_triggers.json` | Built-in overrides/aliases, custom commands, response pools and ordinary-message reactions. |
| `config/personality_settings.json`, `ai_user_blocks.json`, `filters/*.txt` | Personalities/selection/profile instructions, blocked AI accounts and filter rules. |
| Recovery files and root migration markers | Preserve `config/*.recovery`, `.legacy-migration-v1` and `.heetkit-migration-v1`; they retain originals and prevent unintended reimports. |
| OS keyring, outside the profile | Gemini key and Twitch client secret. The default service is `heetkit`; alternate roots use a path-derived namespace. Copying the profile does not transfer these secrets; changing an alternate root changes its namespace. |

Persist the complete profile as private application state, separately from injected
provider secrets. `cache/` is created but the audited providers keep their caches in
memory. Logs use stderr and a 500-entry in-memory buffer, with no application log file;
captured service logs can contain chat content and need operator-owned access/retention.
Session state, cooldowns, output limits, recent-message IDs and unsaved edits do not
survive restart. See [data handling and recovery](data-and-privacy.md).

### Minimum follow-up and validation boundary

The smallest viable implementation is one foreground asyncio runner, shared startup
settings application, the existing per-profile guard, a backend-only install option,
preauthorized token loading with the callback disabled, explicit readiness/failure
handling, durable token saves, and bounded signal-driven cleanup. Reuse the existing
bot, commands, services, database and profile formats; no second bot or remote API is needed.
Keep desktop runtime behavior intact and add focused startup/failure/signal/persistence
checks before claiming headless support. An account must have a single active operator-
controlled instance; hosting/volume/restart enforcement belongs to later deployment work.

Evidence includes focused lifecycle, Twitch/OAuth, settings/credentials, profile
migration/isolation, logging and entry-point tests, plus the desktop-import and rejected-
cache probes above. Tests used disposable synthetic profiles and no live credentials.
No frontend build, Windows packaging, live Twitch/Gemini call, Linux execution,
container or cloud deployment was performed. Those limits do not prevent completing
this audit, but they prevent claiming an operational headless service.

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
