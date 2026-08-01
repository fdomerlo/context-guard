"""PLAN-2.1 F2: `cg setup` absorbs and replaces the shell installer.

The behavioural tests that used to run that script against a fake HOME are
ported here rather than deleted — idempotency, config preservation and "no
absolute paths" remain acceptance criteria, only the implementation changed.

The inversion that dominates the phase: 2.0 installed per-project by default,
2.1 installs globally by default with `--project` keeping the old mode. A
half-finished port would write to both places and every positive assertion
would still pass, so each scope test carries its negative mirror.

HOME is redirected with a real environment variable rather than an injected
parameter, so the tests exercise the same path resolution the binary uses.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from context_guard.guard import assets
from context_guard.guard.cli import parse_args
from context_guard.guard.commands import cmd_doctor, cmd_new, cmd_setup
from context_guard.guard.errors import EXIT_OK, GuardError
from context_guard.guard.setup import _strip_jsonc_comments

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ABS_PATH_RE = r"/home/|/Users/"


def tree_snapshot(root):
    """Every file under `root`, as {relative path: content}.

    Used for the idempotency checks: comparing two snapshots catches a second
    run that rewrites a file with different bytes, which a "the key is still
    there" assertion would miss.
    """
    out = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    out[rel] = f.read()
            except (UnicodeDecodeError, OSError):
                out[rel] = "<binary>"
    return out


class SetupCase(unittest.TestCase):
    """Isolated fake HOME plus a fake project, for every scope combination."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="guard_setup_home_")
        self.project = tempfile.mkdtemp(prefix="guard_setup_project_")
        # Detection consults PATH as well as the config directories, so PATH
        # is redirected too. Left alone, this suite would detect whichever
        # hosts the developer happens to have installed, and the detection
        # tests would pass or fail per machine.
        self.bindir = tempfile.mkdtemp(prefix="guard_setup_bin_")

    def tearDown(self):
        for path in (self.home, self.project, self.bindir):
            shutil.rmtree(path, ignore_errors=True)

    def fake_binary(self, name):
        path = os.path.join(self.bindir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, 0o755)

    def env(self):
        return {"HOME": self.home, "PATH": self.bindir}

    def setup(self, host="all", with_mcp=False, project=None, no_hooks=False):
        with mock.patch.dict(os.environ, self.env()):
            return cmd_setup(host=host, with_mcp=with_mcp, project=project,
                             no_hooks=no_hooks)

    def home_path(self, *parts):
        return os.path.join(self.home, *parts)

    def project_path(self, *parts):
        return os.path.join(self.project, *parts)

    def read_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def detect_all_three(self):
        """Fake config directories, so `--host all` detects every host.

        Replaces the old FORCE_OPENCODE/FORCE_ANTIGRAVITY escape hatches:
        the shell could not fake a config dir, Python tests can, so detection
        itself is exercised instead of being bypassed.
        """
        os.makedirs(self.home_path(".config", "opencode"), exist_ok=True)
        os.makedirs(self.home_path(".gemini"), exist_ok=True)


