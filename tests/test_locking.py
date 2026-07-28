"""Tests for guard.locking — write locks, session locks, acquire logic."""

import json
import os
import sys
import tempfile
import time
import unittest

# Allow importing the guard package from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from guard.locking import with_write_lock, try_create_lockfile, acquire, _is_write_lock_stale
from guard.manifest import save_manifest, load_manifest
from guard.paths import get_paths
from guard.errors import EXIT_OK, EXIT_LOCK_HELD, EXIT_LOCK_CONTENDED


class TestWithWriteLock(unittest.TestCase):
    """Tests for with_write_lock() — short-lived mutex."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_locking_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_acquires_and_releases(self):
        """with_write_lock acquires lock, runs fn, and releases lock."""
        p = get_paths(self.context)
        result = with_write_lock(self.context, lambda: "ok")
        self.assertEqual(result, "ok")
        # Lock file should be cleaned up
        self.assertFalse(os.path.exists(p["write_lock"]))

    def test_lock_released_on_exception(self):
        """with_write_lock releases lock even if fn raises."""
        p = get_paths(self.context)

        def failing_fn():
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            with_write_lock(self.context, failing_fn)

        # Lock file should still be cleaned up
        self.assertFalse(os.path.exists(p["write_lock"]))

    def test_stale_lock_recovery_dead_pid(self):
        """with_write_lock recovers stale lock from a dead PID."""
        p = get_paths(self.context)
        os.makedirs(os.path.dirname(p["write_lock"]), exist_ok=True)

        # Create a lockfile with a dead PID (PID 99999999 shouldn't exist)
        with open(p["write_lock"], "w") as f:
            f.write("99999999\n")
            f.write(f"{time.time()}\n")

        result = with_write_lock(self.context, lambda: "recovered")
        self.assertEqual(result, "recovered")
        self.assertFalse(os.path.exists(p["write_lock"]))

    def test_stale_lock_recovery_expired(self):
        """with_write_lock recovers stale lock that is too old."""
        p = get_paths(self.context)
        os.makedirs(os.path.dirname(p["write_lock"]), exist_ok=True)

        # Create a lockfile with current PID but very old timestamp
        with open(p["write_lock"], "w") as f:
            f.write(f"{os.getpid()}\n")
            f.write(f"{time.time() - 100}\n")  # 100 seconds ago

        result = with_write_lock(self.context, lambda: "recovered")
        self.assertEqual(result, "recovered")

    def test_timeout_on_held_lock(self):
        """with_write_lock raises TimeoutError if lock can't be acquired."""
        p = get_paths(self.context)
        os.makedirs(os.path.dirname(p["write_lock"]), exist_ok=True)

        # Create a lockfile with current PID and recent timestamp (not stale)
        with open(p["write_lock"], "w") as f:
            f.write(f"{os.getpid()}\n")
            f.write(f"{time.time()}\n")

        with self.assertRaises(TimeoutError):
            with_write_lock(self.context, lambda: None, timeout=0.1, retry_interval=0.02)


class TestTryCreateLockfile(unittest.TestCase):
    """Tests for try_create_lockfile() — atomic OS-level lock."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_locking_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_creates_on_first_call(self):
        """First call to try_create_lockfile should succeed."""
        result = try_create_lockfile(self.context)
        self.assertTrue(result)
        p = get_paths(self.context)
        self.assertTrue(os.path.exists(p["lock"]))

    def test_fails_on_second_call(self):
        """Second call to try_create_lockfile should fail."""
        self.assertTrue(try_create_lockfile(self.context))
        result = try_create_lockfile(self.context)
        self.assertFalse(result)

    def test_different_contexts_independent(self):
        """Locks for different contexts are independent."""
        ctx_a = os.path.join(self._tmpdir, "ctx-a")
        ctx_b = os.path.join(self._tmpdir, "ctx-b")
        self.assertTrue(try_create_lockfile(ctx_a))
        self.assertTrue(try_create_lockfile(ctx_b))


class TestAcquire(unittest.TestCase):
    """Tests for acquire() — session lock with stale takeover."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_locking_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_success_fresh_context(self):
        """acquire on a fresh context should succeed."""
        result = acquire(self.context, ttl=1800)
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|LOCK_ACQUIRED", result.message)

        # Manifest should be created with lock info
        m = load_manifest(self.context)
        self.assertIsNotNone(m)
        self.assertTrue(m["lock"]["held"])

    def test_lock_held_by_another(self):
        """acquire fails when lock is already held and not stale."""
        result1 = acquire(self.context, ttl=1800)
        self.assertEqual(result1.exit_code, EXIT_OK)

        result2 = acquire(self.context, ttl=1800)
        self.assertEqual(result2.exit_code, EXIT_LOCK_HELD)
        self.assertIn("FAIL|LOCK_HELD", result2.message)

    def test_stale_takeover(self):
        """acquire takes over a stale lock (TTL expired)."""
        from datetime import datetime, timedelta

        # Set up a lock that is already expired
        result1 = acquire(self.context, ttl=1)
        self.assertEqual(result1.exit_code, EXIT_OK)

        # Backdate the acquired_at to make the lock stale
        m = load_manifest(self.context)
        past = (datetime.now() - timedelta(seconds=10)).isoformat()
        m["lock"]["acquired_at"] = past
        m["lock"]["ttl_seconds"] = 1
        save_manifest(self.context, m)

        # Now a new acquire should succeed via stale takeover
        result2 = acquire(self.context, ttl=1800)
        self.assertEqual(result2.exit_code, EXIT_OK)
        self.assertIn("SUCCESS|LOCK_ACQUIRED", result2.message)


class TestIsWriteLockStale(unittest.TestCase):
    """Tests for _is_write_lock_stale() helper."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_locking_")
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_dead_pid_is_stale(self):
        """A lockfile with a dead PID is stale."""
        lockfile = os.path.join(self._tmpdir, "test.lock")
        with open(lockfile, "w") as f:
            f.write("99999999\n")
            f.write(f"{time.time()}\n")
        self.assertTrue(_is_write_lock_stale(lockfile))

    def test_live_pid_recent_not_stale(self):
        """A lockfile with a live PID and recent timestamp is NOT stale."""
        lockfile = os.path.join(self._tmpdir, "test.lock")
        with open(lockfile, "w") as f:
            f.write(f"{os.getpid()}\n")
            f.write(f"{time.time()}\n")
        self.assertFalse(_is_write_lock_stale(lockfile))

    def test_old_timestamp_is_stale(self):
        """A lockfile with a live PID but very old timestamp is stale."""
        lockfile = os.path.join(self._tmpdir, "test.lock")
        with open(lockfile, "w") as f:
            f.write(f"{os.getpid()}\n")
            f.write(f"{time.time() - 100}\n")
        self.assertTrue(_is_write_lock_stale(lockfile))

    def test_unreadable_file_is_stale(self):
        """A lockfile that can't be parsed is treated as stale."""
        lockfile = os.path.join(self._tmpdir, "test.lock")
        with open(lockfile, "w") as f:
            f.write("garbage\n")
        self.assertTrue(_is_write_lock_stale(lockfile))


if __name__ == "__main__":
    unittest.main()
