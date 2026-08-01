# Claude Code — permission configuration

`cg approve` is the only command in context-guard that a human is supposed to
run. Everything else the agent drives itself.

## What this buys you

The approval gate inside `cg` is **cooperative**: `commit --next-phase EXECUTE`
refuses without a recorded approval (exit code 6), but an agent with a shell
can run `cg approve` itself. Nothing in the process can stop it.

The permission prompt is the part that runs **outside** the agent's process.
With `cg approve` on the `ask` list, the harness stops and asks you before the
command executes — that confirmation is the hard control, and it is the only
one in the model that does not depend on the agent's cooperation. See PLAN.md
0.6 and the Threat Model section of the README.

## Exact snippet

Merge this into `.claude/settings.json` in the project (or into
`~/.claude/settings.json` to apply it everywhere):

```json
{
  "permissions": {
    "ask": [
      "Bash(cg approve*)",
      "Bash(context-guard approve*)"
    ],
    "deny": [
      "Edit(.context-guard/**/manifest.json)"
    ]
  }
}
```

`adapters/install.sh` merges it for you, preserving any entries already there.
Both spellings are listed because the package installs two entrypoints; an
allowlist that only names the short one is trivially sidestepped by using the
long one. The `deny` entry closes the other vector: an agent that cannot run
`cg approve` unprompted could otherwise still write `"approval": {...}` into
`manifest.json` directly and skip the whole protocol.

## What it looks like in practice

1. The agent finishes PLAN and asks you to review `objective.md` and
   `tasks.md`.
2. It proposes `cg approve --context . --change <name> --by <you>`.
3. Claude Code stops and asks. You read the plan, then allow or deny.
4. `cg commit --next-phase EXECUTE` succeeds only after that.

If you deny, the agent stays in PLAN — `commit` returns exit 6
(`APPROVAL_REQUIRED`) until an approval is recorded.

## Verified

Verified against Claude Code by running a full `/new` → approve → `/continue`
cycle in a toy project.
