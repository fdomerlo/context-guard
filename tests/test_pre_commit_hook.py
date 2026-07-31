"""Adversarial tests for the promoted pre-commit hook (PLAN.md 0.6 layer 3).

The hook is the only layer that runs outside the agent's process, so it is the
only one that still applies when the agent ignores the protocol entirely. Its
failure modes are asymmetric: a hook that wrongly blocks teaches the user to
export CONTEXT_GUARD_BYPASS=1 permanently, which disables the layer far more
thoroughly than a missing check would.

Each test drives the real script through a real git repository in a tempdir —
the hook reads git's index, so mocking it would test something else.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.commands import cmd_approve, cmd_new
from context_guard.guard.manifest import load_manifest, save_manifest
from context_guard.guard.transaction import cmd_commit, cmd_rollback
from context_guard.guard.paths import get_paths
from context_guard.guard.errors import EXIT_OK

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO_ROOT, ".githooks", "pre-commit")

SPANISH_LEFTOVERS = ("RECHAZADO", "registrado", "archivos", "Utiliza", "umbral")


@unittest.skipUnless(shutil.which("git"), "git is required to exercise the hook")
class HookTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        # realpath: the hook resolves the repo root through git, and the
        # assertions below read files back from the same path.
        self.repo = os.path.realpath(tempfile.mkdtemp(prefix="guard_hook_"))
        os.chdir(self.repo)
        self._git("init", "-q")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.repo, ignore_errors=True)

    # -- helpers ---------------------------------------------------------

    def _git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True,
            capture_output=True, text=True,
        )

    def stage(self, *relpaths):
        for relpath in relpaths:
            path = os.path.join(self.repo, relpath)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("content\n")
        self._git("add", *relpaths)

    def run_hook(self, **env_overrides):
        env = {k: v for k, v in os.environ.items() if not k.startswith("CONTEXT_GUARD_")}
        env.update(env_overrides)
        return subprocess.run(
            [sys.executable, HOOK], cwd=self.repo,
            capture_output=True, text=True, env=env,
        )

    def idle_change(self, name):
        """A change that exists but has engaged nothing: no completed phase and
        no open transaction. This is what an agent that ignored the protocol
        leaves behind, so it must not count as protocol engaged."""
        self.assertEqual(cmd_new(self.repo, name).exit_code, EXIT_OK)
        self.assertEqual(cmd_rollback(self.repo, change=name).exit_code, EXIT_OK)

    def executing_change(self, name):
        """Drive a change to lock_phase=EXECUTE through the public commands."""
        self.assertEqual(cmd_new(self.repo, name).exit_code, EXIT_OK)
        p = get_paths(self.repo, name)
        with open(os.path.join(p["base"], "objective.md"), "w") as f:
            f.write("# Objective\nReal work.\n")
        with open(p["tasks"], "w") as f:
            f.write("- [ ] 1.1 Do the work\n")
        self.assertEqual(cmd_approve(self.repo, by="tester", change=name).exit_code, EXIT_OK)
        self.assertEqual(cmd_commit(self.repo, "EXECUTE", change=name).exit_code, EXIT_OK)

    def set_manifest_key(self, change, key, value):
        m = load_manifest(self.repo, change)
        m[key] = value
        save_manifest(self.repo, m, change)


class TestHookBlocksUnprotocolledWork(HookTestCase):
    def test_large_commit_without_a_session_is_rejected(self):
        """F4 acceptance criterion. The perimeter check: no context-guard state
        at all, five files staged, nothing to justify them."""
        self.stage("a.py", "b.py", "c.py", "d.py", "e.py")

        res = self.run_hook()

        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("context-guard", res.stderr)

    def test_small_commit_is_never_touched(self):
        """Below the threshold the hook must stay out of the way entirely —
        a gate that fires on every two-line fix gets uninstalled."""
        self.stage("a.py")

        self.assertEqual(self.run_hook().returncode, 0)

    def test_idle_change_does_not_count_as_protocol_engaged(self):
        """Creating a change is not doing the work. If the mere existence of a
        manifest satisfied the hook, `cg new` would become the bypass."""
        self.idle_change("alpha")
        self.stage("a.py", "b.py", "c.py", "d.py")

        self.assertEqual(self.run_hook().returncode, 1)


class TestBypassIsAuditedNotSilent(HookTestCase):
    """F4 acceptance criterion, and 0.4's "mejor idea de gobernanza": the door
    stays open, but nobody walks through it unrecorded."""

    def bypass_log(self):
        path = os.path.join(self.repo, ".context-guard", "bypass.log")
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_bypass_allows_the_commit_and_logs_the_reason(self):
        self.stage("a.py", "b.py", "c.py", "d.py")

        res = self.run_hook(
            CONTEXT_GUARD_BYPASS="1",
            CONTEXT_GUARD_BYPASS_REASON="hotfix for the outage",
        )

        self.assertEqual(res.returncode, 0, res.stderr)
        log = self.bypass_log()
        self.assertIn("hotfix for the outage", log)
        self.assertIn("a.py", log)

    def test_bypass_without_a_reason_is_still_logged(self):
        """An unlogged bypass is a bypass that, to the auditor, never happened.
        Refusing the bypass outright would only push the user to `--no-verify`,
        which leaves no trace at all — so it is recorded, not blocked."""
        self.stage("a.py", "b.py", "c.py", "d.py")

        res = self.run_hook(CONTEXT_GUARD_BYPASS="1")

        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(self.bypass_log().strip())

    def test_bypass_entries_accumulate(self):
        """One line per bypass. A log that overwrites itself hides the pattern
        that matters: not the single bypass, but the habit."""
        self.stage("a.py", "b.py", "c.py", "d.py")
        self.run_hook(CONTEXT_GUARD_BYPASS="1", CONTEXT_GUARD_BYPASS_REASON="first")
        self.stage("e.py")
        self.run_hook(CONTEXT_GUARD_BYPASS="1", CONTEXT_GUARD_BYPASS_REASON="second")

        log = self.bypass_log()
        self.assertIn("first", log)
        self.assertIn("second", log)
        self.assertEqual(len(log.strip().splitlines()), 2)


class TestHookSpeaksEnglish(HookTestCase):
    """CLAUDE.md rule 4 / PLAN.md 0.2: everything a machine or a stranger reads
    is in English. The hook's output is the most user-facing string we ship."""

    def test_rejection_message_is_english(self):
        self.stage("a.py", "b.py", "c.py", "d.py")
        res = self.run_hook()
        for term in SPANISH_LEFTOVERS:
            self.assertNotIn(term, res.stderr)

    def test_bypass_message_is_english(self):
        self.stage("a.py", "b.py", "c.py", "d.py")
        res = self.run_hook(CONTEXT_GUARD_BYPASS="1", CONTEXT_GUARD_BYPASS_REASON="x")
        for term in SPANISH_LEFTOVERS:
            self.assertNotIn(term, res.stderr)

    def test_hook_source_is_english(self):
        with open(HOOK, "r", encoding="utf-8") as f:
            source = f.read()
        for term in ("Bloquea", "iniciada", "archivos", "Utiliza", "Excepción"):
            self.assertNotIn(term, source)


