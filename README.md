# Context Guard

[![CI](https://github.com/fdomerlo/context-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/fdomerlo/context-guard/actions/workflows/ci.yml)

**The transactional memory layer for AI coding agents — your context survives crashes, compaction, and session loss.**

*[Leer en español](README.es.md)*

*[Aqui un tutorial (también en español) para usuarios no técnicos y novatos](TUTORIAL.es.md)*

---

## The problem

Long-running agent sessions degrade. Context drift, "lost in the middle,"
completion hallucination (the agent believes it finished before it verified
anything), and — the one that actually loses work — a crash or a compaction
mid-task that leaves the repository half-edited with no way back.

context-guard is not another agent framework and it does not write code. It
is a small, deterministic state machine that sits between an agent and a
project: a manifest on disk that survives the agent's process ending, a
strict `PLAN → EXECUTE → VERIFY → ARCHIVE` pipeline the agent cannot skip
phases in, and a transaction log that can be rolled back. If the session
dies, the manifest is what the next session reads to pick up exactly where
the last one left off — that persistence, not the pipeline shape, is the
point.

## Quickstart

Five commands: plan a change, get a human to sign off on it, advance into
execution, claim a task, and check where things stand.

<!-- quickstart:start -->
```bash
# (1) start a change — this begins PLAN and scaffolds the artifacts
cg new redis-cache

# fill in the plan — an agent writes this, not you
cat > .context-guard/changes/redis-cache/objective.md <<'EOF'
# Objective: Add Redis caching
Cache the top-N query results behind a 60s TTL.
EOF
cat > .context-guard/changes/redis-cache/tasks.md <<'EOF'
- [ ] 1.1 Add the redis client dependency
- [ ] 1.2 Wrap the query path with a cache lookup
EOF

# (2) a human reviews objective.md and tasks.md, then approves
cg approve

# (3) the recorded approval unlocks EXECUTE
cg commit --next-phase EXECUTE

# (4) claim the next task atomically — safe with several agents at once
cg next-task

# (5) one-shot rehydration after a crash, a compaction, or a new session
cg status
```
<!-- quickstart:end -->

Every line above runs as written against a fresh directory; nothing here is
illustrative shorthand.

## Install

**Zero-install, via `uvx`** — add this to your MCP client's config
(Claude Desktop, Antigravity, Cursor: `claude_desktop_config.json` /
`mcp-settings.json`; OpenCode: `~/.config/opencode/opencode.jsonc`):

```jsonc
{
  "mcpServers": {
    "context-guard": {
      "command": "uvx",
      "args": ["git+https://github.com/fdomerlo/context-guard.git"]
    }
  }
}
```

**CLI only**, for the `cg` binary without an MCP client:

```bash
uv pip install git+https://github.com/fdomerlo/context-guard.git
```

**Local, editable**, for development:

```bash
git clone https://github.com/fdomerlo/context-guard.git
cd context-guard && uv venv && uv pip install -e .
git config core.hooksPath .githooks   # activates the pre-commit gate below
```

To wire up slash commands and permissions for your harness, run `cg setup`
once per machine — see [Adapters](#adapters-and-permission-configuration)
below. Phase files are written into each project by `cg new`.

## How it works

```
PLAN  →  EXECUTE  →  VERIFY  →  ARCHIVE
```

Each change (`.context-guard/changes/<name>/`) moves through this pipeline
one phase at a time, enforced by code, not by convention:

- **`begin`** refuses to start a phase that is not the manifest's
  `lock_phase` — the DAG is checked before work starts, not only when it is
  claimed done.
- **`commit`** validates the phase's artifacts (`objective.md` + `tasks.md`
  for PLAN, `review-report.md` + `verify-report.md` for VERIFY) contain no
  leftover `[PENDING]` marker before advancing `lock_phase`.
- **`begin` on a fresh PLAN** auto-scaffolds five markdown files —
  `objective.md`, `snapshot.md`, `tasks.md`, `review-report.md`,
  `verify-report.md` — each starting as `[PENDING]`, so the agent edits
  templates instead of inventing a shape from scratch.
- **`rollback`** restores the exact manifest snapshot taken when the phase
  began.
- **Session and write locks** are OS-level (`O_CREAT|O_EXCL`), with
  liveness-checked stale detection, so two agents on the same change do not
  silently race each other.
- **Task claims** carry a lease (`claim-task` / `next-task` / `doctor
  --fix`), so several agents can work one change concurrently without two of
  them picking the same task.
- **`--change <name>`** scopes every command to one change. Several changes
  active and no `--change` given is an error naming them — never a silent
  guess at "the first one."

## Threat Model

Read this before you rely on context-guard for anything you actually care
about.

The pipeline enforcement (`begin`/`commit` validating the DAG and the
artifacts) is real code, not a system prompt suggestion — an agent using the
`cg` tool cannot accidentally skip a phase or advance past `[PENDING]`
artifacts. But that enforcement is **cooperative**: it only binds an agent
that calls `cg` in the first place. An agent with a shell can write directly
to `manifest.json`, or simply not use the tool at all, and nothing in the
process stops it.

The one command that is explicitly **human-only** is `cg approve`. It
records the sign-off `commit --next-phase EXECUTE` requires. The name it
records (`--by`, defaulting to the OS user) is **audit metadata, not
authentication**: it says who to ask about this approval later, and an agent
could pass any string it liked. The command itself is just as cooperative as
the rest: an agent with a shell can
run `cg approve` itself, and nothing in `cg` prevents that. The actual hard
control does not live in `cg` at all — it is your harness's permission
prompt on the `cg approve` command, configured per host in
`docs/adapters/*/PERMISSIONS.md`. That prompt runs outside the agent's process,
which is the only place a control that does not depend on the agent's
cooperation can live. `approve` is deliberately not exposed as an MCP tool,
for the same reason: an MCP tool is a channel the permission prompt does not
see.

The pre-commit hook is the one layer that runs entirely outside the agent's
process — git invokes it regardless of what the agent chose to do — but it
is a perimeter check on file count, not a guarantee about correctness, and it
ships with an audited bypass (`CONTEXT_GUARD_BYPASS=1`) by design: an
unconditional block just gets `--no-verify`d, which leaves no trace at all.

## CLI reference

| Command | Purpose |
|---|---|
| `cg new <name> --context <path>` | Create a change and begin PLAN |
| `cg list --context <path>` | List active changes and their phase |
| `cg begin --phase <PHASE> --context <path>` | Start a transaction for the given phase |
| `cg approve [--by <who>] [--hotfix --reason "<text>"]` | Human-only: record the sign-off `commit` into EXECUTE requires |
| `cg commit --next-phase <PHASE> --context <path>` | Validate the current phase's artifacts and advance the DAG |
| `cg rollback --context <path>` | Restore the manifest snapshot taken at `begin` |
| `cg checkpoint --summary "<text>" --context <path>` | Persist a session summary for warm-boot resume |
| `cg claim --context <path>` | Acquire the session lock, taking over a stale one if needed |
| `cg release --context <path> --agent-id <id>` | Release the session lock (ownership-checked) |
| `cg claim-task --task-id <id> --context <path>` | Claim one task with a lease |
| `cg release-task --task-id <id> --agent-id <id> --context <path>` | Release a claimed task |
| `cg next-task --context <path>` | Claim and return the next unclaimed pending task |
| `cg check-completion --context <path>` | Deterministic count of checked-off tasks |
| `cg validate --context <path>` | Lint session artifacts: existence, size cap, language |
| `cg status --context <path>` | One-shot summary for rehydration after context loss |
| `cg doctor --context <path> [--fix]` | Diagnose (or repair) stale claims and locks |
| `cg archive --context <path>` | Move a completed change to `changes/archive/` |
| `cg migrate --context <path>` | Convert a legacy state-guard or context-guard 1.x layout in place |

Every command accepts `--format json`. `cg` and `context-guard` are the same
binary under two entry points.

## MCP server

`context-guard-mcp` exposes eight tools over stdio — the four transactional
ones plus four read-only ones for hosts with no shell (Claude Desktop is the
case these exist for):

`begin_transaction`, `commit_transaction`, `rollback_transaction`,
`save_checkpoint`, `get_status`, `check_completion`, `validate`, `next_task`.

`cg approve` is not an MCP tool. See Threat Model above.

## Multi-change

State lives under `.context-guard/changes/<name>/`, one manifest and lock
set per change, so several changes can be planned and executed
independently in the same project. `cg new <name>` creates one; `cg list`
shows what is active; `cg archive` moves a finished one to
`changes/archive/`. `cg migrate` converts both legacy layouts — state-guard's
`state.ini` and context-guard 1.x's flat `.context-guard/` — in place and
idempotently, preserving any recorded human approval it finds.

## Pre-commit hook

`.githooks/pre-commit` rejects commits touching more than a threshold number
of files when no change shows the protocol was engaged (a completed phase or
an open transaction). Activate it once per clone with
`git config core.hooksPath .githooks`.

- **Threshold**: `hook.file_threshold` in a change's manifest, or the
  `CONTEXT_GUARD_FILE_THRESHOLD` environment variable, which wins over the
  manifest. Across several active changes, the strictest configured value
  applies.
- **`files_in_scope`**: staged files outside an executing change's declared
  scope produce a warning, never a block.
- **Bypass**: `CONTEXT_GUARD_BYPASS=1 CONTEXT_GUARD_BYPASS_REASON='...' git
  commit ...`. Every bypass is appended to `.context-guard/bypass.log` with
  a timestamp and the file list — the door stays open, but nobody walks
  through it unrecorded.

## Exit codes

| Code | Name | Meaning |
|---|---|---|
| `[0]` | `EXIT_OK` | Success. |
| `[1]` | `EXIT_GENERIC` | Corrupt manifest, or no session at this context/change. |
| `[2]` | `EXIT_LOCK_HELD` | Another agent holds the lock or claim. Retryable with backoff. |
| `[3]` | `EXIT_LOCK_CONTENDED` | Lost the takeover race for a stale lock. Retryable. |
| `[4]` | `EXIT_VALIDATION` | Missing artifact, leftover `[PENDING]`, oversized artifact, or non-English text. |
| `[5]` | `EXIT_BAD_TRANSITION` | The phase requested is not the DAG's current `lock_phase`. Do not retry. |
| `[6]` | `EXIT_APPROVAL_REQUIRED` | `commit` into EXECUTE with no recorded `cg approve`. Only a human resolves it. |

## Adapters and permission configuration

Thin, per-harness wrappers ship inside the package under
`context_guard/_data/hosts/{claude-code,opencode,antigravity}/` — each points
at `phases/{plan,execute,verify}.md` rather than duplicating them. How to put
`cg approve` behind each harness's permission prompt is documented in
[docs/adapters/](docs/adapters/), one `PERMISSIONS.md` per host, alongside the
manual smoke-test checklist in [docs/adapters/VERIFY.md](docs/adapters/VERIFY.md).
`cg setup` installs the right one for each detected host. The OpenCode and Antigravity
adapters are ported from state-guard and covered by static tests only — they
have not been run against a live host of either.

## How this compares

context-guard is not a spec-writing tool, and it is not trying to be one.

| | context-guard | spec-kit | Kiro | bare `AGENTS.md` |
|---|---|---|---|---|
| Generates specs/plans from a prompt | No | Yes | Yes | No |
| IDE-native experience | No (CLI + MCP) | Depends on host | Yes | No |
| Enforces phase order in code, not prose | **Yes** | No | Partial | No |
| Atomic manifest, survives a crash mid-phase | **Yes** | No | No | No |
| OS-level locking for concurrent agents | **Yes** | No | No | No |
| Human-approval gate before execution | **Yes** | No | No | No |

What we do that they do not: runtime enforcement of a state machine that
outlives the agent's process. What they do that we do not: everything about
turning a prompt into a good spec in the first place. Use context-guard
together with whichever of them already generates your `objective.md` — it
was designed to consume one, not to write one.

## Development

```bash
git clone https://github.com/fdomerlo/context-guard.git
cd context-guard && uv venv && uv pip install -e .
python -m unittest discover -s tests
```

Framework: `unittest`. Every fix ships with an adversarial test that
reproduces the bypass it closes; see `tests/test_adversarial_*.py` for the
pattern. No fixtures on disk outside `tempfile.mkdtemp()`.

## License

MIT — see [LICENSE](LICENSE).
