"""Tests for multi-phase state machine transitions, cg verify, and status (Fase 4: Integration)."""

import os
import shutil
import tempfile
import unittest

from context_guard.guard.commands import (
    cmd_approve,
    cmd_archive,
    cmd_begin,
    cmd_claim_task,
    cmd_commit,
    cmd_next_task,
    cmd_plan,
    cmd_release_task,
    cmd_status,
    cmd_verify,
)
from context_guard.guard.errors import EXIT_APPROVAL_REQUIRED, EXIT_OK, EXIT_VALIDATION
from context_guard.guard.manifest import load_manifest
from context_guard.guard.paths import get_paths


class TestPhaseTransitions(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_trans_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_full_multiphase_lifecycle(self):
        # 1. Plan requirement with 2 phases
        plan_res = cmd_plan(self.context, requirement="Build billing system", name="billing")
        self.assertEqual(plan_res.exit_code, EXIT_OK)

        # 2. Check status shows Phase F1
        status_res = cmd_status(self.context, change="billing")
        self.assertEqual(status_res.exit_code, EXIT_OK)
        self.assertIn("ACTIVE PHASE: F1", status_res.message)
        self.assertIn("PENDING PHASES: F2", status_res.message)

        # 3. Approve F1 and begin EXECUTE
        cmd_approve(self.context, by="human_tester", change="billing")
        commit_res = cmd_commit(self.context, "EXECUTE", change="billing")
        self.assertEqual(commit_res.exit_code, EXIT_OK)

        # Begin EXECUTE (without passing --phase explicitly)
        begin_exec = cmd_begin(self.context, change="billing")
        self.assertEqual(begin_exec.exit_code, EXIT_OK)
        self.assertIn("phase=EXECUTE", begin_exec.message)

        # 4. Next-task and complete tasks
        next_res = cmd_next_task(self.context, agent_id="agent-1", change="billing")
        self.assertEqual(next_res.exit_code, EXIT_OK)
        self.assertIn("NEXT_TASK|1.1", next_res.message)

        # Release task 1.1 as done
        rel_res = cmd_release_task(self.context, "1.1", agent_id="agent-1", change="billing")
        self.assertEqual(rel_res.exit_code, EXIT_OK)

        # Claim and finish task 1.2
        cmd_claim_task(self.context, "1.2", agent_id="agent-1", change="billing")
        cmd_release_task(self.context, "1.2", agent_id="agent-1", change="billing")

        # 5. Commit EXECUTE -> VERIFY
        commit_verify = cmd_commit(self.context, "VERIFY", change="billing")
        self.assertEqual(commit_verify.exit_code, EXIT_OK)

        # Begin VERIFY
        cmd_begin(self.context, change="billing")

        # 6. Run cg verify (generates verify-report.md and review-report.md)
        verif_res = cmd_verify(self.context, change="billing", fix=True)
        self.assertEqual(verif_res.exit_code, EXIT_OK)
        self.assertIn("all_criteria_met=true", verif_res.message)

        p = get_paths(self.context, "billing")
        with open(os.path.join(p["base"], "verify-report.md"), "r", encoding="utf-8") as f:
            self.assertNotIn("[PENDING]", f.read())
        with open(os.path.join(p["base"], "review-report.md"), "r", encoding="utf-8") as f:
            self.assertNotIn("[PENDING]", f.read())

        # 7. Commit phase F1 and advance to F2
        advance_res = cmd_commit(self.context, "F2", change="billing")
        self.assertEqual(advance_res.exit_code, EXIT_OK)
        self.assertIn("PHASE_COMPLETED|F1", advance_res.message)
        self.assertIn("next_phase=F2", advance_res.message)

        # Manifest must reflect F1 completed, F2 active, lock_phase=PLAN
        m = load_manifest(self.context, "billing")
        self.assertEqual(m["active_phase_id"], "F2")
        self.assertEqual(m["lock_phase"], "PLAN")
        self.assertIn("F1-VERIFY", m["completed_phases"])

        # Status now shows F2 as active and F1 as completed
        status_f2 = cmd_status(self.context, change="billing")
        self.assertIn("ACTIVE PHASE: F2", status_f2.message)
        self.assertIn("COMPLETED PHASES: F1", status_f2.message)

        # 8. Human gate for F2: attempt to commit to EXECUTE without approve must fail
        cmd_begin(self.context, "PLAN", change="billing")
        fail_appr = cmd_commit(self.context, "EXECUTE", change="billing")
        self.assertEqual(fail_appr.exit_code, EXIT_APPROVAL_REQUIRED)

        # Approve F2
        cmd_approve(self.context, by="human_tester", change="billing")
        ok_appr = cmd_commit(self.context, "EXECUTE", change="billing")
        self.assertEqual(ok_appr.exit_code, EXIT_OK)

        # Begin EXECUTE for F2 and finish tasks
        cmd_begin(self.context, change="billing")
        cmd_claim_task(self.context, "2.1", agent_id="agent-1", change="billing")
        cmd_release_task(self.context, "2.1", agent_id="agent-1", change="billing")
        cmd_claim_task(self.context, "2.2", agent_id="agent-1", change="billing")
        cmd_release_task(self.context, "2.2", agent_id="agent-1", change="billing")

        # Move F2 to VERIFY
        cmd_commit(self.context, "VERIFY", change="billing")
        cmd_begin(self.context, change="billing")
        cmd_verify(self.context, change="billing", fix=True)

        # Last phase completes -> advance to ARCHIVE
        commit_arch = cmd_commit(self.context, "ARCHIVE", change="billing")
        self.assertEqual(commit_arch.exit_code, EXIT_OK)

        # 9. Archive the finished change
        arch_res = cmd_archive(self.context, change="billing")
        self.assertEqual(arch_res.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|ARCHIVED|billing", arch_res.message)


if __name__ == "__main__":
    unittest.main()
