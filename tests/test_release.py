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
    def test_version_is_2_5_0(self):
        """A minor bump: Cursor adapter and unified Gemini config path.
        Additive, nothing removed from the public surface. Pinned here so
        the release tag and the CHANGELOG cannot drift from what actually ships."""
        with open(PYPROJECT_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        self.assertIsNotNone(match, "version not declared")
        self.assertEqual(match.group(1), "2.6.0")

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


class TestTwoPointOneEntry(unittest.TestCase):
    """PLAN-2.1 F3 point 2 dictates the entry's content, because a CHANGELOG
    that omits a removal is how a user discovers it from a traceback."""

    def setUp(self):
        with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
            self.text = f.read()
        match = re.search(
            r"^## \[2\.1\.0\].*?(?=^## \[|\Z)",
            self.text, re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match, "CHANGELOG.md has no [2.1.0] entry")
        self.section = match.group(0)

    def test_the_entry_is_dated(self):
        self.assertRegex(self.section, r"^## \[2\.1\.0\] - \d{4}-\d{2}-\d{2}")

    def test_nothing_is_left_under_unreleased(self):
        """The 2.1.0 work sat under Unreleased while the cycle ran. Shipping
        with both headings present leaves a reader unsure which one describes
        the version they installed."""
        match = re.search(
            r"^## \[Unreleased\](.*?)(?=^## \[|\Z)",
            self.text, re.MULTILINE | re.DOTALL,
        )
        if match:
            self.assertEqual(
                match.group(1).strip(), "",
                "the Unreleased section still carries entries that shipped in 2.1.0",
            )

    def test_it_announces_cg_setup_and_the_packaged_data(self):
        self.assertIn("cg setup", self.section)
        self.assertIn("package", self.section.lower())

    def test_it_records_the_removal_with_a_migration_line(self):
        """F3 point 2 asks for the migration line by name. "Removed X" without
        "do Y instead" is a dead end for whoever hits it."""
        self.assertIn("Removed", self.section)
        self.assertRegex(self.section, r"install\.sh")
        # Whitespace-tolerant: the phrase wraps across lines in the file,
        # and where the line break falls is not the requirement.
        self.assertRegex(self.section, r"[Rr]un\s+`cg setup`\s+instead")

    def test_it_records_that_cg_new_scaffolds_the_phases(self):
        self.assertIn("cg new", self.section)


class TestTwoPointTwoEntry(unittest.TestCase):
    """PLAN-2.2 F3: the CHANGELOG entry for the Antigravity discovery-parity
    cycle. Same shape as TestTwoPointOneEntry — dated, nothing orphaned under
    Unreleased, and the entry's content actually names what shipped, so a
    reader upgrading does not have to read the diff to find out."""

    def setUp(self):
        with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
            self.text = f.read()
        match = re.search(
            r"^## \[2\.2\.0\].*?(?=^## \[|\Z)",
            self.text, re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match, "CHANGELOG.md has no [2.2.0] entry")
        self.section = match.group(0)

    def test_the_entry_is_dated(self):
        self.assertRegex(self.section, r"^## \[2\.2\.0\] - \d{4}-\d{2}-\d{2}")

    def test_nothing_is_left_under_unreleased(self):
        match = re.search(
            r"^## \[Unreleased\](.*?)(?=^## \[|\Z)",
            self.text, re.MULTILINE | re.DOTALL,
        )
        if match:
            self.assertEqual(
                match.group(1).strip(), "",
                "the Unreleased section still carries entries that shipped in 2.2.0",
            )

    def test_it_announces_the_antigravity_discovery_skill(self):
        """The headline of this cycle: dogfooding found Antigravity never
        raised the protocol in a fresh project, because it only got the
        enforcement hook, never anything discoverable."""
        self.assertIn("skill", self.section.lower())
        self.assertIn("Antigravity", self.section)

    def test_it_records_the_agy_detection_fix(self):
        self.assertIn("agy", self.section)

    def test_it_records_the_install_docs_fix(self):
        self.assertIn("uv tool install", self.section)

    def test_it_records_verify_completion(self):
        self.assertIn("VERIFY.md", self.section)


if __name__ == "__main__":
    unittest.main()
