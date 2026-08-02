---
name: context-guard
description: >-
  Use when the user asks for a multi-step coding task, when they ask to
  resume work after a lost, crashed or compacted session, or in any project
  that already contains a `.context-guard/` directory. Drives the `cg` CLI so
  a phase-governed change keeps its plan, its progress and its verification
  on disk instead of in the conversation.
---

<!-- context-guard:begin -->
# context-guard

`cg` (long form: `context-guard`) is a transactional state manager. A change
moves through fixed phases and nothing advances without passing that phase's
gate, so a session that dies mid-task resumes instead of restarting.

## The pipeline

```
PLAN --approve--> EXECUTE --tasks done--> VERIFY --approve--> ARCHIVE
```

| Phase   | Produces                               | Gate to leave it              |
|---------|----------------------------------------|-------------------------------|
| PLAN    | `objective.md`, `tasks.md`             | human approval, then `commit` |
| EXECUTE | code changes, `tasks.md` checked off   | every task checked off        |
| VERIFY  | `review-report.md`, `verify-report.md` | human approval, then archive  |

`cg commit` rejects any transition outside that order.

## On entering a phase, read that phase's file

The full instructions live in `.context-guard/phases/plan.md`,
`.context-guard/phases/execute.md` and `.context-guard/phases/verify.md` —
not in this skill. Load the file for the phase you are entering and follow
it exactly.

## Commands

- `cg new <name>` — scaffold a change, open PLAN, write the phase files.
- `cg status` — what phase the change is in and what is still pending. Run
  this first when resuming, before reading any code.
- `cg next-task` — the next unchecked task, during EXECUTE.
- `cg commit --next-phase <PHASE>` — advance, once the gate passes.
- `cg list`, `cg validate`, `cg checkpoint`, `cg rollback` — inspect, check,
  snapshot, undo.

Every command takes `--change <name>`. Pass it whenever more than one change
is active: `cg` errors rather than guessing which one you meant.

## `cg approve` is human-only

Never run `cg approve` yourself, and never run it "on behalf of" the user.
When `cg commit` exits 6 (`APPROVAL_REQUIRED`), stop, show the human the
artifacts the gate covers, and ask them to run the approval themselves.
Editing `.context-guard/**/manifest.json` by hand is the same violation by
another route: it forges the state the gate reads.
<!-- context-guard:end -->
