# context-guard v2 migration — executor contract

You are executing a phased refactor defined in PLAN.md (this repo, root).
Work on exactly ONE phase per session — the phase the human names. Never
start the next phase, even if trivial.

## Non-negotiable rules
1. Read PLAN.md section for your phase before touching anything. The audit
   findings referenced there (file:line) are the spec — reproduce them as
   failing tests BEFORE fixing (RED before GREEN, literally run the test
   and show me the failure).
2. Run `python -m unittest discover -s tests` before your first change
   (baseline) and after every logical unit. Never leave the suite red at
   a commit boundary.
3. Atomic commits: one concern per commit, conventional-commit messages
   in English. No commit mixes a fix with a refactor.
4. All code, comments, errors, and artifacts in ENGLISH. Chat with me in
   Spanish.
5. Never edit manifest.json / state files by hand in tests — go through
   the public functions. Tests use tempfile.mkdtemp, no fixtures on disk
   outside tmp.
6. If PLAN.md is ambiguous or you believe it is wrong: STOP and ask.
   Deviating silently from the plan is the one failure mode this whole
   project exists to prevent — do not embody it.
7. At phase end, output: files changed table, tests added (name + what
   attack it encodes), any deviation from PLAN.md with justification,
   and open questions. Then stop. The human audits the diff before merge.

## Definition of done for any phase
- All acceptance criteria in PLAN.md for the phase: met and demonstrated.
- Adversarial tests for every fix in the phase: present and green.
- Legacy suite (109 tests): green.
- No new dependencies without explicit human approval.
