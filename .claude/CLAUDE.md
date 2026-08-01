# context-guard — contributor & executor contract

## Always
- All code, comments, errors, artifacts: ENGLISH. Chat with the human: Spanish.
- Run `python -m unittest discover -s tests` before first change and after
  every logical unit. Never leave the suite red at a commit boundary.
- Atomic commits, conventional-commit messages. Never edit files under
  `.context-guard/` by hand — use the `cg` commands.

## Plan mode
If a `PLAN-*.md` exists at the repo root, you are executing a planned cycle:
- Work on exactly ONE phase per session — the phase the human names.
- The plan is the spec. Findings referenced in it become failing tests
  BEFORE fixes (show me the RED run).
- If the plan is ambiguous or wrong: STOP and ask. Never deviate silently.
- Phase end: report files changed, tests added, deviations, open questions.
  Then stop — the human audits the diff before merge.
- No new dependencies without explicit approval.
