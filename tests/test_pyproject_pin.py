import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT_PATH = os.path.join(REPO_ROOT, "pyproject.toml")
REQUIREMENTS_PATH = os.path.join(REPO_ROOT, "requirements.txt")


class TestPyprojectPin(unittest.TestCase):
    """Regex-based checks, not a full TOML parse: tomllib needs Python >=3.11
    and this repo supports 3.10, so pulling in a tomli backport just for two
    scalar fields would be an unwarranted new dependency."""

    def setUp(self):
        with open(PYPROJECT_PATH, "r", encoding="utf-8") as f:
            self.text = f.read()

    def test_mcp_dependency_is_upper_bounded(self):
        match = re.search(r'"(mcp[^"]*)"', self.text)
        self.assertIsNotNone(match, "mcp dependency not declared")
        self.assertEqual(
            match.group(1),
            "mcp>=1.0.0,<2.0.0",
            "mcp dependency must be pinned with an upper bound to avoid "
            "an unreviewed breaking major version being installed silently",
        )

    def test_requires_python_floor_is_310(self):
        match = re.search(r'requires-python\s*=\s*"([^"]*)"', self.text)
        self.assertIsNotNone(match, "requires-python not declared")
        self.assertEqual(match.group(1), ">=3.10")

    def test_cg_short_entrypoint_is_declared(self):
        """PLAN.md 0.1: 'cg' is the CLI binary name docs and adapters use,
        alongside the long 'context-guard' entry point."""
        match = re.search(r'^cg\s*=\s*"([^"]*)"', self.text, re.MULTILINE)
        self.assertIsNotNone(match, "cg short entrypoint not declared")
        self.assertEqual(match.group(1), "context_guard.guard.cli:main")


class TestNoStrayRequirementsFile(unittest.TestCase):
    """PLAN.md F7: requirements.txt carried `mcp>=1.0.0` with no upper bound —
    the exact drift F0 fixed in pyproject.toml, surviving unpinned in the file
    next to it, consumed by nothing in this repo (no CI job, no doc, no
    script referenced it). pyproject.toml is the single source of truth;
    anyone installing via requirements.txt would silently get mcp 2.0 the
    day it ships. Deleted rather than pinned, per PLAN.md's own preference —
    a second file to keep in sync is the drift risk, not the fix."""

    def test_requirements_txt_does_not_exist(self):
        self.assertFalse(
            os.path.exists(REQUIREMENTS_PATH),
            "requirements.txt should not exist — pyproject.toml is the "
            "single source of truth for dependencies (PLAN.md F7)",
        )


if __name__ == "__main__":
    unittest.main()
