# Adapter smoke test (manual)

Everything in `adapters/` that touches a real host's config or UI is
covered only by static and subprocess tests against a fake `$HOME` — none
of it has been driven through an actual Claude Code, OpenCode, or
Antigravity session. This checklist is what closes that gap. It is manual
on purpose: the thing being verified is what a human sees and clicks, which
no test in `tests/test_adapters.py` can observe.

Run it against a throwaway toy project, one host at a time. Steps 4-5 are
the test of the whole enforcement model (PLAN.md 0.6); the rest is plumbing
that has to work first for 4-5 to mean anything.

## Per host

### 1. Install

```bash
cd /path/to/toy-project
cg setup --host <claude|opencode|antigravity>
```

Confirm the files land where the tests say they should:
`.claude/commands/`, `.opencode/commands/`, or `.agents/rules/`
respectively, plus the merged permission config
(`.claude/settings.json`, `opencode.json`).

### 2. The command / rule is visible to the host

- **Claude Code**: `/` menu lists `cg-new` and `cg-continue`.
- **OpenCode**: `/help` lists `cg-new` and `cg-continue`.
- **Antigravity**: `/skills` (or the equivalent surface) shows the rule
  loaded, confirmed with `agy inspect` if available.

### 3. `/cg-new demo` drives `cg`, not improvisation

Run the new-change command. Confirm it actually calls `cg new demo
--context .` — check `.context-guard/changes/demo/manifest.json` exists
with `lock_phase: "PLAN"` — rather than the agent inventing its own state
by hand.

### 4. Commit to EXECUTE without approval is refused

Fill `objective.md` and `tasks.md`, then ask the agent to advance to
EXECUTE without approving first. It must stop: `cg commit --next-phase
EXECUTE` returns exit 6 (`APPROVAL_REQUIRED`), and the agent reports that
back and asks you to approve — it does not attempt `cg approve` itself.

### 5. The host's control fires when the agent tries to run `cg approve`

This is the actual enforcement layer (PLAN.md 0.6), not step 4's
cooperative check. Have the agent propose `cg approve` and confirm the host
intercepts it before it runs:

- **Claude Code**: the `ask` permission prompt appears.
- **OpenCode**: the `ask` permission prompt appears.
- **Antigravity**: either the `--with-antigravity-hook` deny fires, or (if
  not installed) the CLI's default `request-review` mode prompts before the
  command runs.

### 6. Headless, where the host has one

- **Claude Code**: `claude -p "..."` — confirm the same ask-list behavior
  applies non-interactively (it should block/queue for approval, not
  silently allow).
- **OpenCode**: `opencode run "..."` — same check.
- **Antigravity**: no headless mode to check as of this writing; skip.

## Recording results

Check off each host below as its checklist passes. Note the context-guard
version, host version, and date — this checklist decays the moment either
side changes its config schema, so a pass from six months ago is not a pass
today.

- [ ] Claude Code — verified by: __________ on: __________
- [ ] OpenCode — verified by: __________ on: __________
- [ ] Antigravity — verified by: __________ on: __________ (may remain
      pending per PLAN.md F6 acceptance criterion 4; record it as such
      rather than leaving it silently unchecked)
