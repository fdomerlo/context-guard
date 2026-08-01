# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- `cg setup` installs the host adapters for Claude Code, OpenCode and
  Antigravity. Global scope by default — one command per machine — with
  `--project <dir>` keeping 2.1's predecessor behaviour of installing into a
  single project for teams that commit the configuration.
- The phase documents and every host artifact now ship inside the package as
  data, so nothing needs a clone of this repository to install.

### Changed

- `cg new` materialises `.context-guard/phases/*.md` into the project from the
  packaged copy, which is what makes a globally installed slash command work
  in a project nobody prepared. A phase file that already exists is never
  overwritten; `cg doctor` reports the difference as INFO.

### Removed

- `adapters/install.sh`, with no compatibility wrapper. Run `cg setup`
  instead.
- `--with-antigravity-hook`. The deny hook is installed by
  `cg setup --host antigravity`, since at global scope it was the only thing
  that flag's host had to install.

## [2.0.0] - 2026-07-31

### The state-guard merge

context-guard 2.0 folds state-guard into this repo: one process instead of two
diverging philosophies. state-guard's multi-change layout, phased
`plan → execute → verify` workflow, and cooperative approval model are ported
here on top of context-guard's atomic manifest and DAG-enforced transaction
core — the better architecture of the two, kept as the skeleton. state-guard
is retired; its repository now points here.

### Core fixes (audited bypasses closed)

- `begin` now validates `lock_phase` before starting a phase. Previously the
  DAG was only checked on `commit`, so an agent that never committed was never
  stopped from working a phase it was never authorized to start.
- Orphaned session locks (lockfile present, no metadata) now age off the
  file's own mtime instead of deadlocking forever.
- A write lock held by a live process is no longer stolen by age alone; a hard
  cap (10x the normal TTL) still recovers one abandoned by a reused PID.
- Task claims carry a lease; `next-task` reclaims expired ones and logs the
  takeover, `doctor --fix` releases claims whose owning PID is gone.
- `release` / `release-task` now require `--agent-id` (or an explicit
  `--force`, logged in the manifest) — an anonymous release could previously
  free a lock or claim it did not own.
- Exit codes are unified across the whole CLI: `0` OK, `1` GENERIC, `2`
  LOCK_HELD, `3` LOCK_CONTENDED, `4` VALIDATION, `5` BAD_TRANSITION, `6`
  APPROVAL_REQUIRED. `--format json` is available on every command.

### Multi-change

- State moves from a single `.context-guard/manifest.json` to
  `.context-guard/changes/{name}/`, so several changes can be planned,
  executed, and locked independently in the same project.
