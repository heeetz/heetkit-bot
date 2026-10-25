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
python -m pip install --only-binary=:all: --require-hashes -r packaging/python-bootstrap.txt
python -m pip install -e ".[dev]"
Push-Location frontend
npm ci
npm run build
Pop-Location
python -m app.main --check
python -m app.main
```

`run.bat` rebuilds the frontend with `npm run build` on every launch, then uses
`.venv\Scripts\python.exe`. It requires Node.js/npm and the installed frontend
dependencies (`npm ci` in `frontend/`). A failed build stops the launch so an older
UI is not opened. It uses the current checkout; it does not pull repository updates
or change the version in `app/version.py`.

The installed `heetkit` entry point is equivalent to `python -m app.main` and does
not rebuild assets. Direct Python launches also use the existing build; rebuild
after frontend changes or use the development server below. Rerun the editable
install after dependency changes.
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

Python owns behavior, validation, providers, persistence and lifecycle. One React
application presents backend state and holds temporary editor drafts. Use synthetic
profiles and provider boundaries in tests; keep credentials and mutable data outside
the application bundle.

### Shared core and lifecycle

[`build_application()`](../app/container.py) composes one `Application`: repositories,
shared HTTP/provider clients, filters, command registry/dispatcher and `RuntimeState`.
Application startup initializes the database, retention task and filters; shutdown
closes the AI provider, the shared HTTP client and database. [`BotRuntime`](../app/bot_runtime.py)
serializes Twitch session transitions and stops the session before application cleanup.

[`SharedAIService`](../app/services/ai_service.py) implements the existing command-facing
`AIService` contract. It assembles shared instructions, personality, language and untrusted
context, then checks the complete output before applying the 220-character answer limit.
The internal [`provider contract`](../app/services/ai_provider.py) carries immutable
prepared inputs and normalized results. [`GeminiProvider`](../app/services/gemini_ai_service.py)
owns SDK requests, search tools, discovery, bounded model fallback, safe errors and client
leases. Profiles without a provider selection continue to use Gemini; no migration is needed.
[`DeepSeekProvider`](../app/services/deepseek_ai_service.py) uses existing HTTPX against
the fixed direct API, with thinking disabled and final text only. Each adapter owns its
capabilities and request parameters. Provider-scoped model choices persist independently;
backend operations expose selection, discovery and secret-free credential status.
Instructions, context, search intent, models and credentials are captured before asynchronous
provider work, so edits apply to the next request and cannot change an in-flight fallback.
Global output filters still use the rules active when the response arrives. The current
shared instruction text and answer limit remain defaults owned by their existing configuration
helpers; the provider adapter does not define them. Playground uses the same shared pipeline.

[`app.main`](../app/main.py) enters the [pywebview host](../app/webview_host.py), whose
`AsyncioBackendHost` owns the core on a background asyncio thread. `DesktopController`
owns the window, Windows tray and bounded exit. [`app.headless`](../app/headless.py)
owns the same core on a foreground loop, adding readiness/failure supervision,
SIGINT/SIGTERM and bounded cleanup, including after partial startup. Both hold the
same per-profile instance guard before loading/migration through final cleanup.
It is a local lock, not a cross-host Twitch-account lease.

Stopping the bot disconnects its Twitch session while leaving the Application,
database and desktop tools or enabled management API available. Exiting the process
closes those resources. Headless uses the persistent
[operation policy](management-api.md#operation-modes), independently of desktop auto-start.
[`OperationPolicy`](../app/operation_policy.py) reconciles the latest intent through
`BotRuntime`; the lifecycle lock covers session close/token flush before another start.
Stream monitoring uses the existing Twitch service and TwitchIO's HTTP-only app-token
client, without chat subscriptions, a callback listener or user-token-cache access.

### Management operations and transports

[`ApplicationManagement`](../app/management.py) owns shared domain operations for
commands, AI, personalities, filters and blocks, reusing existing validation, stores
and runtime state. [`WebUIBridge`](../app/webview_host.py) inherits those operations
and adds desktop/native/credential adapters and bounded submission to the backend loop.
pywebview exposes only explicit, origin-guarded functions; it never exposes the full
application object.

[`ManagementAPI`](../app/management_api.py) maps fixed authenticated HTTP routes to
that shared layer and `BotRuntime`, serializing operations on the core loop across
awaits. It also serves allowlisted production React assets. The typed
[`bridge.ts`](../frontend/src/bridge.ts) surface uses pywebview on Desktop; only the
server's explicit document marker selects [`httpTransport.ts`](../frontend/src/httpTransport.ts).
A delayed desktop bridge does not select HTTP automatically. Browser access uses
same-origin requests and short-lived in-memory bearer sessions; native actions,
update checks and Playground remain desktop-only. Credential editing
is also available through authenticated Server setup. Authentication,
cookie handling, route limits and browser capabilities belong to the
[management API guide](management-api.md).

### Saved configuration and effective state

[`RuntimeState`](../app/runtime_state.py) holds locked effective command, AI, personality
and session state; the registry owns built-in definitions and profile stores own saved
overrides. Apply may affect only the current session; Save persists and applies.
Immediate toggles such as Ask enablement persist before publication. UI drafts are
not runtime state. In-flight work may finish using an earlier captured snapshot.

Both entry points use [`profile_settings.py`](../app/config/profile_settings.py) for
saved Twitch/AI overlays and apply saved memory enablement before runtime startup.
Non-secret saved values override process defaults. Desktop credentials use the OS
keyring before intentional environment fallbacks. Headless uses environment or bounded
`_FILE` inputs without keyring discovery; file contents are not exported to the
environment. OAuth access/refresh tokens belong to the private profile cache, not
ordinary settings or the keyring. SQLite holds users, AI history and durable privacy
opt-out IDs. Recovery originals, migration markers and mutable config remain private
profile data. See [profiles, retention and deletion](data-and-privacy.md) and
[Docker storage, secrets and recovery](docker.md) for operational procedures.

[`ConfigurationTransfer`](../app/configuration_transfer.py) coordinates the existing
stores for portable ZIP export/preview/import on the owning core loop. It holds the
command namespace and store locks, validates the complete replacement namespace,
backs up/stages fixed profile files, then publishes to those same live store objects.
It does not create another bot or configuration authority. Both transports expose
the same fixed operations; the [portable transfer guide](data-and-privacy.md#portable-configuration-transfer)
owns supported fields, exclusions, limits and recovery. Focused coverage lives in
[`test_configuration_transfer.py`](../tests/test_configuration_transfer.py), the
management API integration tests and frontend configuration-transfer tests.

### Twitch connection ownership

[`TwitchChatBot`](../app/twitch/client.py) adapts TwitchIO authorization, chat
subscriptions/events and connection-state reporting. TwitchIO owns token validation/
refresh, EventSub reconnect/backoff and resubscription. Application code serializes
atomic private token-cache writes, retains rotations and untouched records after
partial loading, and flushes before shutdown clears the managed cache.

Desktop authorization uses explicit, expiring single-use OAuth state and the local
callback. Headless disables that desktop listener and supports preauthorized profile
state or authenticated ServerSetup through the same TwitchIO exchange/cache lifecycle.
Server's default localhost callback shares the management port; the explicitly
configured private HTTPS callback uses the same fixed routes and expiring
session-bound attempt. Desktop retains port 4343. Network/TLS setup remains external. See
[remote management](management-api.md#private-remote-https).
ServerSetup's temporary HTTP client selects the verified managed bot token for API
lookups without starting chat, subscriptions or the Desktop adapter. Setup commits
the existing atomic token cache once; temporary-client cleanup never retries that
write. Its integration tests in `tests/test_server_setup.py` run real TwitchIO OAuth,
token validation/refresh, user models, persistence and cleanup against local mocked
HTTP endpoints. [Safe operation diagnostics](management-api.md#twitch-authorization-diagnostics)
separate failures without rendering provider errors or OAuth values.
Its supervisor observes authorization loss, terminal failures and unexpected session
completion; it does not add a competing reconnect loop. A cache file, live process or
socket welcome alone does not prove chat delivery. [Docker health](docker.md#run-and-inspect)
reports recent supervision of connection or intentional idle state; live refresh/reconnect and cloud recovery
need their own acceptance evidence.

All chat responses pass through the Twitch adapter's ID correlation wrapper.
TwitchIO `respond()` returns `SentMessage.id`/`sent`; EventSub provides `id` and shared
chat `source_id`. Application-owned bounded ten-minute caches survive session rebinding.
Same-account ingress waits for already-pending sends before checking IDs; unrelated
accounts do not wait. Uncertain sends fail closed for that sending account and channel
for the cache lifetime, without matching text. Neutral dispatch/reactions use the
explicit outgoing flag rather than account identity. Permissions and privacy checks
still apply to manually authored messages.

### Validation by impact

For ordinary prose changes, review content, internal links/anchors and `git diff --check`;
application suites and frontend builds are unnecessary. Machine-consumed documentation
needs its focused input validation: parse issue-form YAML and preserve its field structure,
or run publication-input checks when changing versioned release notes or their contract.

For behavior changes, run focused Python checks for the affected subsystem. Shared
core/API/transport changes may also need the relevant lifecycle, integration and browser
contract checks: [`test_bot_runtime.py`](../tests/test_bot_runtime.py),
[`test_headless.py`](../tests/test_headless.py), [`test_management_api.py`](../tests/test_management_api.py),
[`test_webview_host.py`](../tests/test_webview_host.py) and the applicable
[`browser-management`](../frontend/tests/browser-management.spec.ts) /
[`browser-server`](../frontend/tests/browser-server.spec.ts) tests. Select by the changed
boundary; do not run all suites for every edit. The [API guide](management-api.md#persistence-limits-and-failures)
owns the opt-in Chrome/Firefox access matrix and its separate Docker-forwarding limit.

Keep headless supervisor timing checks independent of filesystem/SQLite startup by
using an in-memory application. Real profile/database lifecycle coverage remains in
separate integration checks with time for initialization on shared CI runners.

```powershell
python -m pytest -q tests/test_affected_subsystem.py
git diff --check
```

The full Python suite is `python -m pytest -q` when explicitly warranted. For frontend
changes, run `npm run typecheck` and the affected browser cases with
`npm test -- tests/affected.spec.ts` in `frontend/`. Use `npm run build` when changed
assets/build behavior needs it; that command includes typecheck, so do not duplicate it.
Browser tests use synthetic setup and mocked external actions.
On Windows they use installed Microsoft Edge;
on other development platforms install Chromium with `npx playwright install chromium`.
Native window, tray and OAuth behavior may need platform-specific manual validation.

Ordinary `main` pushes run only Quick: coarse path selection chooses the fixed Python
smoke set, TypeScript and/or machine-input tests. Prose-only pushes report explicit
skips. Quick complements the focused local checks for a change; it does not establish
full application acceptance. Workflows or their selection/reporting helper can be
checked locally with `python -m pytest -q tests/test_ci_workflows.py tests/test_release_publication.py tests/test_release_evidence.py`
(install test-only `PyYAML==6.0.3` alongside pytest), then
`python scripts/ci_checks.py inputs`. Neither command builds artifacts or calls GitHub.

Full validation and Build candidate are separate manual workflows accepting a ref
and pinning all jobs to one resolved SHA. Do not start either as incidental local
validation. Full includes Python, frontend production/Edge and native AMD64/ARM64
container checks; candidate uses the canonical Windows builders. Dispatch both from
main and select source through the ref input. Publish is separately manual and requires
an exact SHA, existing matching tag, candidate run ID and Full validation run ID.
It verifies current-attempt evidence and reuses the original candidate artifacts.
Tag pushes start no build or publication. See
[Actions levels, skip reasons and release guards](release-process.md#github-actions-builds).
See [CONTRIBUTING.md](../CONTRIBUTING.md) for pull requests.

### Documentation ownership

Update the guide owning the changed contract and link to it from other guides.
Read only the sections relevant to the affected subsystem; keep README focused on
the product, downloads and a minimal starting flow.

| Change | Guide |
| --- | --- |
| Core lifecycle, ownership and architectural boundaries | This development guide |
| HTTP behavior, authentication and browser management | [Management API](management-api.md) |
| Docker storage, secrets, health, backup and recovery | [Docker](docker.md) |
| Privacy, retention and deletion | [Data and privacy](data-and-privacy.md) |
| Commands, AI and initial Twitch setup | [Commands](commands.md), [AI setup](ai-setup.md), [Twitch setup](twitch-setup.md) |
| Packaging, release inputs and publication | [Release process](release-process.md) |

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
| `AI_PROVIDER` | Unsaved provider default: `gemini` (default) or `deepseek`; saved selection overrides it. |
| `DEEPSEEK_API_KEY` | Optional direct DeepSeek credential fallback; Server also supports `_FILE`. |
| `DEEPSEEK_MODEL`, `DEEPSEEK_FALLBACK_MODEL` | DeepSeek model defaults; saved provider choices override them. |
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

For a fresh installation with management enabled, follow
[Server browser setup](twitch-setup.md#server-browser-setup) instead of copying a
Desktop profile. Headless loads browser-managed secrets from private
`auth/server_credentials.json`; nonempty environment/`_FILE` inputs win and are
read-only through the API. The shared credential validation module lazily loads
keyring only for Desktop. Without management, use the preauthorized path below:

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

TwitchIO retains token validation, refresh and socket retry ownership. Connecting
requires verified bot authorization and a successful initial chat subscription;
missing/rejected authorization, revocation, terminal subscription/listener failures,
unexpected session termination and token write failures stop unattended connectivity.
With management enabled the panel stays available, displays a connection error and
pauses automatic connection attempts; choose Manual and Connect after repairing the
cause, or switch to another automatic mode. Without management, terminal failures
retain exit code 1. Manual/Disabled and waiting Stream Only start without a chat
session. Missing mode settings retain the prior Always On default; invalid modes or
unreadable/unsupported settings keep headless Twitch disabled until repaired.
Check the private storage, network and account/application settings;
reauthorize through authenticated Server Settings, or use the desktop and stop it
before restarting headless. Server authorization validates the registered client,
expected bot login/ID, target identity and required scopes; cached headless tokens
are checked against those identities/scopes again before subscribing.
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
are configured. Its [browser panel](management-api.md#browser-panel) uses the same
React build through a separate HTTP transport and an in-memory administrator session;
source use requires building `frontend/` first. Cloud deployment remains separate work.

## Headless readiness audit

The 2026-10-17 audit of revision `29786ce` described the pre-headless desktop baseline.
Its runner, saved-settings, token-persistence and dependency gaps were subsequently
addressed by the shared headless runtime, Docker packaging and private management API.
Use the current [architecture boundaries](#development-boundaries-and-checks),
[headless runtime](#headless-runtime), [Docker](docker.md) and
[management API](management-api.md) guides for current behavior.

Remaining limits: profile guards do not coordinate hosts or copied profiles; synthetic
Linux/container checks do not establish live-provider refresh/reconnect or cloud
operation. Alternate-loopback Docker Desktop forwarding needs host-specific acceptance.
Cloud deployment, access controls, backups/recovery and operation across host/network
failures remain unverified; local Docker validation does not establish them.

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
- Twitch or AI provider failures: use the setup guides and credential Test actions, and
  redact private information before sharing diagnostic logs.

[Back to README](../README.md#documentation).
