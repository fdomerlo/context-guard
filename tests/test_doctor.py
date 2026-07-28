"""Tests for cmd_doctor — diagnostic health check command."""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

# Allow importing the guard package from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from guard.commands import cmd_doctor
from guard.manifest import save_manifest
from guard.paths import get_paths, MAX_ARTIFACT_CHARS
from guard.errors import EXIT_OK, EXIT_GENERIC


class TestDoctorHealthy(unittest.TestCase):
    """Tests for doctor on a healthy session."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_doctor_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _setup_healthy_session(self):
        """Create a fully healthy session."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
            "reference_docs": [],
            "files_in_scope": [],
        })
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective\nBuild OAuth2 login flow.\n")
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot\nNode.js project with Express.\n")
        with open(p["tasks"], "w") as f:
            f.write("- [x] 1.1 Setup auth module\n- [ ] 1.2 Add token refresh\n")
        return p

    def test_healthy_session_all_ok(self):
        """Doctor reports all OK on a healthy session."""
        self._setup_healthy_session()
        result = cmd_doctor(self.context)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("OK: manifest.json is valid", result.message)
        self.assertIn("OK: objective.md exists", result.message)
        self.assertIn("OK: snapshot.md exists", result.message)
        self.assertIn("OK: tasks.md exists", result.message)
        self.assertIn("OK: Session lock is FREE", result.message)


class TestDoctorMissingArtifacts(unittest.TestCase):
    """Tests for doctor detecting missing artifacts."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_doctor_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_no_session(self):
        """Doctor reports error when no session exists."""
        result = cmd_doctor("nonexistent")
        self.assertEqual(result.exit_code, EXIT_GENERIC)
        self.assertIn("ERROR: No session found", result.message)

    def test_missing_objective(self):
        """Doctor reports missing objective.md."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
        })
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot\n")
        with open(p["tasks"], "w") as f:
            f.write("- [ ] Task\n")

        result = cmd_doctor(self.context)
        self.assertIn("ERROR: objective.md is missing", result.message)

    def test_missing_task_files(self):
        """Doctor reports missing task files."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
        })
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective\n")
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot\n")

        result = cmd_doctor(self.context)
        self.assertIn("ERROR: No task file found", result.message)




class TestDoctorStaleClaims(unittest.TestCase):
    """Tests for doctor detecting stale task claims."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_doctor_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_stale_task_claim_warns(self):
        """Doctor warns about task claims older than 30 minutes."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        past = (datetime.now() - timedelta(seconds=3600)).isoformat()
        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
            "task_claims": {
                "1.1": {
                    "status": "claimed",
                    "agent_id": "old-agent",
                    "claimed_at": past,
                },
            },
        })
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective\nTest.\n")
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot\n")
        with open(p["tasks"], "w") as f:
            f.write("- [ ] 1.1 Task\n")

        result = cmd_doctor(self.context)
        self.assertIn("WARN: Task 1.1 claimed by old-agent", result.message)
        self.assertIn("possibly stale", result.message)

    def test_recent_claim_ok(self):
        """Doctor reports OK for recent task claims."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
            "task_claims": {
                "1.1": {
                    "status": "claimed",
                    "agent_id": "current-agent",
                    "claimed_at": datetime.now().isoformat(),
                },
            },
        })
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective\nTest.\n")
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot\n")
        with open(p["tasks"], "w") as f:
            f.write("- [ ] 1.1 Task\n")

        result = cmd_doctor(self.context)
        self.assertIn("OK: Task 1.1 claimed by current-agent", result.message)


class TestDoctorSizeLimits(unittest.TestCase):
    """Tests for doctor detecting artifacts exceeding size limits."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_doctor_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_oversized_artifact_warns(self):
        """Doctor warns when an artifact exceeds MAX_ARTIFACT_CHARS."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        save_manifest(self.context, {
            "context_name": self.context,
            "lock": {"held": False},
        })
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("x" * (MAX_ARTIFACT_CHARS + 100))
        with open(os.path.join(p["base"], "snapshot.md"), "w") as f:
            f.write("# Snapshot\n")
        with open(p["tasks"], "w") as f:
            f.write("- [ ] Task\n")

        result = cmd_doctor(self.context)
        self.assertIn("WARN: objective.md exceeds size limit", result.message)


if __name__ == "__main__":
    unittest.main()
