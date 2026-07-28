"""Tests for guard.commands.cmd_archive — archival workflow."""

import os
import sys
import tempfile
import unittest

# Allow importing the context_guard package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.commands import cmd_archive, cmd_check_completion
from context_guard.guard.manifest import save_manifest
from context_guard.guard.paths import get_paths, MAX_ARTIFACT_CHARS
from context_guard.guard.errors import EXIT_OK, EXIT_VALIDATION, ValidationError


class TestArchiveSuccess(unittest.TestCase):
    """Tests for successful archive operations."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_archive_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _setup_complete_session(self, context=None):
        """Create a fully valid, completed session with all required artifacts."""
        if context is None:
            context = self._tmpdir
        p = get_paths(context)
        os.makedirs(p["base"], exist_ok=True)

        # Create manifest
        save_manifest(context, {
            "context_name": context,
            "lock": {"held": False},
            "reference_docs": [],
            "files_in_scope": [],
        })

        # Create required artifacts
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective\nTest objective for archive.")

        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot\nCurrent state snapshot.")

        # Create tasks file with all tasks complete
        with open(p["tasks"], "w") as f:
            f.write("- [x] Task 1\n- [x] Task 2\n- [x] Task 3\n")

        return p

    def test_successful_archive(self):
        """Archive succeeds when all tasks are complete and artifacts valid."""
        p = self._setup_complete_session(self._tmpdir)

        result = cmd_archive(self._tmpdir)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|ARCHIVED", result.message)

        # Archive directory should exist with files
        archive_base = p["archive"]
        self.assertTrue(os.path.exists(archive_base))
        archive_dirs = os.listdir(archive_base)
        self.assertEqual(len(archive_dirs), 1)

        archive_dir = os.path.join(archive_base, archive_dirs[0])
        archived_files = os.listdir(archive_dir)
        self.assertIn("objective.md", archived_files)
        self.assertIn("snapshot.md", archived_files)
        self.assertIn("tasks.md", archived_files)

    def test_session_cleaned_after_archive(self):
        """Original session directory should be cleaned after archive."""
        p = self._setup_complete_session(self._tmpdir)

        cmd_archive(self._tmpdir)

        # Active session files (e.g. manifest) should be removed
        self.assertFalse(os.path.exists(p["manifest"]), "Session manifest should be deleted")



class TestArchiveBlocked(unittest.TestCase):
    """Tests for archive blocked by incomplete tasks."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_archive_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_blocked_by_incomplete_tasks(self):
        """Archive fails when tasks are not all complete."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)

        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
        })

        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective")
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot")
        with open(p["tasks"], "w") as f:
            f.write("- [x] Done task\n- [ ] Pending task\n")

        result = cmd_archive(self.context)
        self.assertEqual(result.exit_code, EXIT_VALIDATION)
        self.assertIn("FAIL|ARCHIVE_BLOCKED|tasks_incomplete", result.message)

    def test_blocked_when_no_tasks(self):
        """Archive fails when there are no task files (total=0 → all_complete=false)."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)

        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
        })

        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective")
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot")

        result = cmd_archive(self.context)
        self.assertEqual(result.exit_code, EXIT_VALIDATION)
        self.assertIn("FAIL|ARCHIVE_BLOCKED", result.message)



class TestArchiveValidationFailure(unittest.TestCase):
    """Tests for archive blocked by validation failures."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_archive_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_validation_fails_missing_objective(self):
        """Archive fails when objective.md is missing (validation)."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)

        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
        })

        # No objective.md, but have snapshot and complete tasks
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot")
        with open(p["tasks"], "w") as f:
            f.write("- [x] Done task\n")

        with self.assertRaises(ValidationError) as ctx:
            cmd_archive(self.context)
        self.assertIn("MISSING|objective.md", ctx.exception.message)

    def test_validation_fails_missing_snapshot(self):
        """Archive fails when snapshot.md is missing (validation)."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)

        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
        })

        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective")
        # No snapshot.md
        with open(p["tasks"], "w") as f:
            f.write("- [x] Done task\n")

        with self.assertRaises(ValidationError) as ctx:
            cmd_archive(self.context)
        self.assertIn("MISSING|snapshot.md", ctx.exception.message)

    def test_validation_fails_artifact_too_long(self):
        """Archive fails when an artifact exceeds MAX_ARTIFACT_CHARS."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)

        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
        })

        # Write an artifact that is too long
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("x" * (MAX_ARTIFACT_CHARS + 1))
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot")
        with open(p["tasks"], "w") as f:
            f.write("- [x] Done\n")

        with self.assertRaises(ValidationError) as ctx:
            cmd_archive(self.context)
        self.assertIn("TOO_LONG|objective.md", ctx.exception.message)

    def test_validation_fails_no_task_files(self):
        """Archive validation fails when neither blockers nor tasks exist."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)

        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
        })

        # Only required files, no task files at all — but tasks are "incomplete"
        # so archive is blocked before validation
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective")
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot")

        # This should fail at the completion check, not validation
        result = cmd_archive(self.context)
        self.assertEqual(result.exit_code, EXIT_VALIDATION)
        self.assertIn("FAIL|ARCHIVE_BLOCKED", result.message)


if __name__ == "__main__":
    unittest.main()
