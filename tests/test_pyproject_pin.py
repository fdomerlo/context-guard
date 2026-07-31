import os
import re
import unittest

PYPROJECT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml"
)


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


if __name__ == "__main__":
    unittest.main()