class TestGlobalScopeIsTheDefault(SetupCase):
    """F2 point 1: "scope global por defecto". This is the whole point of the
    phase — one command per machine instead of one per project."""

    def test_claude_installs_into_home(self):
        res = self.setup(host="claude")
        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        for name in ("cg-new.md", "cg-continue.md"):
            self.assertTrue(os.path.exists(self.home_path(".claude", "commands", name)),
                            f"~/.claude/commands/{name} was not installed")
        cfg = self.read_json(self.home_path(".claude", "settings.json"))
        self.assertIn("Bash(cg approve*)", cfg["permissions"]["ask"])

    def test_claude_global_writes_nothing_into_the_working_directory(self):
        """The negative mirror. A port that left the 2.0 per-project writes in
        place would pass every assertion above while still requiring a visit to
        each project — the exact problem F2 exists to remove."""
        before = tree_snapshot(self.project)
        with mock.patch.dict(os.environ, self.env()):
            cwd = os.getcwd()
            os.chdir(self.project)
            try:
                cmd_setup(host="claude")
            finally:
                os.chdir(cwd)
        self.assertEqual(tree_snapshot(self.project), before)

    def test_opencode_installs_into_home(self):
        res = self.setup(host="opencode")
        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        for name in ("cg-new.md", "cg-continue.md"):
            self.assertTrue(
                os.path.exists(self.home_path(".config", "opencode", "commands", name)))
        cfg = self.read_json(self.home_path(".config", "opencode", "opencode.json"))
        self.assertIn("context-guard", cfg["agent"])
        self.assertEqual(cfg["permission"]["edit"][".context-guard/**/manifest.json"], "deny")

    def test_antigravity_installs_the_deny_hook(self):
        """Resolved with the human: `--with-antigravity-hook` is gone. At
        global scope the hook is the only thing Antigravity gets — the
        workspace rule is materialised by `cg new` — so keeping it behind a
        second flag would make `cg setup --host antigravity` a no-op."""
        res = self.setup(host="antigravity")
        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        cfg = self.read_json(self.home_path(".gemini", "config", "hooks.json"))
        hooks = cfg["hooks"]["PreToolUse"]
        self.assertTrue(any(h["matcher"]["tool"] == "run_command" for h in hooks))

    def test_default_host_is_all(self):
        self.detect_all_three()
        res = self.setup()
        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        self.assertTrue(os.path.exists(self.home_path(".claude", "commands", "cg-new.md")))
        self.assertTrue(os.path.exists(
            self.home_path(".config", "opencode", "commands", "cg-new.md")))
        self.assertTrue(os.path.exists(self.home_path(".gemini", "config", "hooks.json")))


class TestProjectScopeMirrorsTwoPointZero(SetupCase):
    """F2 point 1: "--project <dir> conserva el modo por-proyecto de 2.0 para
    equipos que quieren la config commiteada en el repo"."""

    def test_claude_lands_in_the_project(self):
        res = self.setup(host="claude", project=self.project)
        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        self.assertTrue(os.path.exists(self.project_path(".claude", "commands", "cg-new.md")))
        cfg = self.read_json(self.project_path(".claude", "settings.json"))
        self.assertIn("Bash(cg approve*)", cfg["permissions"]["ask"])
        self.assertIn("Edit(.context-guard/**/manifest.json)", cfg["permissions"]["deny"])

    def test_opencode_lands_in_the_project(self):
        self.setup(host="opencode", project=self.project)
        self.assertTrue(os.path.exists(self.project_path(".opencode", "commands", "cg-new.md")))
        cfg = self.read_json(self.project_path("opencode.json"))
        self.assertIn("context-guard", cfg["agent"])

    def test_antigravity_rule_lands_in_the_project(self):
        self.setup(host="antigravity", project=self.project)
        rule = self.project_path(".agents", "rules", "context-guard.md")
        self.assertTrue(os.path.exists(rule))
        with open(rule, "r", encoding="utf-8") as f:
            self.assertIn("cg approve", f.read())

    def test_project_scope_writes_nothing_under_home(self):
        """The mirror of the global tests. Project mode exists so a team can
        commit the config; a stray write into the developer's HOME is both a
        surprise and unreviewable in a pull request."""
        self.setup(host="all", project=self.project)
        self.assertEqual(tree_snapshot(self.home), {})


class TestDetection(SetupCase):
    def test_all_installs_only_detected_hosts(self):
        os.makedirs(self.home_path(".config", "opencode"), exist_ok=True)
        self.setup(host="all")
        self.assertTrue(os.path.exists(
            self.home_path(".config", "opencode", "commands", "cg-new.md")))
        self.assertFalse(os.path.exists(self.home_path(".gemini", "config", "hooks.json")))

    def test_naming_a_host_bypasses_detection(self):
        """Ported from the old --host semantics: asking for a host
        explicitly is itself the signal, so detection does not apply."""
        self.setup(host="antigravity")
        self.assertTrue(os.path.exists(self.home_path(".gemini", "config", "hooks.json")))

    def test_claude_always_installs_under_all(self):
        """Parity with the old installer, which had no detection leg for Claude Code."""
        self.setup(host="all")
        self.assertTrue(os.path.exists(self.home_path(".claude", "commands", "cg-new.md")))


