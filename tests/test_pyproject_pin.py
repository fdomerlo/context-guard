import os
import sys
import unittest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

PYPROJECT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml"
)


class TestPyprojectPin(unittest.TestCase):
    def setUp(self):
        with open(PYPROJECT_PATH, "rb") as f:
            self.data = tomllib.load(f)

    def test_mcp_dependency_is_upper_bounded(self):
        deps = self.data["project"]["dependencies"]
        mcp_dep = next((d for d in deps if d.startswith("mcp")), None)
        self.assertIsNotNone(mcp_dep, "mcp dependency not declared")
        self.assertEqual(
            mcp_dep,
            "mcp>=1.0.0,<2.0.0",
            "mcp dependency must be pinned with an upper bound to avoid "
            "an unreviewed breaking major version being installed silently",
        )

    def test_requires_python_floor_is_310(self):
        self.assertEqual(
            self.data["project"]["requires-python"],
            ">=3.10",
        )


if __name__ == "__main__":
    unittest.main()
