# Durable project decisions

Only active, repository-supported decisions belong here. Update an entry when the decision
changes; do not append meeting notes or reasoning transcripts.

## Decision: Python owns the application and domain core

Status: Active

Decision:
Python owns Twitch, Gemini, database access, validation, persistence, command dispatch, and
application lifecycle.

Reason:
The existing services and runtime are composed in Python and shared by every desktop action.

## Decision: React is a presentation layer

Status: Active

Decision:
React displays backend state, holds temporary form drafts, and invokes explicit operations. It
does not implement permissions, cooldown rules, AI policy, authentication, or persistence.

Reason:
Keeping domain behavior in one backend prevents competing sources of truth.

## Decision: The frontend uses a narrow pywebview bridge

Status: Active

Decision:
Frontend access is limited to explicit application-level `WebUIBridge` methods. Raw service,
database, TwitchIO, Gemini, and runtime objects are not exposed. Calls that wait on backend
asyncio work use bounded, cancelling waits with safe frontend errors and technical logging.
Multi-step persistent/effective settings changes are submitted as narrow backend-loop
transactions rather than exposed through a generic RPC or settings framework.

Reason:
The boundary is easier to validate, thread safely, and evolve than reflection or a second
local backend API.

## Decision: One composed application owns one lifecycle

Status: Active

Decision:
One `AsyncioBackendHost` owns one asyncio loop, one composed `Application`, and one
`BotRuntime`. Desktop close and Tray Exit reuse the same idempotent orderly shutdown path.
Backend close serializes one graceful shutdown attempt; if its deadline expires, pending asyncio
work is cancelled and given a bounded forced-stop grace period. The backend thread is daemonized
only so irrecoverably blocked third-party work cannot keep a headless process alive.

Reason:
Duplicate loops or lifecycle controllers would create races and inconsistent runtime state.
A degraded timeout policy must remain bounded without replacing orderly cleanup as the normal
path.

## Decision: The Gemini service owns provider client resources

Status: Active

Decision:
The composed `GeminiAIService` reuses one SDK client for its current credential and closes
retired clients after active calls finish. `Application.shutdown()` closes the service before
its other resources. Model settings remain per-request values and do not rebuild the client.

Reason:
Provider connections need one clear owner and deterministic cleanup while live model and
credential changes remain effective.

## Decision: One tray controller and icon exist per process

Status: Active

Decision:
The desktop controller owns one idempotently started `SystemTray` on Windows; window settings
change visibility behavior, not tray ownership. On macOS/Linux, no tray is started and the
window remains reachable. A failed Windows tray startup also leaves the window visible.

Reason:
Start-minimized, minimize-to-tray, and close-to-tray combinations must never create duplicate
icons or shutdown paths.

## Decision: One normal desktop process owns local state

Status: Active

Decision:
Normal Windows desktop launches hold a named mutex derived from the resolved local app-settings
path. macOS/Linux hold a nonblocking advisory file lock alongside the settings file. A duplicate
launch exits before loading local state. Read-only `--check` runs without a guard; `--dev-url`
uses it.

Reason:
Concurrent desktop processes would compete over SQLite, Twitch OAuth/cache state, local JSON,
the OAuth port, and tray presence. Both guards release automatically on process termination;
the POSIX lock file may remain in app-data without holding a stale lock.

## Decision: The command registry defines built-in commands

Status: Active

Decision:
`CommandRegistry` is authoritative for command existence and built-in metadata/defaults.
Runtime settings and the UI derive their command list from registered definitions.

Reason:
This prevents manually maintained command lists from drifting apart.

## Decision: Custom commands are validated local templates

Status: Active

Decision:
Built-ins remain application-owned in `CommandRegistry`. User-created commands have stable IDs
and live in a separate versioned app-data store. Their triggers cannot collide with built-ins;
the existing dispatcher enforces permission, cooldown, and output policy. Template variables
come from a fixed allowlist and never execute code.

Reason:
Users can create basic chat commands without gaining an executable scripting surface or
duplicating dispatch policy.

## Decision: Message reactions are bounded local data

Status: Active

Decision:
Non-command reactions live in a separate versioned app-data JSON file seeded from a tracked
example. Python validates exact/contains rules and literal responses at startup. The existing
dispatcher excludes the bot account and command messages, sends at most one reaction per chat
message, and applies its cooldown and global output policy. Editing the file requires restart.

Reason:
Simple chat reactions need predictable matching and safe local customization without an
executable rule language or a second output path.

