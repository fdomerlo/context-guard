"""F3 acceptance checks for AGENTS.md (PLAN.md 0.7 / 0.4: <100 lines, the
only contract the agent loads, extended with the phase table and the
cg approve flow)."""

import os
import re
import unittest

AGENTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "AGENTS.md"
)

SPANISH_INDICATORS = ["á", "é", "í", "ó", "ú", "ñ", "¿", "¡"]


class TestAgentsMd(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(AGENTS_PATH), "AGENTS.md is missing")
        with open(AGENTS_PATH, "r", encoding="utf-8") as f:
            self.text = f.read()
        self.lines = self.text.splitlines()

    def test_under_100_lines(self):
        self.assertLessEqual(
            len(self.lines), 100,
            f"AGENTS.md has {len(self.lines)} lines, PLAN.md 0.7 caps it at 100",
        )

    def test_is_english(self):
        spanish_count = sum(self.text.lower().count(c) for c in SPANISH_INDICATORS)
        self.assertLessEqual(spanish_count, 5, "AGENTS.md must be in English (PLAN.md 0.2)")

    def test_documents_all_three_phases(self):
        for phase in ("PLAN", "EXECUTE", "VERIFY"):
            self.assertIn(phase, self.text, f"AGENTS.md must document the {phase} phase")

    def test_documents_approve_flow(self):
        self.assertIn(
            "cg approve", self.text,
            "AGENTS.md must reference the cg approve step (PLAN.md 0.6 cooperative layer)",
        )

    def test_documents_phases_directory(self):
        self.assertRegex(
            self.text, r"phases/",
            "AGENTS.md should point agents at the ported phases/*.md files",
        )


if __name__ == "__main__":
    unittest.main()
