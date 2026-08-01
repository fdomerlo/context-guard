"""Adversarial tests for `cg approve` and the PLAN -> EXECUTE approval gate.

PLAN.md 1.5 / 0.6: the approval is the one barrier in the pipeline that only a
human can cross. Every test here encodes a way an agent could cross it anyway —
by never asking, by reusing a sign-off it was given once, by borrowing the one
granted to a different change, or by taking the hotfix door without leaving a
reason behind.

The gate is cooperative by construction (an agent with a shell can call
`cg approve` itself); what these tests protect is that the gate exists, is
recorded, and is single-use. The hard control is the harness permission prompt
documented in adapters/.
"""

import configparser
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.commands import cmd_approve, cmd_migrate, cmd_new
from context_guard.guard.manifest import load_manifest
from context_guard.guard.paths import get_paths
from context_guard.guard.transaction import cmd_begin, cmd_commit, cmd_rollback
from context_guard.guard.errors import (
    EXIT_OK,
    EXIT_APPROVAL_REQUIRED,
    EXIT_BAD_TRANSITION,
    EXIT_LOCK_HELD,
    EXIT_VALIDATION,
    AmbiguousChangeError,
)


class ApproveTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_adv_appr_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # -- helpers ---------------------------------------------------------

    def _fill_plan_artifacts(self, change):
        """Write real content over the [PENDING] scaffolding cmd_new leaves.

        Deliberately done by an "agent": the whole point of the gate is that an
        agent can produce a complete-looking plan on its own, so completing the
        artifacts must not be what authorizes the transition.
        """
        p = get_paths(self.context, change)
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective\nShip the approval gate.\n")
        with open(p["tasks"], "w") as f:
            f.write("- [ ] 1.1 Write the gate\n- [ ] 1.2 Test the gate\n")

    def _planned_change(self, name):
        """A change sitting in PLAN with its artifacts complete and unapproved."""
        res = cmd_new(self.context, name)
        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        self._fill_plan_artifacts(name)
        return name


class TestCommitRequiresApproval(ApproveTestCase):
    """F4 acceptance criterion: commit into EXECUTE without approve -> exit 6."""

    def test_commit_to_execute_without_approval_is_rejected(self):
        """The attack this whole phase exists for: an agent writes its own
        objective.md and tasks.md, sees the hard gates satisfied, and walks into
        EXECUTE having never shown the plan to anyone."""
        self._planned_change("alpha")

        res = cmd_commit(self.context, "EXECUTE", change="alpha")

        self.assertEqual(res.exit_code, EXIT_APPROVAL_REQUIRED, res.message)
        self.assertIn("APPROVAL_REQUIRED", res.message)
        m = load_manifest(self.context, "alpha")
        self.assertEqual(
            m["lock_phase"], "PLAN",
            "a rejected commit must leave the pipeline where it was",
        )
        self.assertEqual(
            m["transaction"]["txn_status"], "in_progress",
            "the PLAN transaction stays open so the agent can retry after approval",
        )

    def test_approve_then_commit_advances(self):
        self._planned_change("alpha")

        approved = cmd_approve(self.context, by="fdomerlo", change="alpha")
        self.assertEqual(approved.exit_code, EXIT_OK, approved.message)

        res = cmd_commit(self.context, "EXECUTE", change="alpha")
        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        self.assertEqual(load_manifest(self.context, "alpha")["lock_phase"], "EXECUTE")

    def test_pending_artifacts_beat_approval(self):
        """An approval must not buy a pass through artifact validation.

        Ordering matters: if the approval check ran first, a human could
        rubber-stamp a plan that is still literally [PENDING] and the commit
        would report the human as the problem instead of the empty artifact.
        """
        cmd_new(self.context, "alpha")  # leaves objective/tasks as [PENDING]

        cmd_approve(self.context, by="fdomerlo", change="alpha")
        res = cmd_commit(self.context, "EXECUTE", change="alpha")

        self.assertEqual(res.exit_code, EXIT_VALIDATION, res.message)

    def test_other_transitions_do_not_require_approval(self):
        """Only PLAN -> EXECUTE is gated. Requiring a sign-off to leave EXECUTE
        would make the gate noise, and noisy gates get bypassed wholesale."""
        self._planned_change("alpha")
        cmd_approve(self.context, by="fdomerlo", change="alpha")
        cmd_commit(self.context, "EXECUTE", change="alpha")

        cmd_begin(self.context, "EXECUTE", change="alpha")
        res = cmd_commit(self.context, "VERIFY", change="alpha")

        self.assertEqual(res.exit_code, EXIT_OK, res.message)


