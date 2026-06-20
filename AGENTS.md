# AGENTS.md

Codex Agent Instructions

This repository uses a shared Claude Code + Codex workflow.

## File Roles

- `AGENTS.md` is for Codex.
- `CLAUDE.md` is for Claude Code.
- `changes.log` is the shared append-only handoff log.
- `project_context.md` is the shared project overview.
- `HANDOFF.md` is the machine-portable handoff (branch state + how to continue on another machine).
- `user_todo.md` is the human's pre-go-live checklist (what must happen before real-money trading).

## Before Starting Work

1. Read `project_context.md`.
2. Read `changes.log`.
3. Read the current user request and prefer the newest instruction.
4. Check `git status -sb` before editing.

## Codex Responsibilities

- Implement focused backend changes.
- Wire API, Telegram, scheduler, config, and deployment behavior.
- Add or update tests for every behavior change.
- Run validation before reporting completion.
- Preserve compatibility with existing `LOOPn_*` configuration.

## Sensitive Areas

Do not change these without explicit reason, focused tests, and a clear old-vs-new
behavior note:

- signal generation
- indicator calculations
- risk formulas
- position sizing
- order execution decisions
- portfolio calculations

## Coordination Rules

- Treat `changes.log` as append-only. Never delete prior entries.
- If Claude made nearby changes, read them before editing.
- Do not revert user or Claude changes unless explicitly asked.
- Do not commit `.env`, credentials, logs, databases, caches, or local artifacts.
- If a task affects live trading, prefer testnet validation first.

## Handoff Log Format

Append entries to `changes.log` in this format:

```text
---
Timestamp:
Agent: Codex
Task:
Files Modified:
Summary of Changes:
Validation:
Notes for Next Agent:
---
```
