# Antigravity — permission configuration

`cg approve` is the only command in context-guard that a human is supposed to
run. Everything else the agent drives itself.

## What this buys you

The approval gate inside `cg` is **cooperative**: `commit --next-phase EXECUTE`
refuses without a recorded approval (exit code 6), but an agent with a shell
can run `cg approve` itself. A confirmation that happens outside the agent's
process is the only hard control in the model — see PLAN.md 0.6.

## How to configure it

Antigravity has no per-command bash allowlist equivalent to Claude Code's
`permissions.ask`, so the control is coarser:

1. **Keep terminal auto-run off.** Leave command confirmation enabled for the
   workspace so every shell invocation — `cg approve` included — surfaces
   before it runs. This is the layer that actually enforces anything.
2. **Keep the workspace rule installed.** `rules/context-guard.md` (copied
   into `.agents/rules/context-guard.md` in the target project by
   `adapters/install.sh`, read by IDE, CLI, and Manager) declares
   `cg approve` as human-only and tells the agent to stop and ask when
   `commit` returns exit 6. That is instruction-level, not enforcement: it
   shapes behaviour, it does not constrain it.

If you enable auto-run for convenience, understand what you are turning off:
the pipeline becomes fully cooperative, and the manifest's `approval_history`
becomes a record of what the agent did rather than of what you authorized.

## Unverified

**This adapter is unverified.** It was ported from state-guard and is covered
only by static tests. No Antigravity host was available in the environment
where it was written, so neither the workspace rule nor the confirmation
behaviour described above has been exercised against a running Antigravity.
Check the setting names against your version before relying on them.
