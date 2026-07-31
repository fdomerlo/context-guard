"""F5: PLAN.md 0.7 lists LICENSE (MIT) in the repo tree, and a `uv publish`
with no declared license leaves the package legally ambiguous on day one."""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LICENSE_PATH = os.path.join(REPO_ROOT, "LICENSE")
PYPROJECT_PATH = os.path.join(REPO_ROOT, "pyproject.toml")


class TestLicense(unittest.TestCase):
    def test_license_file_exists_and_is_mit(self):
        self.assertTrue(os.path.exists(LICENSE_PATH), "LICENSE is missing")
        with open(LICENSE_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("MIT License", text)
        self.assertRegex(text, r"Copyright \(c\) \d{4}", "LICENSE must carry a copyright year")

    def test_pyproject_declares_the_license(self):
        with open(PYPROJECT_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        match = re.search(r'license\s*=\s*"([^"]+)"', text)
        self.assertIsNotNone(match, "pyproject.toml must declare license = \"MIT\"")
        self.assertEqual(match.group(1), "MIT")


if __name__ == "__main__":
    unittest.main()
