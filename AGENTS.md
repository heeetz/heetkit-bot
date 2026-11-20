# Agent bootstrap

This file is public. The working contract, task plan and current state for agents
(Codex, Claude and their subagents) live in the private repository
`heeetz/heetkit-context`, which is checked out as `.agent/` inside this repository.
`.agent/` is ignored here and must never be committed to this public repository.

## Before any task

1. Find the private context:
   - local checkout: `.agent/` in the repository root;
   - otherwise clone it: `git clone https://github.com/heeetz/heetkit-context.git .agent`
     (a cloud session may already have it as a sibling checkout named `heetkit-context`).
2. Read `.agent/AGENTS.md` (the operating contract) and follow it. It routes you to
   `.agent/PROCESS.md`, `.agent/TODO.md` and `.agent/HANDOFF.md`.
3. Run `git -C .agent pull --ff-only` before reading, and commit and push context
   changes to `heetkit-context` before you stop. Git carries the context between
   agents and machines; a local-only edit is invisible to the next agent.

If the private context is unavailable, stop and tell the owner instead of guessing
the task state. Public contribution rules are in [CONTRIBUTING.md](CONTRIBUTING.md)
and [docs/development.md](docs/development.md).
