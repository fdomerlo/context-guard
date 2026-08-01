# PLAN Phase

## Purpose

PLAN absorbs exploration, proposal, and scoping into a single block of work.
It produces `objective.md` and `tasks.md` and submits them to a **mandatory
human review** before the change is allowed into EXECUTE.

```
draft  →  human review  →  commit
```

The commit into EXECUTE is the event that closes PLAN. **The agent must
never run that commit without an explicit go-ahead from the human.**

## What to do

### Step 1: Begin the transaction

```bash
cg begin --context <path> --phase PLAN --change <change-name>
```

If the change is new, `cg new <change-name> --context <path>` does this for
you and scaffolds `objective.md`, `snapshot.md`, `tasks.md`,
`review-report.md`, `verify-report.md` in
`.context-guard/changes/<change-name>/`, all starting as `[PENDING]`.

### Step 2: Discover the stack

```bash
ls package.json pyproject.toml composer.json go.mod Cargo.toml docker-compose.yml 2>/dev/null
```

Read whatever manifests exist to identify the stack, framework, and tooling
before analyzing anything.

### Step 3: Explore and analyze

- Is this new functionality, a bug fix, or a refactor?
- Read the relevant code: entry points, affected modules, existing tests.
- Compare approaches if there are real alternatives.

### Step 4: Draft the artifacts

Write directly to disk, replacing the `[PENDING]` scaffolds:

**`objective.md`**
```markdown
# Objective: {Change Title}

## Intent
{What problem this solves and why}

## Scope
### In scope
- {deliverable}
### Out of scope
- {deferred}

## Success criteria
- [ ] {measurable outcome}

## Open questions
- [ ] {unresolved question — mark blocking ones with [!]}
```

**`tasks.md`**
```markdown
# Tasks: {Change Title}

## Phase 1: {e.g. Infrastructure}
- [ ] [T001] {atomic task with a concrete file path}

## Phase 2: {e.g. Core implementation}
- [ ] [T002] {atomic task}

## Phase 3: {e.g. Testing}
- [ ] [T003] {atomic task}
```

Task rules: one task = one file or logical module (no "monster tasks"); IDs
follow `[Txxx]` — `check-completion` and `next-task` parse them; group by
infrastructure → implementation → testing; reference success criteria as
acceptance checks.

Optionally update `snapshot.md` with a short state-of-the-world summary if
the change spans multiple sessions — `cg validate` requires the file to
exist (alongside `objective.md`) and checks size and language, though it
does not check for a leftover `[PENDING]`; that is `commit`'s job.

### Step 5: Human review gate

**The agent cannot proceed on its own — this is the one barrier only a human
can cross.**

1. Present `objective.md` and `tasks.md` with an executive summary.
2. List architecture decisions and open questions explicitly.
3. Run `cg validate --context <path> --change <change-name>` and fix
   anything it flags (missing file, oversized artifact, non-English text) —
   it does not check for `[PENDING]`; confirm by eye that both artifacts
   are actually filled in before asking for approval.
4. Ask the human, in this conversation, to review and confirm.
5. Ask them to record it — **never run this yourself**:

```bash
cg approve --context <path> --change <change-name> --by <who>
```

Without it, Step 6 fails with `APPROVAL_REQUIRED` (exit 6). The approval is
spent by the commit it authorizes, so if the plan is revised afterwards the
human has to approve again. The harness's permission prompt on `cg approve`
(configured per `adapters/*/PERMISSIONS.md`) is what makes that confirmation
hard to skip rather than merely polite.

### Step 6: Commit and close PLAN

Only after the human confirms:

```bash
cg commit --context <path> --change <change-name> --next-phase EXECUTE
```

This advances `lock_phase` to `EXECUTE`, releases the phase lock, and
auto-generates a checkpoint of the DAG state. Report to the user that PLAN is
locked and EXECUTE is open, with the suggested next command: `/cg-continue`.

## Rules

- Never commit into EXECUTE without explicit human approval.
- If the human requests changes, regenerate only the sections asked for, not
  the whole artifact.
- Blocking open questions (`[!]`) must be resolved before requesting review.
- Always read the real code — never assume about the codebase.
- `objective.md` and `tasks.md` are separate artifacts with separate
  purposes; do not merge them into one file.
