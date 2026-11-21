# Agent guide

This file is public and is the entry point for every agent (Codex, Claude, subagents).

## 1. Load the private context first

The rules, task plan and current state live in the private repository
`heeetz/heetkit-context`, checked out as `.agent/` here (ignored, never committed).

- Local: `git -C .agent pull --ff-only`. Cloud: use the sibling checkout
  `../heetkit-context` or `git clone https://github.com/heeetz/heetkit-context.git .agent`.
- Read `.agent/AGENTS.md` and follow it. It owns the priority order and the workflow.
- If the private context is unavailable, stop and tell the owner. Do not guess task state.

The rest of this file is the engineering guide. It applies to any change in this repository.

## 2. How to change code

- **Think first.** State assumptions. If a request has two readings that lead to
  different results, ask; otherwise pick the likely one and say which.
- **Smallest working change.** No features, options or abstractions nobody asked for.
  No error handling for impossible states. If 200 lines could be 50, write 50.
- **Reuse before writing.** Take the first that fits: a helper or component already in
  the repo, the standard library, an installed dependency, then new code. Never add a
  dependency for a few lines.
- **Fix the root cause once.** Before changing a function, find all its callers; fix
  shared code, not each call site. Moved or merged code keeps its validation and
  error handling. Never cut validation at trust boundaries, data-loss protection,
  security or accessibility to make a diff smaller.
- **Mark known limits.** A deliberate shortcut gets one comment:
  `shortcut: <limit>, <when to upgrade>`. Otherwise comment only the why.
- **Surgical diffs.** Every changed line traces to the task. Do not reformat or
  "improve" neighbouring code. Match the local style. Mention unrelated dead code,
  do not delete it. Remove only what your change made unused.
- **Replace, don't layer.** A new mechanism removes the one it replaces in the same
  change (code, tests, docs, i18n keys). Do not add a second path "for compatibility"
  unless the owner asks.
- **Verify by goal.** Turn the task into checks: a bug gets a failing test first, a
  refactor keeps tests green before and after. Run focused tests, not full suites.
- **Tests prove behavior.** A new test proves new or fixed behavior through a public
  entry point. No tests of copy text, CSS classes or workflow YAML. Extend a
  parametrized test or an existing spec rather than add a file. Browser specs cover
  each page once plus critical flows; field validation belongs in Python tests.

## 3. Backend architecture

Stack: Python 3.14, asyncio, TwitchIO, SQLAlchemy, pydantic. One core, two hosts:
Desktop (`app/main.py`, pywebview + tray) and Server (`app/headless.py`, HTTP
management API). Details: [docs/development.md](docs/development.md#development-boundaries-and-checks).

- **One core.** Behavior lives in `app/` services and `app/management.py`. Hosts and
  transports only adapt; they never hold business logic or their own retries.
- **Panel operations are defined once.** Today each operation is copied across
  `management.py`, `webview_host.py`, `management_api.py`, `frontend/src/bridge.ts`
  and `httpTransport.ts`. Do not add a sixth copy: when you add an operation, follow
  the existing pattern exactly, and prefer a shared registry/dispatcher when one exists.
- **Settings use pydantic models.** New or changed persisted settings get a pydantic
  model for validation and defaults, not a hand-written parser. Keep schema
  migrations and backups for existing profiles.
- **AI providers share transport.** DeepSeek and OpenAI are OpenAI-compatible: reuse a
  common HTTP client instead of copying `_http_json`/`discover_models`. A provider
  differs only in config (base URL, models, limits).
- **Errors carry codes.** New user-facing errors carry a stable code and fields from
  the `app/ui_messages.py` catalog; the frontend owns the text in each language. Do not
  add regex rules to `message_code` that guess a code from English text.
- **Persistence and privacy.** New stored data needs: migration, retention, export
  (configuration transfer) and a line in `docs/data-and-privacy.md`. Never log
  secrets or chat content beyond what the guide allows.
- **Both hosts.** Shared behavior is tested on Desktop and Server with synthetic profiles.

## 4. UI design system

Stack: React + TypeScript (Vite), tokens in `frontend/src/styles.css`, strings in
`frontend/src/i18n/` (en, uk, ru; terms in the private glossary).

- **Tokens only.** Colors `--page --panel --hover --separator --input-border --text
  --muted --primary --success --error`; spacing `--space-1..6` (4-24 px). No new hex
  values or one-off spacing. Dark theme only.
- **Reuse components.** `card`, `section-heading`, `form-field`, buttons `primary` /
  `secondary` / `ghost` / `danger`, `Select`, `Switch`, `Accordion`, `EditorDialog`,
  `Confirmation`, `HelpTip`, `FeedbackToast`, `inline-error`. Build a new component only
  when none fits, and then reuse it everywhere.
- **Fewer places, fewer clicks.** Extend an existing page or section before adding a
  page, tab or modal. One setting lives in one place. Routine controls first, rare
  options under an existing Advanced/collapsible section. Simple cases fit one screen.
- **Text.** Labels name the setting or action by its real scope ("Save AI setup",
  "Remove key"). Requirements, errors and cost/privacy/destructive effects stay visible
  next to the control; longer help goes in a labelled `HelpTip`. Every string goes
  through i18n in all three languages; uk/ru follow the glossary. Show local time.
- **Layout.** Works at 1180 px and 390 px; long values wrap or truncate, never stretch
  the layout. Keyboard and touch work for menus and dialogs.
- **Tests.** Accessible, scoped selectors (role + name). Open collapsible sections
  idempotently (check `aria-expanded`).
