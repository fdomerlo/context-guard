"""Tests for guard.commands — business logic for CLI commands."""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

# Allow importing the context_guard package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.commands import (
    cmd_check_lock,
    cmd_claim,
    cmd_release,
    cmd_claim_task,
    cmd_release_task,
)
from context_guard.guard.manifest import save_manifest, load_manifest
from context_guard.guard.paths import get_paths
from context_guard.guard.errors import (
    EXIT_OK,
    EXIT_LOCK_HELD,
    EXIT_GENERIC,
    EXIT_VALIDATION,
)


class TestCmdCheckLock(unittest.TestCase):
    """Tests for cmd_check_lock()."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_commands_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_free_when_no_manifest(self):
        """check_lock returns FREE when no manifest exists."""
        result = cmd_check_lock(self.context)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertEqual(result.message, "FREE")

    def test_free_when_lock_not_held(self):
        """check_lock returns FREE when manifest exists but lock not held."""
        p = get_paths(self.context)
        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
        })
        result = cmd_check_lock(self.context)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertEqual(result.message, "FREE")

    def test_active_state(self):
        """check_lock returns ACTIVE when lock is held and within TTL."""
        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {
                "held": True,
                "acquired_at": datetime.now().isoformat(),
                "acquired_by": "agent-1",
                "ttl_seconds": 1800,
            },
        })
        result = cmd_check_lock(self.context)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertTrue(result.message.startswith("ACTIVE|"))
        self.assertIn("agent-1", result.message)

    def test_stale_state(self):
        """check_lock returns STALE when lock TTL has expired."""
        past = (datetime.now() - timedelta(seconds=100)).isoformat()
        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {
                "held": True,
                "acquired_at": past,
                "acquired_by": "agent-1",
                "ttl_seconds": 10,
            },
        })
        result = cmd_check_lock(self.context)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertTrue(result.message.startswith("STALE|"))

    def test_free_when_empty_lock(self):
        """check_lock returns FREE when lock dict is empty."""
        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {},
        })
        result = cmd_check_lock(self.context)
        self.assertEqual(result.message, "FREE")


class TestCmdClaimReleaseCycle(unittest.TestCase):
    """Tests for cmd_claim() and cmd_release() — session lifecycle."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_commands_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_claim_success(self):
        """cmd_claim succeeds on a fresh context."""
        result = cmd_claim(self.context, ttl=1800)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|LOCK_ACQUIRED", result.message)

    def test_claim_fails_when_held(self):
        """cmd_claim fails when lock is already held."""
        cmd_claim(self.context, ttl=1800)
        result = cmd_claim(self.context, ttl=1800)
        self.assertEqual(result.exit_code, EXIT_LOCK_HELD)
        self.assertIn("FAIL|LOCK_HELD", result.message)

    def _claim_and_get_owner(self):
        """Claim the session lock and return the agent_id that now owns it."""
        cmd_claim(self.context, ttl=1800)
        return load_manifest(self.context)["lock"]["acquired_by"]

    def test_release_success(self):
        """cmd_release successfully releases a lock held by the same agent."""
        owner = self._claim_and_get_owner()
        result = cmd_release(self.context, agent_id=owner)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|LOCK_RELEASED", result.message)

        # After release, lock should be FREE
        check = cmd_check_lock(self.context)
        self.assertEqual(check.message, "FREE")

    def test_release_then_claim_again(self):
        """After release, a new claim should succeed."""
        owner = self._claim_and_get_owner()
        cmd_release(self.context, agent_id=owner)
        result = cmd_claim(self.context, ttl=1800)
        self.assertEqual(result.exit_code, EXIT_OK)

    def test_release_when_no_session(self):
        """cmd_release on a non-existent session succeeds for the owner path:
        there is no lock metadata to contradict the caller."""
        result = cmd_release(self.context, agent_id="agent-A")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|LOCK_RELEASED", result.message)

    def test_release_requires_identity(self):
        """An anonymous release is refused — ownership that is only checked
        when the caller volunteers its id is not ownership."""
        self._claim_and_get_owner()
        result = cmd_release(self.context)
        self.assertEqual(result.exit_code, EXIT_VALIDATION)
        self.assertIn("FAIL|AGENT_ID_REQUIRED", result.message)


class TestCmdTaskClaimRelease(unittest.TestCase):
    """Tests for cmd_claim_task() and cmd_release_task() — task locking."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_commands_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir
        # Create a session first so task operations work
        cmd_claim(self.context, ttl=1800)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_claim_task_success(self):
        """cmd_claim_task succeeds for an unclaimed task."""
        result = cmd_claim_task(self.context, "task-1", agent_id="agent-A")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|TASK_CLAIMED|task-1", result.message)

    def test_claim_task_already_claimed(self):
        """cmd_claim_task fails when task is already claimed."""
        cmd_claim_task(self.context, "task-1", agent_id="agent-A")
        result = cmd_claim_task(self.context, "task-1", agent_id="agent-B")
        self.assertEqual(result.exit_code, EXIT_LOCK_HELD)
        self.assertIn("FAIL|TASK_CLAIMED|agent-A", result.message)

    def test_release_task_success(self):
        """cmd_release_task succeeds for own task."""
        cmd_claim_task(self.context, "task-1", agent_id="agent-A")
        result = cmd_release_task(self.context, "task-1", agent_id="agent-A")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|TASK_RELEASED|task-1", result.message)

    def test_release_task_ownership_mismatch(self):
        """cmd_release_task fails when agent_id doesn't match owner."""
        cmd_claim_task(self.context, "task-1", agent_id="agent-A")
        result = cmd_release_task(self.context, "task-1", agent_id="agent-B")
        self.assertEqual(result.exit_code, EXIT_LOCK_HELD)
        self.assertIn("FAIL|OWNERSHIP_MISMATCH", result.message)

    def test_release_task_force_bypasses_ownership(self):
        """cmd_release_task with force=True bypasses ownership validation."""
        cmd_claim_task(self.context, "task-1", agent_id="agent-A")
        result = cmd_release_task(self.context, "task-1", agent_id="agent-B", force=True)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|TASK_RELEASED|task-1", result.message)

    def test_release_unclaimed_task(self):
        """cmd_release_task fails for a task that is not claimed."""
        result = cmd_release_task(self.context, "task-999")
        self.assertEqual(result.exit_code, EXIT_LOCK_HELD)
        self.assertIn("FAIL|TASK_NOT_CLAIMED", result.message)

    def test_claim_task_no_session_fails(self):
        """cmd_claim_task fails when no session manifest exists."""
        # Release and clean up the session
        owner = load_manifest(self.context)["lock"]["acquired_by"]
        cmd_release(self.context, agent_id=owner)
        p = get_paths(self.context)
        if os.path.exists(p["manifest"]):
            os.remove(p["manifest"])

        result = cmd_claim_task(self.context, "task-1")
        self.assertEqual(result.exit_code, EXIT_GENERIC)
        self.assertIn("FAIL|NO_SESSION", result.message)

    def test_task_claim_release_reclaim_cycle(self):
        """A released task can be reclaimed by another agent."""
        cmd_claim_task(self.context, "task-1", agent_id="agent-A")
        cmd_release_task(self.context, "task-1", agent_id="agent-A")
        # Task status is now "done", not "claimed", so re-claiming should work
        result = cmd_claim_task(self.context, "task-1", agent_id="agent-B")
        self.assertEqual(result.exit_code, EXIT_OK)


if __name__ == "__main__":
    unittest.main()
