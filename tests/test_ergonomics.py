"""PLAN-2.1 F2.1: ergonomics of the human gate.

The approval is the one thing a human must do by hand, and in 2.0 doing it
meant typing three flags correctly. Every flag that can be inferred is a
chance to mistype the change name at the exact moment a human is trying to
authorise work — so `--context` defaults to the working directory, `--by`
defaults to the OS user, and a mistyped change name now says so instead of
reporting a missing session.

The `--by` default reverses a decision 2.0 made deliberately. See
TestApproveDefaultsToTheOsUser for what that trade costs.
"""

import getpass
import os
import shutil
import tempfile
import unittest
from unittest import mock

from context_guard.guard import assets
from context_guard.guard.cli import parse_args
from context_guard.guard.commands import cmd_new, cmd_status
from context_guard.guard.errors import EXIT_GENERIC, EXIT_OK
from context_guard.guard.manifest import load_manifest
from context_guard.guard.transaction import cmd_approve, cmd_begin

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every context-scoped subcommand, with whatever else it requires to parse.
# `setup` is absent on purpose: it configures hosts, not a change, so it has
# no --context to default.
SUBCOMMANDS = {
    "begin": ["begin", "--phase", "PLAN"],
    "commit": ["commit", "--next-phase", "EXECUTE"],
    "approve": ["approve"],
    "rollback": ["rollback"],
    "checkpoint": ["checkpoint", "--summary", "x"],
    "check-lock": ["check-lock"],
    "claim": ["claim"],
    "acquire": ["acquire"],
    "release": ["release"],
    "claim-task": ["claim-task", "--task-id", "1.1"],
    "release-task": ["release-task", "--task-id", "1.1"],
    "check-completion": ["check-completion"],
    "validate": ["validate"],
    "next-task": ["next-task"],
    "status": ["status"],
    "doctor": ["doctor"],
    "archive": ["archive"],
    "new": ["new", "demo"],
    "list": ["list"],
    "migrate": ["migrate"],
}


