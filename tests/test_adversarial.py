"""Adversarial tests — each one encodes a bypass verified during the audits.

These are not happy-path tests. Every test here reproduces a concrete way an
agent (or a crashed peer process) could defeat the guarantees context-guard
claims to provide. A regression in any of them means the tool is lying about
what it enforces.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.manifest import (
    create_initial_manifest,
    load_manifest,
    save_manifest,
)
from context_guard.guard.transaction import cmd_begin
from context_guard.guard import errors
from context_guard.guard.errors import (
    EXIT_OK,
    EXIT_BAD_TRANSITION,
)


class TestExitCodeContract(unittest.TestCase):
    """1.4 — the exit code table is the machine-readable contract every harness
    consumes to decide whether to retry.

    The attack this encodes is not an agent but a wrapper: if GENERIC and
    LOCK_HELD swap places, a harness retrying on "lock held" will spin forever
    against a corrupt manifest, and a harness that gives up on "generic" will
    abandon work that only needed a backoff. Codes are load-bearing, so they
    are pinned by value, not by symbol.
    """

    def test_unified_exit_code_values(self):
        self.assertEqual(errors.EXIT_OK, 0)
        self.assertEqual(errors.EXIT_GENERIC, 1)
        self.assertEqual(errors.EXIT_LOCK_HELD, 2)
        self.assertEqual(errors.EXIT_LOCK_CONTENDED, 3)
        self.assertEqual(errors.EXIT_VALIDATION, 4)
        self.assertEqual(errors.EXIT_BAD_TRANSITION, 5)

    def test_approval_required_code_exists(self):
        """Reserved by 1.4 for `cg approve`; the flow itself lands in F4."""
        self.assertEqual(errors.EXIT_APPROVAL_REQUIRED, 6)

    def test_exit_codes_are_distinct(self):
        codes = [
            errors.EXIT_OK,
            errors.EXIT_GENERIC,
            errors.EXIT_LOCK_HELD,
            errors.EXIT_LOCK_CONTENDED,
            errors.EXIT_VALIDATION,
            errors.EXIT_BAD_TRANSITION,
            errors.EXIT_APPROVAL_REQUIRED,
        ]
        self.assertEqual(len(codes), len(set(codes)))

    def test_typed_exceptions_carry_the_unified_codes(self):
        """The exception classes are a second source of truth for the same
        table — they must not drift from the constants."""
        self.assertEqual(errors.ManifestCorruptError("x").exit_code, 1)
        self.assertEqual(errors.LockHeldError("agent").exit_code, 2)
        self.assertEqual(errors.LockContendedError().exit_code, 3)
        self.assertEqual(errors.ValidationError(["MISSING|x"]).exit_code, 4)
        self.assertEqual(errors.BadTransitionError("PLAN", "VERIFY", "EXECUTE").exit_code, 5)


class TestPhaseAuthorizationBypass(unittest.TestCase):
    """1.1 — `begin` must refuse any phase that is not the manifest's lock_phase.

    The attack: an agent that wants to skip planning simply asks to begin the
    phase it wants. Before this fix, `begin` never read lock_phase at all, so
    the DAG was only enforced on commit — and an agent that never commits is
    never stopped.
    """

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_adv_phase_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_begin_execute_on_fresh_manifest_is_rejected(self):
        """A fresh session is locked to PLAN; begin EXECUTE must be refused."""
        save_manifest(self.context, create_initial_manifest(self.context))

        res = cmd_begin(self.context, "EXECUTE")

        self.assertEqual(res.exit_code, EXIT_BAD_TRANSITION)
        self.assertIn("FAIL|PHASE_NOT_AUTHORIZED", res.message)
        self.assertIn("requested=EXECUTE", res.message)
        self.assertIn("lock_phase=PLAN", res.message)

    def test_begin_verify_on_fresh_manifest_is_rejected(self):
        """Skipping two phases ahead is refused for the same reason."""
        save_manifest(self.context, create_initial_manifest(self.context))

        res = cmd_begin(self.context, "VERIFY")

        self.assertEqual(res.exit_code, EXIT_BAD_TRANSITION)
        self.assertIn("FAIL|PHASE_NOT_AUTHORIZED", res.message)

    def test_begin_execute_without_manifest_is_rejected(self):
        """No manifest at all still defaults to PLAN — it must not be an escape
        hatch that lets the agent start wherever it wants."""
        res = cmd_begin(self.context, "EXECUTE")

        self.assertEqual(res.exit_code, EXIT_BAD_TRANSITION)
        self.assertIn("FAIL|PHASE_NOT_AUTHORIZED", res.message)

    def test_rejected_begin_does_not_persist_a_transaction(self):
        """A refused begin must leave no trace: no in-progress transaction that
        a later commit could ride on."""
        save_manifest(self.context, create_initial_manifest(self.context))

        cmd_begin(self.context, "EXECUTE")

        m = load_manifest(self.context)
        self.assertEqual(m["transaction"]["txn_status"], "idle")
        self.assertEqual(m["lock_phase"], "PLAN")

    def test_begin_matching_lock_phase_still_succeeds(self):
        """The guard must not be so strict that the legitimate path breaks."""
        save_manifest(self.context, create_initial_manifest(self.context))

        res = cmd_begin(self.context, "PLAN")

        self.assertEqual(res.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|BEGIN", res.message)


if __name__ == "__main__":
    unittest.main()
