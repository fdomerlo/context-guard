"""F3 acceptance checks for adapters/ (PLAN.md 0.7/F3): thin per-harness
wrappers that point at phases/*.md instead of duplicating their prose, plus
install.sh which wires them into a target project."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
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
        # F6 6.0.7: unified across hosts as /cg-new and /cg-continue — Claude
        # Code's old /new and /continue collided conceptually with nothing,
        # but OpenCode's per-phase commands (/plan, /execute, /verify) did
        # not match, and "plan" collides with OpenCode's own built-in agent.
        for name in ("cg-new.md", "cg-continue.md"):
            self._read(os.path.join("commands", name))

    def test_commands_stay_thin(self):
        # PLAN.md 0.7: "10-20 líneas cada uno" — thin pointers, not duplicated prose.
        for name in ("cg-new.md", "cg-continue.md"):
            text = self._read(os.path.join("commands", name))
            line_count = len(text.splitlines())
            self.assertLessEqual(
                line_count, 20,
                f"commands/{name} has {line_count} lines, adapters must stay thin",
            )

    def test_commands_point_at_phases_not_duplicate_them(self):
        new_text = self._read(os.path.join("commands", "cg-new.md"))
        self.assertIn("phases/plan.md", new_text)
        continue_text = self._read(os.path.join("commands", "cg-continue.md"))
        for phase_file in ("phases/plan.md", "phases/execute.md", "phases/verify.md"):
            self.assertIn(phase_file, continue_text)

    def test_new_command_uses_cg_new(self):
        text = self._read(os.path.join("commands", "cg-new.md"))
        self.assertIn("cg new", text)

    def test_settings_snippet_puts_approve_on_ask_list(self):
        text = self._read("settings.snippet.json")
        data = json.loads(text)
        ask_list = data.get("permissions", {}).get("ask", [])
        self.assertTrue(
            any("cg approve" in entry for entry in ask_list),
            "settings.snippet.json must put cg approve on the ask list (PLAN.md 0.6)",
        )

    def test_settings_snippet_denies_manifest_edits(self):
        """F6 6.0.6: Claude Code never got the parity fix — editing
        manifest.json by hand skips the whole transaction protocol without
        ever touching a command the ask list would catch."""
        text = self._read("settings.snippet.json")
        data = json.loads(text)
        deny_list = data.get("permissions", {}).get("deny", [])
        self.assertIn("Edit(.context-guard/**/manifest.json)", deny_list)

    def test_no_dead_references(self):
        for name in ("commands/cg-new.md", "commands/cg-continue.md"):
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
        # F6 6.1: permission lives in the top-level permissions.snippet.json,
        # not duplicated inside the agent entry — one source of truth instead
        # of two files that can drift apart.
        path = os.path.join(ADAPTERS_DIR, "opencode", "permissions.snippet.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        bash_rules = data.get("permission", {}).get("bash", {})
        self.assertTrue(
            any("approve" in pattern and mode == "ask"
                for pattern, mode in bash_rules.items()),
            "opencode/permissions.snippet.json must ask before running cg approve",
        )


class TestNoStaleSlashCommandReferences(unittest.TestCase):
    """F6 6.0.7: renaming /new -> /cg-new and /continue -> /cg-continue is
    only a fix if nothing else in the repo still points at the old names —
    a doc telling the agent to run a command that no longer exists is worse
    than no doc at all."""

    STALE_PATTERNS = ("`/new`", "`/continue`", "commands/new.md", "commands/continue.md")

    FILES = (
        os.path.join(REPO_ROOT, "phases", "plan.md"),
        os.path.join(REPO_ROOT, "phases", "verify.md"),
        os.path.join(ADAPTERS_DIR, "claude-code", "PERMISSIONS.md"),
    )

    def test_no_file_references_the_old_command_names(self):
        for path in self.FILES:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            for pattern in self.STALE_PATTERNS:
                with self.subTest(file=path, pattern=pattern):
                    self.assertNotIn(pattern, text)


class TestOpenCodePermissionParity(unittest.TestCase):
    """F6 6.0.2/6.0.3: agent.snippet.json's `"tools"` block is deprecated
    since OpenCode v1.1.1 (merged into `permission`), and OpenCode never
    received the manifest-edit deny Claude Code has — the third enforcement
    layer (0.6) simply did not exist for this host."""

    def _agent_snippet(self):
        path = os.path.join(ADAPTERS_DIR, "opencode", "agent.snippet.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _permissions_snippet(self):
        path = os.path.join(ADAPTERS_DIR, "opencode", "permissions.snippet.json")
        self.assertTrue(os.path.exists(path), "adapters/opencode/permissions.snippet.json is missing")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_agent_snippet_has_no_deprecated_tools_key(self):
        agent = self._agent_snippet()["context-guard"]
        self.assertNotIn(
            "tools", agent,
            "\"tools\" was folded into \"permission\" as of OpenCode v1.1.1",
        )

    def test_agent_snippet_does_not_duplicate_the_permission_block(self):
        """Permission now lives once, in permissions.snippet.json — keeping a
        second copy inside the agent entry is exactly the kind of duplication
        that lets the two silently drift apart."""
        agent = self._agent_snippet()["context-guard"]
        self.assertNotIn("permission", agent)

    def test_permissions_snippet_denies_manifest_edits(self):
        data = self._permissions_snippet()
        edit_rules = data.get("permission", {}).get("edit", {})
        self.assertEqual(
            edit_rules.get(".context-guard/**/manifest.json"), "deny",
            "OpenCode never got the manifest-edit deny Claude Code has — "
            "closing that vector is the parity fix in F6",
        )

    def test_permissions_snippet_is_valid_opencode_config_shape(self):
        data = self._permissions_snippet()
        self.assertIn("$schema", data)
        self.assertIn("permission", data)


@unittest.skipUnless(shutil.which("bash"), "bash is required to run install.sh")
class InstallShRunCase(unittest.TestCase):
    """Base for tests that run install.sh for real against an isolated fake
    HOME and target project, rather than only inspecting its source. F6's
    bugs are behavioral (files landing in the wrong place, absolute paths
    leaking into generated content) — a source-text check cannot catch
    those, only actually running the script can."""

    def setUp(self):
        self.target = tempfile.mkdtemp(prefix="guard_install_target_")
        self.home = tempfile.mkdtemp(prefix="guard_install_home_")

    def tearDown(self):
        shutil.rmtree(self.target, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def run_install(self, *args, env_overrides=None):
        env = dict(os.environ)
        env["HOME"] = self.home
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            ["bash", INSTALL_SH, self.target, *args],
            env=env, capture_output=True, text=True,
        )


class TestOpenCodePermissionsAreInstalled(InstallShRunCase):
    def test_permissions_snippet_is_merged_into_the_opencode_config(self):
        res = self.run_install(env_overrides={"FORCE_OPENCODE": "1"})
        self.assertEqual(res.returncode, 0, res.stderr)

        cfg_path = os.path.join(self.home, ".config", "opencode", "opencode.jsonc")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        self.assertEqual(
            cfg.get("permission", {}).get("edit", {}).get(".context-guard/**/manifest.json"),
            "deny",
        )
        self.assertNotIn(
            "tools", cfg.get("agent", {}).get("context-guard", {}),
            "the deprecated tools key must not be installed into the target config",
        )

    def test_running_install_twice_does_not_duplicate_permission_entries(self):
        self.run_install(env_overrides={"FORCE_OPENCODE": "1"})
        res = self.run_install(env_overrides={"FORCE_OPENCODE": "1"})
        self.assertEqual(res.returncode, 0, res.stderr)

        cfg_path = os.path.join(self.home, ".config", "opencode", "opencode.jsonc")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # A dict merge is duplicate-proof by construction; this pins that a
        # future rewrite of the merge does not regress to a list-append that
        # would grow unboundedly across reinstalls.
        self.assertEqual(
            cfg["permission"]["bash"]["cg approve*"], "ask",
        )


class TestClaudeCodeDenyIsInstalled(InstallShRunCase):
    def test_deny_list_is_merged_into_claude_settings(self):
        res = self.run_install()
        self.assertEqual(res.returncode, 0, res.stderr)

        settings_path = os.path.join(self.target, ".claude", "settings.json")
        with open(settings_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertIn(
            "Edit(.context-guard/**/manifest.json)",
            cfg.get("permissions", {}).get("deny", []),
        )

    def test_running_install_twice_does_not_duplicate_deny_entries(self):
        self.run_install()
        self.run_install()
        settings_path = os.path.join(self.target, ".claude", "settings.json")
        with open(settings_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        deny = cfg["permissions"]["deny"]
        self.assertEqual(deny.count("Edit(.context-guard/**/manifest.json)"), 1)

    def test_a_preexisting_deny_entry_survives(self):
        """6.4: 'las configs previas del usuario sobreviven intactas' — a
        deny rule the user already had for something unrelated must not be
        clobbered by the merge."""
        os.makedirs(os.path.join(self.target, ".claude"), exist_ok=True)
        settings_path = os.path.join(self.target, ".claude", "settings.json")
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump({"permissions": {"deny": ["Bash(rm -rf /*)"]}}, f)

        self.run_install()

        with open(settings_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertIn("Bash(rm -rf /*)", cfg["permissions"]["deny"])
        self.assertIn("Edit(.context-guard/**/manifest.json)", cfg["permissions"]["deny"])


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
