"""Tests for `cg init` command (Fase 2: Init / Scaffold)."""

import os
import shutil
import subprocess
import tempfile
import unittest

from context_guard.guard.cli import main, parse_args
from context_guard.guard.commands import cmd_init
from context_guard.guard.errors import EXIT_OK
from context_guard.guard.init_cmd import (
    OWNERSHIP_MARKER_BEGIN,
    OWNERSHIP_MARKER_END,
)


class TestInitCommand(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_init_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_init_fresh_directory(self):
        res = cmd_init(self.context)
        self.assertEqual(res.exit_code, EXIT_OK)

        # 1. AGENTS.md exists and has markers
        agents_path = os.path.join(self.context, "AGENTS.md")
        self.assertTrue(os.path.isfile(agents_path))
        with open(agents_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(OWNERSHIP_MARKER_BEGIN, content)
        self.assertIn(OWNERSHIP_MARKER_END, content)
        self.assertIn("Core Disciplines", content)
        self.assertIn("Context Guard Protocol", content)
        self.assertIn("cg approve", content)
        self.assertIn("Conventional Commits", content)

        # 2. CLAUDE.md exists and points to @AGENTS.md
        claude_path = os.path.join(self.context, "CLAUDE.md")
        self.assertTrue(os.path.isfile(claude_path))
        with open(claude_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "@AGENTS.md")

        # 3. .context-guard/phases/ exists
        phases_dir = os.path.join(self.context, ".context-guard", "phases")
        self.assertTrue(os.path.isdir(phases_dir))
        for p in ("plan.md", "execute.md", "verify.md"):
            self.assertTrue(os.path.isfile(os.path.join(phases_dir, p)))

        # 4. .githooks exist and are executable
        githooks_dir = os.path.join(self.context, ".githooks")
        self.assertTrue(os.path.isdir(githooks_dir))
        commit_msg = os.path.join(githooks_dir, "commit-msg")
        pre_commit = os.path.join(githooks_dir, "pre-commit")
        self.assertTrue(os.path.isfile(commit_msg))
        self.assertTrue(os.path.isfile(pre_commit))
        self.assertTrue(os.access(commit_msg, os.X_OK))
        self.assertTrue(os.access(pre_commit, os.X_OK))

    def test_init_is_idempotent(self):
        # Run init first time
        res1 = cmd_init(self.context)
        self.assertEqual(res1.exit_code, EXIT_OK)
        agents_path = os.path.join(self.context, "AGENTS.md")
        with open(agents_path, "r", encoding="utf-8") as f:
            content1 = f.read()

        # Run init second time
        res2 = cmd_init(self.context)
        self.assertEqual(res2.exit_code, EXIT_OK)
        with open(agents_path, "r", encoding="utf-8") as f:
            content2 = f.read()

        self.assertEqual(content1, content2)

    def test_init_preserves_existing_human_agents_md(self):
        # User already wrote their custom AGENTS.md
        agents_path = os.path.join(self.context, "AGENTS.md")
        human_text = "# Custom Company Rules\n- Never touch production DB directly.\n"
        with open(agents_path, "w", encoding="utf-8") as f:
            f.write(human_text)

        res = cmd_init(self.context)
        self.assertEqual(res.exit_code, EXIT_OK)

        with open(agents_path, "r", encoding="utf-8") as f:
            combined = f.read()

        # Custom rules must be preserved at top
        self.assertTrue(combined.startswith(human_text))
        # Context guard block appended cleanly
        self.assertIn(OWNERSHIP_MARKER_BEGIN, combined)
        self.assertIn("Context Guard Protocol", combined)

    def test_init_updates_owned_block_preserving_outside_text(self):
        agents_path = os.path.join(self.context, "AGENTS.md")
        initial = (
            "# My Custom Header\n\n"
            f"{OWNERSHIP_MARKER_BEGIN}\nOld version\n{OWNERSHIP_MARKER_END}\n\n"
            "# My Custom Footer\n"
        )
        with open(agents_path, "w", encoding="utf-8") as f:
            f.write(initial)

        res = cmd_init(self.context, test_cmd="pytest -v")
        self.assertEqual(res.exit_code, EXIT_OK)

        with open(agents_path, "r", encoding="utf-8") as f:
            updated = f.read()

        self.assertTrue(updated.startswith("# My Custom Header\n\n"))
        self.assertTrue(updated.endswith("# My Custom Footer\n"))
        self.assertIn("pytest -v", updated)
        self.assertNotIn("Old version", updated)

    def test_init_in_git_repo_sets_hooks_path(self):
        # Initialize git repo in context
        subprocess.run(["git", "init"], cwd=self.context, check=True, capture_output=True)

        res = cmd_init(self.context)
        self.assertEqual(res.exit_code, EXIT_OK)

        hooks_path = subprocess.check_output(
            ["git", "config", "core.hooksPath"], cwd=self.context, text=True
        ).strip()
        self.assertEqual(hooks_path, ".githooks")

    def test_init_no_hooks_flag(self):
        subprocess.run(["git", "init"], cwd=self.context, check=True, capture_output=True)

        res = cmd_init(self.context, no_hooks=True)
        self.assertEqual(res.exit_code, EXIT_OK)

        # .githooks directory should not have been created
        githooks_dir = os.path.join(self.context, ".githooks")
        self.assertFalse(os.path.exists(githooks_dir))

    def test_cli_parsing(self):
        args = parse_args(["init", "--context", "/some/path", "--no-hooks", "--test-cmd", "cargo test"])
        self.assertEqual(args.command, "init")
        self.assertEqual(args.context, "/some/path")
        self.assertTrue(args.no_hooks)
        self.assertEqual(args.test_cmd, "cargo test")


if __name__ == "__main__":
    unittest.main()
