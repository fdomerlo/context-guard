# VERIFY Phase

## Purpose

VERIFY is the final quality gate. It proves — with evidence from real
execution, not static reasoning alone — that the implementation is complete
and correct. If the verdict is APPROVED, the **archive step** runs
immediately as part of this same phase.

## What to do

### Step 1: Begin the transaction

```bash
cg begin --context <path> --phase VERIFY --change <change-name>
```

### Step 2: Read the context

1. **Plan** — `objective.md` for intent and success criteria.
2. **Tasks** — `tasks.md` for what was supposed to happen.

### Step 3: Check completeness

```bash
cg check-completion --context <path> --change <change-name>
```

List any incomplete tasks. Mark CRITICAL if core tasks are unfinished,
WARNING if only cleanup tasks remain.

### Step 4: Check correctness against the objective

For each success criterion in `objective.md`: is there real evidence in the
codebase that it's met? Mark CRITICAL if a criterion has no implementation,
WARNING if only partially covered.

### Step 5: Run tests and build for real

> CRITICAL: use a real terminal. Simulating or inferring results is not
> allowed.

Detect and run the project's test command (`package.json` scripts, `pytest`/
`pyproject.toml`, a `Makefile` target, or whatever `objective.md` calls out)
and its build/typecheck command if one exists. A missing build step is a
WARNING, not a CRITICAL — some projects have none.

### Step 6: Write `review-report.md` and `verify-report.md`

`review-report.md` covers static findings (code quality, plan adherence,
deviations). `verify-report.md` covers dynamic evidence:

```markdown
## Verification report

**Change**: {change-name}

### Completeness
| Metric | Value |
|--------|-------|
| Total tasks | {N} |
| Completed | {N} |
| Incomplete | {N} |

### Build and test run
**Build**: pass / fail
**Tests**: {N} passed / {N} failed / {N} skipped

### Issues found
**CRITICAL**: {list, or "None"}
**WARNING**: {list, or "None"}

### Verdict
{APPROVED / APPROVED WITH WARNINGS / REJECTED}
```

### Step 7: Decide

```text
If there are CRITICAL issues:
  → run `cg rollback --context <path> --change <change-name>`
  → report the issues to the user; the change returns to EXECUTE

If the verdict is APPROVED or APPROVED WITH WARNINGS:
  → run `cg commit --context <path> --change <change-name> --next-phase ARCHIVE`
  → continue immediately to Step 8 (archive), in the same invocation
```

---

### Step 8: ARCHIVE — close out the change

This runs automatically after an APPROVED verdict, in the same `/continue`
invocation that ran VERIFY. There is no separate manual archive command for
this path.

1. Confirm `verify-report.md` and `review-report.md` contain no `[PENDING]`
   and no unresolved CRITICAL issue. If they do, abort.
2. Check `git status --porcelain`: a dirty tree blocks archiving — ask the
   user to commit first.
3. Run:
   ```bash
   cg archive --context <path> --change <change-name>
   ```
   This copies `.context-guard/changes/<change-name>/` to
   `.context-guard/changes/archive/<change-name>/` and removes the live
   change directory. The archive is an audit trail — never edit or delete an
   archived change.
4. Report to the user:
   ```markdown
   ## Change archived

   **Change**: {change-name}
   **Archived at**: .context-guard/changes/archive/{change-name}/

   The change has been planned, implemented, verified, and archived.
   Ready for the next `/new`.
   ```

## Rules

- Always read real source and run real tests — static analysis alone is not
  verification.
- CRITICAL issues must be resolved before archiving.
- WARNING issues should be resolved but do not block.
- Do not fix problems found during VERIFY — only report them; fixes happen
  back in EXECUTE.
- Never archive while `verify-report.md` has an unresolved CRITICAL issue.
- Never modify or delete an already-archived change.