class TestApprovalIsSingleUse(ApproveTestCase):
    """1.5 — "el approval se consume en el commit ... para que no se reutilice
    entre iteraciones del plan"."""

    def test_approval_is_consumed_by_the_commit(self):
        """A sign-off left live in the manifest is a sign-off that silently
        authorizes every future re-entry into EXECUTE. It has to be spent."""
        self._planned_change("alpha")
        cmd_approve(self.context, by="fdomerlo", change="alpha")
        cmd_commit(self.context, "EXECUTE", change="alpha")

        m = load_manifest(self.context, "alpha")
        self.assertIsNone(
            m.get("approval"),
            "the approval must not survive the commit that consumed it",
        )
        history = m.get("approval_history", [])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["by"], "fdomerlo")
        self.assertTrue(history[0].get("at"))
        self.assertTrue(
            history[0].get("consumed_at"),
            "the audit trail must record when the approval was spent, not only "
            "when it was granted",
        )

    def test_approval_survives_a_rollback_within_plan(self):
        """Consumption is tied to the commit, not to any manifest write. An
        approval that evaporated on rollback would force the human to re-approve
        an identical plan every time the agent aborted a transaction."""
        self._planned_change("alpha")
        cmd_approve(self.context, by="fdomerlo", change="alpha")

        cmd_rollback(self.context, change="alpha")

        self.assertIsNotNone(load_manifest(self.context, "alpha").get("approval"))

    def test_approval_does_not_leak_across_changes(self):
        """Approving "alpha" must not advance "beta". Manifests are per change,
        so this is a regression guard on the day someone moves approval to a
        shared file: one sign-off authorizing a change the human never read is
        exactly the failure the gate is supposed to prevent."""
        self._planned_change("alpha")
        self._planned_change("beta")

        cmd_approve(self.context, by="fdomerlo", change="alpha")

        res = cmd_commit(self.context, "EXECUTE", change="beta")
        self.assertEqual(res.exit_code, EXIT_APPROVAL_REQUIRED, res.message)