class TestIdempotency(SetupCase):
    """F2 point 1: "idempotente [...] misma garantía verificada en F6 de 2.0:
    segunda corrida = diff vacío"."""

    def test_second_global_run_changes_nothing(self):
        self.detect_all_three()
        self.setup(with_mcp=True)
        first = tree_snapshot(self.home)
        self.setup(with_mcp=True)
        self.assertEqual(tree_snapshot(self.home), first)

    def test_second_project_run_changes_nothing(self):
        self.setup(host="all", project=self.project, with_mcp=True)
        first = tree_snapshot(self.project)
        self.setup(host="all", project=self.project, with_mcp=True)
        self.assertEqual(tree_snapshot(self.project), first)

    def test_preexisting_claude_entries_survive(self):
        os.makedirs(self.home_path(".claude"), exist_ok=True)
        with open(self.home_path(".claude", "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"permissions": {"ask": ["Bash(git push*)"],
                                       "deny": ["Bash(rm -rf /*)"]}}, f)
        self.setup(host="claude")
        cfg = self.read_json(self.home_path(".claude", "settings.json"))
        self.assertIn("Bash(git push*)", cfg["permissions"]["ask"])
        self.assertIn("Bash(rm -rf /*)", cfg["permissions"]["deny"])
        self.assertIn("Bash(cg approve*)", cfg["permissions"]["ask"])

    def test_running_twice_does_not_duplicate_entries(self):
        self.setup(host="claude")
        self.setup(host="claude")
        cfg = self.read_json(self.home_path(".claude", "settings.json"))
        self.assertEqual(cfg["permissions"]["ask"].count("Bash(cg approve*)"), 1)

    def test_a_url_bearing_opencode_config_is_not_silently_discarded(self):
        """Ported verbatim from the shell installer's suite, because the port to
        Python is exactly where it would be lost.

        The JSONC comment-stripping regex matched the "//" in
        "https://opencode.ai/config.json" and ate the rest of the line; the
        broad except around the parse then treated the corrupted read as "no
        config yet" and overwrote the file. A plain "did $schema survive"
        check does not catch it — the fallback happens to hardcode the same
        URL, masking the corruption. A marker key with no such lucky fallback
        does. It only misfires once the $schema line is followed by a real
        newline, so the first run (which pretty-prints) has to happen before
        the marker is planted.
        """
        self.setup(host="opencode")
        cfg_path = self.home_path(".config", "opencode", "opencode.json")
        cfg = self.read_json(cfg_path)
        self.assertEqual(cfg["$schema"], "https://opencode.ai/config.json")
        cfg["my_custom_setting"] = "keep-me"
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

        self.setup(host="opencode")

        cfg = self.read_json(cfg_path)
        self.assertEqual(cfg.get("my_custom_setting"), "keep-me")

    def test_a_preexisting_mcp_server_entry_survives(self):
        os.makedirs(self.home_path(".claude"), exist_ok=True)
        with open(self.home_path(".claude.json"), "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"other-tool": {"command": "other-tool-mcp"}}}, f)
        self.setup(host="claude", with_mcp=True)
        cfg = self.read_json(self.home_path(".claude.json"))
        self.assertIn("other-tool", cfg["mcpServers"])
        self.assertIn("context-guard", cfg["mcpServers"])

    def test_a_preexisting_unrelated_hook_survives(self):
        os.makedirs(self.home_path(".gemini", "config"), exist_ok=True)
        with open(self.home_path(".gemini", "config", "hooks.json"), "w", encoding="utf-8") as f:
            json.dump({"hooks": {"PreToolUse": [
                {"matcher": {"tool": "write_file"}, "action": {"decision": "allow"}}]}}, f)
        self.setup(host="antigravity")
        cfg = self.read_json(self.home_path(".gemini", "config", "hooks.json"))
        tools = [h["matcher"]["tool"] for h in cfg["hooks"]["PreToolUse"]]
        self.assertIn("write_file", tools)
        self.assertIn("run_command", tools)

    def test_the_deny_hook_is_not_duplicated_across_runs(self):
        self.setup(host="antigravity")
        self.setup(host="antigravity")
        cfg = self.read_json(self.home_path(".gemini", "config", "hooks.json"))
        matching = [h for h in cfg["hooks"]["PreToolUse"]
                    if h.get("matcher", {}).get("tool") == "run_command"
                    and "approve" in h.get("matcher", {}).get("commandPattern", "")]
        self.assertEqual(len(matching), 1)


class TestJsoncCommentStripping(unittest.TestCase):
    """Two bugs of the same family, both found in production code, pinned as
    unit tests because both were originally found only through their
    second-order effects.

    A regex cannot tell a comment from a comment-shaped substring of a string
    value. The `//` case was found in 2.0 (a URL); the `/**/` case was found
    here, by the idempotency test, and is worse: the installer writes the
    glob `.context-guard/**/manifest.json` itself, so it corrupted its own
    output on every second run.
    """

    def test_a_url_inside_a_string_is_not_treated_as_a_comment(self):
        raw = '{"$schema": "https://opencode.ai/config.json", "keep": 1}'
        self.assertEqual(json.loads(_strip_jsonc_comments(raw))["keep"], 1)

    def test_a_glob_inside_a_string_is_not_treated_as_a_comment(self):
        raw = '{"permission": {"edit": {".context-guard/**/manifest.json": "deny"}}}'
        parsed = json.loads(_strip_jsonc_comments(raw))
        self.assertEqual(
            parsed["permission"]["edit"][".context-guard/**/manifest.json"], "deny")

    def test_real_comments_are_still_removed(self):
        raw = '{\n  // a line comment\n  "a": 1, /* a block comment */ "b": 2\n}'
        self.assertEqual(json.loads(_strip_jsonc_comments(raw)), {"a": 1, "b": 2})

    def test_an_escaped_quote_does_not_end_the_string(self):
        raw = r'{"a": "he said \"//not a comment\"", "b": 2}'
        parsed = json.loads(_strip_jsonc_comments(raw))
        self.assertEqual(parsed["b"], 2)
        self.assertIn("//not a comment", parsed["a"])


class TestUnparseableConfigIsNeverClobbered(SetupCase):
    """The shell installer caught JSONDecodeError and carried on with an empty dict,
    which is what turned a parsing bug into data loss. Refusing is the only
    safe response: this code cannot distinguish a file it fails to parse from
    a file it is about to destroy."""

    def test_setup_refuses_and_leaves_the_file_untouched(self):
        os.makedirs(self.home_path(".claude"), exist_ok=True)
        path = self.home_path(".claude", "settings.json")
        original = '{"permissions": {"ask": [ THIS IS NOT JSON'
        with open(path, "w", encoding="utf-8") as f:
            f.write(original)

        with self.assertRaises(GuardError):
            self.setup(host="claude")

        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), original)


