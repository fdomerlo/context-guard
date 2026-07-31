"""Adversarial tests for the multi-change layout.

Each test encodes a way the multi-change refactor could reintroduce a bug
that context-guard already paid for once — most of them ported straight from
state-guard, where the same features shipped with the same holes.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.commands import (
    cmd_archive,
    cmd_claim,
    cmd_list,
    cmd_new,
    cmd_release,
)
from context_guard.guard.manifest import load_manifest
from context_guard.guard.paths import (
    get_archive_dir,
    get_paths,
    list_changes,
    resolve_change,
)
from context_guard.guard.transaction import cmd_begin, cmd_commit
from context_guard.guard.errors import (
    EXIT_OK,
    EXIT_BAD_TRANSITION,
    EXIT_LOCK_HELD,
    AmbiguousChangeError,
)


class MultiChangeTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_adv_mc_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _complete_plan(self, change):
        """Drive a change from PLAN to lock_phase=EXECUTE through public calls."""
        cmd_begin(self.context, "PLAN", change=change)
        p = get_paths(self.context, change)
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("Objective defined.\n")
        with open(p["tasks"], "w") as f:
            f.write("- [x] 1.1 Task\n")
        return cmd_commit(self.context, "EXECUTE", change=change)


class TestAmbiguousChangeResolution(MultiChangeTestCase):
    """The bug ported from state-guard: with several changes active, picking
    the alphabetically first one silently makes the agent operate on the wrong
    change while believing it got the right one.

    In state-guard this lived in sg.py `_active_change()` (sorted(...) then
    first hit) and in the git hook (`changes[0]['name']`). Working on "zebra"
    meant the hook validated "alpha". Nothing warned anyone.
    """

    def test_ambiguous_change_is_never_resolved_silently(self):
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")

        with self.assertRaises(AmbiguousChangeError) as ctx:
            resolve_change(self.context, None)

        message = ctx.exception.message
        self.assertIn("alpha", message)
        self.assertIn("zebra", message)

    def test_ambiguity_is_independent_of_creation_order(self):
        """Creating zebra first must not make zebra the implicit winner
        either — no ordering is the right one."""
        cmd_new(self.context, "zebra")
        cmd_new(self.context, "alpha")

        with self.assertRaises(AmbiguousChangeError):
            resolve_change(self.context, None)

    def test_single_active_change_resolves_implicitly(self):
        """The guard must not be so strict that the common case needs a flag."""
        cmd_new(self.context, "only-one")

        self.assertEqual(resolve_change(self.context, None), "only-one")

    def test_explicit_change_wins_over_ambiguity(self):
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")

        self.assertEqual(resolve_change(self.context, "zebra"), "zebra")

    def test_commands_surface_ambiguity_instead_of_guessing(self):
        """The error must reach the caller through the normal command path,
        not just the helper — a command that swallows it is the whole bug."""
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")

        with self.assertRaises(AmbiguousChangeError):
            cmd_claim(self.context, ttl=1800)

    def test_list_reports_every_active_change(self):
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")

        result = cmd_list(self.context)

        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("alpha", result.message)
        self.assertIn("zebra", result.message)
        self.assertEqual(sorted(list_changes(self.context)), ["alpha", "zebra"])


class TestChangeIsolation(MultiChangeTestCase):
    """Two changes are two workstreams. Anything shared between them is a way
    for one agent to corrupt or stall another's work."""

    def test_locks_are_independent_per_change(self):
        """A shared session lock would serialize unrelated work and, worse,
        let the agent holding change A block change B for its whole TTL."""
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")

        first = cmd_claim(self.context, ttl=1800, change="alpha")
        second = cmd_claim(self.context, ttl=1800, change="zebra")

        self.assertEqual(first.exit_code, EXIT_OK)
        self.assertEqual(second.exit_code, EXIT_OK)

    def test_claiming_one_change_twice_still_conflicts(self):
        """Isolation must not be so total that the lock stops locking."""
        cmd_new(self.context, "alpha")
        cmd_claim(self.context, ttl=1800, change="alpha")

        again = cmd_claim(self.context, ttl=1800, change="alpha")

        self.assertEqual(again.exit_code, EXIT_LOCK_HELD)

    def test_releasing_one_change_does_not_free_another(self):
        """The nastier half of a shared lock: agent A's release frees B."""
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")
        cmd_claim(self.context, ttl=1800, change="alpha")
        cmd_claim(self.context, ttl=1800, change="zebra")
        zebra_owner = load_manifest(self.context, "zebra")["lock"]["acquired_by"]

        cmd_release(self.context, agent_id=zebra_owner, change="zebra")

        alpha_lock = load_manifest(self.context, "alpha")["lock"]
        self.assertTrue(alpha_lock["held"])
        self.assertTrue(os.path.exists(get_paths(self.context, "alpha")["lock"]))

    def test_phase_state_does_not_leak_across_changes(self):
        """Advancing alpha to EXECUTE must not authorize EXECUTE on zebra.

        This is the F1 lock_phase bypass reopened through the multi-change
        door: if lock_phase is read from the wrong change's manifest, an agent
        skips planning on zebra by advancing alpha.
        """
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")
        self._complete_plan("alpha")

        res = cmd_begin(self.context, "EXECUTE", change="zebra")

        self.assertEqual(res.exit_code, EXIT_BAD_TRANSITION)
        self.assertIn("FAIL|PHASE_NOT_AUTHORIZED", res.message)
        self.assertIn("lock_phase=PLAN", res.message)

    def test_advancing_one_change_leaves_the_other_manifest_untouched(self):
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")

        self._complete_plan("alpha")

        self.assertEqual(load_manifest(self.context, "alpha")["lock_phase"], "EXECUTE")
        self.assertEqual(load_manifest(self.context, "zebra")["lock_phase"], "PLAN")

    def test_artifacts_are_not_shared_between_changes(self):
        """Scaffolding or writing in one change must not appear in another."""
        cmd_new(self.context, "alpha")
        cmd_new(self.context, "zebra")
        p_alpha = get_paths(self.context, "alpha")
        p_zebra = get_paths(self.context, "zebra")

        with open(os.path.join(p_alpha["base"], "objective.md"), "w") as f:
            f.write("Alpha objective.\n")

        with open(os.path.join(p_zebra["base"], "objective.md")) as f:
            self.assertNotIn("Alpha objective", f.read())
        self.assertNotEqual(p_alpha["base"], p_zebra["base"])
        self.assertNotEqual(p_alpha["lock"], p_zebra["lock"])
        self.assertNotEqual(p_alpha["write_lock"], p_zebra["write_lock"])