class TestHookSeesTheMultiChangeLayout(HookTestCase):
    """F2 moved every manifest to .context-guard/changes/{name}/. The hook was
    still reading .context-guard/manifest.json, which now never exists — so it
    rejected every large commit no matter how correctly the agent behaved."""

    def test_open_transaction_in_a_change_counts_as_engaged(self):
        cmd_new(self.repo, "alpha")  # leaves a PLAN transaction in progress
        self.stage("a.py", "b.py", "c.py", "d.py")

        res = self.run_hook()

        self.assertEqual(res.returncode, 0, res.stderr)

    def test_completed_phase_in_a_change_counts_as_engaged(self):
        self.executing_change("alpha")
        self.stage("a.py", "b.py", "c.py", "d.py")

        self.assertEqual(self.run_hook().returncode, 0)

    def test_one_engaged_change_covers_the_commit(self):
        """A repo with several changes only needs one of them to be engaged:
        the staged files belong to whichever change is doing the work, and the
        hook cannot tell which without guessing."""
        self.idle_change("alpha")
        self.executing_change("beta")
        self.stage("a.py", "b.py", "c.py", "d.py")

        self.assertEqual(self.run_hook().returncode, 0)

    def test_legacy_flat_layout_still_recognised(self):
        """1.x repos that have not run `cg migrate` yet must not be blocked by
        an upgrade of the hook alone."""
        base = os.path.join(self.repo, ".context-guard")
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as f:
            f.write('{"completed_phases": ["PLAN"], "transaction": {"txn_status": "idle"}}')
        self.stage("a.py", "b.py", "c.py", "d.py")

        self.assertEqual(self.run_hook().returncode, 0)


class TestHookFailsOpenOnBrokenState(HookTestCase):
    """A corrupt manifest is a context-guard problem. Making it a git problem
    too would leave the user unable to commit the fix."""

    def test_corrupt_manifest_does_not_crash_the_hook(self):
        self.idle_change("alpha")
        p = get_paths(self.repo, "alpha")
        with open(p["manifest"], "w", encoding="utf-8") as f:
            f.write("{not json")
        self.stage("a.py", "b.py", "c.py", "d.py")

        res = self.run_hook()

        self.assertIn(res.returncode, (0, 1), res.stderr)
        self.assertNotIn("Traceback", res.stderr)


