"""Adversarial tests — each one encodes a bypass verified during the audits.

These are not happy-path tests. Every test here reproduces a concrete way an
agent (or a crashed peer process) could defeat the guarantees context-guard
claims to provide. A regression in any of them means the tool is lying about
what it enforces.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.manifest import (
    create_initial_manifest,
    load_manifest,
    save_manifest,
)
from context_guard.guard.cli import _to_json
from context_guard.guard.locking import (
    acquire,
    with_write_lock,
    _is_write_lock_stale,
    WRITE_LOCK_MAX_AGE,
)
from context_guard.guard.paths import get_paths
from context_guard.guard.transaction import cmd_begin
from context_guard.guard.commands import (
    cmd_claim,
    cmd_claim_task,
    cmd_doctor,
    cmd_next_task,
    cmd_release,
    cmd_release_task,
    DEFAULT_LEASE_SECONDS,
)
from context_guard.guard import errors
from context_guard.guard.errors import (
    EXIT_OK,
    EXIT_BAD_TRANSITION,
    EXIT_LOCK_HELD,
    EXIT_VALIDATION,
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


class TestOrphanSessionLockDeadlock(unittest.TestCase):
    """1.2.1 — a lockfile with no manifest metadata must not deadlock forever.

    The attack is a crash, not an agent: a process dies between creating
    `.lock` and writing its metadata into the manifest. `acquired_at` is then
    None, the staleness check silently evaluates to False, and every future
    claim returns LOCK_HELD forever. The session becomes permanently
    unusable with no way out short of deleting files by hand — the exact
    failure a crash-survival tool must not have.
    """

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_adv_orphan_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _orphan_lockfile(self, age_seconds):
        """Create a .lock with no manifest lock metadata, aged via mtime."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        save_manifest(self.context, create_initial_manifest(self.context))
        with open(p["lock"], "w"):
            pass
        past = time.time() - age_seconds
        os.utime(p["lock"], (past, past))
        return p

    def test_orphan_lockfile_older_than_ttl_is_taken_over(self):
        """No acquired_at: fall back to the lockfile's mtime to judge staleness."""
        self._orphan_lockfile(age_seconds=7200)

        result = acquire(self.context, ttl=1800)

        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|LOCK_ACQUIRED", result.message)

    def test_orphan_lockfile_within_ttl_is_still_respected(self):
        """The fallback must not become a free pass: a recent orphan lock is
        still a lock, because the peer that made it may be seconds from
        writing its metadata."""
        self._orphan_lockfile(age_seconds=5)

        result = acquire(self.context, ttl=1800)

        self.assertEqual(result.exit_code, EXIT_LOCK_HELD)
        self.assertIn("FAIL|LOCK_HELD", result.message)

    def test_takeover_records_the_new_owner(self):
        """After a takeover the manifest must name the agent that now holds
        the lock, or the next crash repeats the same ambiguity."""
        self._orphan_lockfile(age_seconds=7200)

        acquire(self.context, ttl=1800)

        m = load_manifest(self.context)
        self.assertTrue(m["lock"]["held"])
        self.assertIsNotNone(m["lock"]["acquired_at"])
        self.assertIsNotNone(m["lock"]["acquired_by"])