class TestApproveAuditTrail(ApproveTestCase):
    def test_approve_records_who_and_when(self):
        """The audit trail is the entire value of a cooperative gate: it cannot
        stop an agent, so it must at least name whoever authorized the work."""
        self._planned_change("alpha")

        cmd_approve(self.context, by="ci-pipeline", change="alpha")

        approval = load_manifest(self.context, "alpha")["approval"]
        self.assertEqual(approval["by"], "ci-pipeline")
        self.assertTrue(approval["at"])

    def test_the_recorded_approver_is_never_empty(self):
        """PLAN.md F7 made --by required, arguing that defaulting to the
        environment made an agent-run approve indistinguishable from a
        human-run one. PLAN-2.1 F2.1 reversed that: the flag never
        authenticated anyone (an agent can pass any string), and requiring it
        put friction on the one step that must not be automated, which is what
        pushes people into letting the agent run it.

        What survives the reversal, and what this defends, is narrower: the
        audit trail must always name someone. A cooperative gate that records
        an empty approver has no value left at all — it can neither stop the
        work nor say who authorised it. The defaulting rules are covered in
        tests/test_ergonomics.py; this is the invariant underneath them."""
        for i, by in enumerate((None, "", "   ")):
            with self.subTest(by=by):
                name = f"blank{i}"
                self._planned_change(name)
                res = cmd_approve(self.context, by=by, change=name)
                self.assertEqual(res.exit_code, EXIT_OK, res.message)
                approval = load_manifest(self.context, name)["approval"]
                self.assertTrue(
                    approval["by"] and approval["by"].strip(),
                    "an approval was recorded naming nobody",
                )

    def test_approve_on_a_context_without_session_fails(self):
        res = cmd_approve(self.context, by="fdomerlo", change="ghost")
        self.assertNotEqual(res.exit_code, EXIT_OK)

    def test_approve_with_several_changes_and_no_change_is_ambiguous(self):
        """F2's rule holds here too: approving "whichever change happens to sort
        first" is how a human signs off on work they never looked at."""
        self._planned_change("alpha")
        self._planned_change("beta")

        with self.assertRaises(AmbiguousChangeError):
            cmd_approve(self.context, by="fdomerlo")

    def test_approve_outside_plan_is_rejected(self):
        """An approval can only ever be spent by PLAN -> EXECUTE. Recording one
        in EXECUTE leaves a live sign-off nothing will consume, waiting to
        authorize a transition the human was never asked about."""
        self._planned_change("alpha")
        cmd_approve(self.context, by="fdomerlo", change="alpha")
        cmd_commit(self.context, "EXECUTE", change="alpha")

        res = cmd_approve(self.context, by="fdomerlo", change="alpha")

        self.assertEqual(res.exit_code, EXIT_BAD_TRANSITION, res.message)
        self.assertIsNone(load_manifest(self.context, "alpha").get("approval"))


class TestHotfixDoor(ApproveTestCase):
    """1.5 / 0.4 — the hotfix flag replaces state-guard's parallel 150-line
    bypass flow. A door with no audit is the thing that made that flow useless."""

    def test_hotfix_requires_a_reason(self):
        """state-guard's hotfix could be taken silently. If --reason is
        optional, every hotfix in the log reads "unspecified" and the manifest
        records that the pipeline was skipped by nobody, for nothing."""
        self._planned_change("alpha")

        res = cmd_approve(self.context, by="fdomerlo", hotfix=True, change="alpha")

        self.assertEqual(res.exit_code, EXIT_VALIDATION, res.message)
        m = load_manifest(self.context, "alpha")
        self.assertEqual(m["lock_phase"], "PLAN", "a refused hotfix must not move the pipeline")
        self.assertIsNone(m.get("approval"))

    def test_hotfix_jumps_lock_phase_to_execute_and_persists_the_reason(self):
        cmd_new(self.context, "alpha")  # artifacts still [PENDING] — that is the point
        cmd_rollback(self.context, change="alpha")

        res = cmd_approve(self.context, by="fdomerlo", hotfix=True,
                          reason="production is down", change="alpha")

        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        m = load_manifest(self.context, "alpha")
        self.assertEqual(m["lock_phase"], "EXECUTE")
        entry = m["approval_history"][-1]
        self.assertTrue(entry["hotfix"])
        self.assertEqual(entry["reason"], "production is down")
        self.assertEqual(entry["by"], "fdomerlo")

        begun = cmd_begin(self.context, "EXECUTE", change="alpha")
        self.assertEqual(begun.exit_code, EXIT_OK, begun.message)

    def test_hotfix_does_not_mark_plan_as_completed(self):
        """PLAN was skipped, not done. Writing it into completed_phases would
        make the manifest — the artifact an auditor reads after an incident —
        claim a plan was produced and reviewed when none ever existed."""
        cmd_new(self.context, "alpha")
        cmd_rollback(self.context, change="alpha")

        cmd_approve(self.context, by="fdomerlo", hotfix=True,
                    reason="production is down", change="alpha")

        m = load_manifest(self.context, "alpha")
        self.assertNotIn("PLAN", m["completed_phases"])
        self.assertNotIn(
            "PLAN", m["pending_phases"],
            "a skipped phase left pending is a phase the pipeline will ask for again",
        )
        self.assertIn("PLAN", m.get("skipped_phases", []))

    def test_hotfix_approval_is_not_reusable_as_a_plan_approval(self):
        """The hotfix consumes its own approval as it jumps. Left live, a
        hotfix taken during an incident would sit in the manifest and silently
        authorize the next plan, weeks later, with nobody in the loop."""
        cmd_new(self.context, "alpha")
        cmd_rollback(self.context, change="alpha")

        cmd_approve(self.context, by="fdomerlo", hotfix=True,
                    reason="production is down", change="alpha")

        self.assertIsNone(load_manifest(self.context, "alpha").get("approval"))

    def test_hotfix_is_refused_while_a_transaction_is_open(self):
        """cmd_new leaves a PLAN transaction in progress, holding a snapshot of
        lock_phase=PLAN. Jumping the pipeline behind its back means a later
        rollback restores a state the change already left — silently undoing the
        hotfix."""
        cmd_new(self.context, "alpha")

        res = cmd_approve(self.context, by="fdomerlo", hotfix=True,
                          reason="production is down", change="alpha")

        self.assertEqual(res.exit_code, EXIT_LOCK_HELD, res.message)
        self.assertEqual(load_manifest(self.context, "alpha")["lock_phase"], "PLAN")

    def test_plain_approve_is_allowed_while_the_plan_transaction_is_open(self):
        """The normal flow: the agent begins PLAN, writes the artifacts, and the
        human approves without anyone having to close the transaction first."""
        self._planned_change("alpha")

        res = cmd_approve(self.context, by="fdomerlo", change="alpha")

        self.assertEqual(res.exit_code, EXIT_OK, res.message)