class HooksCase(SetupCase):
    def hooks_path(self):
        return self.home_path(".gemini", "config", "hooks.json")

    def plant_hooks(self, raw):
        os.makedirs(os.path.dirname(self.hooks_path()), exist_ok=True)
        with open(self.hooks_path(), "w", encoding="utf-8") as f:
            f.write(raw)
        return raw

    def hooks_raw(self):
        with open(self.hooks_path(), "r", encoding="utf-8") as f:
            return f.read()


class TestAntigravityHooksMergeIsDefensive(HooksCase):
    """Pre-release audit, item 1. An installer must not traceback at the sight
    of a user's real config file.

    `cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])` assumes a shape
    nothing had verified. Against `{"hooks": [...]}` — a list where a dict was
    assumed — it raised AttributeError and printed a raw traceback. It failed
    before writing, so nothing was corrupted, but "it happens to crash early"
    is not a preservation guarantee: it is the same code path that would
    overwrite the file if the crash moved one line later.
    """

    UNRECOGNISED_SHAPES = {
        "hooks is a list": '{"hooks": [{"matcher": {"tool": "write_file"}}]}',
        "root is a list": '[{"hooks": {}}]',
        "hooks is a string": '{"hooks": "none"}',
        "PreToolUse is a dict": '{"hooks": {"PreToolUse": {"a": 1}}}',
    }

    def test_an_unrecognised_shape_is_reported_not_crashed_on(self):
        for label, raw in self.UNRECOGNISED_SHAPES.items():
            with self.subTest(shape=label):
                self.setUp()
                original = self.plant_hooks(raw)
                res = self.setup(host="antigravity")
                self.assertEqual(res.exit_code, 4, res.message)
                self.assertIn("FAIL|HOOKS_UNRECOGNISED", res.message)
                self.assertIn(self.hooks_path(), res.message)
                self.assertIn("PERMISSIONS.md", res.message)
                self.assertEqual(self.hooks_raw(), original,
                                 "the file was modified despite the failure")

    def test_unparseable_json_is_reported_not_crashed_on(self):
        original = self.plant_hooks('{"hooks": {"PreToolUse": [ THIS IS NOT JSON')
        res = self.setup(host="antigravity")
        self.assertEqual(res.exit_code, 4, res.message)
        self.assertIn("FAIL|HOOKS_UNPARSEABLE", res.message)
        self.assertEqual(self.hooks_raw(), original)

    def test_a_recognised_shape_still_merges_and_stays_idempotent(self):
        """The defensive check must not become a refusal to work: the shape
        the deny hook is designed to merge into has to keep merging, and a
        hook the user already had has to survive."""
        self.plant_hooks(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": {"tool": "write_file"}, "action": {"decision": "allow"}}]}}))

        res = self.setup(host="antigravity")
        self.assertEqual(res.exit_code, EXIT_OK, res.message)

        cfg = self.read_json(self.hooks_path())
        tools = [h["matcher"]["tool"] for h in cfg["hooks"]["PreToolUse"]]
        self.assertIn("write_file", tools)
        self.assertIn("run_command", tools)

        first = self.hooks_raw()
        self.setup(host="antigravity")
        self.assertEqual(self.hooks_raw(), first)

    def test_an_empty_hooks_object_is_a_recognised_shape(self):
        """`{}` and `{"hooks": {}}` are what a fresh config looks like. A
        shape check strict enough to reject them would break the common case
        in the name of the rare one."""
        for raw in ("{}", '{"hooks": {}}'):
            with self.subTest(raw=raw):
                self.setUp()
                self.plant_hooks(raw)
                res = self.setup(host="antigravity")
                self.assertEqual(res.exit_code, EXIT_OK, res.message)


class TestOneHostFailingDoesNotAbortTheOthers(HooksCase):
    """Pre-release audit, item 1. `cg setup` is one command configuring three
    independent hosts. If a broken Antigravity config left Claude Code and
    OpenCode unconfigured, one unrelated file on disk would silently decide
    that the tool does not work on that machine."""

    def test_claude_and_opencode_still_install(self):
        self.detect_all_three()
        self.plant_hooks('{"hooks": [{"matcher": {"tool": "write_file"}}]}')

        res = self.setup(host="all")

        self.assertTrue(os.path.exists(self.home_path(".claude", "commands", "cg-new.md")))
        self.assertTrue(os.path.exists(
            self.home_path(".config", "opencode", "commands", "cg-new.md")))

    def test_the_summary_reports_the_failure_alongside_what_was_touched(self):
        self.detect_all_three()
        self.plant_hooks('{"hooks": [{"matcher": {"tool": "write_file"}}]}')

        res = self.setup(host="all")

        self.assertIn("FAIL|HOOKS_UNRECOGNISED", res.message)
        self.assertIn(".claude/settings.json", res.message)
        self.assertEqual(res.exit_code, 4, "a failed host must not report success")

    def test_the_failed_file_is_not_listed_as_touched(self):
        """A summary that lists a file it did not write sends the user
        deleting something the installer never created."""
        self.detect_all_three()
        self.plant_hooks('{"hooks": [{"matcher": {"tool": "write_file"}}]}')

        res = self.setup(host="all")

        touched = res.message.split("Files touched:", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("hooks.json", touched)


class TestNoHooksEscapeHatch(HooksCase):
    """Pre-release audit, item 2. Installing the deny hook by default is
    blessed — `cg setup` is already a consented act of global configuration,
    and the hook is the enforcement. What was missing is that it happened
    silently, with no way to decline it."""

    def test_no_hooks_leaves_the_file_alone(self):
        self.setup(host="antigravity", no_hooks=True)
        self.assertFalse(os.path.exists(self.hooks_path()),
                         "--no-hooks must not create the hooks file")

    def test_no_hooks_does_not_modify_an_existing_file(self):
        original = self.plant_hooks(json.dumps({"hooks": {"PreToolUse": []}}))
        self.setup(host="antigravity", no_hooks=True)
        self.assertEqual(self.hooks_raw(), original)

    def test_the_hook_is_installed_by_default(self):
        self.setup(host="antigravity")
        self.assertTrue(os.path.exists(self.hooks_path()))

    def test_the_output_says_what_the_hook_is_and_how_to_skip_it(self):
        """Consented does not mean silent: the line naming the file has to
        say what it does and how to decline it, or the escape hatch exists
        only for people who read the source."""
        res = self.setup(host="antigravity")
        self.assertIn(".gemini/config/hooks.json (deny hook for cg approve "
                      "— skip with --no-hooks)", res.message)

    def test_no_hooks_still_installs_the_other_hosts(self):
        self.detect_all_three()
        self.setup(host="all", no_hooks=True)
        self.assertTrue(os.path.exists(self.home_path(".claude", "commands", "cg-new.md")))
        self.assertFalse(os.path.exists(self.hooks_path()))


class TestNoHooksIsDocumentedInHelp(unittest.TestCase):
    def test_help_names_the_flag_and_what_is_lost(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            parse_args(["setup", "--help"])
        text = buf.getvalue()
        self.assertIn("--no-hooks", text)
        self.assertIn("cg approve", text,
                      "the help must say which protection is being declined")


class TestWithMcpFlag(SetupCase):
    def test_mcp_is_not_registered_without_the_flag(self):
        self.setup(host="claude")
        self.assertFalse(os.path.exists(self.home_path(".claude.json")))

    def test_with_mcp_registers_claude_globally(self):
        self.setup(host="claude", with_mcp=True)
        cfg = self.read_json(self.home_path(".claude.json"))
        self.assertEqual(cfg["mcpServers"]["context-guard"]["command"], "context-guard-mcp")

    def test_with_mcp_registers_claude_per_project(self):
        self.setup(host="claude", with_mcp=True, project=self.project)
        cfg = self.read_json(self.project_path(".mcp.json"))
        self.assertEqual(cfg["mcpServers"]["context-guard"]["command"], "context-guard-mcp")

    def test_with_mcp_registers_opencode(self):
        self.setup(host="opencode", with_mcp=True)
        cfg = self.read_json(self.home_path(".config", "opencode", "opencode.json"))
        self.assertIn("context-guard", cfg["mcp"])


class TestNoAbsolutePathsLeakIntoInstalledFiles(SetupCase):
    """Ported, and it matters more than it did in 2.0: a global install is
    shared by every project on the machine, so one absolute path leaking in
    breaks all of them at once instead of one."""

    def test_no_installed_file_embeds_an_absolute_path(self):
        self.detect_all_three()
        self.setup(with_mcp=True)
        for rel, content in tree_snapshot(self.home).items():
            with self.subTest(file=rel):
                self.assertNotRegex(content, ABS_PATH_RE)


class TestFilesTouchedSummary(SetupCase):
    """F2 point 1: "Al final imprime la lista exacta de archivos tocados."
    With no --uninstall (explicit backlog), that list is the only record of
    what to remove by hand."""

    def test_summary_lists_every_file_touched(self):
        res = self.setup(host="claude", with_mcp=True)
        for fragment in (".claude/commands/cg-new.md",
                         ".claude/commands/cg-continue.md",
                         ".claude/settings.json",
                         ".claude.json"):
            with self.subTest(path=fragment):
                self.assertIn(fragment, res.message)

    def test_summary_only_lists_hosts_actually_installed(self):
        res = self.setup(host="claude")
        self.assertNotIn(".opencode/", res.message)
        self.assertNotIn(".gemini/", res.message)

    def test_every_listed_file_actually_exists(self):
        """A summary that names files the run did not create is worse than no
        summary: it sends the user deleting paths that were never touched."""
        self.detect_all_three()
        res = self.setup(with_mcp=True)
        body = res.message.split("Files touched:", 1)[1].split("\n\n", 1)[0]
        listed = [line.strip() for line in body.splitlines() if line.strip()]
        self.assertTrue(listed, f"no files listed in:\n{res.message}")
        for entry in listed:
            # An entry may carry a trailing note explaining what it is — the
            # Antigravity hook line does, so the escape hatch is visible where
            # the file is named. The path is the part before it.
            entry = entry.split(" (", 1)[0]
            path = entry if os.path.isabs(entry) else self.home_path(entry)
            with self.subTest(path=entry):
                self.assertTrue(os.path.exists(path), f"{entry} was listed but does not exist")


class TestInvalidHostIsRejected(SetupCase):
    def test_unknown_host_is_an_error(self):
        res = self.setup(host="bogus")
        self.assertNotEqual(res.exit_code, EXIT_OK)
        self.assertIn("bogus", res.message)

    def test_nothing_is_written_when_the_host_is_invalid(self):
        self.setup(host="bogus")
        self.assertEqual(tree_snapshot(self.home), {})


class TestCgNewMaterialisesPhases(SetupCase):
    """F2 point 3: the global commands reference `.context-guard/phases/*.md`,
    so they only work if something writes those files into a fresh project.
    `cg new` is that something."""

    def test_a_virgin_project_gets_the_three_phase_files(self):
        res = cmd_new(self.project, "demo")
        self.assertEqual(res.exit_code, EXIT_OK, res.message)
        for name in ("plan", "execute", "verify"):
            path = os.path.join(self.project, ".context-guard", "phases", f"{name}.md")
            self.assertTrue(os.path.exists(path), f"phases/{name}.md was not materialised")
            with open(path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), assets.get_phase(name))

    def test_a_customised_phase_file_is_never_overwritten(self):
        """F2 point 3: "Si el archivo ya existe y difiere del embebido, NO se
        pisa (el proyecto pudo personalizarlo)". Silently restoring the stock
        text would delete a team's local process without a word."""
        cmd_new(self.project, "first")
        plan_path = os.path.join(self.project, ".context-guard", "phases", "plan.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("# PLAN\nour own house rules\n")

        cmd_new(self.project, "second")

        with open(plan_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "# PLAN\nour own house rules\n")

    def _new_project(self):
        path = tempfile.mkdtemp(prefix="guard_setup_project_")
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def _rule(self, project):
        return os.path.join(project, ".agents", "rules", "context-guard.md")

    def test_no_antigravity_rule_without_detection_or_flag(self):
        """HOME is redirected even here. The developer machine running this
        suite has a real ~/.gemini, so without the redirect this test would
        pass or fail depending on whose laptop it runs on."""
        project = self._new_project()
        with mock.patch.dict(os.environ, self.env()):
            cmd_new(project, "demo")
        self.assertFalse(os.path.exists(self._rule(project)))

    def test_a_detected_antigravity_gets_the_rule(self):
        os.makedirs(self.home_path(".gemini"), exist_ok=True)
        project = self._new_project()
        with mock.patch.dict(os.environ, self.env()):
            cmd_new(project, "demo")
        self.assertTrue(os.path.exists(self._rule(project)))

    def test_the_host_flag_writes_the_rule_without_detection(self):
        project = self._new_project()
        with mock.patch.dict(os.environ, self.env()):
            cmd_new(project, "demo", host="antigravity")
        self.assertTrue(os.path.exists(self._rule(project)))


class TestDoctorReportsPhaseDivergence(SetupCase):
    """F2 point 3: "cg doctor reporta la divergencia como INFO"."""

    def _doctor(self):
        return cmd_doctor(self.project, change="demo")

    def test_untouched_phases_are_not_reported_as_diverged(self):
        cmd_new(self.project, "demo")
        self.assertNotIn("INFO:", self._doctor().message)

    def test_a_customised_phase_is_reported_as_info(self):
        cmd_new(self.project, "demo")
        plan_path = os.path.join(self.project, ".context-guard", "phases", "plan.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("# PLAN\nour own house rules\n")

        res = self._doctor()
        self.assertIn("INFO:", res.message)
        self.assertIn("plan.md", res.message)

    def test_divergence_does_not_change_the_exit_code(self):
        """INFO is informational by definition. If it made doctor fail, every
        project that customised a phase would look broken forever."""
        cmd_new(self.project, "demo")
        clean = self._doctor().exit_code
        plan_path = os.path.join(self.project, ".context-guard", "phases", "plan.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("# PLAN\nour own house rules\n")
        self.assertEqual(self._doctor().exit_code, clean)


# Built from parts so this file does not itself contain the string it asserts
# is gone from the repository. Spelling it out here would make the acceptance
# criterion — "only the CHANGELOG still names it" — impossible to satisfy, and
# weakening the assertion to accommodate the test would defeat its purpose.
REMOVED_INSTALLER = "install" + ".sh"


class TestTheShellInstallerIsGone(unittest.TestCase):
    """F2 point 2: the installer is deleted with no compatibility wrapper."""

    def test_the_file_does_not_exist(self):
        self.assertFalse(
            os.path.exists(os.path.join(REPO_ROOT, "adapters", REMOVED_INSTALLER)))

    def test_git_no_longer_tracks_it(self):
        """Checked through git, not the filesystem — deleting a file without
        staging the deletion leaves it in every fresh clone, which is exactly
        the mistake F1 made and only a git-level assertion caught."""
        res = subprocess.run(["git", "ls-files", "adapters/"],
                             cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "")

    def test_nothing_but_the_changelog_still_mentions_it(self):
        """F2's acceptance criterion, read literally."""
        res = subprocess.run(["git", "grep", "-l", REMOVED_INSTALLER],
                             cwd=REPO_ROOT, capture_output=True, text=True)
        files = [line for line in res.stdout.splitlines() if line.strip()]
        self.assertEqual(
            files, ["CHANGELOG.md"],
            "only the CHANGELOG may still name it, as the record of its removal",
        )


class TestEmbeddedCommandsAreScopeAgnostic(unittest.TestCase):
    """F2 point 4: the commands are installed globally now, so any assumption
    that they sit inside the project they act on is a bug that only shows up
    on the second project the user opens."""

    def test_commands_point_at_project_relative_phase_paths(self):
        for host in ("claude-code", "opencode"):
            for relpath, text in assets.iter_host_files(host):
                if not relpath.startswith("commands/"):
                    continue
                with self.subTest(host=host, command=relpath):
                    self.assertIn(".context-guard/phases/", text)

    def test_no_command_references_a_project_scoped_settings_file(self):
        """Scoped to the command files on purpose: the snippets are *about*
        those config files, so naming them there is correct. It is the
        commands, which now live in a single global copy, that must not
        assume where the config sits."""
        for host in ("claude-code", "opencode"):
            for relpath, text in assets.iter_host_files(host):
                if not relpath.startswith("commands/"):
                    continue
                with self.subTest(host=host, command=relpath):
                    self.assertNotIn(".claude/settings.json", text)
                    self.assertNotIn(".opencode/", text)


if __name__ == "__main__":
    unittest.main()
