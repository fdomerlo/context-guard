# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.6.0] - 2026-09-04

### Added

- `cg init`: repository scaffolding command that establishes the AI agent contract
  in `AGENTS.md` (idempotent, delimited by `<!-- context-guard:begin -->` / `<!-- context-guard:end -->`),
  configures harness rules (`CLAUDE.md`, `.cursorrules`, `.agent/rules/`), installs
  git hooks (`.githooks/commit-msg` and `.githooks/pre-commit`), and activates
  `core.hooksPath .githooks`.
- `cg plan`: requirement decomposition engine that turns a prompt or specification
  into a structured plan, multi-phase DAG (`F1`, `F2`, …), tasks, and acceptance criteria
  persisted in `manifest.json` as the single source of truth.
- `cg verify`: formal verification gate that validates completion of tasks and
  acceptance criteria, checks off criteria in `tasks.md`, and updates audit reports
  (`verify-report.md`, `review-report.md`).
- Multi-phase transition support in `cg begin` and `cg commit`: advancing from `VERIFY`
  to the next phase marks the current phase completed, switches `active_phase_id`,
  and resets `lock_phase` to `PLAN` with mandatory human approval (`cg approve`)
  before execution.
- Enhanced `cg status` showing active phase, phase task progress, and completed/pending
  phase lists.
- Conventional Commits enforcement via `.githooks/commit-msg`, rejecting non-compliant
  commit messages while supporting emergency bypass via `--no-verify`.

### Changed

- Unification of `disciplined-scaffold` into `context-guard`: absorbed repository
  scaffolding, agent contract generation, commit discipline, and phased planning
  into a single transactional state machine.
- Deprecated `disciplined-scaffold` as a separate tool; existing phased plans continue
  to be supported via `cg new --from-plan`.

## [2.5.0] - 2026-09-03

### Added

- Support for Cursor as a host adapter: `cg setup --host cursor` installs
  `.cursor/rules/context-guard.mdc` (both globally in `~/.cursor/rules` and
  per-project) and optionally registers `context-guard-mcp` in `.cursor/mcp.json`
  via `--with-mcp`.
- `cg new` automatically detects Cursor and materialises `.cursor/rules/context-guard.mdc`
  in newly created changes.
- Documentation for Cursor's cooperative approval gate model in
  `docs/adapters/cursor/PERMISSIONS.md`.

### Changed

- Unified Gemini/Antigravity global skill installation path to
  `~/.gemini/config/skills/context-guard/SKILL.md` (the canonical machine-local
  configuration root shared across Gemini CLI, IDE, Desktop, and ACP).
  This fixes broken symlinks when `~/.gemini/config/skills/` was not yet created.
  Any legacy owned skill file at `~/.gemini/antigravity-cli/skills/context-guard/SKILL.md`
  is cleaned up automatically on setup.

## [2.4.0] - 2026-08-06

The bridge between a plan and a change was copy-paste. A phased `PLAN-N.md`
already holds what `cg new` leaves as `[PENDING]`; now the tool reads it.

### Added

- `cg new <name> --from-plan <file>` imports a phased `PLAN-N.md`, creating
  one change per `## F<N>` phase (`<name>-f1`, `<name>-f2`, …). Each phase's
  prose and spec become `objective.md`; its test items and acceptance
  criteria become `tasks.md` in the `- [ ] N.M <text>` form `next-task`
  already parses. `--phase F2` imports one phase. `snapshot.md` stays
  `[PENDING]` — it records the repository state at start, which no plan
  written beforehand can know.
- `context_guard/guard/plan_import.py`: `parse_plan()` reads a plan into
  title, one-sentence objective, and phases. Headings delimit phases;
  `**Spec:**`, `**Tests:**` and `**Acceptance criteria:**` sub-blocks are
  recognized in English and Spanish. A missing sub-block is empty, not an
  error; a file with no phase heading is `FAIL|PLAN_NO_PHASES|<path>`.
  Parsed with `re` alone — no new dependencies.
- Changes imported from a plan carry no approval. `cg commit --next-phase
  EXECUTE` still exits 6 until a human runs `cg approve`, once per phase.
  Covered by an adversarial test: a pre-written objective is not a reviewed
  one.
- Re-importing skips changes that already exist
  (`SKIP|CHANGE_EXISTS|<name>`) instead of overwriting work in flight.
- A plan quoting the scaffold sentinel `[PENDING]` in its own prose — any
  plan about context-guard itself — would have produced a change the
  PLAN→EXECUTE gate refuses as unfilled, stuck before the approval gate was
  ever reached. The brackets are stripped on import and the substitution is
  reported (`NOTE|SENTINEL_NEUTRALIZED|<change>|<file>`). Fixed on the
  import side deliberately: the artifact really was filled, so loosening the
  gate would have loosened it for every change, imported or not.

## [2.2.0] - 2026-08-02

Triggered by real dogfooding: Antigravity never raised the context-guard
protocol in a fresh project, because `cg setup` only installed its
enforcement hook, nothing discoverable.

### Added

