# Context Guard — Agent Guide

## Overview

Transactional state manager for AI agents via CLI and MCP. Enforces a strict
`PLAN → EXECUTE → VERIFY → ARCHIVE` pipeline per change, with atomic rollback.
State lives in `<project-root>/.context-guard/changes/{name}/manifest.json`.

## Entrypoints

- **CLI**: `cg` (short) or `context-guard` (long) — `context_guard.guard.cli:main`
- **MCP server**: `context-guard-mcp` — transactional tools plus read-only ones
  (`get_status`, `next_task`, `check_completion`, `validate`)

## Multi-change

Every command accepts `--change <name>`. Omit it only when exactly one change
is active — with several, the command errors and asks you to be explicit; it
never guesses. `cg new <name>` scaffolds a change and begins PLAN. `cg list`
shows active changes. `cg archive` moves a finished one to `changes/archive/`.
`cg migrate` converts a legacy single-change or state-guard layout in place.

## Pipeline phases

Full instructions for each phase live in `.context-guard/phases/{plan,execute,
verify}.md`, installed into the project from the package's embedded copy —
load the file for the phase you are entering and follow it. Do not skip a
phase; `commit` rejects any transition outside this table.

| Phase   | Produces                              | Then                          |
|---------|----------------------------------------|--------------------------------|
| PLAN    | `objective.md`, `tasks.md`             | human review, then `cg approve` |
| EXECUTE | code changes, `tasks.md` checked off   | `check-completion`             |
| VERIFY  | `review-report.md`, `verify-report.md` | archive on approval             |

## Hard gates (validated on `commit`)

- **PLAN → EXECUTE**: `objective.md` + `tasks.md` must exist and contain no
  `[PENDING]`.
- **VERIFY → ARCHIVE**: `review-report.md` + `verify-report.md` must exist and
  contain no `[PENDING]`.

`begin` on a fresh PLAN auto-scaffolds 5 markdown files in the change
directory, all initialized with `[PENDING]`.

## The `cg approve` step

Before running `commit --next-phase EXECUTE`, present `objective.md` and
`tasks.md` to the human and wait for explicit go-ahead — never advance the
phase unprompted. `commit` enforces this: without a recorded approval it fails
with `APPROVAL_REQUIRED` (code 6).

`cg approve --change <name> --by <who> [--hotfix --reason "<text>"]` records
it. **Never run it yourself** — ask the human to. `--by` is required: there is
no default, so an agent that runs it anyway cannot pass silently as the
environment's `$USER`. The approval is spent by the
commit it authorizes, so a new iteration of the plan needs a new one.
`--hotfix` skips PLAN and opens EXECUTE directly; it requires a reason, which
is persisted. The real control is your harness's permission prompt: put
`cg approve` on the "ask" list (see `docs/adapters/*/PERMISSIONS.md`) so a human
confirms it out of band, not just in the conversation.

## Exit codes (schema v3)

`0` OK · `1` GENERIC · `2` LOCK_HELD (retry) · `3` LOCK_CONTENDED (retry) ·
`4` VALIDATION · `5` BAD_TRANSITION (do not retry) · `6` APPROVAL_REQUIRED
(human-only). `--format json` is available on every command.

## Testing

- Framework: **unittest**, run: `python -m unittest discover -s tests`
- Tests use `tempfile.mkdtemp()` — no fixtures, no services

## Architecture notes

- `context_guard/guard/`: `paths` (change resolution), `errors`, `manifest`
  (atomic tmp+rename), `locking` (session + write lock, stale via PID/mtime),
  `transaction` (`begin`/`commit`/`rollback`), `commands`, `cli`.
- Task claims use a lease (`claim-task`/`next-task`/`doctor --fix`) for
  multi-agent swarms working the same change concurrently.
- Language enforcement: artifacts must be in English; `validate` rejects
  Spanish text.
- Pre-commit hook (`git config core.hooksPath .githooks`) rejects large
  commits outside an active transaction. Threshold: `hook.file_threshold` in
  the manifest (strictest across changes) or `CONTEXT_GUARD_FILE_THRESHOLD`,
  which wins. Files outside `files_in_scope` warn, never block. Bypass:
  `CONTEXT_GUARD_BYPASS=1 CONTEXT_GUARD_BYPASS_REASON='...' git commit ...`
  — recorded in `.context-guard/bypass.log`.
- `files_in_scope` and `hook.file_threshold` are manual-only fields: no `cg`
  command writes either one. To use them, edit
  `.context-guard/changes/<name>/manifest.json` directly — `files_in_scope`
  is a list of path prefixes, `hook` is `{"file_threshold": <int>}`. Both
  default to unset (empty scope, threshold 2) and work fine left alone.
