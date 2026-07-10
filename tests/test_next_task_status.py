"""Tests for cmd_next_task and cmd_status — new P1 commands."""

import os
import sys
import tempfile
import unittest

# Allow importing the guard package from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from guard.commands import (
    cmd_claim,
    cmd_next_task,
    cmd_status,
    cmd_claim_task,
)
from guard.manifest import save_manifest, load_manifest
from guard.paths import get_paths
from guard.errors import EXIT_OK, EXIT_GENERIC


class TestCmdNextTask(unittest.TestCase):
    """Tests for cmd_next_task() — auto-find-and-claim next pending task."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_next_task_")
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _setup_session(self, tasks_content):
        """Create a session with tasks file."""
        p = get_paths("ctx-test")
        os.makedirs(p["base"], exist_ok=True)
        save_manifest("ctx-test", {
            "context_name": "ctx-test",
            "lock": {"held": False},
            "reference_docs": [],
            "files_in_scope": [],
        })
        with open(p["tasks"], "w") as f:
            f.write(tasks_content)
        return p

    def test_next_task_returns_first_pending(self):
        """next-task returns the first unchecked task."""
        self._setup_session(
            "- [x] 1.1 Done task\n"
            "- [ ] 1.2 Pending task\n"
            "- [ ] 1.3 Another pending\n"
        )
        result = cmd_next_task("ctx-test")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|NEXT_TASK|1.2", result.message)
        self.assertIn("Pending task", result.message)

    def test_next_task_skips_claimed(self):
        """next-task skips tasks already claimed by another agent."""
        self._setup_session(
            "- [ ] 1.1 First task\n"
            "- [ ] 1.2 Second task\n"
        )
        # Claim first task manually
        cmd_claim_task("ctx-test", "1.1", agent_id="other-agent")
        result = cmd_next_task("ctx-test")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|NEXT_TASK|1.2", result.message)

    def test_next_task_done_when_all_complete(self):
        """next-task returns DONE when all tasks are checked."""
        self._setup_session(
            "- [x] 1.1 Done task\n"
            "- [x] 1.2 Also done\n"
        )
        result = cmd_next_task("ctx-test")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("DONE|NO_PENDING_TASKS", result.message)

    def test_next_task_picks_wip(self):
        """next-task treats [/] as not done — returns it as next."""
        self._setup_session(
            "- [x] 1.1 Done\n"
            "- [/] 1.2 In progress\n"
            "- [ ] 1.3 Pending\n"
        )
        result = cmd_next_task("ctx-test")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|NEXT_TASK|1.2", result.message)

    def test_next_task_no_session(self):
        """next-task fails gracefully when no session exists."""
        result = cmd_next_task("nonexistent")
        self.assertEqual(result.exit_code, EXIT_GENERIC)
        self.assertIn("FAIL|NO_SESSION", result.message)

    def test_next_task_without_numbered_ids(self):
        """next-task handles tasks without numeric IDs (uses sequential index)."""
        self._setup_session(
            "- [x] Done task\n"
            "- [ ] Pending task without number\n"
        )
        result = cmd_next_task("ctx-test")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|NEXT_TASK|2", result.message)

    def test_next_task_from_blockers(self):
        """next-task also reads from blockers_todo.md."""
        p = get_paths("ctx-test")
        os.makedirs(p["base"], exist_ok=True)
        save_manifest("ctx-test", {
            "context_name": "ctx-test",
            "lock": {"held": False},
        })
        with open(p["blockers"], "w") as f:
            f.write("- [x] Fixed blocker\n- [ ] Open blocker\n")
        result = cmd_next_task("ctx-test")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|NEXT_TASK", result.message)
        self.assertIn("Open blocker", result.message)


class TestCmdStatus(unittest.TestCase):
    """Tests for cmd_status() — one-shot context summary."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_status_")
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _setup_session(self, tasks_content="- [ ] Task 1\n",
                       objective="Build the thing."):
        """Create a full session with objective, snapshot, and tasks."""
        p = get_paths("ctx-test")
        os.makedirs(p["base"], exist_ok=True)
        save_manifest("ctx-test", {
            "context_name": "ctx-test",
            "lock": {"held": False},
            "reference_docs": [],
            "files_in_scope": [],
        })
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write(f"# Objective\n{objective}\n")
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot\nCurrent state.\n")
        with open(p["tasks"], "w") as f:
            f.write(tasks_content)
        return p

    def test_status_shows_context(self):
        """status output contains the context name."""
        self._setup_session()
        result = cmd_status("ctx-test")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("CONTEXT: ctx-test", result.message)

    def test_status_shows_objective(self):
        """status output contains the objective summary."""
        self._setup_session(objective="Implement OAuth2 login flow.")
        result = cmd_status("ctx-test")
        self.assertIn("OBJECTIVE: Implement OAuth2 login flow.", result.message)

    def test_status_shows_progress(self):
        """status output contains progress metrics."""
        self._setup_session(
            "- [x] Done\n- [ ] Pending\n- [ ] Also pending\n"
        )
        result = cmd_status("ctx-test")
        self.assertIn("PROGRESS: 1/3 tasks complete", result.message)

    def test_status_shows_next_task(self):
        """status output contains the next pending task."""
        self._setup_session(
            "- [x] 1.1 Done\n- [ ] 1.2 Next thing\n"
        )
        result = cmd_status("ctx-test")
        self.assertIn("NEXT: 1.2 -", result.message)

    def test_status_shows_lock_free(self):
        """status shows LOCK: FREE when no lock held."""
        self._setup_session()
        result = cmd_status("ctx-test")
        self.assertIn("LOCK: FREE", result.message)

    def test_status_shows_lock_held(self):
        """status shows LOCK: HELD when lock is active."""
        p = self._setup_session()
        m = load_manifest("ctx-test")
        m["lock"] = {"held": True, "acquired_by": "agent-X"}
        save_manifest("ctx-test", m)
        result = cmd_status("ctx-test")
        self.assertIn("LOCK: HELD by agent-X", result.message)

    def test_status_no_session(self):
        """status fails gracefully when no session exists."""
        result = cmd_status("nonexistent")
        self.assertEqual(result.exit_code, EXIT_GENERIC)
        self.assertIn("FAIL|NO_SESSION", result.message)

    def test_status_no_next_when_all_done(self):
        """status shows NEXT: (none) when all tasks complete."""
        self._setup_session("- [x] Done\n- [x] Also done\n")
        result = cmd_status("ctx-test")
        self.assertIn("NEXT: (none)", result.message)


if __name__ == "__main__":
    unittest.main()