- New commands: `cg new <name>`, `cg list`, `cg archive --change <name>`.
- `cg migrate` converts both legacy layouts (state-guard's `state.ini` and
  context-guard 1.x's flat directory) in place, idempotently. A 1.x layout's
  own `archive/` subdirectories are copied into `changes/archive/` too, not
  just its live changes. Phases state-guard tracked that this pipeline does
  not recognise (a `hotfix` bypass state, for example) land in a
  `legacy_phases` field instead of silently corrupting `completed_phases`.
- Every command accepts `--change`; with several changes active and no flag,
  commands report the ambiguity and name them — never guess the first one
  alphabetically, the bug both predecessor repos shipped with.

### Human approval gate

- `cg approve --change <name> --by <who> [--hotfix --reason "<text>"]`
  records a human sign-off in the manifest. `commit --next-phase EXECUTE`
  refuses without one (`APPROVAL_REQUIRED`, exit 6). The approval is consumed
  by the commit it authorizes, so a later iteration of the plan needs a new
  one. `--by` is required — no default, so an agent-run approve cannot pass
  silently as the environment's `$USER`.
- `--hotfix` is the audited door out of the pipeline: it requires a reason,
  jumps straight to EXECUTE, and records PLAN as skipped rather than
  completed.
- The gate is cooperative by construction — see Threat Model in the README.
  The hard control is your harness's permission prompt on `cg approve`,
  documented per host in `adapters/*/PERMISSIONS.md`. `approve` is
  deliberately not exposed over MCP, for the same reason.

### Pre-commit hook, promoted

- Reads the multi-change layout (previously blind to it, and blocking every
  large commit regardless of protocol state).
- File threshold is configurable via `hook.file_threshold` in the manifest or
  `CONTEXT_GUARD_FILE_THRESHOLD` (env wins); the strictest configured value
  applies across changes.
- Files staged outside `files_in_scope` on an executing change now warn, never
  block. Output is in English. The audited bypass
  (`CONTEXT_GUARD_BYPASS=1 CONTEXT_GUARD_BYPASS_REASON=...`) is unchanged.

### Phases and adapters

- `phases/{plan,execute,verify}.md`, ported from state-guard, translated to
  English, trimmed, and integrated with `[PENDING]` and `cg approve`.
- Thin per-harness adapters in `adapters/{claude-code,opencode,antigravity}/`
  plus `install.sh`, all installing per-project now — OpenCode and
  Antigravity used to write into `$HOME` (a stale absolute path to the repo
  clone for OpenCode's generated commands, a global `~/.gemini/GEMINI.md`
  injection for Antigravity that contaminated every project on the machine).
  Nine confirmed bugs closed in the pass: the deprecated OpenCode `tools`
  key, a missing manifest-edit `deny` on both OpenCode and Claude Code,
  inconsistent command names across hosts (unified on `/cg-new` /
  `/cg-continue`), a missing Antigravity deny hook on `run_command`, and no
  MCP server registration anywhere.
- `install.sh` gains `--host claude|opencode|antigravity|all`, `--with-mcp`
  (registers `context-guard-mcp` per host; optional, every adapter works
  without it), and `--with-antigravity-hook` (opt-in, touches user config).
  Every config merge is idempotent and preserves what was already there;
  the installer prints the exact list of files it touched.
- Each adapter documents its own permission configuration for `cg approve`
  in `PERMISSIONS.md`; OpenCode and Antigravity are marked unverified —
  rewritten and covered by tests that actually run `install.sh`, but never
  driven through a real host session. `adapters/VERIFY.md` is the manual
  checklist for closing that gap.
- `AGENTS.md` rewritten to under 100 lines as the single contract an agent
  loads.

### MCP server

- Gains the four read tools promised since F3: `get_status`, `next_task`,
  `check_completion`, `validate`, alongside the existing transactional four.
- `approve` is not an MCP tool — see Threat Model.

### Packaging

- `mcp` dependency pinned with an upper bound (`>=1.0.0,<2.0.0`).
- `requires-python = ">=3.10"`, tested in CI across 3.10–3.13.
- `cg` ships as a short entry point alongside `context-guard`.
- MIT license added.
- `requirements.txt` removed — it carried `mcp>=1.0.0` with no upper bound,
  the exact drift fixed in `pyproject.toml`, and nothing in the repo
  consumed it. `pyproject.toml` is the single source of truth.
- `.claude/` excluded from the sdist after a `uv build` dry run showed it
  bundling `.claude/settings.local.json` — untracked, ignored by this
  machine's global gitignore rather than the repo's own, carrying absolute
  local paths.

---

## [1.2.0] - 2026-07-28

### 🔒 Git Hard Gate (Pre-Commit Hook)

- Implemented a Git pre-commit hook (`.githooks/pre-commit`) that rejects commits touching more than 2 files without an active `context-guard` transaction.
- Prevents large changes to the repository that bypass the `PLAN → EXECUTE → VERIFY` protocol.
- Supports an emergency bypass via `CONTEXT_GUARD_BYPASS=1`, automatically logged to `.context-guard/bypass.log`.

### 📦 Package Namespace Fix

- Renamed the source directory from `scripts/` to `context_guard/` to avoid global collisions in Python, standardizing the module name with the tool's name.
- Updated internal imports to use relative references (`from .X import Y`) within the `guard` submodule, decoupling it from the root package name.
- Updated the entry point in `pyproject.toml` to reflect the new structure: `context_guard.mcp_server:main`.

---

## [1.1.0] - 2026-07-28

### 🏗️ Automatic Artifact Scaffolding

- **`_scaffold_artifacts(context_path)`** in `transaction.py`:
  - When a `PLAN` transaction starts via `begin_transaction`, five Markdown templates are auto-generated in `.context-guard/` if they do not already exist: `objective.md`, `snapshot.md`, `tasks.md`, `review-report.md`, and `verify-report.md`.
  - Each template is initialized with the `[PENDING]` marker to guide the LLM on which fields need to be completed before advancing phase.

### 🚧 Hard Gates in `cmd_commit`

- Strict Python-side validations before authorizing phase transitions (no dependency on system prompt compliance):
  - **`PLAN` → `EXECUTE`**: Verifies that `objective.md` and `tasks.md` exist and contain no `[PENDING]`. Otherwise returns `EXIT_VALIDATION` with a descriptive message.
  - **`VERIFY` → `ARCHIVE`**: Verifies that `review-report.md` and `verify-report.md` exist and contain no `[PENDING]`. Otherwise returns `EXIT_VALIDATION` with a descriptive message.

### 📜 Updated MCP Docstrings (`mcp_server.py`)

- `begin_transaction`: Documents the auto-scaffolding of the 5 `.md` files in the `PLAN` phase.
- `commit_transaction`: Documents the strict Hard Gate validation rules per file and per phase, exposing the constraints to the LLM via the tool schema.

### ✅ Test Suite Improvements

- New test cases in `test_transaction.py`:
  - `test_begin_valid_phase`: verifies creation of the 5 scaffold artifacts with `[PENDING]` content.
  - `test_commit_hard_gate_plan_to_execute_pending`: validates rejection when `PLAN` files still contain markers.
  - `test_commit_hard_gate_verify_to_archive_pending`: validates rejection when `VERIFY` files still contain markers.
- Updated `test_phases.py` and `test_mcp_server.py` to prepare valid artifacts before each `commit_transaction`.
- Full suite: **111 tests, 0 failures**.

---

## [1.0.0] - 2026-07-28

### 🚀 Highlights and Core Features

- **Native MCP Server (Model Context Protocol):**
  - Exposes native tools over `stdio` transport: `begin_transaction`, `commit_transaction`, `rollback_transaction`, and `save_checkpoint`.
  - Transparent integration with MCP clients such as Claude Desktop, Antigravity, OpenCode, and Cursor.

- **3-State Transactional Pipeline (DAG):**
  - Strict implementation of the phase sequence: `PLAN` $\longrightarrow$ `EXECUTE` $\longrightarrow$ `VERIFY` $\longrightarrow$ `ARCHIVE`.
  - Validates allowed transitions to prevent arbitrary phase jumps by the LLM.

- **Atomicity and Rollback Mechanism:**
  - Automatic `manifest.json` snapshots taken on `begin_transaction`.
  - `rollback_transaction` tool restores the exact prior state on execution failures or failed tests during the `VERIFY` phase.

- **Concurrency Control and Write Lock (OS-level):**
  - OS-level session locks and write mutexes (`O_CREAT|O_EXCL`) to prevent race conditions (*TOCTOU*) between concurrent agents or sessions.
  - Automatic detection and recovery of orphaned (*stale*) locks via PID verification and timestamping.

- **Per-Project Absolute Path Anchoring:**
  - Isolated, transparent persistence inside each project's root directory (`<PROJECT_ROOT>/.context-guard/`), eliminating contamination of the home directory (`$HOME`).

- **Standard Packaging and Zero-Install Support (`uvx`):**
  - Added `pyproject.toml` with the `hatchling` backend and the `context-guard` executable entry point.
  - Supports one-line execution with no prior clone via `uvx git+https://github.com/fdomerlo/context-guard.git`.

- **Tool Discovery Optimization (i18n):**
  - Docstrings and auto-summaries standardized in English to maximize language model adherence during tool discovery and selection.