class TestMigratedApprovalIsHonoured(ApproveTestCase):
    """F2 preserved state-guard's [Gate] section into `approval`. F4 is where
    that field starts meaning something — if the gate ignored it, every migrated
    user would be asked to re-approve work they already signed off on."""

    def _write_state_guard_change(self, name):
        change_dir = os.path.join(self.context, ".state-guard", "changes", name)
        os.makedirs(change_dir, exist_ok=True)
        config = configparser.ConfigParser()
        config["Metadata"] = {"last_updated": "2026-07-02T10:30:00.000000",
                              "schema_version": "2"}
        config["Transaction"] = {"txn_status": "idle", "txn_phase": "None",
                                 "txn_started_at": "None"}
        config["Graph"] = {"current_phase": "plan", "lock_phase": "plan",
                           "completed_phases": "", "pending_phases": "plan, execute, verify"}
        config["Session"] = {"session_summary": f"summary for {name}"}
        config["Gate"] = {"plan_approved_at": "2026-07-02T11:00:00",
                          "plan_approved_by": "fdomerlo"}
        with open(os.path.join(change_dir, "state.ini"), "w", encoding="utf-8") as f:
            config.write(f)
        with open(os.path.join(change_dir, "objective.md"), "w") as f:
            f.write("# Objective\nMigrated work.\n")
        with open(os.path.join(change_dir, "snapshot.md"), "w") as f:
            f.write("# Snapshot\nState of the world.\n")
        with open(os.path.join(change_dir, "tasks.md"), "w") as f:
            f.write("- [ ] 1.1 Finish the migrated work\n")

    def test_migrated_approval_authorizes_the_commit(self):
        self._write_state_guard_change("legacy")
        self.assertEqual(cmd_migrate(self.context).exit_code, EXIT_OK)

        self.assertEqual(cmd_begin(self.context, "PLAN", change="legacy").exit_code, EXIT_OK)
        res = cmd_commit(self.context, "EXECUTE", change="legacy")

        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        m = load_manifest(self.context, "legacy")
        self.assertIsNone(m.get("approval"), "the migrated approval is consumed like any other")
        self.assertEqual(m["approval_history"][0]["by"], "fdomerlo")


if __name__ == "__main__":
    unittest.main()
