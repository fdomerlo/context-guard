---
name: context-guard-slim
description: Compact persistence middleware protocol for AI agents with limited instruction-following capacity.
---

# Context Guard — Compact Protocol

You are a stateless agent. All persistent state lives in `.context-guard/sessions/{context}/`.
Use the CLI middleware for ALL state operations. NEVER edit `manifest.json` directly.

## BOOT

Check if `.context-guard/sessions/{context}/manifest.json` exists.

### If it does NOT exist (Cold Boot):

1. Detect the project stack (`ls package.json pyproject.toml go.mod Cargo.toml`)
2. Run: `python3 ~/.agents/skills/context-guard/scripts/guard.py claim --context {target-objective} --ttl 300`
3. Create these files in `.context-guard/sessions/{context}/`:
   - `objective.md` — one paragraph describing the goal
   - `snapshot.md` — current project state (stack, key files, dependencies)
   - `blockers_todo.md` — checklist of tasks: `- [ ] description`
4. Run: `python3 ~/.agents/skills/context-guard/scripts/guard.py validate --context {context}`
   - If exit code ≠ 0: fix the failing file, then re-run validate
5. Run: `python3 ~/.agents/skills/context-guard/scripts/guard.py release --context {context}`
6. Print a welcome summary and STOP.

### If it exists (Resume):

1. Run: `python3 ~/.agents/skills/context-guard/scripts/guard.py status --context {context}`
2. Read the output to understand current state, then proceed to EXECUTION.

## EXECUTION

Get the next available task:

1. Run: `python3 ~/.agents/skills/context-guard/scripts/guard.py next-task --context {context}`
2. If output contains `DONE|NO_PENDING_TASKS` → go to CLOSURE
3. If output contains `SUCCESS|NEXT_TASK|{task-id}|{description}` → execute the task
4. When the task is done, run: `python3 ~/.agents/skills/context-guard/scripts/guard.py release-task --context {context} --task-id {task-id}`
5. Mark the task as `[x]` in the task file
6. Repeat from step 1

## CLOSURE

1. Run: `python3 ~/.agents/skills/context-guard/scripts/guard.py check-completion --context {context}`
2. If `all_complete=true` → run: `python3 ~/.agents/skills/context-guard/scripts/guard.py archive --context {context}`
3. If tasks remain incomplete → continue EXECUTION

## RULES

- All files inside `.context-guard/` are written in English
- Use `[x]` for done, `[/]` for in-progress, `[ ]` for pending
- When yielding control to the user, print a brief status summary
