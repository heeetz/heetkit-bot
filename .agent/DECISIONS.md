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

## Decision: One tray controller and icon exist per process

Status: Active

Decision:
The desktop controller owns one idempotently started `SystemTray`; window settings change
visibility behavior, not tray ownership.

Reason:
Start-minimized, minimize-to-tray, and close-to-tray combinations must never create duplicate
icons or shutdown paths.

## Decision: One normal desktop process owns local state

Status: Active

Decision:
Normal Windows desktop launches hold a named mutex derived from the resolved local app-settings
path for the duration of the process. A duplicate launch displays a clear message and exits
before loading local state. Read-only `--check` runs without the mutex; `--dev-url` uses it.

Reason:
Concurrent desktop processes would compete over SQLite, Twitch OAuth/cache state, local JSON,
the OAuth port, and tray presence. An OS mutex is released on process termination and does not
create or rewrite user settings.

## Decision: The command registry defines built-in commands

Status: Active

Decision:
`CommandRegistry` is authoritative for command existence and built-in metadata/defaults.
Runtime settings and the UI derive their command list from registered definitions.

Reason:
This prevents manually maintained command lists from drifting apart.

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
Ordinary non-secret desktop preferences use the versioned `data/app_settings.json` file.
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
tokens remain in its ignored library-managed token cache.

Reason:
Ordinary settings are user-editable and portable; credentials require stricter storage and
logging rules.

## Decision: Local runtime and user state is not committed

Status: Active

Decision:
Local settings, tokens, databases, logs, caches, virtual environments, dependencies, and
generated frontend output remain ignored. Safe defaults, schemas, source, lockfiles, and
example configuration remain tracked.

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
Generated frontend output, frozen applications, installers, and release archives remain
untracked build artifacts. A standalone application must include its runtime and tracked
resources, exclude development-only/private state, and keep mutable user data and credentials
outside the install directory. Windows is the first release target; later platform artifacts
are built and validated on their native operating systems.

Reason:
Developer context is useful in source control but is not end-user application content. Keeping
runtime state outside the installation makes builds reproducible and upgrades safer without
shipping secrets, local databases, or machine-specific configuration.
