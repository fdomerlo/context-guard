"""F5 acceptance criterion, verbatim: "vos leés el README como si fueras un
extraño y no encontrás ninguna claim que las auditorías puedan falsar." Every
test here turns a specific claim the README makes into an assertion checked
against the actual code, the same way an audit finding becomes a test in every
other phase. A README claim nothing here checks is a claim nobody verified.
"""

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard import errors as guard_errors
from context_guard import mcp_server

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(REPO_ROOT, "README.md")
CLI_PATH = os.path.join(REPO_ROOT, "context_guard", "guard", "cli.py")

SPANISH_INDICATORS = ["á", "é", "í", "ó", "ú", "ñ", "¿", "¡"]

# Same list test_adapters.py checks the adapters against: leftovers from the
# state-guard machinery PLAN.md 0.4 kills.
DEAD_TERMS = ("watchdog", "hook_daemon", "/dev/tty", "sha-256", "sha256")

PITCH = (
    "The transactional memory layer for AI coding agents — your context "
    "survives crashes, compaction, and session loss"
)


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class ReadmeTestCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(README_PATH), "README.md is missing")
        self.text = _read(README_PATH)


class TestPitchAndLanguage(ReadmeTestCase):
    def test_pitch_sentence_is_present_verbatim(self):
        self.assertIn(PITCH, self.text, "PLAN.md 0.7's one-sentence pitch must appear verbatim")

    def test_is_english(self):
        spanish_count = sum(self.text.lower().count(c) for c in SPANISH_INDICATORS)
        self.assertLessEqual(spanish_count, 5, "README.md must be in English (PLAN.md 0.2)")

    def test_no_dead_machinery_referenced(self):
        lowered = self.text.lower()
        for term in DEAD_TERMS:
            self.assertNotIn(term, lowered, f"README.md references dead state-guard machinery: {term}")

    def test_links_to_the_spanish_mirror(self):
        self.assertIn("README.es.md", self.text)

    def test_ci_badge_points_at_the_real_workflow(self):
        """PLAN.md F7: only the CI badge, verifiable right now via GitHub
        Actions — no PyPI version badge until the package is actually
        published, or it would 404/show nothing the day someone clicks it."""
        self.assertIn(
            "github.com/fdomerlo/context-guard/actions/workflows/ci.yml/badge.svg",
            self.text,
        )
        self.assertNotIn("img.shields.io/pypi", self.text)


class TestExitCodeTable(ReadmeTestCase):
    """The exact bug this phase exists to catch: the old table described
    EXIT_APPROVAL_REQUIRED as reserved for a flow that shipped in F4."""

    TABLE_ROW_RE = re.compile(r"\[(\d)\]`\s*\|\s*`(EXIT_\w+)`")

    def test_every_documented_code_matches_errors_py(self):
        rows = self.TABLE_ROW_RE.findall(self.text)
        self.assertTrue(rows, "no exit code table rows found in README.md")
        for code_str, name in rows:
            with self.subTest(code=name):
                actual = getattr(guard_errors, name, None)
                self.assertIsNotNone(actual, f"errors.py has no {name}")
                self.assertEqual(
                    int(code_str), actual,
                    f"README documents {name} as {code_str}, errors.py says {actual}",
                )

    def test_all_seven_codes_are_documented(self):
        rows = self.TABLE_ROW_RE.findall(self.text)
        documented = {name for _, name in rows}
        expected = {
            "EXIT_OK", "EXIT_GENERIC", "EXIT_LOCK_HELD", "EXIT_LOCK_CONTENDED",
            "EXIT_VALIDATION", "EXIT_BAD_TRANSITION", "EXIT_APPROVAL_REQUIRED",
        }
        self.assertEqual(documented, expected)

    def test_approval_required_is_not_described_as_unimplemented(self):
        """The exact drift found at the top of this phase: the old README
        called code 6 "reserved for the cg approve flow", which shipped in F4."""
        match = re.search(r"`6`.*?\n", self.text) or re.search(r"\[6\]`.*", self.text)
        self.assertIsNotNone(match)
        row_text = match.group(0).lower()
        for hedge in ("reservado", "reserved for", "not yet", "no shipped"):
            self.assertNotIn(hedge, row_text)


class TestCliCommandsAreReal(ReadmeTestCase):
    # Words that plausibly follow "cg " in prose without naming a subcommand.
    # NOT used to decide pass/fail — only to avoid false alarms on English
    # grammar; every word that survives this list must be a real subcommand.
    PROSE_WORDS = {
        "is", "was", "the", "will", "can", "and", "or", "a", "an", "to", "for",
        "with", "when", "in", "on", "at", "if", "cli", "mcp", "command",
        "commands", "subcommand", "subcommands", "tool", "binary", "requires",
        "needs", "runs", "reads", "writes", "does", "it", "that", "also",
        "not", "you", "your", "context", "change", "phase", "invocation",
        "invocations", "as", "of", "itself", "before", "after", "so",
    }

    def test_mentioned_subcommands_exist_in_cli_py(self):
        with open(CLI_PATH, "r", encoding="utf-8") as f:
            cli_source = f.read()
        valid_commands = set(re.findall(r'add_parser\("([\w-]+)"\)', cli_source))
        self.assertTrue(valid_commands, "could not extract subcommands from cli.py")

        mentioned = set(re.findall(r"\bcg (?:--format \w+ )?([a-z][a-z-]*)\b", self.text))
        candidates = mentioned - self.PROSE_WORDS

        self.assertTrue(candidates, "no `cg <command>` invocations found in README.md")
        for cmd in sorted(candidates):
            with self.subTest(command=cmd):
                self.assertIn(cmd, valid_commands, f"README mentions `cg {cmd}`, which cli.py does not define")

    def test_approve_is_documented(self):
        self.assertIn("cg approve", self.text)


