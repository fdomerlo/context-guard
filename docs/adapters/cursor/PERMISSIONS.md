# Cursor — permission configuration

`cg approve` is the only command in context-guard that a human is supposed to
run. Everything else the agent drives itself.

## What this buys you

The approval gate inside `cg` is **cooperative**: `commit --next-phase EXECUTE`
refuses without a recorded approval (exit code 6), but an agent with a shell
can run `cg approve` itself. A confirmation that happens outside the agent's
process is the only hard control in the model — see PLAN.md 0.6.

## How to configure it

Cursor does not currently provide a per-command shell deny hook (like Antigravity's
`PreToolUse` hook in `hooks.json`) or a fine-grained command permission list (like
Claude Code's `permissions.ask`).

Therefore, enforcement in Cursor is **cooperative**:

1. **Keep terminal confirmation enabled.** Leave terminal command confirmation
   enabled in Cursor settings so terminal commands — `cg approve` included —
   surface for human confirmation before execution.
2. **Keep the workspace rule installed.** `.cursor/rules/context-guard.mdc`
   (installed by `cg setup --host cursor`) instructs the agent that `cg approve`
   is human-only and directs it to pause and request human approval when `commit`
   returns exit code 6.

If auto-run terminal commands is enabled in Cursor, understand that enforcement
becomes purely cooperative, and the manifest's `approval_history` records what
the agent decided rather than what you explicitly gated.

## MCP registration

`cg setup --host cursor --with-mcp` automatically registers `context-guard-mcp`
in `.cursor/mcp.json`. Registration is optional; `cg` works completely via CLI
without MCP.

## Unverified

**This adapter is unverified.** It is covered by static tests and has not been
tested in an interactive end-to-end Cursor session.
