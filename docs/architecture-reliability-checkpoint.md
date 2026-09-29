# Architecture and reliability checkpoint

This review records the repository state after TODO-001 through TODO-008. It is an audit,
not an implementation plan or a request to collapse the current module structure. Source code
was inspected as the authority; the earlier configuration and feature-parity audits were used
only for historical context.

No critical secret exposure, circular import, duplicate bot lifecycle, duplicate tray owner, or
competing command-settings owner was found. No executable code is changed in the audit commit.
Any selected high-confidence cleanup is kept in a later, separate commit; the broader items
below need focused tasks and regression tests.

## High-confidence cleanup

These are small, isolated candidates suitable for separate commits.

1. **Remove the duplicate tray menu refresh.** `DesktopController.toggle_bot()` refreshes the
   tray menu, and `SystemTray._handle_toggle()` refreshes it again after invoking that callback.
   Keep one refresh and cover the adapter callback with a focused test.
2. **Validate filter regular expressions when loading them.** The loader's `try` block cannot
   currently detect an invalid expression because `FilterManager.add_blocked_pattern()` stores
   raw text without compiling it. Invalid patterns are then retried and silently skipped for
   every incoming message. Compile once at the boundary, log the file and line without logging
   chat content, and keep only valid rules.
3. **Make the Pillow dependency explicit if direct-import ownership is retained.**
   `app/system_tray.py` imports `PIL` directly while `pyproject.toml` receives Pillow only as a
   transitive dependency of `pystray`. The current environment is complete, but the direct
   dependency should be declared or image creation should be encapsulated behind the tray
   dependency.
4. **Review three compatibility-shaped APIs before deleting them.** `load_settings()`,
   `RuntimeState.runtime_toggleable_commands`, and `RuntimeState.is_command_enabled()` have no
   tracked application callers. They are not harmful and may be useful public seams, so removal
   should happen only after confirming that no external launch/customization code relies on
   them.

No files were deleted merely because they are small. In particular, `app/main.py`, package
`__init__.py` files, service contracts, and the service facade all have clear roles.

## Reliability risks

### R1 — Shutdown timeout can leave a hidden, live process (high)

`AsyncioBackendHost.close()` waits for `BotRuntime.shutdown()`, then stops the event loop in a
`finally` block even when that wait times out. The backend thread is non-daemon. On a timeout,
the loop's own `finally` path can begin another shutdown while the first shutdown coroutine is
still pending; if the thread still does not stop, `DesktopController.exit_application()` logs
the failure and destroys the tray/window anyway. The result can be a headless process, pending
tasks, or duplicate cleanup attempts.

Follow-up: give backend shutdown one explicit state machine and deadline policy. Do not stop or
close the loop until the one shutdown task has completed or been deliberately cancelled and
drained. Preserve a visible failure path if a non-daemon thread cannot stop. Add real
`AsyncioBackendHost` tests for successful startup/close, startup failure, shutdown timeout, and
idempotent repeated close.

### R2 — Multiple application processes can compete for local state (high)

The tray is correctly singleton **per process**, but the application has no single-process
guard. Two launches can connect duplicate bots and contend for the OAuth callback port, SQLite
database, Twitch token file, and three JSON settings files. Atomic replacement prevents a
half-written JSON document, but it does not prevent cross-process lost updates.

Follow-up: before distribution, choose a Windows single-instance policy and make a second launch
focus the existing window or exit with a clear message. Do not add file locking independently
to every settings store unless multi-process operation becomes an explicit product feature.

### R3 — Filter loading does not implement a consistent failure policy (high)

`Application.startup()` says filter failures should abort startup, but
`load_filters_from_directory()` catches directory and file errors internally and returns after
logging. The bot can therefore run with partially loaded or empty filters after an I/O failure.
Invalid regexes are not detected at load time, as noted above.

Follow-up: decide explicitly between fail-fast and best-effort startup. For safety-sensitive
rules, fail-fast with a clear UI/startup error is the simpler contract. If best-effort behavior
is intentional, surface degraded filter health in application status rather than only logs.
Add tests for missing files, unreadable files/directories, invalid regexes, and partial loads.

### R4 — Twitch recovery state is under-observed (medium-high)

TwitchIO owns normal EventSub WebSocket reconnection, token revalidation, and refresh; the
application should not build a second reconnect loop. The current adapter marks the connection
disconnected on `event_websocket_closed`, but there is no focused test proving the runtime flag
returns to connected after a successful library reconnect or that a terminal reconnect failure
is surfaced. A terminal `run_twitch_bot()` failure ends the session task and leaves manual Start
as the only application-level recovery path. TwitchIO logging is disabled above `CRITICAL`, so
library diagnostics are also unavailable.

