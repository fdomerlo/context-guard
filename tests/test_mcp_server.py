"""Unit tests for Context Guard MCP server (scripts/mcp_server.py)."""

import os
import sys
import tempfile
import unittest
import shutil

# Ensure context_guard package is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard import mcp_server
from context_guard.mcp_server import (
    begin_transaction,
    check_completion,
    commit_transaction,
    get_status,
    next_task,
    rollback_transaction,
    save_checkpoint,
    validate,
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


class TestReadToolsAreExposed(unittest.TestCase):
    """PLAN.md 0.5: the MCP keeps the transactional tools and gains the four
    read ones. AGENTS.md has documented them as available since F3, so the gap
    was a promise the transport did not keep — and on a host with no shell
    (Claude Desktop) a missing read tool is not an inconvenience, it is the
    difference between an agent that can rehydrate its state and one that
    cannot.
    """

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_mcp_read_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir
        cmd_new(self.context, "alpha")
        p = get_paths(self.context, "alpha")
        with open(os.path.join(p["base"], "objective.md"), "w", encoding="utf-8") as f:
            f.write("# Objective\nShip the read tools.\n")
        with open(os.path.join(p["base"], "snapshot.md"), "w", encoding="utf-8") as f:
            f.write("# Snapshot\nNothing done yet.\n")
        with open(p["tasks"], "w", encoding="utf-8") as f:
            f.write("- [x] 1.1 First\n- [ ] 1.2 Second\n")

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_get_status_reports_the_pipeline_state(self):
        res = get_status(self.context, change="alpha")
        self.assertTrue(res.startswith("[0]"), res)
        self.assertIn("PROGRESS: 1/2", res)

    def test_check_completion_counts_deterministically(self):
        res = check_completion(self.context, change="alpha")
        self.assertIn("total=2", res)
        self.assertIn("completed=1", res)
        self.assertIn("all_complete=false", res)

    def test_validate_reports_failures_with_the_validation_exit_code(self):
        """cmd_validate raises rather than returning, so this also pins that the
        MCP wrapper converts a GuardError into a coded string instead of
        crashing the server for every other tool in the session."""
        os.remove(os.path.join(get_paths(self.context, "alpha")["base"], "snapshot.md"))

        res = validate(self.context, change="alpha")

        self.assertTrue(res.startswith(f"[{EXIT_VALIDATION}]"), res)
        self.assertIn("MISSING|snapshot.md", res)

    def test_validate_passes_on_complete_artifacts(self):
        res = validate(self.context, change="alpha")
        self.assertTrue(res.startswith("[0] SUCCESS|VALIDATE_OK"), res)

    def test_next_task_returns_the_claiming_agent_id(self):
        """1.2.4: the agent_id is part of the contract — a caller that is never
        told which identity won the claim cannot release what it just claimed."""
        res = next_task(self.context, change="alpha", agent_id="agent-7")

        self.assertIn("SUCCESS|NEXT_TASK", res)
        self.assertIn("1.2", res)
        self.assertIn("agent-7", res)

    def test_read_tools_report_ambiguity_instead_of_guessing(self):
        cmd_new(self.context, "zebra")
        for tool in (get_status, check_completion, validate, next_task):
            with self.subTest(tool=tool.__name__):
                self.assertIn("AMBIGUOUS_CHANGE", tool(self.context))

    def test_approve_is_not_exposed_over_mcp(self):
        """PLAN.md 0.6 names the harness permission prompt on `cg approve` as
        the only hard control in the model. An MCP tool is exactly the channel
        that routes around it, so the omission is the design, not an oversight —
        this test is here to stop someone "completing" the API later."""
        self.assertFalse(
            hasattr(mcp_server, "approve"),
            "approve must not be an MCP tool; it would bypass the permission prompt",
        )


if __name__ == "__main__":
    unittest.main()