- A discovery skill for Antigravity, installed by `cg setup` at
  `~/.gemini/antigravity-cli/skills/context-guard/SKILL.md` alongside the existing
  deny hook. Antigravity loads skills by progressive disclosure — only the
  name and description sit in context until the model picks it — which is
  what makes this affordable without repeating 2.0's bug 6.0.4
  (`~/.gemini/GEMINI.md` contamination of every project on the machine,
  which stays permanently out of scope). The skill carries the three-phase
  DAG, the operative `cg` commands, and marks `cg approve` human-only.
- `cg setup --project <dir>` now installs the Antigravity workspace rule
  directly, instead of that artifact only ever being written by `cg new`.
- A shared ownership-marker check: a skill or rule file not written by
  context-guard is never overwritten — reported as `SKIP|SKILL_EXISTS|<path>`
  and left alone, whether hit through `cg setup` or `cg new`.

### Fixed

- Antigravity detection now checks for `agy` — the CLI's actual binary name
  — and `~/.gemini/antigravity-cli`, its state directory. The prior check
  named `antigravity`, which resolves on PATH to an unrelated program.
- `cg setup --project` was overwriting an `.agents/rules/context-guard.md`
  a team had edited; `cg new` never did. Both paths now honor the same
  ownership marker.

### Changed

- README.md, README.es.md and TUTORIAL.es.md Install sections lead with
  `uv tool install context-guard-cli` / `pipx install`, isolated installs
  that land `cg` on PATH globally — what a once-per-machine `cg setup`
  assumes. `pip install` remains documented as a fallback. Explicit warning
  added against `uv pip install context-guard-cli`, which installs into
  whichever project venv is active rather than the machine, silently
  defeating a global `cg setup`.
- `docs/adapters/VERIFY.md`: step 2 no longer checks Antigravity discovery
  via `agy inspect`, which does not exist as a subcommand — replaced with
  the actual verification, behavioral: a new session, a multi-step task,
  and whether the agent invokes `cg` unprompted. Step 5 no longer names
  `--with-antigravity-hook`, a flag removed in 2.1; the deny hook installs
  by default now, declined with `--no-hooks`.
- VERIFY.md is complete for all three hosts — Claude Code, OpenCode and
  Antigravity — closing the gap the README used to admit openly. The line
  stating the OpenCode and Antigravity adapters had not been run against a
  live host is removed; both have been.

## [2.1.0] - 2026-08-01

### Added

- `cg setup` installs the host adapters for Claude Code, OpenCode and
  Antigravity. Global scope by default — one command per machine — with
  `--project <dir>` keeping 2.1's predecessor behaviour of installing into a
  single project for teams that commit the configuration.
- The phase documents and every host artifact now ship inside the package as
  data, so nothing needs a clone of this repository to install.
- `cg setup --no-hooks` declines Antigravity's `PreToolUse` deny hook, which
  is installed by default. That hook is what stops the agent from running
  `cg approve` itself, so the file it writes is annotated in the summary with
  what it is and how to skip it.

### Changed

- `--context` defaults to the working directory on every subcommand, and
  `--by` defaults to the OS user, so with a single active change the whole
  human approval is `cg approve` with no flags at all.
- **`--by` is no longer required.** 2.0 required it, arguing that inheriting
  the environment made an agent-run approve indistinguishable from a
  human-run one. The flag never authenticated anyone — an agent can pass any
  string — and requiring it put friction on the one step that must not be
  automated. It is audit metadata: who to ask about an approval later. The
  authentication was and remains the harness permission prompt, which the
  Threat Model now says explicitly.
- Naming a change that does not exist reports
  `FAIL|CHANGE_NOT_FOUND|<name>|available: <list>` instead of
  `FAIL|NO_SESSION`, which read as a broken project rather than a typo. A
  mistyped name also no longer creates the change it names: `begin` used to
  answer a misspelling by bringing that change into being.
- `cg new` materialises `.context-guard/phases/*.md` into the project from the
  packaged copy, which is what makes a globally installed slash command work
  in a project nobody prepared. A phase file that already exists is never
  overwritten; `cg doctor` reports the difference as INFO.

### Fixed

- `cg setup --host antigravity` no longer crashes on an existing
  `hooks.json` whose shape it did not expect (`{"hooks": [...]}` raised
  `AttributeError` with a raw traceback). The shape is validated before the
  merge; anything unrecognised or unparseable is reported and left byte-for-
  byte untouched, and a host that cannot be configured no longer aborts the
  others in the same run.

### Removed

- `adapters/install.sh`, with no compatibility wrapper. Run `cg setup`
  instead.
- `--with-antigravity-hook`. The deny hook is installed by
  `cg setup --host antigravity`, since at global scope it was the only thing
  that flag's host had to install.

### Known gaps

Deliberately out of scope for 2.1, recorded here so the decisions outlive the
plan that made them:

- No `get.sh` curl-pipe bootstrap; installation is `pip install` plus
  `cg setup`.
- No `cg setup --uninstall`. The exact list of files each run touches is
  printed for that reason — it is the only record of what to remove by hand.
- The tutorial exists in Spanish only; no English mirror yet.
- `cg setup` and the three host adapters are still unverified against a real
  host session. `docs/adapters/VERIFY.md` is the manual checklist.

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
