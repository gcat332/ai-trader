# CLAUDE.md

Claude Code Agent Instructions

This repository uses a shared Claude Code + Codex workflow.

## File Roles

- `CLAUDE.md` is for Claude Code.
- `AGENTS.md` is for Codex.
- `changes.log` is the shared append-only handoff log.
- `project_context.md` is the shared project overview.
- `HANDOFF.md` is the machine-portable handoff (branch state + how to continue on another machine).
- `user_todo.md` is the human's pre-go-live checklist (what must happen before real-money trading).

## Before Starting Work

1. Read `project_context.md`.
2. Read `changes.log`.
3. Check `git status -sb`.
4. Preserve the newest user instruction over older handoff context.

## Claude Responsibilities

- Architecture decisions and design review.
- Deep debugging and root-cause analysis.
- Larger refactoring and maintainability improvements.
- Performance and reliability reviews.
- Cross-checking Codex changes in live-trading paths.

## Sensitive Areas

Do not change these without explicit reason, focused tests, and an old-vs-new
behavior note:

- trading signals
- indicators
- risk formulas
- position sizing
- order execution
- portfolio calculations

## Coordination Rules

- Treat `changes.log` as append-only.
- Read Codex changes before modifying nearby files.
- Do not revert user or Codex changes unless explicitly asked.
- Never commit `.env`, API keys, exchange credentials, Telegram tokens, logs,
  databases, or local artifacts.
- For live trading changes, require testnet validation or document why it was not
  run.

## Handoff Log Format

```text
---
Timestamp:
Agent: Claude
Task:
Files Modified:
Summary of Changes:
Engineering Notes:
Validation:
Notes for Next Agent:
---
```
