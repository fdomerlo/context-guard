# EXECUTE Phase

## Purpose

EXECUTE is the only phase that changes the project's source code. It works
through `tasks.md` task by task until the change is implemented.

**Prerequisite:** `lock_phase == EXECUTE` — this only happens after the human
approved the PLAN commit.

## What to do

### Step 1: Begin the transaction

```bash
cg begin --context <path> --phase EXECUTE --change <change-name>
```

### Step 2: Read the context

Before writing any code:

1. **Plan** — read `objective.md` for intent and scope.
2. **Tasks** — read `tasks.md` for the full breakdown.
3. **Existing code** — read the files each task actually touches.

### Step 3: Detect TDD mode

Check, in order: a project config declaring `tdd: true`, existing test
patterns in the codebase (a `tests/` directory with a consistent style is a
strong signal), otherwise assume standard mode (code first).

### Step 4: Implement tasks

**TDD mode (RED → GREEN → REFACTOR)**, for each task:
1. Read the task description and any related acceptance criteria.
2. **RED**: write a test describing the expected behavior → confirm it FAILS.
3. **GREEN**: implement the minimum code to make it pass → confirm it PASSES.
4. **REFACTOR**: clean up without changing behavior → confirm it still PASSES.
5. Check the task off in `tasks.md` (`- [x]`).

> CRITICAL: run tests in a real terminal. Simulating or inferring results is
> not allowed.

**Standard mode**, for each task: read the description, read existing code
patterns, write the code, check the task off.

Default batch size: 3 tasks per invocation, adjusted to available context.
For task lists that support parallel work, `cg next-task --context <path>
--change <name>` and `cg claim-task` let multiple agents work the same
change without stepping on each other — each claim carries a lease, so a
crashed agent's tasks become available again automatically; see `AGENTS.md`.

### Step 5: Verify progress with the middleware

```bash
cg check-completion --context <path> --change <change-name>
```

Reports `total`, `completed`, and whether every task is done — the agent
never counts checkboxes by hand.

### Step 6: Report

```markdown
## Implementation progress

**Change**: {change-name}
**Mode**: {TDD | Standard}

### Completed tasks
- [x] [T001] {description}

### Files changed
| File | Action | What happened |
|------|--------|----------------|

### Deviations from the plan
{List, or "None — implementation matches the plan."}

### Issues found
{List, or "None."}

### Status
{N}/{total} tasks complete. {Ready for VERIFY / next batch pending}
```

## Rules

- Always follow the plan's decisions — do not improvise architecture.
- Always match existing code patterns and conventions.
- Check tasks off in `tasks.md` as you complete them, never in bulk at the
  end.
- If the plan turns out to be wrong or incomplete, write it down as a
  deviation — never diverge silently.
- If a task is blocked, stop and report it instead of skipping ahead.

Once every task is checked off, run `cg commit --context <path> --change
<change-name> --next-phase VERIFY` and move on to `phases/verify.md`.