class TestThresholdIsConfigurable(HookTestCase):
    """F4: "umbral configurable vía manifest o env"."""

    def test_threshold_from_the_manifest_raises_the_bar(self):
        self.idle_change("alpha")
        self.set_manifest_key("alpha", "hook", {"file_threshold": 6})
        self.stage("a.py", "b.py", "c.py", "d.py", "e.py")

        self.assertEqual(self.run_hook().returncode, 0)

    def test_manifest_threshold_still_blocks_above_it(self):
        self.idle_change("alpha")
        self.set_manifest_key("alpha", "hook", {"file_threshold": 3})
        self.stage("a.py", "b.py", "c.py", "d.py")

        self.assertEqual(self.run_hook().returncode, 1)

    def test_the_strictest_configured_threshold_wins(self):
        """Two changes, two thresholds. Picking "the first one" would resolve a
        repo-wide policy by directory order — the alphabetical-guess bug PLAN.md
        1.3 forbids by name. The minimum is order-independent and errs toward
        asking."""
        self.idle_change("alpha")
        self.idle_change("beta")
        self.set_manifest_key("alpha", "hook", {"file_threshold": 9})
        self.set_manifest_key("beta", "hook", {"file_threshold": 3})
        self.stage("a.py", "b.py", "c.py", "d.py")

        self.assertEqual(self.run_hook().returncode, 1)

    def test_env_overrides_the_manifest(self):
        """The env var is the per-invocation escape hatch; it has to win over
        committed configuration or it is not an escape hatch."""
        self.idle_change("alpha")
        self.set_manifest_key("alpha", "hook", {"file_threshold": 9})
        self.stage("a.py", "b.py", "c.py", "d.py")

        self.assertEqual(self.run_hook(CONTEXT_GUARD_FILE_THRESHOLD="2").returncode, 1)

    def test_unparseable_threshold_falls_back_to_the_default(self):
        """A typo in the manifest must not silently disable the hook."""
        self.idle_change("alpha")
        self.set_manifest_key("alpha", "hook", {"file_threshold": "many"})
        self.stage("a.py", "b.py", "c.py", "d.py")

        self.assertEqual(self.run_hook().returncode, 1)


class TestFilesInScopeIsAdvisoryOnly(HookTestCase):
    """F4: "chequeo soft de files_in_scope (warning, no bloqueo, para no
    pelearte con tu propio flujo)"."""

    def test_out_of_scope_files_warn_but_never_block(self):
        self.executing_change("alpha")
        self.set_manifest_key("alpha", "files_in_scope", ["src/"])
        self.stage("src/a.py", "src/b.py", "docs/readme.md", "other.py")

        res = self.run_hook()

        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("WARN", res.stderr)
        self.assertIn("other.py", res.stderr)

    def test_in_scope_files_produce_no_warning(self):
        self.executing_change("alpha")
        self.set_manifest_key("alpha", "files_in_scope", ["src/", "setup.py"])
        self.stage("src/a.py", "src/nested/b.py", "setup.py", "src/c.py")

        res = self.run_hook()

        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("WARN", res.stderr)

    def test_guard_artifacts_are_always_in_scope(self):
        """The agent's own state files are written by every phase. Warning about
        them on every commit is how a soft check gets tuned out."""
        self.executing_change("alpha")
        self.set_manifest_key("alpha", "files_in_scope", ["src/"])
        self.stage("src/a.py", "src/b.py", "src/c.py")
        self._git("add", "-A", ".context-guard")

        res = self.run_hook()

        self.assertNotIn("WARN", res.stderr)

    def test_empty_files_in_scope_warns_about_nothing(self):
        """An unfilled files_in_scope means "not declared", not "nothing is
        allowed" — the manifest ships with it empty."""
        self.executing_change("alpha")
        self.stage("a.py", "b.py", "c.py", "d.py")

        res = self.run_hook()

        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("WARN", res.stderr)

    def test_scope_is_only_checked_while_executing(self):
        """In PLAN the scope has not been decided yet, so every file is out of
        it. Warning there would train the user to ignore the warning."""
        cmd_new(self.repo, "alpha")
        self.set_manifest_key("alpha", "files_in_scope", ["src/"])
        self.stage("a.py", "b.py", "c.py", "d.py")

        res = self.run_hook()

        self.assertNotIn("WARN", res.stderr)


if __name__ == "__main__":
    unittest.main()
