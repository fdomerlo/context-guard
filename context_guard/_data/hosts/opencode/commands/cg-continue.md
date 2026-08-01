---
description: Resume the active context-guard change from where it left off
agent: context-guard
---

!`cg status --format json`

Change (optional): $ARGUMENTS. The status above is already current — do not
re-run `cg status` yourself.

1. Load and follow, exactly, the file matching the reported `lock_phase`:
   - PLAN    -> `.context-guard/phases/plan.md`
   - EXECUTE -> `.context-guard/phases/execute.md`
   - VERIFY  -> `.context-guard/phases/verify.md`
2. If the lock is held by another agent, stop and report the conflict —
   do not retry automatically.
