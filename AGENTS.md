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
