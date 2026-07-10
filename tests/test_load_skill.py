"""Tests for cmd_load_skill."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from guard.commands import cmd_load_skill
from guard.errors import EXIT_OK, EXIT_GENERIC

class TestCmdLoadSkill(unittest.TestCase):
    def test_load_skill_success(self):
        """It should load existing skill content."""
        # review.md should exist in references/
        result = cmd_load_skill("review")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("Review", result.message)
        
    def test_load_skill_not_found(self):
        """It should fail gracefully if skill doesn't exist."""
        result = cmd_load_skill("nonexistent_skill")
        self.assertEqual(result.exit_code, EXIT_GENERIC)
        self.assertIn("FAIL|SKILL_NOT_FOUND|nonexistent_skill", result.message)
        
    def test_load_skill_invalid_path(self):
        """It should reject traversal attempts."""
        result = cmd_load_skill("../SKILL")
        self.assertEqual(result.exit_code, EXIT_GENERIC)
        self.assertIn("FAIL|INVALID_SKILL_NAME", result.message)

if __name__ == "__main__":
    unittest.main()
