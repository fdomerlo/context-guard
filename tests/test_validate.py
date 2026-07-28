"""Tests for cmd_validate."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.commands import cmd_validate
from context_guard.guard.errors import EXIT_OK, ValidationError
from context_guard.guard.paths import get_paths

class TestCmdValidate(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_validate_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir
        self.p = get_paths(self.context)
        os.makedirs(self.p["base"], exist_ok=True)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_file(self, fname, content):
        with open(os.path.join(self.p["base"], fname), "w", encoding="utf-8") as f:
            f.write(content)

    def test_validate_success(self):
        self._write_file("objective.md", "English text")
        self._write_file("snapshot.md", "More english text")
        self._write_file("tasks.md", "- [ ] Task 1")
        
        result = cmd_validate(self.context)
        self.assertEqual(result.exit_code, EXIT_OK)
        
    def test_validate_max_length(self):
        self._write_file("objective.md", "x" * 150)
        self._write_file("snapshot.md", "English")
        self._write_file("tasks.md", "English")
        
        with self.assertRaises(ValidationError) as ctx:
            cmd_validate(self.context, max_length=100)
        self.assertIn("TOO_LONG|objective.md", ctx.exception.message)
        
    def test_validate_spanish_detected(self):
        self._write_file("objective.md", "Este es un texto en español con á é í ó ú.")
        self._write_file("snapshot.md", "English")
        self._write_file("tasks.md", "English")
        
        with self.assertRaises(ValidationError) as ctx:
            cmd_validate(self.context)
        self.assertIn("LANGUAGE_BOUNDARY|objective.md", ctx.exception.message)

if __name__ == "__main__":
    unittest.main()