Follow-up: test the actual TwitchIO 3 event sequence, handle only terminal reconnect failure at
the application boundary, and decide whether the product should remain manual-restart or use a
bounded backoff. Restore safe warning/error observability rather than enabling verbose logs that
could contain authentication data. Relevant library behavior is documented in the
[TwitchIO client reference](https://twitchio.dev/en/latest/references/client.html).

### R5 — Bridge timeouts do not stop backend work (medium)

Several `WebUIBridge` methods submit a coroutine and call `Future.result(timeout=...)`. When the
wait times out, the bridge returns an error but does not cancel or observe the submitted future.
Reconnect, credential tests, model discovery, start, or stop may complete later after the UI has
reported failure. This can make the displayed result disagree temporarily with runtime state.

Follow-up: give each long operation an explicit cancellation/continuation policy. If an
operation is safe to continue, return an operation state and refresh from backend truth. If it
must stop, cancel the concurrent future and drain it on the owning loop. Test late completion.

### R6 — Cross-thread settings updates are not one transaction (medium)

pywebview executes exposed API functions in separate threads. `RuntimeState` and the settings
stores use locks, which is correct, but `update_ai_provider_settings()` persists through
`AppSettingsStore` and then mutates the asyncio-owned application's `Settings` object outside
that lock and outside the backend loop. Concurrent saves can theoretically leave disk and
runtime model selections in different orders. The same persist-then-apply pattern should be
reviewed anywhere a local store and runtime state are updated separately.

Follow-up: schedule effective model changes on the backend loop or add one narrow application
operation that serializes save-and-apply. Do not expose `Settings` itself through the bridge or
create a general settings framework. The pywebview threading contract is documented in its
[JavaScript/Python bridge guide](https://pywebview.flowrl.com/guide/interdomain).

### R7 — Gemini clients have no explicit lifetime (medium)

Model discovery and every generated reply create a new `google.genai.Client`; neither is
explicitly closed or application-owned. The installed project SDK is `google-genai 0.8.0`,
whose client does not expose the modern public `close`/`aclose` methods, so a blind cleanup call
would not be compatible with the declared `>=0.5,<1.0` range.

Follow-up: decide between one application-owned client and a scoped client after selecting a
supported SDK baseline. Then close it through `Application.shutdown()` and add timeout,
cancellation, fallback, malformed-response, and cleanup tests. Preserve the current fail-soft
chat behavior and model-not-found-only fallback policy.

### R8 — Missing required Twitch configuration prevents opening Settings (medium)

Typed settings validation happens before pywebview starts. Missing Twitch identity or client
secret therefore exits through the command-line parser, so the desktop Settings page cannot be
used to repair first-run configuration. This is not a secret leak—the keyring and private
`.env` fallback remain correctly separated—but it is a recovery/onboarding gap.

Follow-up: handle first-run configuration as a dedicated product task. Keep secrets in the OS
credential store with `.env` fallback; do not solve this by moving credentials into
`app_settings.json`.

### R9 — Logs favor secrecy but hide some actionable failures (low-medium)

Application logs generally record safe error types rather than provider bodies, and the recent
buffer is bounded. Secret-handling tests cover credential and Twitch token failures. However,
all TwitchIO logs are suppressed, Gemini failures collapse to only an exception type, and the
WebSocket-closed handler logs an arbitrary payload representation. This makes some reconnect or
provider failures difficult to diagnose while leaving an avoidable third-party payload in logs.

Follow-up: define safe structured diagnostic fields for Twitch close/reconnect and Gemini
provider categories/status codes. Keep tokens, request headers, credential values, prompt text,
and provider bodies out of logs. Continue treating the live log buffer as local private data.

## Architecture concerns

1. **`app/webview_host.py` now contains four distinct seams.** It owns the background asyncio
   host, the entire frontend bridge, desktop/tray coordination, and CLI composition. At roughly
   900 lines it is still understandable, but further bridge growth will make lifecycle review
   harder. A future split should follow those existing responsibilities; do not introduce
   forwarding services or a generic RPC framework.
2. **Mutable `Settings` crosses ownership boundaries.** Most deployment settings are immutable
   after composition, while Gemini models and Twitch targets are mutated later. The Twitch
   change is correctly scheduled through `BotRuntime`; Gemini model mutation is not. Make
   runtime-mutable provider selection an explicit backend operation rather than broadly making
   all settings mutable.
3. **The frontend bridge contract is duplicated by hand.** Python dictionaries and TypeScript
   interfaces are intentionally narrow, but no test verifies their runtime shapes agree. Add a
   small contract fixture/test before the bridge grows; do not move permission, validation, or
   persistence logic into React.
4. **Compatibility-shaped personality and settings names remain.** `AI_PERSONALITY_PRESETS`
   still materializes shared instructions plus every prompt even though runtime code primarily
   needs IDs and personality-specific resources. This is safe compatibility residue, not a
   reason to rewrite the personality system during reliability work.
5. **A built wheel is not yet the runtime contract.** The application still imports root
   `config.py` and source-tree `data/filters`, while setuptools package discovery includes
   `app*`. Editable/source launches are the supported current path. TODO-012 must explicitly
   include or relocate required resources and verify a clean-machine launch before the console
   entry point is treated as a standalone distribution.

No circular import was found in the current dependency direction. The command registry avoids a
cycle by supplying the settings-definition protocol; React depends only on serialized bridge
data; Twitch, Gemini, weather, database, and persistence remain behind Python-owned boundaries.

## Persistence assessment

- `app_settings.json` is versioned; malformed files and invalid individual values fall back
  safely. The legacy flat window shape is input-only and any successful save rewrites version 1.
- Command and personality stores ignore stale names and malformed entries without blocking
  startup. Save/reset paths update runtime only after successful persistence where required.
- All three JSON writers use a same-directory temporary file, flush, `fsync`, and `os.replace`.
  This is appropriate for the current one-process design.
- Missing files are valid. Local settings, SQLite data, OAuth tokens, logs, caches, frontend
  output, and `.env` are ignored by Git; tracked filters and safe resources remain tracked.
- An unsupported future app-settings version falls back to defaults. A later successful save
  overwrites that file rather than quarantining it. This is acceptable for version 1 but should
  be revisited before schema 2 or downgrade support.
- There is no inter-process coordination; that is covered by R2 rather than adding locks to
  every store.

## Dependency assessment

- Every declared runtime dependency has a current source-level use; no clearly dead declared
  package was found. `pip check` reports no broken installed requirements.
- `PIL` is a direct application import supplied transitively by `pystray`; the cleanup section
  records the ownership improvement without treating the current environment as broken.
- The installed `google-genai 0.8.0` matches the declared range but constrains client-lifetime
  options, as described in R7.
- The Python dependency set has ranges but no lock file. That is acceptable for current
  editable development, but TODO-012 should produce and validate a reproducible build input.
- The full suite passes but emits dependency deprecation warnings: TwitchIO's `AiohttpAdapter`
  inheritance and `pytest-asyncio` event-loop-policy APIs. They do not represent current test
  failures, but should be rechecked when raising the supported Python/dependency baseline.
- Frontend source has a tracked npm lockfile; `node_modules` and generated Vite output remain
  ignored. No frontend dependency was added or changed by this audit.

## Important missing regression coverage

1. Real `AsyncioBackendHost` startup, failure, close, timeout, and repeated-close behavior.
2. The concrete `SystemTray` adapter's singleton/start-failure/callback behavior plus a Windows
   smoke check for Open, minimize, close-to-tray, and Exit.
3. Filter file I/O failures, invalid regex validation, and the chosen degraded/fail-fast policy.
4. TwitchIO reconnect success, terminal reconnect failure, connection-state restoration, and
   manual restart after a failed session task.
5. Bridge-operation timeout/late-completion behavior and concurrent save-and-apply ordering.
6. Gemini timeout/cancellation, client cleanup for the selected SDK baseline, empty/malformed
   provider responses, and safe diagnostic logging. The 404-only fallback policy is covered.
7. A runtime contract check between representative Python bridge payloads and TypeScript
   interfaces. Frontend typecheck/build cannot detect a Python payload-shape drift.
8. A clean wheel/distribution launch that includes root behavior configuration, frontend assets,
   personality/model resources, and filter defaults. This belongs with TODO-012.

Malformed/stale settings, atomic-write failure, credentials not appearing in bridge responses or
logs, command dispatch semantics, personality protection, category caching, weather provider
failure, and controller-level tray/window behavior already have focused regression coverage.

## Things that should explicitly remain as-is

- Python remains the application/domain core; React remains presentation only.
- Keep one composed `Application`, one `BotRuntime`, one `RuntimeState`, and one tray controller
  per process.
- Keep the command registry authoritative for command existence and built-in metadata.
- Keep app, command, and personality persistence separate. They have different schemas and
  semantics; combining the JSON files would not improve ownership.
- Keep shared AI instructions source-controlled and non-editable, built-in personality prompts
  tracked as resources, and user overrides local.
- Keep secrets in Windows Credential Manager with the private `.env` fallback. Keep TwitchIO
  tokens separate from ordinary JSON settings.
- Keep normal EventSub reconnection owned by TwitchIO. Add observation and terminal-failure
  policy, not a competing reconnect subsystem.
- Keep Gemini and weather failures fail-soft for chat. Provider failure must not crash command
  dispatch or the desktop application.
- Keep the bounded backend/frontend log buffers and local-only Clear semantics.
- Keep `app/main.py` as the stable canonical entry point and `run.bat` as the explicit venv
  launcher. The small forwarding function is useful, not accidental indirection.
- Keep service protocols/facade and the composition root. They provide test seams and explicit
  dependency wiring without a service locator or plugin framework.

## Recommended follow-up order

1. Fix and test R1 shutdown timeout behavior.
2. Define and test filter-loading failure semantics (R3), including load-time regex validation.
3. Add Twitch reconnect/terminal-failure observation and tests (R4).
4. Serialize bridge save-and-apply operations and define timeout behavior (R5/R6).
5. Select a supported Gemini SDK baseline and fix client lifetime (R7).
6. Add a single-instance policy before standalone distribution (R2).
7. Address first-run configuration and safe diagnostics (R8/R9).
8. Perform the small cleanup candidates in focused commits, and resolve or explicitly accept
   remaining findings before TODO-012/TODO-013 declares the project release-ready.
