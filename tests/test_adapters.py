"""F3 acceptance checks for adapters/ (PLAN.md 0.7/F3): thin per-harness
wrappers that point at phases/*.md instead of duplicating their prose, plus
install.sh which wires them into a target project."""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTERS_DIR = os.path.join(REPO_ROOT, "adapters")
CLAUDE_CODE_DIR = os.path.join(ADAPTERS_DIR, "claude-code")
OPENCODE_DIR = os.path.join(ADAPTERS_DIR, "opencode")
INSTALL_SH = os.path.join(ADAPTERS_DIR, "install.sh")
ABS_PATH_RE = re.compile(r"/home/|/Users/")

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


class TestOpenCodeAdapterIsPerProject(unittest.TestCase):
    """F6 6.0.1/6.0.7/6.1: OpenCode's adapter mirrors Claude Code's — commands
    installed into the target project, not generated into $HOME pointing at
    the repo clone's own phases/ directory."""

    def _read(self, relpath):
        path = os.path.join(OPENCODE_DIR, relpath)
        self.assertTrue(os.path.exists(path), f"adapters/opencode/{relpath} is missing")
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

    RULE_PATH = os.path.join(ADAPTERS_DIR, "antigravity", "rules", "context-guard.md")
    OLD_SNIPPET_PATH = os.path.join(ADAPTERS_DIR, "antigravity", "bootstrap.snippet.md")

    def test_rule_file_exists_at_the_new_location(self):
        self.assertTrue(os.path.exists(self.RULE_PATH), "adapters/antigravity/rules/context-guard.md is missing")
        with open(self.RULE_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("cg approve", text)
        self.assertIn("AGENTS.md", text)

    def test_old_global_snippet_path_is_gone(self):
        """A stale copy left behind is a second source of truth that can
        drift from the one install.sh actually uses."""
        self.assertFalse(
            os.path.exists(self.OLD_SNIPPET_PATH),
            "adapters/antigravity/bootstrap.snippet.md should be replaced by rules/context-guard.md, not kept alongside it",
        )


class TestMcpRegistrationSnippets(unittest.TestCase):
    """F6 6.0.8: nobody registered the MCP server. It is a channel separate
    from the adapters (not a skill, not a command) and needs explicit
    per-host registration — install.sh did none of it for any host."""

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
        path = os.path.join(ADAPTERS_DIR, "antigravity", "PERMISSIONS.md")
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("context-guard-mcp", text)

    def test_mcp_is_documented_as_optional(self):
        """PLAN.md 6.1: 'el MCP es transporte alternativo, no requisito — los
        adapters funcionan completos sin él. install.sh lo dice en su
        output.'"""
        with open(INSTALL_SH, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("--with-mcp", text)
        self.assertIn("optional", text.lower())


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


class TestOpenCodeInstallsPerProject(InstallShRunCase):
    """F6 6.0.1: the bug this closes — commands generated into
    $HOME/.config/opencode/commands/ read $PHASES_SRC, the absolute path of
    whatever repo clone install.sh was run from. Move the clone or delete
    it and every installed command breaks; and it read the repo's own
    phases/, not the copy install.sh puts in the target project."""

    def test_commands_land_in_the_target_project(self):
        res = self.run_install(env_overrides={"FORCE_OPENCODE": "1"})
        self.assertEqual(res.returncode, 0, res.stderr)

        for name in ("cg-new.md", "cg-continue.md"):
            self.assertTrue(
                os.path.exists(os.path.join(self.target, ".opencode", "commands", name)),
                f".opencode/commands/{name} was not installed into the target project",
            )

    def test_nothing_is_written_under_home(self):
        self.run_install(env_overrides={"FORCE_OPENCODE": "1"})
        self.assertFalse(
            os.path.exists(os.path.join(self.home, ".config", "opencode", "commands")),
            "OpenCode commands must not be generated into $HOME anymore",
        )

    def test_installed_commands_carry_no_absolute_repo_path(self):
        self.run_install(env_overrides={"FORCE_OPENCODE": "1"})
        commands_dir = os.path.join(self.target, ".opencode", "commands")
        for name in os.listdir(commands_dir):
            with open(os.path.join(commands_dir, name), "r", encoding="utf-8") as f:
                text = f.read()
            self.assertNotRegex(text, ABS_PATH_RE, f"{name} embeds an absolute path")

    def test_a_url_bearing_preexisting_config_is_not_silently_discarded(self):
        """Found while wiring --with-mcp: the JSONC comment-stripping regex
        (r'//.*?\\n') matched the "//" in "https://opencode.ai/config.json"
        and ate the rest of that line, corrupting the file. The broad
        except (FileNotFoundError, JSONDecodeError) around the parse then
        silently treated the corrupted read as "no config yet" and
        overwrote it — every run of the installer against a config
        containing that (very standard) $schema URL was quietly discarding
        the file's actual content, including anything the user had
        customized by hand. A plain "did $schema survive" check does not
        catch this: the except branch's own fallback happens to hardcode
        the same URL, masking the corruption. A marker key with no such
        lucky fallback does. The regex only misfires once the $schema line
        is followed by a real newline before EOF — a single-line JSON seed
        does not reproduce it, so this drives install.sh once first (its own
        writes are pretty-printed with indent=2, i.e. real newlines) and
        plants the marker into that pretty file before the second run, which
        is the one that reads it back and corrupts it."""
        self.run_install(env_overrides={"FORCE_OPENCODE": "1"})

        cfg_path = os.path.join(self.target, "opencode.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["$schema"], "https://opencode.ai/config.json")
        cfg["my_custom_setting"] = "keep-me"
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

        res = self.run_install(env_overrides={"FORCE_OPENCODE": "1"})
        self.assertEqual(res.returncode, 0, res.stderr)

        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg.get("my_custom_setting"), "keep-me")

    def test_config_is_merged_into_the_project_opencode_json(self):
        res = self.run_install(env_overrides={"FORCE_OPENCODE": "1"})
        self.assertEqual(res.returncode, 0, res.stderr)

        cfg_path = os.path.join(self.target, "opencode.json")
        self.assertTrue(os.path.exists(cfg_path), "opencode.json was not written to the target project")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertIn("context-guard", cfg.get("agent", {}))
        self.assertEqual(
            cfg["permission"]["edit"][".context-guard/**/manifest.json"], "deny",
        )
        self.assertNotIn(
            "tools", cfg.get("agent", {}).get("context-guard", {}),
            "the deprecated tools key must not be installed into the target config",
        )

    def test_running_install_twice_does_not_duplicate_permission_entries(self):
        self.run_install(env_overrides={"FORCE_OPENCODE": "1"})
        res = self.run_install(env_overrides={"FORCE_OPENCODE": "1"})
        self.assertEqual(res.returncode, 0, res.stderr)

        cfg_path = os.path.join(self.target, "opencode.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # A dict merge is duplicate-proof by construction; this pins that a
        # future rewrite of the merge does not regress to a list-append that
        # would grow unboundedly across reinstalls.
        self.assertEqual(cfg["permission"]["bash"]["cg approve*"], "ask")


class TestAntigravityInstallsPerProject(InstallShRunCase):
    def test_rule_file_lands_in_the_target_project(self):
        res = self.run_install(env_overrides={"FORCE_ANTIGRAVITY": "1"})
        self.assertEqual(res.returncode, 0, res.stderr)

        rule_path = os.path.join(self.target, ".agents", "rules", "context-guard.md")
        self.assertTrue(os.path.exists(rule_path), ".agents/rules/context-guard.md was not installed")
        with open(rule_path, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("cg approve", text)

    def test_gemini_md_is_not_touched(self):
        self.run_install(env_overrides={"FORCE_ANTIGRAVITY": "1"})
        self.assertFalse(
            os.path.exists(os.path.join(self.home, ".gemini", "GEMINI.md")),
            "the global GEMINI.md injection must be gone",
        )

    def test_running_install_twice_leaves_identical_content(self):
        self.run_install(env_overrides={"FORCE_ANTIGRAVITY": "1"})
        rule_path = os.path.join(self.target, ".agents", "rules", "context-guard.md")
        with open(rule_path, "r", encoding="utf-8") as f:
            first = f.read()

        res = self.run_install(env_overrides={"FORCE_ANTIGRAVITY": "1"})
        self.assertEqual(res.returncode, 0, res.stderr)
        with open(rule_path, "r", encoding="utf-8") as f:
            second = f.read()
        self.assertEqual(first, second)


class TestHostFlagSelectsWhichHostsInstall(InstallShRunCase):
    """F6 6.0.9/6.2: install.sh always installed "everything detected" with
    no way to ask for just one host. --host all (the default) keeps that
    detection-as-filter behavior; naming a single host forces it regardless
    of detection, since asking for it explicitly is itself the signal."""

    def test_default_is_host_all(self):
        res = self.run_install()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.target, ".claude", "commands")))

    def test_host_claude_installs_only_claude_code(self):
        res = self.run_install("--host", "claude")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.target, ".claude", "commands")))
        self.assertFalse(os.path.exists(os.path.join(self.target, ".opencode")))
        self.assertFalse(os.path.exists(os.path.join(self.target, ".agents")))

    def test_host_opencode_forces_install_without_detection(self):
        """No FORCE_OPENCODE and no ~/.config/opencode in the fake HOME —
        explicitly asking for this host must install it anyway."""
        res = self.run_install("--host", "opencode")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.target, ".opencode", "commands", "cg-new.md")))
        self.assertFalse(os.path.exists(os.path.join(self.target, ".claude")))

    def test_host_antigravity_forces_install_without_detection(self):
        res = self.run_install("--host", "antigravity")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.target, ".agents", "rules", "context-guard.md")))
        self.assertFalse(os.path.exists(os.path.join(self.target, ".claude")))

    def test_invalid_host_value_is_rejected(self):
        res = self.run_install("--host", "bogus")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("bogus", res.stderr)

    def test_help_documents_the_host_flag(self):
        res = subprocess.run(["bash", INSTALL_SH, "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("--host", res.stdout)


class TestWithMcpFlag(InstallShRunCase):
    def test_mcp_json_is_not_created_without_the_flag(self):
        res = self.run_install("--host", "claude")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.target, ".mcp.json")))

    def test_with_mcp_registers_claude_code_mcp_json(self):
        res = self.run_install("--host", "claude", "--with-mcp")
        self.assertEqual(res.returncode, 0, res.stderr)

        mcp_path = os.path.join(self.target, ".mcp.json")
        self.assertTrue(os.path.exists(mcp_path), ".mcp.json was not created")
        with open(mcp_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["mcpServers"]["context-guard"]["command"], "context-guard-mcp")

    def test_with_mcp_registers_opencode_mcp_block(self):
        res = self.run_install("--host", "opencode", "--with-mcp")
        self.assertEqual(res.returncode, 0, res.stderr)

        cfg_path = os.path.join(self.target, "opencode.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertIn("context-guard", cfg.get("mcp", {}))

    def test_running_with_mcp_twice_is_idempotent(self):
        self.run_install("--host", "claude", "--with-mcp")
        res = self.run_install("--host", "claude", "--with-mcp")
        self.assertEqual(res.returncode, 0, res.stderr)

        with open(os.path.join(self.target, ".mcp.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["mcpServers"]["context-guard"]["command"], "context-guard-mcp")

    def test_a_preexisting_mcp_server_entry_survives(self):
        os.makedirs(self.target, exist_ok=True)
        with open(os.path.join(self.target, ".mcp.json"), "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"other-tool": {"command": "other-tool-mcp"}}}, f)

        self.run_install("--host", "claude", "--with-mcp")

        with open(os.path.join(self.target, ".mcp.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertIn("other-tool", cfg["mcpServers"])
        self.assertIn("context-guard", cfg["mcpServers"])


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
