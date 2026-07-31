# OpenCode — permission configuration

`cg approve` is the only command in context-guard that a human is supposed to
run. Everything else the agent drives itself.

## What this buys you

The approval gate inside `cg` is **cooperative**: `commit --next-phase EXECUTE`
refuses without a recorded approval (exit code 6), but an agent with a shell
can run `cg approve` itself. The permission prompt is the part that runs
outside the agent's process, and it is the only hard control in the model —
see PLAN.md 0.6.

## Snippet

`agent.snippet.json` declares the permission alongside the agent, so
`adapters/install.sh` installs both together into
`~/.config/opencode/opencode.jsonc`:

```json
{
  "agent": {
    "context-guard": {
      "permission": {
        "bash": {
          "cg approve*": "ask",
          "context-guard approve*": "ask"
        }
      }
    }
  }
}
```

Both spellings are listed because the package installs two entrypoints; an
allowlist that only names the short one is sidestepped by using the long one.

If your OpenCode version does not honour per-pattern bash rules, fall back to
asking for every bash invocation (`"bash": "ask"`) or run the agent in a mode
that confirms commands. A prompt on everything is noisier but still a control;
a prompt on nothing is not.

## Unverified

**This adapter is unverified.** It was ported from state-guard and is covered
only by static tests (structure, no dead references). No OpenCode host was
available in the environment where it was written, so the permission block
above has never been exercised against a running OpenCode. Treat the exact key
names as a starting point and check them against your version's config schema
before relying on the prompt.
