"""Unit tests for transaction and checkpoint capabilities in guard.transaction."""

import os
import sys
import tempfile
import unittest
import shutil
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from guard.transaction import (
    cmd_begin,
    cmd_commit,
    cmd_rollback,
    cmd_checkpoint,
    MAX_SUMMARY_CHARS,
)
from guard.manifest import load_manifest, save_manifest
from guard.errors import (
    EXIT_OK,
    EXIT_LOCK_HELD,
    EXIT_GENERIC,
    EXIT_VALIDATION,
    EXIT_BAD_TRANSITION,
)


class TestTransaction(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_txn_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_begin_valid_phase(self):
        """begin successfully starts a transaction for PLAN phase and scaffolds artifacts."""
        res = cmd_begin(self.context, "PLAN")
        self.assertEqual(res.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|BEGIN", res.message)

        m = load_manifest(self.context)
        self.assertIsNotNone(m)
        self.assertEqual(m["transaction"]["txn_status"], "in_progress")
        self.assertEqual(m["transaction"]["txn_phase"], "PLAN")

        base_dir = os.path.join(self.context, ".context-guard")
        for fname in ["objective.md", "snapshot.md", "tasks.md", "review-report.md", "verify-report.md"]:
            fpath = os.path.join(base_dir, fname)
            self.assertTrue(os.path.exists(fpath))
            with open(fpath, "r", encoding="utf-8") as f:
                self.assertIn("[PENDING]", f.read())

    def test_begin_invalid_phase(self):
        """begin returns EXIT_VALIDATION for an unknown phase."""
        res = cmd_begin(self.context, "INVALID")
        self.assertEqual(res.exit_code, EXIT_VALIDATION)
        self.assertIn("FAIL|INVALID_PHASE", res.message)

    def test_begin_conflict_and_stale(self):
        """begin fails if a transaction is in progress, but succeeds if stale."""
        res1 = cmd_begin(self.context, "PLAN")
        self.assertEqual(res1.exit_code, EXIT_OK)

        # Active transaction conflict
        res2 = cmd_begin(self.context, "PLAN")
        self.assertEqual(res2.exit_code, EXIT_LOCK_HELD)

        # Make transaction stale
        m = load_manifest(self.context)
        stale_time = (datetime.now() - timedelta(seconds=2000)).isoformat()
        m["transaction"]["txn_started_at"] = stale_time
        save_manifest(self.context, m)

        # Should allow begin takeover
        res3 = cmd_begin(self.context, "PLAN", ttl=1800)
        self.assertEqual(res3.exit_code, EXIT_OK)

    def test_commit_valid_transition(self):
        """commit advances phases correctly according to the DAG."""
        cmd_begin(self.context, "PLAN")

        # Fill objective.md and tasks.md so hard gate passes
        base_dir = os.path.join(self.context, ".context-guard")
        with open(os.path.join(base_dir, "objective.md"), "w", encoding="utf-8") as f:
            f.write("Objective defined")
        with open(os.path.join(base_dir, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [x] Task 1")

        res = cmd_commit(self.context, "EXECUTE")
        self.assertEqual(res.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|COMMIT", res.message)

        m = load_manifest(self.context)
        self.assertEqual(m["current_phase"], "PLAN")
        self.assertEqual(m["lock_phase"], "EXECUTE")
        self.assertIn("PLAN", m["completed_phases"])
        self.assertEqual(m["transaction"]["txn_status"], "idle")
        self.assertIn("completed_phase=PLAN", m["session"]["session_summary"])

    def test_commit_hard_gate_plan_to_execute_pending(self):
        """commit PLAN -> EXECUTE fails if objective.md or tasks.md contain [PENDING]."""
        cmd_begin(self.context, "PLAN")
        res = cmd_commit(self.context, "EXECUTE")
        self.assertEqual(res.exit_code, EXIT_VALIDATION)
        self.assertIn("Debe completar objective.md y tasks.md", res.message)

    def test_commit_hard_gate_verify_to_archive_pending(self):
        """commit VERIFY -> ARCHIVE fails if review-report.md or verify-report.md contain [PENDING]."""
        cmd_begin(self.context, "PLAN")
        base_dir = os.path.join(self.context, ".context-guard")
        with open(os.path.join(base_dir, "objective.md"), "w", encoding="utf-8") as f:
            f.write("Objective defined")
        with open(os.path.join(base_dir, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [x] Task 1")
        cmd_commit(self.context, "EXECUTE")

        cmd_begin(self.context, "EXECUTE")
        cmd_commit(self.context, "VERIFY")

        cmd_begin(self.context, "VERIFY")
        res = cmd_commit(self.context, "ARCHIVE")
        self.assertEqual(res.exit_code, EXIT_VALIDATION)
        self.assertIn("Debe completar la auditoría", res.message)

    def test_commit_invalid_transition(self):
        """commit returns EXIT_BAD_TRANSITION on illegal phase skip."""
        cmd_begin(self.context, "PLAN")
        res = cmd_commit(self.context, "VERIFY")  # Invalid skip from PLAN to VERIFY
        self.assertEqual(res.exit_code, EXIT_BAD_TRANSITION)
        self.assertIn("FAIL|BAD_TRANSITION", res.message)

    def test_commit_no_transaction(self):
        """commit fails when no transaction is in progress."""
        save_manifest(self.context, {"context_name": self.context})
        res = cmd_commit(self.context, "EXECUTE")
        self.assertEqual(res.exit_code, EXIT_GENERIC)
        self.assertIn("FAIL|NO_TXN_IN_PROGRESS", res.message)

    def test_rollback_restores_snapshot(self):
        """rollback restores previous manifest state and resets transaction to idle."""
        save_manifest(self.context, {
            "context_name": self.context,
            "current_phase": "PLAN",
            "lock_phase": "PLAN",
            "completed_phases": [],
            "pending_phases": ["PLAN", "EXECUTE", "VERIFY"],
        })

        cmd_begin(self.context, "PLAN")

        # Mutate during transaction
        m = load_manifest(self.context)
        m["current_phase"] = "MUTATED"
        save_manifest(self.context, m)

        res = cmd_rollback(self.context)
        self.assertEqual(res.exit_code, EXIT_OK)

        m_after = load_manifest(self.context)
        self.assertEqual(m_after["current_phase"], "PLAN")
        self.assertEqual(m_after["transaction"]["txn_status"], "idle")

    def test_rollback_no_transaction(self):
        """rollback fails when no transaction is active."""
        save_manifest(self.context, {"context_name": self.context})
        res = cmd_rollback(self.context)
        self.assertEqual(res.exit_code, EXIT_GENERIC)

    def test_checkpoint_valid_and_limit(self):
        """checkpoint stores session_summary or rejects oversized summary."""
        save_manifest(self.context, {"context_name": self.context})

        res = cmd_checkpoint(self.context, "Short summary")
        self.assertEqual(res.exit_code, EXIT_OK)

        m = load_manifest(self.context)
        self.assertEqual(m["session"]["session_summary"], "Short summary")

        # Oversized summary
        long_summary = "x" * (MAX_SUMMARY_CHARS + 10)
        res_long = cmd_checkpoint(self.context, long_summary)
        self.assertEqual(res_long.exit_code, EXIT_VALIDATION)
        self.assertIn("FAIL|SUMMARY_TOO_LONG", res_long.message)


if __name__ == "__main__":
    unittest.main()