class TestWriteLockTheft(unittest.TestCase):
    """1.2.2 — the write mutex must not be stolen from a process that is alive.

    The attack is a slow peer. The write lock serializes read-modify-write on
    the manifest; before this fix, age alone declared a lock stale. Any
    operation that legitimately took longer than WRITE_LOCK_MAX_AGE had its
    mutex torn away mid-flight, and two processes then read-modify-wrote the
    same manifest concurrently — silently losing whichever write landed first.
    A liveness check is what makes the mutex a mutex.

    The hard cap remains, because a PID can be reused by an unrelated process
    and liveness alone would then deadlock just as permanently.
    """

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_adv_wlock_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _lockfile(self, pid, age_seconds):
        lockfile = os.path.join(self._tmpdir, "test.lock")
        with open(lockfile, "w") as f:
            f.write(f"{pid}\n")
            f.write(f"{time.time() - age_seconds}\n")
        return lockfile

    def test_live_pid_past_max_age_is_not_stale(self):
        """The core theft case: our own PID is alive, the lock is older than
        WRITE_LOCK_MAX_AGE, and it must still be respected."""
        lockfile = self._lockfile(os.getpid(), WRITE_LOCK_MAX_AGE + 70)

        self.assertFalse(_is_write_lock_stale(lockfile))

    def test_dead_pid_is_stale_regardless_of_age(self):
        """Liveness is the primary signal: a dead owner frees the lock at once."""
        lockfile = self._lockfile(99999999, 0)

        self.assertTrue(_is_write_lock_stale(lockfile))

    def test_live_pid_past_hard_cap_is_stale(self):
        """PID reuse protection: beyond 10x the max age we stop believing the
        PID belongs to the original owner, or a recycled PID deadlocks us."""
        lockfile = self._lockfile(os.getpid(), WRITE_LOCK_MAX_AGE * 10 + 60)

        self.assertTrue(_is_write_lock_stale(lockfile))

    def test_live_pid_recent_is_not_stale(self):
        lockfile = self._lockfile(os.getpid(), 0)

        self.assertFalse(_is_write_lock_stale(lockfile))

    def test_unparseable_lockfile_is_stale(self):
        """An unreadable lock names no owner to protect."""
        lockfile = os.path.join(self._tmpdir, "test.lock")
        with open(lockfile, "w") as f:
            f.write("garbage\n")

        self.assertTrue(_is_write_lock_stale(lockfile))

    def test_with_write_lock_does_not_steal_from_live_peer(self):
        """End to end: a live peer holding an aged write lock makes us wait and
        time out, rather than silently running concurrently with it."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        with open(p["write_lock"], "w") as f:
            f.write(f"{os.getpid()}\n")
            f.write(f"{time.time() - (WRITE_LOCK_MAX_AGE + 70)}\n")

        with self.assertRaises(TimeoutError):
            with_write_lock(self.context, lambda: "stolen",
                            timeout=0.1, retry_interval=0.02)

    def test_with_write_lock_recovers_from_dead_peer(self):
        """The fix must not strand work behind a crashed peer."""
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        with open(p["write_lock"], "w") as f:
            f.write("99999999\n")
            f.write(f"{time.time()}\n")

        self.assertEqual(with_write_lock(self.context, lambda: "recovered"),
                         "recovered")


class TestReleaseWithoutOwnership(unittest.TestCase):
    """1.2.4 — releasing someone else's claim must require saying who you are.

    The attack: agent B releases agent A's task simply by omitting
    --agent-id. Ownership was only checked when an agent_id happened to be
    supplied, so the check was opt-in — and the agent with something to gain
    by skipping it is exactly the one who will. Anonymous release is now an
    error; --force still exists, but it is explicit and recorded.
    """

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_adv_own_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir
        cmd_claim(self.context, ttl=1800)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_anonymous_task_release_is_rejected(self):
        """The bypass itself: no agent_id, no release."""
        cmd_claim_task(self.context, "task-1", agent_id="agent-A")

        result = cmd_release_task(self.context, "task-1")

        self.assertEqual(result.exit_code, EXIT_VALIDATION)
        self.assertIn("FAIL|AGENT_ID_REQUIRED", result.message)

    def test_anonymous_release_leaves_the_claim_intact(self):
        """A rejected release must not half-apply."""
        cmd_claim_task(self.context, "task-1", agent_id="agent-A")

        cmd_release_task(self.context, "task-1")

        m = load_manifest(self.context)
        self.assertEqual(m["task_claims"]["task-1"]["status"], "claimed")
        self.assertEqual(m["task_claims"]["task-1"]["agent_id"], "agent-A")

    def test_forced_task_release_is_recorded(self):
        """--force stays available for real deadlocks, but leaves a trace of
        who forced what and when."""
        cmd_claim_task(self.context, "task-1", agent_id="agent-A")

        result = cmd_release_task(self.context, "task-1", force=True)

        self.assertEqual(result.exit_code, EXIT_OK)
        m = load_manifest(self.context)
        claim = m["task_claims"]["task-1"]
        self.assertTrue(claim.get("force_released"))
        self.assertIn("released_at", claim)

    def test_anonymous_session_release_is_rejected(self):
        """The session lock follows the same rule as task claims — otherwise
        the weaker of the two is the one an agent will reach for."""
        result = cmd_release(self.context)

        self.assertEqual(result.exit_code, EXIT_VALIDATION)
        self.assertIn("FAIL|AGENT_ID_REQUIRED", result.message)

    def test_session_release_by_wrong_owner_is_rejected(self):
        m = load_manifest(self.context)
        owner = m["lock"]["acquired_by"]
        self.assertIsNotNone(owner)

        result = cmd_release(self.context, agent_id="somebody-else")

        self.assertEqual(result.exit_code, EXIT_LOCK_HELD)
        self.assertIn("FAIL|OWNERSHIP_MISMATCH", result.message)
        self.assertTrue(os.path.exists(get_paths(self.context)["lock"]))

    def test_session_release_by_true_owner_succeeds(self):
        m = load_manifest(self.context)
        owner = m["lock"]["acquired_by"]

        result = cmd_release(self.context, agent_id=owner)

        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|LOCK_RELEASED", result.message)


class TestOrphanTaskClaimDeadlock(unittest.TestCase):
    """1.2.3 — a claim held by a dead agent must not block a task forever.

    The attack is again a crash, and it is the one that silently kills a
    swarm: next-task skipped any task whose claim status was "claimed",
    regardless of how old the claim was or whether the claiming process still
    existed. One agent dying mid-task removed that task from the queue
    permanently, and the run reported DONE with work left undone — the worst
    kind of failure, because it looks like success.
    """

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_adv_lease_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _session_with_tasks(self, tasks="- [ ] 1.1 Only task\n"):
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        save_manifest(self.context, create_initial_manifest(self.context))
        for name in ("objective.md", "snapshot.md"):
            with open(os.path.join(p["base"], name), "w") as f:
                f.write("Content.\n")
        with open(p["tasks"], "w") as f:
            f.write(tasks)
        return p

    def _expire_claim(self, task_id):
        """Age a claim past its lease, as a crashed agent's claim would be."""
        m = load_manifest(self.context)
        claim = m["task_claims"][task_id]
        lease = claim.get("lease_seconds", DEFAULT_LEASE_SECONDS)
        claim["claimed_at"] = (
            datetime.now() - timedelta(seconds=lease + 60)
        ).isoformat()
        save_manifest(self.context, m)

    def test_claim_records_a_lease(self):
        """Without a lease there is no way to tell abandoned from in-flight."""
        self._session_with_tasks()
        cmd_claim_task(self.context, "1.1", agent_id="agent-A")

        claim = load_manifest(self.context)["task_claims"]["1.1"]
        self.assertEqual(claim["lease_seconds"], DEFAULT_LEASE_SECONDS)

    def test_expired_claim_is_reclaimable_by_next_task(self):
        """The deadlock itself: the only task is held by a dead agent."""
        self._session_with_tasks()
        cmd_claim_task(self.context, "1.1", agent_id="dead-agent")
        self._expire_claim("1.1")

        result = cmd_next_task(self.context, agent_id="agent-B")

        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|NEXT_TASK|1.1", result.message)
        self.assertNotIn("DONE|NO_PENDING_TASKS", result.message)

    def test_takeover_is_logged_in_the_manifest(self):
        """Stealing a lease is legitimate but must never be silent."""
        self._session_with_tasks()
        cmd_claim_task(self.context, "1.1", agent_id="dead-agent")
        self._expire_claim("1.1")

        cmd_next_task(self.context, agent_id="agent-B")

        claim = load_manifest(self.context)["task_claims"]["1.1"]
        self.assertEqual(claim["agent_id"], "agent-B")
        takeovers = claim.get("takeovers", [])
        self.assertEqual(len(takeovers), 1)
        self.assertEqual(takeovers[0]["from_agent"], "dead-agent")
        self.assertEqual(takeovers[0]["to_agent"], "agent-B")
        self.assertIn("at", takeovers[0])

    def test_live_claim_within_lease_is_still_respected(self):
        """The lease must not become a license to trample working agents."""
        self._session_with_tasks("- [ ] 1.1 First\n- [ ] 1.2 Second\n")
        cmd_claim_task(self.context, "1.1", agent_id="agent-A")

        result = cmd_next_task(self.context, agent_id="agent-B")

        self.assertIn("SUCCESS|NEXT_TASK|1.2", result.message)
        self.assertEqual(
            load_manifest(self.context)["task_claims"]["1.1"]["agent_id"],
            "agent-A",
        )

    def test_doctor_fix_releases_claims_of_dead_pids(self):
        """doctor --fix is the operator's escape hatch when a whole swarm died."""
        self._session_with_tasks()
        cmd_claim_task(self.context, "1.1", agent_id="99999999-somehost-1700000000")

        result = cmd_doctor(self.context, fix=True)

        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("FIXED", result.message)
        claim = load_manifest(self.context)["task_claims"]["1.1"]
        self.assertNotEqual(claim["status"], "claimed")

    def test_doctor_fix_keeps_claims_of_live_pids(self):
        """A live owner is not collateral damage."""
        self._session_with_tasks()
        live_agent = f"{os.getpid()}-somehost-1700000000"
        cmd_claim_task(self.context, "1.1", agent_id=live_agent)

        cmd_doctor(self.context, fix=True)

        claim = load_manifest(self.context)["task_claims"]["1.1"]
        self.assertEqual(claim["status"], "claimed")

    def test_doctor_fix_tolerates_opaque_agent_ids(self):
        """agent_id is free-form; an id with no parseable PID must not crash
        the only tool an operator has left."""
        self._session_with_tasks()
        cmd_claim_task(self.context, "1.1", agent_id="agent-A")

        result = cmd_doctor(self.context, fix=True)

        self.assertEqual(result.exit_code, EXIT_OK)
        claim = load_manifest(self.context)["task_claims"]["1.1"]
        self.assertEqual(claim["status"], "claimed")

    def test_doctor_without_fix_does_not_mutate(self):
        """Diagnosis and repair are separate verbs."""
        self._session_with_tasks()
        cmd_claim_task(self.context, "1.1", agent_id="99999999-somehost-1700000000")

        cmd_doctor(self.context)

        claim = load_manifest(self.context)["task_claims"]["1.1"]
        self.assertEqual(claim["status"], "claimed")


