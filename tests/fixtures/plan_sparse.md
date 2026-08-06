# PLAN-9 — Sparse plan that skips template blocks

Prove the parser tolerates a plan that does not follow the template.

## F1 — Phase with no sub-blocks at all

Just prose. No spec, no tests, no acceptance criteria. This is still a
phase and must parse.

## F2 — Phase with a spec but no tests

**Spec:**
- Rename the config key.

**Acceptance criteria:**
- The old key still resolves for one release.
