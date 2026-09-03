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
cg setup --host <claude|opencode|antigravity|cursor>
```

Confirm the files land where the tests say they should:
`.claude/commands/`, `.opencode/commands/`, or `.agents/rules/`
respectively, plus the merged permission config
(`.claude/settings.json`, `opencode.json`).

### 2. The entry point is discovered, not just installed

- **Claude Code**: `/` menu lists `cg-new` and `cg-continue`.
- **OpenCode**: `/help` lists `cg-new` and `cg-continue`.
- **Antigravity**: there is no `agy inspect` or equivalent command to check
  instead. Open a **new** session — rules and skills load at session start,
  so an already-open one will not see anything just written — give it a
  multi-step coding task, and watch whether it invokes `cg` on its own,
  unprompted. That behavior, not any command's output, is the verification.

  The `description` in `skills/context-guard/SKILL.md` governs whether the
  skill loads at all for a given prompt — PLAN-2.3 F2 found the prior
  wording did not fire on a direct implementation prompt ("build a simple
  todo app") without an explicit `/context-guard` invocation. Current
  `description` covers build/implement/scaffold requests explicitly;
  validated live against **Antigravity CLI 1.1.10** on 2026-08-06, verified
  by: fdomerlo. Re-verify this trigger whenever the `description` text or
  the Antigravity CLI's skill-loading behavior changes.

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
- **Antigravity**: the deny hook `cg setup --host antigravity` installs by
  default fires. If that machine was set up with `--no-hooks`, the CLI's
  default `request-review` mode prompts before the command runs instead.

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

- [x] Claude Code — verified by: fdomerlo on: 2026-08-02
- [x] OpenCode — verified by: fdomerlo on: 2026-08-02
- [x] Antigravity — verified by: fdomerlo on: 2026-08-02
- [ ] Cursor — unverified