class TestNextTaskExposesOwnership(unittest.TestCase):
    """1.2.4 — next-task must tell the caller which identity now owns the task.

    next-task claims the task on the caller's behalf, generating an agent_id
    when none was supplied. If it never reports that id back, the caller
    cannot release what it just claimed: it has to either guess, or omit the
    id entirely — which is precisely the anonymous-release bypass. Ownership
    you cannot name is ownership you cannot enforce.
    """

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_adv_owner_out_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir
        p = get_paths(self.context)
        os.makedirs(p["base"], exist_ok=True)
        save_manifest(self.context, create_initial_manifest(self.context))
        with open(p["tasks"], "w") as f:
            f.write("- [ ] 1.1 Only task\n")

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_next_task_reports_the_claiming_agent(self):
        result = cmd_next_task(self.context, agent_id="agent-A")

        self.assertEqual(result.message, "SUCCESS|NEXT_TASK|1.1|agent-A|1.1 Only task")

    def test_generated_agent_id_is_reported_back(self):
        """The caller supplied no id, so the only way it can ever release this
        task is if next-task hands the generated one back."""
        result = cmd_next_task(self.context)

        parts = result.message.split("|")
        reported_agent = parts[3]
        self.assertTrue(reported_agent)
        self.assertEqual(
            load_manifest(self.context)["task_claims"]["1.1"]["agent_id"],
            reported_agent,
        )

    def test_reported_agent_id_can_actually_release_the_task(self):
        """End to end: the identity next-task reports is accepted by the
        ownership check, closing the claim/release loop without --force."""
        result = cmd_next_task(self.context)
        reported_agent = result.message.split("|")[3]

        released = cmd_release_task(self.context, "1.1", agent_id=reported_agent)

        self.assertEqual(released.exit_code, EXIT_OK)

    def test_json_output_exposes_agent_id(self):
        """The three harnesses consume --format json, not the text line."""
        result = cmd_next_task(self.context, agent_id="agent-A")
        payload = json.loads(_to_json(result.message, result.exit_code, "next-task"))

        self.assertEqual(payload["details"][1], "agent-A")


if __name__ == "__main__":
    unittest.main()
