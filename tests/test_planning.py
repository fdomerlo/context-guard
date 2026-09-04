"""Tests for `cg plan` command (Fase 3: Planning)."""

import os
import shutil
import tempfile
import unittest

from context_guard.guard.cli import parse_args
from context_guard.guard.commands import cmd_approve, cmd_plan
from context_guard.guard.errors import EXIT_APPROVAL_REQUIRED, EXIT_OK, EXIT_VALIDATION
from context_guard.guard.manifest import load_manifest
from context_guard.guard.paths import get_paths
from context_guard.guard.planning import slugify_requirement
from context_guard.guard.transaction import cmd_commit

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    return os.path.join(FIXTURES, name)


class TestPlanning(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_plan_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_slugify_requirement(self):
        self.assertEqual(slugify_requirement("Implement OAuth2 authentication"), "oauth2-authentication")
        self.assertEqual(slugify_requirement("Fix #123 memory leak"), "fix-123-memory-leak")
        self.assertEqual(slugify_requirement("Agregar endpoint de usuarios"), "endpoint-usuarios")
        self.assertTrue(slugify_requirement("").isalnum() or "-" in slugify_requirement(""))

    def test_plan_from_requirement_string(self):
        res = cmd_plan(self.context, requirement="Implement OAuth2 authentication")
        self.assertEqual(res.exit_code, EXIT_OK)
        self.assertIn("PLAN_CREATED", res.message)
        self.assertIn("oauth2-authentication", res.message)

        # Manifest assertions
        m = load_manifest(self.context, "oauth2-authentication")
        self.assertIsNotNone(m)
        self.assertEqual(m["lock_phase"], "PLAN")
        self.assertEqual(m["requirement"], "Implement OAuth2 authentication")
        self.assertEqual(len(m["phases"]), 2)
        self.assertEqual(m["phases"][0]["id"], "F1")
        self.assertEqual(m["phases"][1]["id"], "F2")
        self.assertEqual(m["active_phase_id"], "F1")
        self.assertIsNone(m.get("approval"))

        # Derived artifacts exist
        p = get_paths(self.context, "oauth2-authentication")
        plan_path = os.path.join(p["base"], "plan.md")
        tasks_path = os.path.join(p["base"], "tasks.md")
        obj_path = os.path.join(p["base"], "objective.md")

        self.assertTrue(os.path.isfile(plan_path))
        self.assertTrue(os.path.isfile(tasks_path))
        self.assertTrue(os.path.isfile(obj_path))

        with open(plan_path, "r", encoding="utf-8") as f:
            plan_text = f.read()
        self.assertIn("# Plan: oauth2-authentication", plan_text)
        self.assertIn("F1 — Core Implementation", plan_text)
        self.assertIn("F2 — Verification & Integration", plan_text)
        self.assertIn("Acceptance Criteria", plan_text)

        with open(tasks_path, "r", encoding="utf-8") as f:
            tasks_text = f.read()
        self.assertIn("F1", tasks_text)
        self.assertIn("- [ ] 1.1", tasks_text)

    def test_plan_requires_human_approval_to_execute(self):
        cmd_plan(self.context, requirement="Add user billing", name="billing")
        # Attempting commit without approve must fail with APPROVAL_REQUIRED
        commit_res = cmd_commit(self.context, "EXECUTE", change="billing")
        self.assertEqual(commit_res.exit_code, EXIT_APPROVAL_REQUIRED)
        self.assertIn("APPROVAL_REQUIRED", commit_res.message)

        # Once approved by human, commit succeeds
        cmd_approve(self.context, by="tester", change="billing")
        commit_ok = cmd_commit(self.context, "EXECUTE", change="billing")
        self.assertEqual(commit_ok.exit_code, EXIT_OK)

    def test_plan_with_custom_name_and_spec(self):
        res = cmd_plan(
            self.context,
            requirement="Setup caching layer",
            name="redis-cache",
            spec="Use redis-py with 5s connection timeout",
        )
        self.assertEqual(res.exit_code, EXIT_OK)
        m = load_manifest(self.context, "redis-cache")
        self.assertEqual(m["change_name"], "redis-cache")
        self.assertEqual(m["spec"], "Use redis-py with 5s connection timeout")

    def test_plan_from_legacy_plan_file(self):
        plan_file = fixture("plan_es.md")
        res = cmd_plan(self.context, from_plan=plan_file, name="unified-plan")
        self.assertEqual(res.exit_code, EXIT_OK)

        m = load_manifest(self.context, "unified-plan")
        self.assertIsNotNone(m)
        self.assertEqual(len(m["phases"]), 3)
        self.assertEqual(m["phases"][0]["id"], "F1")
        self.assertEqual(m["phases"][1]["id"], "F2")
        self.assertEqual(m["phases"][2]["id"], "F3")

        p = get_paths(self.context, "unified-plan")
        with open(os.path.join(p["base"], "plan.md"), "r", encoding="utf-8") as f:
            plan_text = f.read()
        self.assertIn("F1", plan_text)
        self.assertIn("F2", plan_text)
        self.assertIn("F3", plan_text)

    def test_plan_collision_fails(self):
        cmd_plan(self.context, requirement="Deploy monitoring", name="monitor")
        dup = cmd_plan(self.context, requirement="Deploy monitoring again", name="monitor")
        self.assertEqual(dup.exit_code, EXIT_VALIDATION)
        self.assertIn("CHANGE_EXISTS", dup.message)

    def test_plan_inspection_mode(self):
        cmd_plan(self.context, requirement="Setup telemetry", name="telemetry")
        res = cmd_plan(self.context, name="telemetry")
        self.assertEqual(res.exit_code, EXIT_OK)
        self.assertIn("Plan: telemetry", res.message)

    def test_cli_parsing(self):
        args = parse_args(["plan", "Implement search", "--name", "search-v2", "--spec", "Elasticsearch integration"])
        self.assertEqual(args.command, "plan")
        self.assertEqual(args.requirement, "Implement search")
        self.assertEqual(args.name, "search-v2")
        self.assertEqual(args.spec, "Elasticsearch integration")


if __name__ == "__main__":
    unittest.main()
