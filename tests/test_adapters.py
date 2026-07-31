"""F3 acceptance checks for adapters/ (PLAN.md 0.7/F3): thin per-harness
wrappers that point at phases/*.md instead of duplicating their prose, plus
install.sh which wires them into a target project."""

import json
import os
import stat
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTERS_DIR = os.path.join(REPO_ROOT, "adapters")
CLAUDE_CODE_DIR = os.path.join(ADAPTERS_DIR, "claude-code")
INSTALL_SH = os.path.join(ADAPTERS_DIR, "install.sh")

DEAD_TERMS = ("watchdog", "hook_daemon", "/dev/tty", "sha-256", "sha256")


class TestClaudeCodeAdapter(unittest.TestCase):
    def _read(self, relpath):
        path = os.path.join(CLAUDE_CODE_DIR, relpath)
        self.assertTrue(os.path.exists(path), f"adapters/claude-code/{relpath} is missing")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_new_and_continue_commands_exist(self):
        for name in ("new.md", "continue.md"):
            self._read(os.path.join("commands", name))

    def test_commands_stay_thin(self):
        # PLAN.md 0.7: "10-20 líneas cada uno" — thin pointers, not duplicated prose.
        for name in ("new.md", "continue.md"):
            text = self._read(os.path.join("commands", name))
            line_count = len(text.splitlines())
            self.assertLessEqual(
                line_count, 20,
                f"commands/{name} has {line_count} lines, adapters must stay thin",
            )

    def test_commands_point_at_phases_not_duplicate_them(self):
        new_text = self._read(os.path.join("commands", "new.md"))
        self.assertIn("phases/plan.md", new_text)
        continue_text = self._read(os.path.join("commands", "continue.md"))
        for phase_file in ("phases/plan.md", "phases/execute.md", "phases/verify.md"):
            self.assertIn(phase_file, continue_text)

    def test_new_command_uses_cg_new(self):
        text = self._read(os.path.join("commands", "new.md"))
        self.assertIn("cg new", text)

    def test_settings_snippet_puts_approve_on_ask_list(self):
        text = self._read("settings.snippet.json")
        data = json.loads(text)
        ask_list = data.get("permissions", {}).get("ask", [])
        self.assertTrue(
            any("cg approve" in entry for entry in ask_list),
            "settings.snippet.json must put cg approve on the ask list (PLAN.md 0.6)",
        )

    def test_no_dead_references(self):
        for name in ("commands/new.md", "commands/continue.md"):
            text = self._read(name).lower()
            for term in DEAD_TERMS:
                self.assertNotIn(term, text, f"{name} references dead state-guard machinery: {term}")


class TestPermissionDocsPerHarness(unittest.TestCase):
    """F4: "Documentar la configuración de permisos por harness en cada
    adapter". PLAN.md 0.6 names the harness permission prompt as the only hard
    control in the whole model — an adapter that installs the protocol without
    it ships the cooperative half and calls it enforcement.
    """

    HOSTS = ("claude-code", "opencode", "antigravity")

    def _permissions_doc(self, host):
        path = os.path.join(ADAPTERS_DIR, host, "PERMISSIONS.md")
        self.assertTrue(
            os.path.exists(path),
            f"adapters/{host}/PERMISSIONS.md is missing — each harness must "
            "document how to put cg approve behind a human confirmation",
        )
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_every_host_documents_how_to_gate_approve(self):
        for host in self.HOSTS:
            text = self._permissions_doc(host)
            self.assertIn("cg approve", text, f"adapters/{host}/PERMISSIONS.md must name the command")

    def test_docs_are_honest_about_what_the_prompt_guarantees(self):
        """0.6 requires each layer to be honest about what it guarantees. An
        adapter that promises the permission prompt stops a determined agent
        repeats state-guard's crypto-gate mistake in a config file."""
        for host in self.HOSTS:
            text = self._permissions_doc(host).lower()
            self.assertTrue(
                "cooperative" in text,
                f"adapters/{host}/PERMISSIONS.md must say what is cooperative "
                "and what is hard (PLAN.md 0.6)",
            )

    def test_unverified_hosts_say_so(self):
        """PLAN.md backlog: the OpenCode and Antigravity adapters were never run
        against a real host. Documenting them as if they were is the kind of
        claim the audits exist to falsify."""
        for host in ("opencode", "antigravity"):
            text = self._permissions_doc(host).lower()
            self.assertIn("unverified", text)

    def test_claude_code_doc_carries_the_exact_snippet(self):
        """F4 asks for "el snippet exacto de settings.json" for Claude Code."""
        text = self._permissions_doc("claude-code")
        self.assertIn("settings.json", text)
        self.assertIn('"ask"', text)
        self.assertIn("Bash(cg approve*)", text)

    def test_opencode_snippet_declares_the_permission(self):
        path = os.path.join(ADAPTERS_DIR, "opencode", "agent.snippet.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        agent = data["context-guard"]
        permission = agent.get("permission", {})
        bash_rules = permission.get("bash", {})
        self.assertTrue(
            any("approve" in pattern and mode == "ask"
                for pattern, mode in bash_rules.items()),
            "opencode/agent.snippet.json must ask before running cg approve",
        )


class TestInstallSh(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(INSTALL_SH), "adapters/install.sh is missing")
        with open(INSTALL_SH, "r", encoding="utf-8") as f:
            self.text = f.read()

    def test_is_executable(self):
        mode = os.stat(INSTALL_SH).st_mode
        self.assertTrue(mode & stat.S_IXUSR, "adapters/install.sh must be executable")

    def test_no_dead_daemon_or_crypto_gate_references(self):
        lowered = self.text.lower()
        for term in DEAD_TERMS:
            self.assertNotIn(term, lowered, f"install.sh references dead machinery: {term}")

    def test_installs_claude_code_commands_into_target_project(self):
        # Resolved by the human: per-project install, not global — Claude
        # Code's own convention for team-shared slash commands.
        self.assertIn(".claude/commands", self.text)

    def test_copies_phases_into_target_project(self):
        self.assertIn("phases", self.text)
        self.assertIn(".context-guard", self.text)


if __name__ == "__main__":
    unittest.main()
