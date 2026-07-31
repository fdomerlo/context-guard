"""F3 acceptance checks for phases/{plan,execute,verify}.md — ported from
state-guard's phases/*.md (PLAN.md 1.3/2 F3), translated to English, trimmed
to ~4-5KB, with the crypto gate replaced by cg approve and no duplication of
templates the code already scaffolds (transaction.py:_scaffold_artifacts)."""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHASES_DIR = os.path.join(REPO_ROOT, "phases")

SPANISH_INDICATORS = ["á", "é", "í", "ó", "ú", "ñ", "¿", "¡"]

# What transaction.py:_scaffold_artifacts writes verbatim as placeholder
# content. A ported phase file re-stating these word for word would be the
# "duplicated scaffolding" PLAN.md F3 explicitly says to cut.
SCAFFOLD_PLACEHOLDERS = [
    "[PENDING] Define objective here",
    "[PENDING] Define snapshot here",
    "[PENDING] Define tasks here",
    "[PENDING] Write static review here",
    "[PENDING] Write dynamic verification here",
]

PHASE_FILES = {
    "plan.md": "PLAN",
    "execute.md": "EXECUTE",
    "verify.md": "VERIFY",
}


class TestPhaseDocs(unittest.TestCase):
    def _read(self, name):
        path = os.path.join(PHASES_DIR, name)
        self.assertTrue(os.path.exists(path), f"phases/{name} is missing")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_all_three_phase_files_exist(self):
        for name in PHASE_FILES:
            self.assertTrue(
                os.path.exists(os.path.join(PHASES_DIR, name)),
                f"phases/{name} is missing",
            )

    def test_phases_are_english(self):
        for name in PHASE_FILES:
            text = self._read(name)
            spanish_count = sum(text.lower().count(c) for c in SPANISH_INDICATORS)
            self.assertLessEqual(
                spanish_count, 5, f"phases/{name} must be in English (PLAN.md 0.2)"
            )

    def test_phases_are_within_size_band(self):
        # PLAN.md F3: "~4-5KB c/u". Leave headroom (2-7KB) since ported prose
        # never lands exactly on a byte estimate from a design doc.
        for name in PHASE_FILES:
            text = self._read(name)
            size = len(text.encode("utf-8"))
            self.assertGreaterEqual(size, 2000, f"phases/{name} is suspiciously thin ({size}B)")
            self.assertLessEqual(size, 7000, f"phases/{name} exceeds the ~4-5KB budget ({size}B)")

    def test_phases_mention_pending_marker(self):
        # Only plan.md and verify.md gate on [PENDING] (transaction.py's
        # PLAN->EXECUTE and VERIFY->ARCHIVE hard gates); execute.md has no
        # such check, so requiring the marker there would be padding.
        for name in ("plan.md", "verify.md"):
            text = self._read(name)
            self.assertIn("[PENDING]", text, f"phases/{name} must reference the [PENDING] marker")

    def test_plan_references_cg_approve(self):
        text = self._read("plan.md")
        self.assertIn("cg approve", text)

    def test_plan_does_not_reference_dead_crypto_gate(self):
        text = self._read("plan.md").lower()
        for dead_term in ("/dev/tty", "sha-256", "plan-confirm", "plan-approve"):
            self.assertNotIn(
                dead_term, text,
                f"phases/plan.md still references the dead crypto gate ('{dead_term}'), "
                "which PLAN.md 0.4 replaces with cg approve",
            )

    def test_phases_do_not_duplicate_scaffold_templates(self):
        for name in PHASE_FILES:
            text = self._read(name)
            for placeholder in SCAFFOLD_PLACEHOLDERS:
                self.assertNotIn(
                    placeholder, text,
                    f"phases/{name} duplicates a template transaction.py already scaffolds",
                )

    def test_phases_use_uppercase_phase_names(self):
        # state-guard used lowercase phase names (plan/execute/verify); this
        # repo's DAG (transaction.py:TRANSITIONS) uses uppercase.
        for name, phase_name in PHASE_FILES.items():
            text = self._read(name)
            self.assertIn(phase_name, text, f"phases/{name} should reference phase {phase_name}")

    def test_phases_do_not_reference_state_guard_paths(self):
        for name in PHASE_FILES:
            text = self._read(name)
            self.assertNotIn(".state-guard/", text, f"phases/{name} still points at the old .state-guard/ layout")
            self.assertNotIn("state_manager.py", text, f"phases/{name} still invokes state-guard's middleware directly")

    def test_verify_covers_archive_step(self):
        # PLAN.md 0.7: "archive = paso final de verify, como en state-guard"
        text = self._read("verify.md")
        self.assertIn("ARCHIVE", text)
        self.assertIn("cg archive", text)


if __name__ == "__main__":
    unittest.main()
