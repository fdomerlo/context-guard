"""Unit tests for the 3-state verification pipeline (PLAN -> EXECUTE -> VERIFY)."""

import os
import sys
import tempfile
import unittest
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.manifest import create_initial_manifest, load_manifest, save_manifest
from context_guard.guard.paths import get_paths
from context_guard.guard.transaction import (
    cmd_approve,
    cmd_begin,
    cmd_commit,
    cmd_rollback,
)
from context_guard.guard.errors import (
    EXIT_OK,
    EXIT_VALIDATION,
    EXIT_BAD_TRANSITION,
)


class TestThreeStatePhases(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_phases_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_initial_manifest_structure(self):
        """create_initial_manifest initializes the 3-state pipeline fields."""
        m = create_initial_manifest(self.context)
        self.assertEqual(m["context_name"], self.context)
        self.assertEqual(m["current_phase"], "PLAN")
        self.assertEqual(m["lock_phase"], "PLAN")
        self.assertEqual(m["completed_phases"], [])
        self.assertEqual(m["pending_phases"], ["PLAN", "EXECUTE", "VERIFY"])

    def test_full_pipeline_lifecycle(self):
        """Test strict transition PLAN -> EXECUTE -> VERIFY -> ARCHIVE."""
        save_manifest(self.context, create_initial_manifest(self.context))

        # 1. PLAN -> EXECUTE
        res_b1 = cmd_begin(self.context, "PLAN")
        self.assertEqual(res_b1.exit_code, EXIT_OK)

        base_dir = get_paths(self.context)["base"]
        with open(os.path.join(base_dir, "objective.md"), "w", encoding="utf-8") as f:
            f.write("Objective defined")
        with open(os.path.join(base_dir, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [x] Task 1")
        # F4: PLAN -> EXECUTE is gated on a recorded human sign-off.
        cmd_approve(self.context, by="tester")

        res_c1 = cmd_commit(self.context, "EXECUTE")
        self.assertEqual(res_c1.exit_code, EXIT_OK)

        m1 = load_manifest(self.context)
        self.assertEqual(m1["current_phase"], "PLAN")
        self.assertEqual(m1["lock_phase"], "EXECUTE")
        self.assertEqual(m1["completed_phases"], ["PLAN"])
        self.assertEqual(m1["pending_phases"], ["EXECUTE", "VERIFY"])

        # 2. EXECUTE -> VERIFY
        res_b2 = cmd_begin(self.context, "EXECUTE")
        self.assertEqual(res_b2.exit_code, EXIT_OK)

        res_c2 = cmd_commit(self.context, "VERIFY")
        self.assertEqual(res_c2.exit_code, EXIT_OK)

        m2 = load_manifest(self.context)
        self.assertEqual(m2["current_phase"], "EXECUTE")
        self.assertEqual(m2["lock_phase"], "VERIFY")
        self.assertEqual(m2["completed_phases"], ["PLAN", "EXECUTE"])
        self.assertEqual(m2["pending_phases"], ["VERIFY"])

        # 3. VERIFY -> ARCHIVE
        res_b3 = cmd_begin(self.context, "VERIFY")
        self.assertEqual(res_b3.exit_code, EXIT_OK)

        with open(os.path.join(base_dir, "review-report.md"), "w", encoding="utf-8") as f:
            f.write("Review complete")
        with open(os.path.join(base_dir, "verify-report.md"), "w", encoding="utf-8") as f:
            f.write("Verification complete")

        res_c3 = cmd_commit(self.context, "ARCHIVE")
        self.assertEqual(res_c3.exit_code, EXIT_OK)

        m3 = load_manifest(self.context)
        self.assertEqual(m3["current_phase"], "VERIFY")
        self.assertEqual(m3["lock_phase"], "ARCHIVE")
        self.assertEqual(m3["completed_phases"], ["PLAN", "EXECUTE", "VERIFY"])
        self.assertEqual(m3["pending_phases"], [])

    def test_illegal_phase_skip(self):
        """Attempting to skip from PLAN directly to VERIFY is rejected."""
        save_manifest(self.context, create_initial_manifest(self.context))

        cmd_begin(self.context, "PLAN")
        res = cmd_commit(self.context, "VERIFY")
        self.assertEqual(res.exit_code, EXIT_BAD_TRANSITION)
        self.assertIn("FAIL|BAD_TRANSITION", res.message)

    def test_illegal_begin_phase(self):
        """Attempting to begin an unsupported phase (e.g. state-guard's old phases) is rejected."""
        save_manifest(self.context, create_initial_manifest(self.context))

        res_explore = cmd_begin(self.context, "explore")
        self.assertEqual(res_explore.exit_code, EXIT_VALIDATION)

        res_design = cmd_begin(self.context, "design")
        self.assertEqual(res_design.exit_code, EXIT_VALIDATION)


if __name__ == "__main__":
    unittest.main()