## Decision: Defaults, local overrides, and effective runtime state are distinct

Status: Active

Decision:
Source-controlled defaults flow through optional validated local overrides into effective
runtime state. A default plus an override is intentional layering, not duplicate ownership.

Reason:
Users need recoverable defaults, persistent customization, and session-only Apply behavior.

## Decision: Runtime settings never rewrite Python source

Status: Active

Decision:
Desktop edits are persisted as data in the appropriate local store. `config.py`, registry
definitions, and built-in resources remain developer-owned.

Reason:
Source rewriting is fragile, unsafe, and makes Reset and upgrades difficult.

## Decision: Ordinary app settings use one versioned local file

Status: Active

Decision:
Ordinary non-secret desktop preferences use the versioned platform app-data
`config/app_settings.json` file.
Schema version 1 contains independent `startup`/`window` settings, AI memory and
selected/fallback model settings, and an optional non-secret Twitch target-channel override
with named target presets; future ordinary sections may extend this model. Twitch presets have
stable IDs but do not contain credentials or represent authenticated bot accounts. Command and
personality overrides remain separate domain stores. Automatic bot startup defaults off and is
opt-in local state.

Reason:
One evolvable local model avoids files per checkbox while preserving clear ownership and
recoverable source defaults. Domain-specific override semantics do not belong in a generic
settings file.

## Decision: Personality overrides cannot replace protected shared instructions

Status: Active

Decision:
Built-in personality-specific text is tracked non-executable data in
`app/resources/personalities.json`. Users edit only local personality-specific overrides.
Shared system/safety instructions remain application-owned Python code and are combined with
the effective personality by Python.

Reason:
Tone customization must not override core policy or prompt-safety boundaries.

## Decision: Secrets are separate from ordinary settings

Status: Active

Decision:
API keys, client secrets, and OAuth tokens must not be written to ordinary application JSON.
User-entered Gemini and Twitch client credentials use the OS keyring (Windows Credential
Manager) and override the private `.env` developer/deployment fallback at startup. The UI may
show source/configuration status but must never read credential values back. TwitchIO OAuth
tokens remain in its library-managed cache under the platform app-data `auth/` directory.

Reason:
Ordinary settings are user-editable and portable; credentials require stricter storage and
logging rules.

## Decision: Local runtime and user state is not committed

Status: Active

Decision:
Local settings, tokens, databases, logs, and caches live outside the repository under one
platform app-data root. Virtual environments, dependencies, and generated frontend output
remain ignored. Safe defaults, schemas, source, lockfiles, and example configuration remain
tracked. First normal launch copies legacy local state once; old files are not deleted.

Reason:
The repository must not leak credentials/private data or mix machine state with distributable
source.

## Decision: Semantic log metadata originates in Python

Status: Active

Decision:
Important application events attach explicit semantic metadata to standard Python log records.
The recent-log handler exposes only a small whitelist of safe fields; React presents that data
and does not infer event meaning by parsing message text. Severity and raw messages remain the
primary diagnostic record.

Reason:
Producer-owned metadata is stable, searchable, and safer than coupling the UI to wording while
preserving one authoritative logging pipeline.

## Decision: Source context and end-user release contents are separate

Status: Active

Decision:
The source repository may retain tests, agent context, TODOs, and development documentation.
`scripts/package.ps1` is a tracked-files developer source archive, not an app release.
Generated frontend output, frozen applications, installers, and release archives remain
untracked build artifacts. A standalone application packaging spec must explicitly include its
runtime and resources, exclude development-only/private state, and keep mutable user data and
credentials outside the install directory. Public source publication requires a separate review
of the current tree and Git history for secrets and private data. Windows is the first release
target; later platform artifacts are built and validated on their native operating systems.

Reason:
Developer context is useful in source control but is not end-user application content. Keeping
runtime state outside the installation makes builds reproducible and upgrades safer without
shipping secrets, local databases, or machine-specific configuration.

## Decision: One shipped icon supplies platform assets

Status: Active

Decision:
`app/resources/icon.png` is the tracked 1024 px branding source. The original supplied image
is temporary input and is not retained in the repository. `scripts/generate_icons.py` derives
Windows ICO, macOS ICNS, tray, and frontend icons from the shipped PNG. Windows source launches
set the `TwitchBot.Desktop` taskbar identity; future installer shortcuts should use the same ID.

Reason:
One source keeps the desktop window, tray, UI, and future release bundles visually consistent.
The explicit Windows identity separates a source launch from the Python interpreter taskbar group.
