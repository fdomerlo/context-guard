"""Adversarial tests for `cg migrate`.

Migration is the one operation that reads data it did not write, and the one
whose failure mode is losing a user's history rather than blocking them. Every
test here is about not destroying or silently discarding work.

The legacy layouts are written directly into a tempdir because no public
function of context-guard 2.0 can produce them — a state-guard state.ini and a
context-guard 1.x flat directory come from other tools. Constructing the input
a migration exists to consume is not the same as hand-editing internal state.
"""

import configparser
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.commands import cmd_claim, cmd_list, cmd_migrate, cmd_new
from context_guard.guard.manifest import SCHEMA_VERSION, load_manifest
from context_guard.guard.paths import (
    get_base,
    get_changes_dir,
    get_paths,
    list_changes,
)
from context_guard.guard.errors import (
    EXIT_OK,
    EXIT_VALIDATION,
    LegacyLayoutError,
)


class MigrateTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_adv_mig_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # -- legacy layout builders ------------------------------------------

    def write_state_guard_change(self, name, lock_phase="execute",
                                 completed="plan", current="plan",
                                 with_gate=False, schema_version="2"):
        """Write a state-guard .state-guard/changes/{name}/ directory."""
        change_dir = os.path.join(self.context, ".state-guard", "changes", name)
        os.makedirs(change_dir, exist_ok=True)

        config = configparser.ConfigParser()
        config["Metadata"] = {
            "last_updated": "2026-07-02T10:30:00.000000",
            "schema_version": schema_version,
        }
        config["Transaction"] = {
            "txn_status": "idle",
            "txn_phase": "None",
            "txn_started_at": "None",
        }
        config["Graph"] = {
            "current_phase": current,
            "lock_phase": lock_phase,
            "completed_phases": completed,
            "pending_phases": "execute, verify",
        }
        config["Session"] = {"session_summary": f"summary for {name}"}
        if with_gate:
            config["Gate"] = {
                "plan_approved_at": "2026-07-02T11:00:00",
                "plan_approved_by": "fdomerlo",
            }
        with open(os.path.join(change_dir, "state.ini"), "w", encoding="utf-8") as f:
            config.write(f)

        with open(os.path.join(change_dir, "objective.md"), "w") as f:
            f.write(f"# Objective\nBuild {name}.\n")
        with open(os.path.join(change_dir, "design.md"), "w") as f:
            f.write(f"# Design\nArchitecture for {name}.\n")
        with open(os.path.join(change_dir, "tasks.md"), "w") as f:
            f.write("- [x] 1.1 First\n- [ ] 1.2 Second\n")
        return change_dir

    def write_flat_1x_layout(self):
        """Write a context-guard 1.x flat .context-guard/ directory."""
        base = get_base(self.context)
        os.makedirs(base, exist_ok=True)
        manifest = {
            "context_name": self.context,
            "current_phase": "PLAN",
            "lock_phase": "EXECUTE",
            "completed_phases": ["PLAN"],
            "pending_phases": ["EXECUTE", "VERIFY"],
            "lock": {},
            "transaction": {"txn_status": "idle", "txn_phase": "None",
                            "txn_started_at": None},
            "reference_docs": [],
            "files_in_scope": [],
            "task_claims": {},
            "session": {"session_summary": "legacy 1.x summary"},
        }
        with open(os.path.join(base, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)
        with open(os.path.join(base, "objective.md"), "w") as f:
            f.write("# Objective\nLegacy flat objective.\n")
        with open(os.path.join(base, "tasks.md"), "w") as f:
            f.write("- [x] 1.1 Legacy task\n")
        return base


class TestUnmigratedLayoutIsVisible(MigrateTestCase):
    """A 1.x context that is not migrated must never look like a fresh empty
    one. Silently starting a new change on top of it makes the user's entire
    history appear to have vanished — the precise failure a tool built to
    survive context loss cannot have."""

    def test_unmigrated_layout_is_not_treated_as_empty(self):
        self.write_flat_1x_layout()

        with self.assertRaises(LegacyLayoutError) as ctx:
            get_paths(self.context)

        self.assertIn("LEGACY_LAYOUT", ctx.exception.message)
        self.assertIn("migrate", ctx.exception.message)

    def test_commands_refuse_to_run_on_an_unmigrated_layout(self):
        self.write_flat_1x_layout()

        with self.assertRaises(LegacyLayoutError):
            cmd_claim(self.context, ttl=1800)

    def test_fresh_context_is_not_mistaken_for_a_legacy_one(self):
        """The detector must not fire on an empty project."""
        self.assertEqual(list_changes(self.context), [])
        self.assertEqual(get_paths(self.context)["change"], "default")


class TestMigrateFlat1xLayout(MigrateTestCase):
    def test_flat_layout_moves_to_default_change(self):
        self.write_flat_1x_layout()

        result = cmd_migrate(self.context)

        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("default", list_changes(self.context))
        m = load_manifest(self.context, "default")
        self.assertEqual(m["lock_phase"], "EXECUTE")
        self.assertEqual(m["completed_phases"], ["PLAN"])

    def test_flat_layout_artifacts_survive(self):
        """Migration that drops the artifacts loses the actual work."""
        self.write_flat_1x_layout()

        cmd_migrate(self.context)

        p = get_paths(self.context, "default")
        with open(os.path.join(p["base"], "objective.md")) as f:
            self.assertIn("Legacy flat objective", f.read())
        with open(p["tasks"]) as f:
            self.assertIn("Legacy task", f.read())

    def test_flat_layout_migration_stamps_schema_v3(self):
        self.write_flat_1x_layout()

        cmd_migrate(self.context)

        self.assertEqual(
            load_manifest(self.context, "default")["schema_version"],
            SCHEMA_VERSION,
        )

    def test_flat_layout_migration_is_idempotent(self):
        """Running migrate twice must converge, not duplicate or corrupt."""
        self.write_flat_1x_layout()

        first = cmd_migrate(self.context)
        after_first = load_manifest(self.context, "default")
        second = cmd_migrate(self.context)
        after_second = load_manifest(self.context, "default")

        self.assertEqual(first.exit_code, EXIT_OK)
        self.assertEqual(second.exit_code, EXIT_OK)
        self.assertEqual(after_first, after_second)
        self.assertEqual(list_changes(self.context), ["default"])

    def test_old_flat_manifest_is_not_left_behind(self):
        """A leftover flat manifest.json would keep is_legacy_flat_layout
        firing and make the context permanently 'unmigrated'."""
        self.write_flat_1x_layout()

        cmd_migrate(self.context)

        self.assertFalse(
            os.path.exists(os.path.join(get_base(self.context), "manifest.json")))


class TestMigrateStateGuardIni(MigrateTestCase):
    def test_state_ini_becomes_a_change(self):
        self.write_state_guard_change("add-oauth")

        result = cmd_migrate(self.context)

        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("add-oauth", list_changes(self.context))

    def test_phase_names_are_normalised_to_uppercase(self):
        """state-guard writes lowercase phases; the DAG here is uppercase. A
        missed conversion would leave lock_phase='execute', which matches no
        valid phase and locks the change out of every transition."""
        self.write_state_guard_change("add-oauth", lock_phase="execute",
                                      completed="plan", current="plan")

        cmd_migrate(self.context)

        m = load_manifest(self.context, "add-oauth")
        self.assertEqual(m["lock_phase"], "EXECUTE")
        self.assertEqual(m["current_phase"], "PLAN")
        self.assertEqual(m["completed_phases"], ["PLAN"])
        self.assertEqual(m["pending_phases"], ["EXECUTE", "VERIFY"])

    def test_current_phase_none_becomes_plan(self):
        """state-guard uses the literal 'none' before anything completes."""
        self.write_state_guard_change("fresh", lock_phase="plan",
                                      completed="", current="none")

        cmd_migrate(self.context)

        m = load_manifest(self.context, "fresh")
        self.assertEqual(m["current_phase"], "PLAN")
        self.assertEqual(m["completed_phases"], [])

    def test_unrecognised_completed_phase_goes_to_legacy_phases(self):
        """PLAN.md F7: state-guard tracked pseudo-phases this pipeline never
        had (a 'hotfix' bypass state, in the audit that found this). Carrying
        it into completed_phases verbatim plants a value no DAG invariant
        check here would ever expect — harmless today only because nothing
        validates completed_phases against the pipeline yet. Silently
        dropping it would be just as wrong: it is real history the user
        might want back, so it goes to legacy_phases instead of vanishing."""
        self.write_state_guard_change("add-oauth", lock_phase="verify",
                                      completed="plan,hotfix", current="execute")

        cmd_migrate(self.context)

        m = load_manifest(self.context, "add-oauth")
        self.assertEqual(m["completed_phases"], ["PLAN"])
        self.assertNotIn("HOTFIX", m["completed_phases"])
        self.assertEqual(m.get("legacy_phases"), ["HOTFIX"])

    def test_recognised_completed_phases_still_land_correctly(self):
        """The filter must not eat real pipeline phases along with the
        unrecognised ones."""
        self.write_state_guard_change("add-oauth", lock_phase="verify",
                                      completed="plan,execute", current="execute")

        cmd_migrate(self.context)

        m = load_manifest(self.context, "add-oauth")
        self.assertEqual(m["completed_phases"], ["PLAN", "EXECUTE"])
        self.assertNotIn("legacy_phases", m)

    def test_session_summary_is_preserved(self):
        """The summary is the warm-boot state; losing it defeats the point."""
        self.write_state_guard_change("add-oauth")

        cmd_migrate(self.context)

        m = load_manifest(self.context, "add-oauth")
        self.assertEqual(m["session"]["session_summary"], "summary for add-oauth")

    def test_recorded_human_approval_is_preserved(self):
        """Discarding a recorded human approval silently would make the user
        re-approve work they already signed off on."""
        self.write_state_guard_change("add-oauth", with_gate=True)

        cmd_migrate(self.context)

        approval = load_manifest(self.context, "add-oauth").get("approval")
        self.assertIsNotNone(approval)
        self.assertEqual(approval["by"], "fdomerlo")
        self.assertEqual(approval["at"], "2026-07-02T11:00:00")

    def test_artifacts_including_design_are_carried_over(self):
        """design.md has no counterpart in this pipeline. It is copied
        verbatim rather than mapped onto snapshot.md, because they are
        different documents and inventing the mapping would be a lie."""
        self.write_state_guard_change("add-oauth")

        cmd_migrate(self.context)

        p = get_paths(self.context, "add-oauth")
        with open(os.path.join(p["base"], "objective.md")) as f:
            self.assertIn("Build add-oauth", f.read())
        with open(os.path.join(p["base"], "design.md")) as f:
            self.assertIn("Architecture for add-oauth", f.read())
        with open(p["tasks"]) as f:
            self.assertIn("1.2 Second", f.read())

    def test_missing_snapshot_is_scaffolded_as_pending(self):
        """The migrated change genuinely lacks a snapshot; saying so with
        [PENDING] routes it through the normal gate instead of pretending."""
        self.write_state_guard_change("add-oauth")

        cmd_migrate(self.context)

        p = get_paths(self.context, "add-oauth")
        with open(os.path.join(p["base"], "snapshot.md")) as f:
            self.assertIn("[PENDING]", f.read())

    def test_multiple_changes_all_migrate(self):
        self.write_state_guard_change("alpha")
        self.write_state_guard_change("zebra")

        cmd_migrate(self.context)

        self.assertEqual(sorted(list_changes(self.context)), ["alpha", "zebra"])

    def test_state_ini_migration_is_idempotent(self):
        self.write_state_guard_change("add-oauth")

        first = cmd_migrate(self.context)
        after_first = load_manifest(self.context, "add-oauth")
        second = cmd_migrate(self.context)
        after_second = load_manifest(self.context, "add-oauth")

        self.assertEqual(first.exit_code, EXIT_OK)
        self.assertEqual(second.exit_code, EXIT_OK)
        self.assertEqual(after_first, after_second)
        self.assertEqual(list_changes(self.context), ["add-oauth"])


class TestMigrateRefusesToDestroy(MigrateTestCase):
    """Migration must never be the reason work disappears."""

    def test_migrate_refuses_to_clobber_an_existing_change(self):
        """Re-running migrate after work has started on the migrated change
        must not overwrite it with the stale legacy copy."""
        self.write_state_guard_change("add-oauth")
        cmd_migrate(self.context)

        p = get_paths(self.context, "add-oauth")
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective\nRewritten after migration.\n")

        result = cmd_migrate(self.context)

        self.assertEqual(result.exit_code, EXIT_OK)
        with open(os.path.join(p["base"], "objective.md")) as f:
            self.assertIn("Rewritten after migration", f.read())

    def test_flat_migration_does_not_clobber_an_existing_default(self):
        """A 1.x flat layout alongside an already-created `default` change is
        a collision: the flat data must not silently overwrite live work."""
        cmd_new(self.context, "default")
        p = get_paths(self.context, "default")
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective\nActive work.\n")
        # A flat manifest appearing next to an existing changes/ directory
        with open(os.path.join(get_base(self.context), "manifest.json"), "w") as f:
            json.dump({"context_name": self.context, "lock_phase": "VERIFY"}, f)

        result = cmd_migrate(self.context)

        self.assertEqual(result.exit_code, EXIT_VALIDATION)
        with open(os.path.join(p["base"], "objective.md")) as f:
            self.assertIn("Active work", f.read())

    def test_migrate_on_a_clean_context_is_a_no_op(self):
        result = cmd_migrate(self.context)

        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("NOTHING_TO_MIGRATE", result.message)
        self.assertFalse(os.path.isdir(get_changes_dir(self.context)))

    def test_state_guard_source_is_left_untouched(self):
        """Migration copies; it does not move. If the result is wrong the user
        still has the original to go back to."""
        change_dir = self.write_state_guard_change("add-oauth")

        cmd_migrate(self.context)

        self.assertTrue(os.path.exists(os.path.join(change_dir, "state.ini")))
        self.assertTrue(os.path.exists(os.path.join(change_dir, "design.md")))


if __name__ == "__main__":
    unittest.main()