class TestMcpToolsAreReal(ReadmeTestCase):
    def test_every_registered_tool_is_mentioned(self):
        tool_names = {t.name for t in _list_mcp_tools()}
        self.assertEqual(
            tool_names,
            {
                "begin_transaction", "commit_transaction", "rollback_transaction",
                "save_checkpoint", "get_status", "check_completion", "validate",
                "next_task",
            },
            "the set of registered MCP tools drifted; update this test's expectation",
        )
        for name in tool_names:
            with self.subTest(tool=name):
                self.assertIn(name, self.text, f"MCP tool {name} is registered but not documented")

    def test_approve_is_not_presented_as_an_mcp_tool(self):
        """PLAN.md 0.6: the harness permission prompt on `cg approve` is the
        only hard control in the model, and an MCP tool would route around it.
        mcp_server.py deliberately does not register one; the README must not
        imply otherwise."""
        tool_names = {t.name for t in _list_mcp_tools()}
        self.assertNotIn("approve", tool_names)
        self.assertIn("not an MCP tool", self.text.replace("isn't", "is not"))


def _list_mcp_tools():
    import asyncio
    return asyncio.run(mcp_server.mcp.list_tools())


class TestThreatModel(ReadmeTestCase):
    """PLAN.md 0.6: 'dos párrafos que digan explícitamente qué es cooperativo
    y qué es duro'."""

    def test_threat_model_section_exists(self):
        self.assertRegex(self.text, r"#+\s*Threat Model")

    def test_names_the_cooperative_and_hard_layers(self):
        self.assertIn("cooperative", self.text.lower())
        self.assertIn("permission prompt", self.text.lower())

    def test_states_cg_approve_is_shell_reachable(self):
        """The honesty PLAN.md 0.6 asks for: an agent with a shell can run
        `cg approve` itself. A Threat Model that omits this is decoration."""
        self.assertIn("shell", self.text.lower())


class TestComparisonTable(ReadmeTestCase):
    def test_names_the_three_alternatives(self):
        for name in ("spec-kit", "Kiro", "AGENTS.md"):
            self.assertIn(name, self.text)

    def test_frames_them_as_complementary_not_competing(self):
        # PLAN.md 0.7: "úsanos juntos" — the honest framing is "use us
        # together", not "instead of them".
        self.assertIn("together", self.text.lower())


class TestHookSectionReflectsF4(ReadmeTestCase):
    def test_documents_the_configurable_threshold(self):
        self.assertIn("file_threshold", self.text)
        self.assertIn("CONTEXT_GUARD_FILE_THRESHOLD", self.text)

    def test_documents_the_scope_warning(self):
        self.assertIn("files_in_scope", self.text)

    def test_documents_the_bypass_log(self):
        self.assertIn("bypass.log", self.text)


class TestScaffoldClaim(ReadmeTestCase):
    def test_five_files_claim_matches_the_code(self):
        transaction_path = os.path.join(REPO_ROOT, "context_guard", "guard", "transaction.py")
        with open(transaction_path, "r", encoding="utf-8") as f:
            source = f.read()
        # Scoped to the scaffold dict's own "<file>.md": "[PENDING] ..." lines,
        # not every occurrence of the literal "[PENDING]" in the module (the
        # PLAN->EXECUTE and VERIFY->ARCHIVE hard gates also test for it).
        artifact_count = len(re.findall(r'"\S+\.md":\s*"\[PENDING\]', source))
        self.assertEqual(artifact_count, 5, "transaction.py's scaffold count changed; update this test")
        self.assertIn("five", self.text.lower())


@unittest.skipUnless(shutil.which("bash"), "bash is required to run the quickstart")
class TestQuickstartActuallyRuns(ReadmeTestCase):
    """The single worst kind of README lie: a copy-pasteable command block
    that does not actually work. This extracts the fenced ```bash quickstart
    block and runs it for real against a scratch project."""

    def _quickstart_block(self):
        match = re.search(
            r"<!-- quickstart:start -->.*?```bash\n(.*?)```.*?<!-- quickstart:end -->",
            self.text, re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "no <!-- quickstart:start/end --> markers found around a ```bash block",
        )
        return match.group(1)

    def test_quickstart_is_five_cg_commands(self):
        script = self._quickstart_block()
        commands = re.findall(r"^cg\s+([a-z][a-z-]*)", script, re.MULTILINE)
        self.assertEqual(
            len(commands), 5,
            f"quickstart must be exactly 5 `cg` commands, found {len(commands)}: {commands}",
        )

    def test_quickstart_runs_to_completion(self):
        script = self._quickstart_block()
        tmpdir = tempfile.mkdtemp(prefix="guard_readme_quickstart_")
        bindir = tempfile.mkdtemp(prefix="guard_readme_bin_")
        try:
            # `cg` is not installed in the test environment; shim it onto PATH
            # so the extracted script runs completely unmodified — that is
            # the whole point of testing the literal fenced block.
            shim = os.path.join(bindir, "cg")
            with open(shim, "w", encoding="utf-8") as f:
                f.write(f"#!/usr/bin/env bash\nexec {sys.executable} -m context_guard.guard.cli \"$@\"\n")
            os.chmod(shim, os.stat(shim).st_mode | stat.S_IEXEC)

            env = dict(os.environ)
            env["PATH"] = bindir + os.pathsep + env["PATH"]
            env["PYTHONPATH"] = REPO_ROOT
            proc = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", script],
                cwd=tmpdir, env=env, capture_output=True, text=True,
            )
            self.assertEqual(
                proc.returncode, 0,
                f"quickstart failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            shutil.rmtree(bindir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
