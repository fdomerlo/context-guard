"""PLAN-2.5 F2: `cg new --from-plan` materializes a phased PLAN-N.md as one
change per phase.

The property that matters most here is negative: importing a plan writes
`objective.md` and `tasks.md` ahead of time, and that must not be mistaken
for the human having approved anything. The adversarial test below is the
one that proves the gate survived the shortcut."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.commands import cmd_new_from_plan
from context_guard.guard.errors import (
    EXIT_APPROVAL_REQUIRED,
    EXIT_OK,
    EXIT_VALIDATION,
    GuardError,
)
from context_guard.guard.manifest import load_manifest
from context_guard.guard.paths import get_paths
from context_guard.guard.transaction import cmd_commit

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    return os.path.join(FIXTURES, name)


class FromPlanTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_from_plan_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def artifact(self, change, filename):
        path = os.path.join(get_paths(self.context, change)["base"], filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def changes_on_disk(self):
        changes_dir = os.path.join(self.context, ".context-guard", "changes")
        if not os.path.isdir(changes_dir):
            return []
        return sorted(os.listdir(changes_dir))


class TestImportCreatesOneChangePerPhase(FromPlanTestCase):
    def setUp(self):
        super().setUp()
        self.result = cmd_new_from_plan(
            self.context, "demo", fixture("plan_es.md"))

    def test_succeeds(self):
        self.assertEqual(self.result.exit_code, EXIT_OK)

    def test_one_change_per_phase_named_after_the_phase_id(self):
        self.assertEqual(self.changes_on_disk(), ["demo-f1", "demo-f2", "demo-f3"])

    def test_objective_carries_the_plans_one_sentence_objective(self):
        objective = self.artifact("demo-f1", "objective.md")
        self.assertIn("dogfooding real", objective)

    def test_objective_carries_the_phase_body(self):
        objective = self.artifact("demo-f1", "objective.md")
        self.assertIn("Step 6", objective)

    def test_objective_carries_the_phase_spec(self):
        objective = self.artifact("demo-f2", "objective.md")
        self.assertIn("Candidato A", objective)

    def test_objective_no_longer_says_pending(self):
        self.assertNotIn("[PENDING]", self.artifact("demo-f1", "objective.md"))

    def test_tasks_are_written_in_the_format_next_task_parses(self):
        tasks = self.artifact("demo-f1", "tasks.md")
        self.assertNotIn("[PENDING]", tasks)
        # `- [ ] N.M text` — the shape _parse_task_lines extracts ids from.
        self.assertRegex(tasks, r"(?m)^- \[ \] \d+\.\d+ \S")

    def test_tasks_cover_acceptance_criteria_and_test_items(self):
        tasks = self.artifact("demo-f2", "tasks.md")
        self.assertIn("validó en vivo", tasks)      # acceptance criterion
        self.assertIn("extender el test", tasks)    # test item

    def test_snapshot_stays_pending_because_it_is_not_derivable(self):
        # "snapshot.md no es derivable del plan (es el estado del repositorio
        # en el momento de arrancar, no una decisión de diseño)."
        self.assertIn("[PENDING]", self.artifact("demo-f1", "snapshot.md"))

    def test_every_change_starts_in_plan(self):
        for change in self.changes_on_disk():
            m = load_manifest(self.context, change)
            self.assertEqual(m.get("lock_phase"), "PLAN", change)

    def test_the_imported_tasks_feed_next_task_without_hand_editing(self):
        from context_guard.guard.commands import cmd_next_task
        result = cmd_next_task(self.context, change="demo-f1")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("TASK", result.message)


class TestImportDoesNotWeakenTheApprovalGate(FromPlanTestCase):
    """The adversarial case. A pre-written objective is still an unapproved
    objective: only `cg approve` opens EXECUTE."""

    def setUp(self):
        super().setUp()
        cmd_new_from_plan(self.context, "demo", fixture("plan_es.md"))

    def test_no_approval_is_present_in_the_manifest(self):
        m = load_manifest(self.context, "demo-f1")
        self.assertIsNone(m.get("approval"))

    def test_commit_to_execute_is_refused_with_exit_6(self):
        result = cmd_commit(self.context, "EXECUTE", change="demo-f1")
        self.assertEqual(result.exit_code, EXIT_APPROVAL_REQUIRED)
        self.assertIn("APPROVAL_REQUIRED", result.message)

    def test_the_change_stays_in_plan_after_the_refused_commit(self):
        cmd_commit(self.context, "EXECUTE", change="demo-f1")
        m = load_manifest(self.context, "demo-f1")
        self.assertEqual(m.get("lock_phase"), "PLAN")


class TestSelectingASinglePhase(FromPlanTestCase):
    def test_phase_flag_creates_only_that_change(self):
        result = cmd_new_from_plan(
            self.context, "demo", fixture("plan_es.md"), phase="F2")
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertEqual(self.changes_on_disk(), ["demo-f2"])

    def test_phase_flag_is_case_insensitive(self):
        cmd_new_from_plan(self.context, "demo", fixture("plan_es.md"), phase="f2")
        self.assertEqual(self.changes_on_disk(), ["demo-f2"])

    def test_an_unknown_phase_is_an_error_and_creates_nothing(self):
        result = cmd_new_from_plan(
            self.context, "demo", fixture("plan_es.md"), phase="F9")
        self.assertEqual(result.exit_code, EXIT_VALIDATION)
        self.assertIn("PHASE_NOT_IN_PLAN", result.message)
        self.assertEqual(self.changes_on_disk(), [])


class TestIdempotence(FromPlanTestCase):
    """"si un change de destino ya existe, SKIP y seguir con los demás;
    nunca pisar un change en curso"."""

    def test_rerunning_skips_existing_changes(self):
        cmd_new_from_plan(self.context, "demo", fixture("plan_es.md"))
        result = cmd_new_from_plan(self.context, "demo", fixture("plan_es.md"))
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SKIP|CHANGE_EXISTS|demo-f1", result.message)

    def test_rerunning_does_not_overwrite_work_in_progress(self):
        cmd_new_from_plan(self.context, "demo", fixture("plan_es.md"))
        path = os.path.join(
            get_paths(self.context, "demo-f1")["base"], "objective.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("edited by the agent during PLAN")

        cmd_new_from_plan(self.context, "demo", fixture("plan_es.md"))
        self.assertEqual(self.artifact("demo-f1", "objective.md"),
                         "edited by the agent during PLAN")

    def test_a_missing_phase_is_still_created_alongside_skipped_ones(self):
        cmd_new_from_plan(self.context, "demo", fixture("plan_es.md"), phase="F1")
        result = cmd_new_from_plan(self.context, "demo", fixture("plan_es.md"))
        self.assertIn("SKIP|CHANGE_EXISTS|demo-f1", result.message)
        self.assertEqual(self.changes_on_disk(), ["demo-f1", "demo-f2", "demo-f3"])


class TestAPlanWithNoPhasesCreatesNothing(FromPlanTestCase):
    """"nada a medias": the parser runs before any change is created."""

    def test_raises_plan_no_phases(self):
        with self.assertRaises(GuardError) as ctx:
            cmd_new_from_plan(self.context, "demo", fixture("plan_no_phases.md"))
        self.assertIn("PLAN_NO_PHASES", ctx.exception.message)

    def test_no_change_is_left_behind(self):
        with self.assertRaises(GuardError):
            cmd_new_from_plan(self.context, "demo", fixture("plan_no_phases.md"))
        self.assertEqual(self.changes_on_disk(), [])


class TestEnglishTemplatePlan(FromPlanTestCase):
    def test_imports_a_template_generated_plan(self):
        result = cmd_new_from_plan(self.context, "ingest", fixture("plan_en.md"))
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertEqual(self.changes_on_disk(), ["ingest-f1", "ingest-f2"])
        self.assertIn("max_attempts", self.artifact("ingest-f1", "objective.md"))


class TestAPlanQuotingTheScaffoldSentinel(FromPlanTestCase):
    """A plan about context-guard itself quotes `[PENDING]` in its prose. Copied
    verbatim into objective.md that literal reads to the PLAN->EXECUTE hard gate
    as an artifact nobody filled in, so the change is born stuck — refused with
    VALIDATION before the approval gate is ever reached.

    Neutralised on the import side, not in the gate: the artifact really was
    filled, so the sentinel is a false positive here. Weakening the gate would
    weaken it for every change, imported or not."""

    def setUp(self):
        super().setUp()
        self.result = cmd_new_from_plan(
            self.context, "quoted", fixture("plan_sentinel.md"))

    def test_the_sentinel_does_not_survive_into_the_artifact(self):
        self.assertNotIn("[PENDING]", self.artifact("quoted-f1", "objective.md"))
        self.assertNotIn("[PENDING]", self.artifact("quoted-f1", "tasks.md"))

    def test_the_surrounding_sentence_still_reads(self):
        objective = self.artifact("quoted-f1", "objective.md")
        self.assertIn("PENDING", objective)
        self.assertIn("marker left by the scaffold", objective)

    def test_snapshot_keeps_its_own_scaffold_sentinel(self):
        # Only imported prose is rewritten; the artifact the import genuinely
        # leaves unfilled must still trip the gate.
        self.assertIn("[PENDING]", self.artifact("quoted-f1", "snapshot.md"))

    def test_the_substitution_is_reported_not_silent(self):
        self.assertIn("NOTE|SENTINEL_NEUTRALIZED|quoted-f1|objective.md",
                      self.result.message)

    def test_commit_now_reaches_the_approval_gate_instead_of_validation(self):
        """The regression this whole class exists for: exit 6, not exit 4."""
        result = cmd_commit(self.context, "EXECUTE", change="quoted-f1")
        self.assertEqual(result.exit_code, EXIT_APPROVAL_REQUIRED)
        self.assertIn("APPROVAL_REQUIRED", result.message)

    def test_a_plan_without_the_sentinel_reports_no_note(self):
        result = cmd_new_from_plan(
            self.context, "clean", fixture("plan_en.md"))
        self.assertNotIn("SENTINEL_NEUTRALIZED", result.message)


class TestPhaseWithNoSubBlocks(FromPlanTestCase):
    """A phase carrying only prose still has to produce a usable change —
    an empty tasks.md would strand it with nothing for next-task to hand out."""

    def test_tasks_file_is_never_left_empty(self):
        cmd_new_from_plan(self.context, "sparse", fixture("plan_sparse.md"))
        tasks = self.artifact("sparse-f1", "tasks.md")
        self.assertTrue(tasks.strip(), "tasks.md must not be empty")
        self.assertRegex(tasks, r"(?m)^- \[ \] \d+\.\d+ \S")


if __name__ == "__main__":
    unittest.main()