class ErgonomicsCase(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.mkdtemp(prefix="guard_ergo_ctx_")
        # cg new consults HOME to decide whether to write the Antigravity
        # rule; redirected so these tests do not depend on what the developer
        # running them has installed.
        self.home = tempfile.mkdtemp(prefix="guard_ergo_home_")

    def tearDown(self):
        shutil.rmtree(self.context, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def planned_change(self, name):
        with mock.patch.dict(os.environ, {"HOME": self.home}):
            res = cmd_new(self.context, name)
        self.assertEqual(res.exit_code, EXIT_OK, res.message)


class TestContextDefaultsToTheWorkingDirectory(unittest.TestCase):
    """F2.1 point 1: `--context` stops being required everywhere."""

    def test_every_context_scoped_subcommand_defaults_to_cwd(self):
        for name, argv in SUBCOMMANDS.items():
            with self.subTest(subcommand=name):
                args = parse_args(argv)
                self.assertEqual(args.context, ".")

    def test_an_explicit_context_still_wins(self):
        """The default must not shadow the flag. A command that quietly
        operated on the working directory while the caller named another
        project would corrupt the wrong repository."""
        args = parse_args(["status", "--context", "/somewhere/else"])
        self.assertEqual(args.context, "/somewhere/else")

    def test_setup_has_no_context_flag(self):
        """`cg setup` configures hosts, not a change. A --context there would
        be a flag with nothing to point at."""
        args = parse_args(["setup"])
        self.assertFalse(hasattr(args, "context"))


class TestContextDefaultResolvesAtCallTime(ErgonomicsCase):
    """"." is resolved when the command runs, not when the module is
    imported. A default frozen at import time would silently point every
    invocation at whatever directory the process happened to start in."""

    def test_status_without_context_reads_the_current_directory(self):
        self.planned_change("alpha")
        cwd = os.getcwd()
        os.chdir(self.context)
        try:
            args = parse_args(["status"])
            res = cmd_status(args.context, change="alpha")
        finally:
            os.chdir(cwd)
        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        # The reported context is the proof: it has to be the directory the
        # process was in, not whatever "." meant when the module was imported.
        self.assertIn(f"CONTEXT: {self.context}", res.message)


class TestApproveDefaultsToTheOsUser(ErgonomicsCase):
    """F2.1 point 2, and the reversal of a 2.0 decision, recorded here because
    the reasoning matters more than the line of code.

    2.0 made `--by` required, arguing that defaulting to the environment made
    an agent-run approve indistinguishable from a human-run one whenever the
    shell reported a plausible name. That argument was always half true: an
    agent could pass any string it liked, so the flag never authenticated
    anyone — it only forced an active choice.

    F2.1 trades that forced choice for the thing the gate is actually for.
    The approval a human gives by hand is the product; three flags to type is
    friction on the only step that must not be automated, and friction on
    that step is what pushes people toward letting the agent do it. The
    authentication was, and remains, the harness permission prompt. `--by` is
    audit metadata: who to ask about this later, not proof of who ran it.
    """

    def test_approve_without_by_records_the_os_user(self):
        self.planned_change("alpha")

        res = cmd_approve(self.context, change="alpha")

        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        approval = load_manifest(self.context, "alpha")["approval"]
        self.assertEqual(approval["by"], getpass.getuser())
        self.assertTrue(approval["at"])

    def test_an_explicit_by_still_wins(self):
        """The override is the whole reason the flag survives: CI and teams
        need to record something other than the account that ran it."""
        self.planned_change("alpha")

        cmd_approve(self.context, by="ci-pipeline", change="alpha")

        self.assertEqual(
            load_manifest(self.context, "alpha")["approval"]["by"], "ci-pipeline")

    def test_an_empty_by_falls_back_rather_than_recording_nothing(self):
        """An empty string is not a name. Recording it would leave an
        approval in the manifest that names nobody, which is worse than
        either alternative."""
        self.planned_change("alpha")

        res = cmd_approve(self.context, by="   ", change="alpha")

        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        self.assertEqual(
            load_manifest(self.context, "alpha")["approval"]["by"], getpass.getuser())

    def test_the_approval_still_names_someone(self):
        """Whatever the defaulting rules, the audit trail's one job is to not
        be empty: a cooperative gate that cannot say who authorised the work
        has no value at all."""
        self.planned_change("alpha")
        cmd_approve(self.context, change="alpha")
        who = load_manifest(self.context, "alpha")["approval"]["by"]
        self.assertTrue(who and who.strip())


class TestAdaptersDropTheRedundantFlag(unittest.TestCase):
    """F2.1 point 1: "Los adapters se simplifican quitando `--context .`"."""

    def test_no_embedded_command_passes_context_dot(self):
        for host in ("claude-code", "opencode"):
            for relpath, text in assets.iter_host_files(host):
                with self.subTest(host=host, file=relpath):
                    self.assertNotIn("--context .", text)


class TestDocsDescribeTheFlaglessApproval(unittest.TestCase):
    """F2.1's acceptance criterion: "con un solo change activo, la aprobación
    completa es `cg approve` sin ningún flag; el tutorial sección 5 y 6 se
    actualizan a esa forma"."""

    def _read(self, name):
        with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as f:
            return f.read()

    def test_the_tutorial_shows_the_bare_command(self):
        text = self._read("TUTORIAL.es.md")
        self.assertNotIn("cg approve --context . --change", text)
        self.assertRegex(text, r"```bash\ncg approve\n```")

    def test_the_threat_model_calls_by_audit_metadata_not_authentication(self):
        """The plan requires this in words, not only in behaviour: a reader
        who takes the recorded name as proof of who approved has misread the
        one control the whole model rests on."""
        for name in ("README.md", "README.es.md"):
            text = self._read(name).lower()
            with self.subTest(readme=name):
                self.assertIn("--by", text)
                self.assertTrue(
                    "metadata" in text or "metadato" in text,
                    f"{name} must say what --by is (audit metadata)",
                )


if __name__ == "__main__":
    unittest.main()
