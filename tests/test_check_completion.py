"""Tests for guard.commands.cmd_check_completion — deterministic checkbox counting."""

import os
import sys
import tempfile
import unittest

# Allow importing the context_guard package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.commands import cmd_check_completion
from context_guard.guard.paths import get_paths
from context_guard.guard.errors import EXIT_OK


class TestCheckCompletionNoFiles(unittest.TestCase):
    """Tests when no task files exist."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_completion_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_no_files_total_zero(self):
        """No blockers or tasks files → total=0, all_complete=false."""
        result = cmd_check_completion(self.context)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("total=0", result.message)
        self.assertIn("completed=0", result.message)
        self.assertIn("all_complete=false", result.message)




class TestCheckCompletionOnlyTasks(unittest.TestCase):
    """Tests with only tasks.md present."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_completion_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_tasks(self, content):
        p = get_paths(self.context)
        os.makedirs(os.path.dirname(p["tasks"]), exist_ok=True)
        with open(p["tasks"], "w") as f:
            f.write(content)

    def test_all_tasks_complete(self):
        """All tasks checked → all_complete=true."""
        self._write_tasks(
            "# Tasks\n"
            "- [x] Task one\n"
            "- [x] Task two\n"
            "- [x] Task three\n"
        )
        result = cmd_check_completion(self.context)
        self.assertIn("source=tasks.md", result.message)
        self.assertIn("total=3", result.message)
        self.assertIn("completed=3", result.message)
        self.assertIn("all_complete=true", result.message)

    def test_no_tasks_complete(self):
        """All tasks unchecked → completed=0."""
        self._write_tasks(
            "- [ ] Task A\n"
            "- [ ] Task B\n"
        )
        result = cmd_check_completion(self.context)
        self.assertIn("total=2", result.message)
        self.assertIn("completed=0", result.message)
        self.assertIn("all_complete=false", result.message)

    def test_non_checkbox_lines_ignored(self):
        """Non-checkbox lines are not counted."""
        self._write_tasks(
            "# Task List\n"
            "\n"
            "Some description text.\n"
            "- [x] Actual task\n"
            "- Regular list item without checkbox\n"
        )
        result = cmd_check_completion(self.context)
        self.assertIn("total=1", result.message)
        self.assertIn("completed=1", result.message)




class TestCheckCompletionEdgeCases(unittest.TestCase):
    """Edge cases for checkbox parsing."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_completion_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_tasks(self, content):
        p = get_paths(self.context)
        os.makedirs(os.path.dirname(p["tasks"]), exist_ok=True)
        with open(p["tasks"], "w") as f:
            f.write(content)

    def test_uppercase_x(self):
        """Uppercase [X] is treated as complete."""
        self._write_tasks("- [X] Task with uppercase X\n")
        result = cmd_check_completion(self.context)
        self.assertIn("completed=1", result.message)

    def test_indented_checkbox(self):
        """Indented checkboxes are still counted."""
        self._write_tasks("  - [x] Indented task\n    - [ ] Nested task\n")
        result = cmd_check_completion(self.context)
        self.assertIn("total=2", result.message)
        self.assertIn("completed=1", result.message)

    def test_checkbox_with_extra_content(self):
        """Checkbox with detailed content after the marker is parsed."""
        self._write_tasks("- [x] Complex task: with colons and (parens)\n")
        result = cmd_check_completion(self.context)
        self.assertIn("total=1", result.message)
        self.assertIn("completed=1", result.message)


class TestCheckCompletionInProgress(unittest.TestCase):
    """Tests for [/] in-progress marker support."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_completion_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_tasks(self, content):
        p = get_paths(self.context)
        os.makedirs(os.path.dirname(p["tasks"]), exist_ok=True)
        with open(p["tasks"], "w") as f:
            f.write(content)

    def test_in_progress_counted_as_incomplete(self):
        """[/] tasks are counted in total but NOT in completed."""
        self._write_tasks(
            "- [x] Done task\n"
            "- [/] In progress task\n"
            "- [ ] Pending task\n"
        )
        result = cmd_check_completion(self.context)
        self.assertIn("total=3", result.message)
        self.assertIn("completed=1", result.message)
        self.assertIn("all_complete=false", result.message)

    def test_all_in_progress_not_complete(self):
        """All [/] tasks → total > 0, completed = 0."""
        self._write_tasks("- [/] WIP 1\n- [/] WIP 2\n")
        result = cmd_check_completion(self.context)
        self.assertIn("total=2", result.message)
        self.assertIn("completed=0", result.message)
        self.assertIn("all_complete=false", result.message)

    def test_mixed_states(self):
        """Mix of [x], [/], [ ] correctly counted."""
        self._write_tasks(
            "- [x] Done\n"
            "- [/] WIP\n"
            "- [ ] Todo\n"
            "- [X] Also done\n"
        )
        result = cmd_check_completion(self.context)
        self.assertIn("total=4", result.message)
        self.assertIn("completed=2", result.message)


if __name__ == "__main__":
    unittest.main()
