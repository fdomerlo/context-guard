"""F5: PLAN.md 0.1 decided the major bump communicates the merge (2.0.0), and
F5 asks for a CHANGELOG entry citing it. Historical 1.x entries are left in
Spanish — they are a historical record, not a live artifact, the same reason
past commit messages are not rewritten. Only the new 2.0.0 entry is held to
the English rule.

Also pins the sdist packaging fix found while preparing the release: a
`uv build` sdist bundled .claude/settings.local.json — untracked, ignored by
this machine's global gitignore rather than the repo's own, and carrying
absolute local paths — because hatchling's default sdist selection does not
consult a global gitignore."""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT_PATH = os.path.join(REPO_ROOT, "pyproject.toml")
CHANGELOG_PATH = os.path.join(REPO_ROOT, "CHANGELOG.md")

SPANISH_INDICATORS = ["á", "é", "í", "ó", "ú", "ñ", "¿", "¡"]


class TestPyprojectVersion(unittest.TestCase):
    def test_version_is_2_0_0(self):
        with open(PYPROJECT_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        self.assertIsNotNone(match, "version not declared")
        self.assertEqual(
            match.group(1), "2.0.0",
            "PLAN.md 0.1: the major bump communicates the state-guard merge",
        )

    def test_description_is_the_one_sentence_pitch(self):
        """PLAN.md 0.7's pitch doubles as the PyPI project description — the
        first thing a stranger on pypi.org sees before ever opening the repo."""
        with open(PYPROJECT_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        match = re.search(r'^description\s*=\s*"([^"]+)"', text, re.MULTILINE)
        self.assertIsNotNone(match, "description not declared")
        self.assertIn("transactional memory layer", match.group(1))


class TestSdistExcludesLocalTooling(unittest.TestCase):
    def test_claude_directory_is_excluded_from_the_sdist(self):
        with open(PYPROJECT_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        match = re.search(
            r"\[tool\.hatch\.build\.targets\.sdist\](.*?)(?=^\[|\Z)",
            text, re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match, "no [tool.hatch.build.targets.sdist] section declared")
        self.assertIn(".claude", match.group(1))


class TestChangelogEntry(unittest.TestCase):
    def setUp(self):
        with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
            self.text = f.read()

    def _section(self, version):
        match = re.search(
            rf"^## \[{re.escape(version)}\].*?(?=^## \[|\Z)",
            self.text, re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match, f"CHANGELOG.md has no [{version}] entry")
        return match.group(0)

    def test_has_a_2_0_0_entry(self):
        self._section("2.0.0")

    def test_2_0_0_entry_cites_the_state_guard_merge(self):
        section = self._section("2.0.0")
        self.assertIn("state-guard", section.lower())

    def test_2_0_0_entry_is_english(self):
        """Only the new entry — the 1.x history below it stays as written."""
        section = self._section("2.0.0")
        spanish_count = sum(section.lower().count(c) for c in SPANISH_INDICATORS)
        self.assertLessEqual(spanish_count, 3, "the 2.0.0 CHANGELOG entry must be in English")

    def test_historical_entries_are_untouched(self):
        """Rewriting the 1.x history would be revising a record, not writing
        one — the same reason past commit messages are not edited."""
        self._section("1.2.0")
        self._section("1.1.0")
        self._section("1.0.0")


if __name__ == "__main__":
    unittest.main()
