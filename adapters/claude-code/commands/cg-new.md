---
description: Start a new context-guard change and run its PLAN phase
---

Change name: $ARGUMENTS (ask the user for one if empty).

1. Run `cg new $ARGUMENTS --context .`
2. Load `.context-guard/phases/plan.md` and follow it exactly for this
   change, through its human review gate.
3. Never run `cg commit --next-phase EXECUTE` without an explicit
   go-ahead from the user in this chat.
