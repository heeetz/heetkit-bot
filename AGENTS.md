# Agent operating contract

This file is the permanent operating contract for coding agents working in this repository.
Repository code is authoritative when any project note is stale.

## Required start sequence

Every task begins by:

1. Reading `AGENTS.md`.
2. Reading `TODO.md`.
3. Reading `.agent/HANDOFF.md`.
4. Reading `.agent/ARCHITECTURE.md` only as relevant to the requested work.
5. Reading `.agent/DECISIONS.md` before making architectural decisions.
6. Inspecting the current Git branch, working tree, recent history, and relevant repository files.

Context loading rule:

For normal TODO work, read only:
- AGENTS.md
- TODO.md
- .agent/HANDOFF.md

Read `.agent/ARCHITECTURE.md` only when the task changes architecture,
ownership, lifecycle, persistence boundaries, or major dependencies.

Read `.agent/DECISIONS.md` only before making or revisiting a durable
architectural decision.

Do not routinely read files under `docs/`.
They are task-specific reference/audit artifacts unless the current TODO
explicitly depends on them.

Do not create new Markdown planning/context files unless an existing file
cannot reasonably hold the information.

## Execution rules

- Work only on the explicitly requested TODO item or task.
- Do not automatically continue to the next TODO.
- Do not perform unrelated cleanup, refactoring, or feature work.
- Do not repeatedly audit the whole repository for every task.
- Once the relevant dependency flow is understood, start implementation.
- Prefer modifying the existing architecture instead of inventing new layers.
- Avoid abstraction for abstraction's sake; optimize for clarity and reliable behavior.
- Preserve the established Python-core/React-presentation boundary.
- Run focused tests appropriate to the changed subsystem.
- Run frontend type checking/builds only when frontend code changed.
- Perform one final code-review pass before commit.
- Repeat review or testing only when that pass finds a concrete defect.
- If environment or tooling blocks the task, report the blocker instead of entering retry loops.
- Preserve unrelated user changes and stage only task files.
- Never use destructive Git commands such as `git reset --hard` or `git clean -fd`.
- Never force push or rewrite established history.
- Never expose or commit secrets, credentials, tokens, private runtime data, or local user state.
- Use semantic commit prefixes such as `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, or `chore:`.
- Push completed work to `origin/main` unless the user explicitly directs otherwise.
- Stop immediately after the requested task is complete.

## Required completion sequence

At the end of every completed task:

1. Update `TODO.md` when the requested TODO item was completed.
2. Rewrite or update `.agent/HANDOFF.md` to describe the new current state.
3. Update `.agent/ARCHITECTURE.md` only when architecture or ownership changed.
4. Update `.agent/DECISIONS.md` only when a durable decision was made.
5. Commit the relevant context updates together with the implementation.
6. Push the completed commit.
7. Stop without beginning the next task.

## Project-memory rules

`AGENTS.md` and `.agent/*.md` are project memory, not reasoning logs. Keep them concise,
current, and useful to a future engineer. Replace obsolete statements rather than appending
endless history.

Do not store in project memory:

- chain-of-thought or hidden reasoning;
- long session transcripts or command logs;
- giant diffs or temporary debugging notes;
- secrets, API keys, OAuth/access/refresh tokens;
- private runtime or user data.

### Python interpreter

Prefer the project virtual environment when available:

`.venv\Scripts\python.exe`

If the agent environment cannot execute that interpreter, it may use the system/default Python for checks that do not depend on missing project packages.

Do not treat inability to access `.venv` inside the agent environment as a project defect if the repository/user environment is otherwise valid.

If the fallback interpreter is missing required dependencies:
- do not repeatedly retry equivalent commands;
- do not install packages globally unless necessary for the requested task;
- use static validation where sufficient, or clearly report which validation could not be executed.

Never modify project code merely to work around an agent-specific Python environment issue.

### Delegation and review budget

The primary agent owns architecture, integration, final validation, commit, and push.

When delegation is available:
- Prefer one GPT-5.6 Luna High subagent for a clearly specified, bounded implementation task.
- Use at most 1 subagent by default.
- Use 2 only when tasks are genuinely independent and parallel.
- Do not let subagents spawn further subagents.
- Give subagents only the context needed for their task.
- Keep ambiguous architecture, concurrency, security decisions, and cross-cutting debugging with the primary Sol agent.

Review policy:
- The implementation agent runs focused checks for its own work.
- The primary agent performs ONE final review and the required validation.
- Do not spawn a generic reviewer by default.
- Do not repeat reviews/tests after they pass unless:
    - code changed afterward;
    - a concrete failure occurred;
    - a specific unresolved risk remains.
- For genuinely high-risk work (security, concurrency, persistence corruption), one independent focused review is allowed.

Web research:
- Use it when current external documentation matters.
- Prefer official sources.
- Do not research facts already clear from the repository.

Stop when:
- acceptance criteria are met;
- required checks pass;
- no known blocking defect remains.

Do not continue polishing, reviewing, or delegating merely because context/time remains.

### README maintenance

Update README.md only when a task changes user-facing behavior such as:
- installation or launch instructions;
- configuration/setup;
- commands or features available to users;
- supported platforms;
- required dependencies/runtime prerequisites;
- important usage workflows.

Do not update README for internal refactors, tests, reliability implementation details, or architecture-only changes.

When completing a user-facing task, briefly check whether README is now stale.