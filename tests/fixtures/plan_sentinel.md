# PLAN-7 — A plan that quotes the scaffold sentinel

Improve how the tool reports artifacts the agent has not filled in yet.

## F1 — Report unfilled artifacts by name

Today `cg validate` reports that something is unfilled without saying which
file still carries the `[PENDING]` marker left by the scaffold.

**Spec:**
- List every artifact whose body still contains `[PENDING]`.
- Report them one per line, not as a single joined string.

**Tests:**
- An artifact left at `[PENDING]` is named in the output.
- A filled artifact is not named.

**Acceptance criteria:**
- The operator can tell which file to open without grepping for `[PENDING]`.
