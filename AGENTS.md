# Context Guard — Agent Guide

## Overview

Transactional state manager for AI agents via MCP. Enforces `PLAN → EXECUTE → VERIFY → ARCHIVE` pipeline with atomic rollback. State lives in `<project-root>/.context-guard/manifest.json`.

## Entrypoints

- **MCP server** (default): `context-guard-mcp` — entrypoint `context_guard.mcp_server:main` (FastMCP over stdio)
- **CLI**: `context-guard` — entrypoint `context_guard.guard.cli:main`
- Shim: `context_guard/guard.py` delegates to `context_guard.guard.cli`

## Commands

| Action | CLI | MCP tool |
|---|---|---|
| Start phase | `begin --context <path> --phase <PHASE>` | `begin_transaction(context, phase)` |
| Advance phase | `commit --context <path> --next-phase <PHASE>` | `commit_transaction(context, next_phase)` |
| Abort | `rollback --context <path>` | `rollback_transaction(context)` |
| Save progress | `checkpoint --context <path> --summary <text>` | `save_checkpoint(context, summary)` |
| Claim/release lock | `claim --context <path>` / `release ...` | — |
| Claim task | `claim-task --context <path> --task-id <id>` | — |
| Next pending task | `next-task --context <path>` | — |
| Status dump | `status --context <path>` | — |
| Validate artifacts | `validate --context <path>` | — |
| Doctor diagnostics | `doctor --context <path>` | — |
| Archive completed | `archive --context <path>` | — |

## Pipeline DAG (strict)

```
PLAN → EXECUTE → VERIFY → ARCHIVE
```

No skipping allowed. `commit` validates the legal transition matrix.

## Hard Gates (validated on commit)

- **PLAN → EXECUTE**: `objective.md` + `tasks.md` must exist and not contain `[PENDING]`
- **VERIFY → ARCHIVE**: `review-report.md` + `verify-report.md` must exist and not contain `[PENDING]`

On `begin_transaction` with phase `PLAN`, 5 markdown files are auto-scaffolded in `.context-guard/` if missing: `objective.md`, `snapshot.md`, `tasks.md`, `review-report.md`, `verify-report.md` — all initialized with `[PENDING]`.

## Testing

- Framework: **unittest** (no pytest)
- Run all: `python -m unittest discover -s tests`
- Single file: `python -m unittest tests/test_transaction.py`
- Tests use `tempfile.mkdtemp()` — no fixtures, no services, no integration deps
- Always run tests before committing: `python -m unittest discover -s tests`
- Current suite: ~111 tests

## Build & Dependencies

- Python >= 3.9, only dependency: `mcp>=1.0.0`
- Build backend: `hatchling`
- Install: `uv pip install -e .` or `pip install -e .`

## Pre-commit Hook

File gate in `.githooks/pre-commit`. Activate with:

```
git config core.hooksPath .githooks
```

Rejects commits touching >2 files without an active context-guard transaction. Bypass: `CONTEXT_GUARD_BYPASS=1 CONTEXT_GUARD_BYPASS_REASON='...' git commit ...`

## Architecture Notes

- **Package**: `context_guard/guard/` contains all business logic; `mcp_server.py` is a thin wrapper over `transaction.py`.
- **Locking**: Two levels — OS-level `.context-guard/.lock` (session lock via `O_CREAT|O_EXCL`) and `.context-guard/.write.lock` (short-lived mutex, stale after 30s).
- **Stale detection**: PID check + timestamp TTL on both lock types.
- **Agent identity**: `{pid}-{hostname}-{timestamp}` — generated per claim.
- **Artifact cap**: 6000 chars per artifact.
- **Language enforcement**: Artifacts must be in English; `validate` detects Spanish chars.
- **Archive**: `cmd_archive` copies `.context-guard/` to `.context-guard/archive/{timestamp}_{ctxname}/` then clears the live session.
- **Summary cap**: Checkpoint summary max 2000 chars.
- **Lock legacy alias**: `acquire` subcommand is an alias for `claim`.
