"""F5: PLAN.md 0.1 decided the major bump communicates the merge (2.0.0), and
F5 asks for a CHANGELOG entry citing it. Historical 1.x entries were
originally left in Spanish as a historical record, not a live artifact — F8
8.1.3 overrode that judgment call explicitly ("CHANGELOG.md íntegramente en
inglés") and had them translated. `test_historical_entries_are_untouched`
checks the sections were translated, not deleted or reworded beyond that.

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
        section = self._section("2.0.0")
        spanish_count = sum(section.lower().count(c) for c in SPANISH_INDICATORS)
        self.assertLessEqual(spanish_count, 3, "the 2.0.0 CHANGELOG entry must be in English")

    def test_historical_entries_are_untouched(self):
        """Translated in F8, but the sections themselves — same versions,
        same facts — must still be there afterward, not dropped."""
        self._section("1.2.0")
        self._section("1.1.0")
        self._section("1.0.0")

    def test_whole_file_is_english(self):
        """PLAN.md F8 8.1.3: 'CHANGELOG.md íntegramente en inglés' — F8
        explicitly overrides F5's "historical entries stay as written"
        judgment call for this one file. Header and 1.x entries included,
        not just the 2.0.0 section checked above."""
        spanish_count = sum(self.text.lower().count(c) for c in SPANISH_INDICATORS)
        self.assertLessEqual(spanish_count, 3, "CHANGELOG.md must be entirely in English (PLAN.md F8 8.1.3)")


if __name__ == "__main__":
    unittest.main()