class TestArchiveScoping(MultiChangeTestCase):
    """Archiving is destructive. Anything it touches beyond its own change is
    unrecoverable work belonging to someone else."""

    def _completable_change(self, name):
        cmd_new(self.context, name)
        p = get_paths(self.context, name)
        for fname in ("objective.md", "snapshot.md"):
            with open(os.path.join(p["base"], fname), "w") as f:
                f.write(f"{fname} for {name}.\n")
        with open(p["tasks"], "w") as f:
            f.write("- [x] 1.1 Done\n")
        return p

    def test_archive_is_scoped_to_its_change(self):
        """Archiving alpha must leave zebra's directory and artifacts intact."""
        self._completable_change("alpha")
        p_zebra = self._completable_change("zebra")

        result = cmd_archive(self.context, change="alpha")

        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertTrue(os.path.exists(p_zebra["manifest"]))
        self.assertTrue(os.path.exists(os.path.join(p_zebra["base"], "objective.md")))
        self.assertIn("zebra", list_changes(self.context))

    def test_archived_change_leaves_the_active_list(self):
        """An emptied-but-present directory would keep the change looking
        active forever, and would make the next resolve_change ambiguous
        against a change that no longer exists."""
        self._completable_change("alpha")
        self._completable_change("zebra")

        cmd_archive(self.context, change="alpha")

        self.assertNotIn("alpha", list_changes(self.context))
        self.assertEqual(list_changes(self.context), ["zebra"])

    def test_archive_preserves_the_change_name_in_the_archive(self):
        """An archive that only records a timestamp makes two archived changes
        indistinguishable after the fact."""
        self._completable_change("alpha")

        result = cmd_archive(self.context, change="alpha")

        self.assertIn("alpha", result.message)
        archived = os.listdir(get_archive_dir(self.context))
        self.assertTrue(any("alpha" in entry for entry in archived), archived)

    def test_archive_does_not_delete_the_archive_directory(self):
        """Archiving a second change must not wipe the first one's archive."""
        self._completable_change("alpha")
        self._completable_change("zebra")
        cmd_archive(self.context, change="alpha")

        cmd_archive(self.context, change="zebra")

        archived = os.listdir(get_archive_dir(self.context))
        self.assertEqual(len(archived), 2, archived)


if __name__ == "__main__":
    unittest.main()
