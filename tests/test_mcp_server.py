"""Unit tests for Context Guard MCP server (scripts/mcp_server.py)."""

import os
import sys
import tempfile
import unittest
import shutil

# Ensure context_guard package is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.mcp_server import (
    begin_transaction,
    commit_transaction,
    rollback_transaction,
    save_checkpoint,
)
from context_guard.guard.manifest import load_manifest
from context_guard.guard.paths import get_paths
from context_guard.guard.commands import cmd_approve, cmd_new
from context_guard.guard.errors import EXIT_VALIDATION


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_mcp_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_begin_and_commit_mcp_tools(self):
        """Test begin_transaction and commit_transaction MCP tools."""
        res_begin = begin_transaction(self.context, "PLAN")
        self.assertTrue(res_begin.startswith("[0] SUCCESS|BEGIN"))

        res_chk = save_checkpoint(self.context, "MCP Checkpoint")
        self.assertTrue(res_chk.startswith("[0] SUCCESS|CHECKPOINT_SAVED"))

        m_chk = load_manifest(self.context)
        self.assertEqual(m_chk["session"]["session_summary"], "MCP Checkpoint")

        base_dir = get_paths(self.context)["base"]
        with open(os.path.join(base_dir, "objective.md"), "w", encoding="utf-8") as f:
            f.write("Objective defined")
        with open(os.path.join(base_dir, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [x] Task 1")
        # F4: the approval gate applies to the MCP transport too. `approve`
        # is deliberately not an MCP tool — routing it through this channel
        # would bypass the harness permission prompt that PLAN.md 0.6 names as
        # the only hard control in the model.
        cmd_approve(self.context, by="tester")

        res_commit = commit_transaction(self.context, "EXECUTE")
        self.assertTrue(res_commit.startswith("[0] SUCCESS|COMMIT"))

        m = load_manifest(self.context)
        self.assertEqual(m["lock_phase"], "EXECUTE")
        self.assertIn("completed_phase=PLAN", m["session"]["session_summary"])


    def test_rollback_mcp_tool(self):
        """Test rollback_transaction MCP tool."""
        begin_transaction(self.context, "PLAN")
        res_rb = rollback_transaction(self.context)
        self.assertTrue(res_rb.startswith("[0] SUCCESS|ROLLBACK"))

        m = load_manifest(self.context)
        self.assertEqual(m["transaction"]["txn_status"], "idle")

    def test_tools_operate_on_an_explicit_change(self):
        """The MCP transport must be able to name a change, or it is unusable
        on any project with more than one in flight.

        `cg new` leaves each change with PLAN already begun, so rolling one
        back is what proves the tool acted on the change it was told to.
        """
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")

        res = rollback_transaction(self.context, change="zebra")

        self.assertTrue(res.startswith("[0] SUCCESS|ROLLBACK"), res)
        self.assertEqual(
            load_manifest(self.context, "zebra")["transaction"]["txn_status"],
            "idle")
        self.assertEqual(
            load_manifest(self.context, "alpha")["transaction"]["txn_status"],
            "in_progress")

    def test_ambiguous_change_is_reported_not_guessed(self):
        """Omitting the change with several active must surface the error
        through the MCP transport too, not resolve to one of them."""
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")

        res = begin_transaction(self.context, "PLAN")

        self.assertIn("AMBIGUOUS_CHANGE", res)
        self.assertIn("alpha", res)
        self.assertIn("zebra", res)

    def test_invalid_phase_mcp_tool(self):
        """Test error handling in MCP tools returns formatted string with exit code."""
        res = begin_transaction(self.context, "INVALID_PHASE")
        self.assertTrue(res.startswith(f"[{EXIT_VALIDATION}] FAIL|INVALID_PHASE"))


if __name__ == "__main__":
    unittest.main()
