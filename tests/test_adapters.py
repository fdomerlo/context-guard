"""Static acceptance checks for the packaged host adapters: thin per-harness
wrappers that point at the phase documents instead of duplicating their prose.

The behavioural half of this file — everything that ran the shell installer
against a fake HOME — moved to tests/test_setup.py in PLAN-2.1 F2, when `cg setup`
replaced it. Those tests were ported, not dropped: idempotency and
config preservation are still acceptance criteria."""

import contextlib
import io
import json
import os
import re
import unittest

from context_guard.guard.cli import parse_args

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# PLAN-2.1 F1 split what used to live under adapters/ in two: the installable
# artifacts became package data, the human-facing docs became documentation.
HOSTS_DIR = os.path.join(REPO_ROOT, "context_guard", "_data", "hosts")
DOCS_DIR = os.path.join(REPO_ROOT, "docs", "adapters")
CLAUDE_CODE_DIR = os.path.join(HOSTS_DIR, "claude-code")
OPENCODE_DIR = os.path.join(HOSTS_DIR, "opencode")
ABS_PATH_RE = re.compile(r"/home/|/Users/")

DEAD_TERMS = ("watchdog", "hook_daemon", "/dev/tty", "sha-256", "sha256")


class TestClaudeCodeAdapter(unittest.TestCase):
    def _read(self, relpath):
        path = os.path.join(CLAUDE_CODE_DIR, relpath)
        self.assertTrue(os.path.exists(path), f"_data/hosts/claude-code/{relpath} is missing")
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

    HOSTS = ("claude-code", "opencode", "antigravity", "cursor")

    def _permissions_doc(self, host):
        path = os.path.join(DOCS_DIR, host, "PERMISSIONS.md")
        self.assertTrue(
            os.path.exists(path),
            f"docs/adapters/{host}/PERMISSIONS.md is missing — each harness must "
            "document how to put cg approve behind a human confirmation",
        )
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_every_host_documents_how_to_gate_approve(self):
        for host in self.HOSTS:
            text = self._permissions_doc(host)
            self.assertIn("cg approve", text, f"docs/adapters/{host}/PERMISSIONS.md must name the command")

    def test_docs_are_honest_about_what_the_prompt_guarantees(self):
        """0.6 requires each layer to be honest about what it guarantees. An
        adapter that promises the permission prompt stops a determined agent
        repeats state-guard's crypto-gate mistake in a config file."""
        for host in self.HOSTS:
            text = self._permissions_doc(host).lower()
            self.assertTrue(
                "cooperative" in text,
                f"docs/adapters/{host}/PERMISSIONS.md must say what is cooperative "
                "and what is hard (PLAN.md 0.6)",
            )

    def test_unverified_hosts_say_so(self):
        """PLAN.md backlog: the OpenCode and Antigravity adapters were never run
        against a real host. Documenting them as if they were is the kind of
        claim the audits exist to falsify."""
        for host in ("opencode", "antigravity", "cursor"):
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
        path = os.path.join(OPENCODE_DIR, "permissions.snippet.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        bash_rules = data.get("permission", {}).get("bash", {})
        self.assertTrue(
            any("approve" in pattern and mode == "ask"
                for pattern, mode in bash_rules.items()),
            "_data/hosts/opencode/permissions.snippet.json must ask before running cg approve",
        )


class TestOpenCodeAdapterIsPerProject(unittest.TestCase):
    """F6 6.0.1/6.0.7/6.1: OpenCode's adapter mirrors Claude Code's — commands
    installed into the target project, not generated into $HOME pointing at
    the repo clone's own phases/ directory."""

    def _read(self, relpath):
        path = os.path.join(OPENCODE_DIR, relpath)
        self.assertTrue(os.path.exists(path), f"_data/hosts/opencode/{relpath} is missing")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_cg_new_and_cg_continue_commands_exist(self):
        for name in ("cg-new.md", "cg-continue.md"):
            self._read(os.path.join("commands", name))

    def test_commands_stay_thin(self):
        for name in ("cg-new.md", "cg-continue.md"):
            text = self._read(os.path.join("commands", name))
            line_count = len(text.splitlines())
            self.assertLessEqual(line_count, 20, f"commands/{name} has {line_count} lines")

    def test_commands_point_at_phases_not_duplicate_them(self):
        new_text = self._read(os.path.join("commands", "cg-new.md"))
        self.assertIn("phases/plan.md", new_text)
        continue_text = self._read(os.path.join("commands", "cg-continue.md"))
        for phase_file in ("phases/plan.md", "phases/execute.md", "phases/verify.md"):
            self.assertIn(phase_file, continue_text)

    def test_cg_continue_injects_status_via_shell_templating(self):
        """PLAN.md 6.1: state injected in the prompt so the agent starts with
        real state, no tool-calling round trip needed."""
        text = self._read(os.path.join("commands", "cg-continue.md"))
        self.assertIn("!`cg status", text)

    def test_commands_carry_no_absolute_path(self):
        for name in ("cg-new.md", "cg-continue.md"):
            text = self._read(os.path.join("commands", name))
            self.assertNotRegex(text, ABS_PATH_RE, f"commands/{name} embeds an absolute path")


class TestClaudeCodeAndOpenCodeExposeTheSameCommands(unittest.TestCase):
    def test_same_two_command_names(self):
        claude_names = {
            f for f in os.listdir(os.path.join(CLAUDE_CODE_DIR, "commands"))
            if f.endswith(".md")
        }
        opencode_names = {
            f for f in os.listdir(os.path.join(OPENCODE_DIR, "commands"))
            if f.endswith(".md")
        }
        self.assertEqual(claude_names, opencode_names)
        self.assertEqual(claude_names, {"cg-new.md", "cg-continue.md"})


class TestAntigravityAdapterIsPerProject(unittest.TestCase):
    """F6 6.0.4: the bootstrap was injected into ~/.gemini/GEMINI.md, global
    to every project the user has — a control meant to apply to one repo
    contaminated all of them. The correct, IDE+CLI+Manager-supported location
    is the workspace rule file, which travels with the repo."""

    RULE_PATH = os.path.join(HOSTS_DIR, "antigravity", "rules", "context-guard.md")
    OLD_SNIPPET_PATH = os.path.join(HOSTS_DIR, "antigravity", "bootstrap.snippet.md")

    def test_rule_file_exists_at_the_new_location(self):
        self.assertTrue(os.path.exists(self.RULE_PATH), "_data/hosts/antigravity/rules/context-guard.md is missing")
        with open(self.RULE_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("cg approve", text)
        self.assertIn("AGENTS.md", text)

    def test_old_global_snippet_path_is_gone(self):
        """A stale copy left behind is a second source of truth that can
        drift from the one the installer actually uses."""
        self.assertFalse(
            os.path.exists(self.OLD_SNIPPET_PATH),
            "a bootstrap.snippet.md should be replaced by rules/context-guard.md, not kept alongside it",
        )


class TestAntigravityHookSnippet(unittest.TestCase):
    """F6 6.0.5: Antigravity's CLI never got the deny hook on run_command —
    the equivalent, and stronger, of Claude Code's ask list. Optional
    hardening (PLAN.md 6.1) since it touches user config, not project."""

    PATH = os.path.join(HOSTS_DIR, "antigravity", "hooks.snippet.json")

    def _snippet(self):
        with open(self.PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_snippet_exists_and_is_valid_json(self):
        self.assertTrue(os.path.exists(self.PATH), "_data/hosts/antigravity/hooks.snippet.json is missing")
        self._snippet()

    def test_declares_a_pre_tool_use_hook_on_run_command(self):
        data = self._snippet()
        pre_tool_use = data.get("hooks", {}).get("PreToolUse", [])
        self.assertTrue(pre_tool_use, "no PreToolUse hooks declared")
        self.assertEqual(pre_tool_use[0]["matcher"]["tool"], "run_command")

    def test_matcher_pattern_catches_both_entrypoint_spellings(self):
        data = self._snippet()
        pattern = data["hooks"]["PreToolUse"][0]["matcher"]["commandPattern"]
        regex = re.compile(pattern)
        self.assertTrue(regex.match("cg approve --change demo"))
        self.assertTrue(regex.match("context-guard approve --change demo"))
        self.assertFalse(regex.match("cg approved-something-else"))

    def test_action_denies_with_a_human_readable_message(self):
        data = self._snippet()
        action = data["hooks"]["PreToolUse"][0]["action"]
        self.assertEqual(action["decision"], "deny")
        self.assertIn("human-only", action["message"])

    def test_permissions_doc_mentions_the_opt_in_hook(self):
        path = os.path.join(DOCS_DIR, "antigravity", "PERMISSIONS.md")
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("hooks.snippet.json", text)
        # F2 folded --with-antigravity-hook away: at global scope the hook was
        # the only thing this host installed, so a second flag guarding it made
        # `cg setup --host antigravity` a no-op.
        self.assertIn("cg setup --host antigravity", text)


class TestMcpRegistrationSnippets(unittest.TestCase):
    """F6 6.0.8: nobody registered the MCP server. It is a channel separate
    from the adapters (not a skill, not a command) and needs explicit
    per-host registration — the old installer did none of it."""

    def test_claude_code_mcp_snippet_is_valid(self):
        path = os.path.join(CLAUDE_CODE_DIR, "mcp.snippet.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["mcpServers"]["context-guard"]["command"], "context-guard-mcp")

    def test_opencode_mcp_snippet_is_valid(self):
        path = os.path.join(OPENCODE_DIR, "mcp.snippet.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("context-guard", data["mcp"])

    def test_antigravity_documents_manual_registration(self):
        """PLAN.md 6.1: not automated in 2.0 — a short manual instruction is
        enough, since the CLI's MCP config lives in user/plugin config this
        installer does not touch."""
        path = os.path.join(DOCS_DIR, "antigravity", "PERMISSIONS.md")
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("context-guard-mcp", text)

    def test_mcp_is_documented_as_optional(self):
        """PLAN.md 6.1: 'el MCP es transporte alternativo, no requisito — los
        adapters funcionan completos sin él.' The installer used to say so in
        its output; `cg setup --help` is where that now has to live."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            parse_args(["setup", "--help"])
        text = buf.getvalue()
        self.assertIn("--with-mcp", text)
        self.assertIn("optional", text.lower())


class TestNoStaleSlashCommandReferences(unittest.TestCase):
    """F6 6.0.7: renaming /new -> /cg-new and /continue -> /cg-continue is
    only a fix if nothing else in the repo still points at the old names —
    a doc telling the agent to run a command that no longer exists is worse
    than no doc at all."""

    STALE_PATTERNS = ("`/new`", "`/continue`", "commands/new.md", "commands/continue.md")

    FILES = (
        os.path.join(REPO_ROOT, "context_guard", "_data", "phases", "plan.md"),
        os.path.join(REPO_ROOT, "context_guard", "_data", "phases", "verify.md"),
        os.path.join(DOCS_DIR, "claude-code", "PERMISSIONS.md"),
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
        path = os.path.join(OPENCODE_DIR, "agent.snippet.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _permissions_snippet(self):
        path = os.path.join(OPENCODE_DIR, "permissions.snippet.json")
        self.assertTrue(os.path.exists(path), "_data/hosts/opencode/permissions.snippet.json is missing")
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


class TestVerifyChecklist(unittest.TestCase):
    """F6 6.3/acceptance criterion 4: a repeatable manual smoke-test
    checklist, since none of the adapters' real host interaction (menus,
    permission prompts) can be observed from a subprocess test."""

    PATH = os.path.join(DOCS_DIR, "VERIFY.md")

    def setUp(self):
        self.assertTrue(os.path.exists(self.PATH), "docs/adapters/VERIFY.md is missing")
        with open(self.PATH, "r", encoding="utf-8") as f:
            self.text = f.read()

    def test_covers_all_three_hosts(self):
        for host in ("Claude Code", "OpenCode", "Antigravity"):
            self.assertIn(host, self.text)

    def test_covers_the_approval_gate_step(self):
        """PLAN.md 6.3: 'el test del modelo de enforcement completo' —
        forcing a commit without approval and confirming the host's own
        control fires when the agent tries to run cg approve."""
        self.assertIn("APPROVAL_REQUIRED", self.text)
        self.assertIn("cg approve", self.text)

    def test_has_a_recordable_checklist(self):
        """Markdown checkbox syntax, checked or not — this stopped pinning
        "still unchecked" once PLAN-2.2 F3 actually completed all three
        rows; the property worth keeping is that the format is recordable
        at all."""
        self.assertRegex(self.text, r"- \[[ x]\]")



CURSOR_DIR = os.path.join(HOSTS_DIR, "cursor")


class TestCursorAdapter(unittest.TestCase):
    RULE_PATH = os.path.join(CURSOR_DIR, "rules", "context-guard.mdc")
    MCP_PATH = os.path.join(CURSOR_DIR, "mcp.snippet.json")

    def test_rule_file_exists(self):
        self.assertTrue(os.path.exists(self.RULE_PATH), "cursor rule file missing")
        with open(self.RULE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("cg approve", content)
        self.assertIn("AGENTS.md", content)

    def test_mcp_snippet_is_valid_json(self):
        self.assertTrue(os.path.exists(self.MCP_PATH), "cursor mcp snippet missing")
        with open(self.MCP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["mcpServers"]["context-guard"]["command"], "context-guard-mcp")
