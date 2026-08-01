---
description: Resume the active context-guard change from where it left off
---

Change (optional): $ARGUMENTS

1. Run `cg status --context . [--change $ARGUMENTS]`.
2. Load and follow, exactly, the file matching the reported `lock_phase`:
   - PLAN    -> `.context-guard/phases/plan.md`
   - EXECUTE -> `.context-guard/phases/execute.md`
   - VERIFY  -> `.context-guard/phases/verify.md`
3. If the lock is held by another agent, stop and report the conflict —
   do not retry automatically.
