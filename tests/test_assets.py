"""PLAN-2.1 F1: every artifact a host needs becomes package data under
`context_guard/_data/`, reachable through `guard/assets.py` via
importlib.resources.

The bug this fixes: the wheel only shipped `context_guard/`, so phases and
snippets lived in the repo tree and the installer needed a clone sitting next
to the target project. These tests pin the accessor contract and, just as
importantly, that the move left exactly one copy of each artifact behind.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

from context_guard.guard import assets

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "context_guard", "_data")

PHASES = ("plan", "execute", "verify")

# The tree PLAN-2.1 F1 point 1 spells out, as an exact set. assertIn-style
# checks would let a file be dropped during the move without anything failing.
EXPECTED_DATA_FILES = {
    "phases/plan.md",
    "phases/execute.md",
    "phases/verify.md",
    "hosts/claude-code/commands/cg-new.md",
    "hosts/claude-code/commands/cg-continue.md",
    "hosts/claude-code/settings.snippet.json",
    "hosts/claude-code/mcp.snippet.json",
    "hosts/opencode/commands/cg-new.md",
    "hosts/opencode/commands/cg-continue.md",
    "hosts/opencode/agent.snippet.json",
    "hosts/opencode/permissions.snippet.json",
    "hosts/opencode/mcp.snippet.json",
    "hosts/antigravity/rules/context-guard.md",
    "hosts/antigravity/hooks.snippet.json",
}

EXPECTED_HOST_FILES = {
    "claude-code": {
        "commands/cg-new.md",
        "commands/cg-continue.md",
        "settings.snippet.json",
        "mcp.snippet.json",
    },
    "opencode": {
        "commands/cg-new.md",
        "commands/cg-continue.md",
        "agent.snippet.json",
        "permissions.snippet.json",
        "mcp.snippet.json",
    },
    "antigravity": {
        "rules/context-guard.md",
        "hooks.snippet.json",
    },
}

SNIPPETS = (
    ("claude-code", "settings"),
    ("claude-code", "mcp"),
    ("opencode", "agent"),
    ("opencode", "permissions"),
    ("opencode", "mcp"),
    ("antigravity", "hooks"),
)


class TestEmbeddedDataTree(unittest.TestCase):
    def test_data_tree_matches_the_plan_exactly(self):
        found = set()
        for dirpath, _dirnames, filenames in os.walk(DATA_DIR):
            for name in filenames:
                if name.endswith(".pyc"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, name), DATA_DIR)
                found.add(rel.replace(os.sep, "/"))
        self.assertEqual(found, EXPECTED_DATA_FILES)


class TestGetPhase(unittest.TestCase):
    def test_returns_the_embedded_phase_content(self):
        for name in PHASES:
            text = assets.get_phase(name)
            with open(os.path.join(DATA_DIR, "phases", f"{name}.md"), encoding="utf-8") as f:
                self.assertEqual(text, f.read(), f"get_phase({name!r}) does not match _data")

    def test_unknown_phase_raises_a_typed_error(self):
        with self.assertRaises(assets.AssetNotFoundError):
            assets.get_phase("nope")

    def test_path_traversal_is_refused(self):
        """The accessor takes a phase name, not a path. If it joins whatever it
        is handed onto the data directory, `cg` becomes an arbitrary-file
        reader for anything that can influence that argument."""
        for hostile in ("../../../etc/passwd", "../pyproject", "../../__init__", "plan/../plan"):
            with self.subTest(name=hostile):
                with self.assertRaises(assets.AssetNotFoundError):
                    assets.get_phase(hostile)


class TestIterHostFiles(unittest.TestCase):
    def test_yields_the_exact_file_set_per_host(self):
        for host, expected in EXPECTED_HOST_FILES.items():
            with self.subTest(host=host):
                found = {relpath for relpath, _text in assets.iter_host_files(host)}
                self.assertEqual(found, expected)

    def test_yields_readable_content(self):
        for _relpath, text in assets.iter_host_files("claude-code"):
            self.assertTrue(text.strip(), "an embedded host file came back empty")

    def test_relative_paths_use_forward_slashes(self):
        """`cg setup` (F2) writes these straight into a target directory. A
        backslash-separated key from a Windows walk would create a file named
        `commands\\cg-new.md` instead of a commands/ directory."""
        for host in EXPECTED_HOST_FILES:
            for relpath, _text in assets.iter_host_files(host):
                self.assertNotIn("\\", relpath)

    def test_unknown_host_raises_a_typed_error(self):
        """Not an empty iterator: `cg setup --host typo` silently installing
        nothing and exiting 0 is the failure mode this forbids."""
        with self.assertRaises(assets.AssetNotFoundError):
            list(assets.iter_host_files("bogus"))

    def test_host_traversal_is_refused(self):
        with self.assertRaises(assets.AssetNotFoundError):
            list(assets.iter_host_files("../phases"))


class TestReadSnippet(unittest.TestCase):
    def test_every_snippet_resolves_and_parses_as_json(self):
        for host, name in SNIPPETS:
            with self.subTest(host=host, snippet=name):
                json.loads(assets.read_snippet(host, name))

    def test_unknown_snippet_raises_a_typed_error(self):
        with self.assertRaises(assets.AssetNotFoundError):
            assets.read_snippet("claude-code", "nope")

    def test_snippet_traversal_is_refused(self):
        with self.assertRaises(assets.AssetNotFoundError):
            assets.read_snippet("claude-code", "../../phases/plan")


class TestResolutionDoesNotDependOnTheRepoTree(unittest.TestCase):
    """PLAN-2.1 F1 point 2: "Nunca rutas relativas al repo". The clean-venv
    proof lives in test_packaging.py; this catches the cheaper local mistake of
    resolving against the current working directory."""

    def test_source_does_not_walk_out_of_the_package(self):
        with open(os.path.join(REPO_ROOT, "context_guard", "guard", "assets.py"), encoding="utf-8") as f:
            source = f.read()
        for pattern in (r"\.\./", r'"\.\."', r"'\.\.'", r"os\.getcwd", r"\.parent\.parent"):
            with self.subTest(pattern=pattern):
                self.assertNotRegex(source, pattern)

    def test_accessors_work_from_an_unrelated_working_directory(self):
        program = (
            "from context_guard.guard import assets;"
            "import sys;"
            "sys.stdout.write(assets.get_phase('plan'))"
        )
        with tempfile.TemporaryDirectory() as outside:
            env = dict(os.environ, PYTHONPATH=REPO_ROOT)
            res = subprocess.run(
                [sys.executable, "-c", program],
                cwd=outside, env=env, capture_output=True, text=True,
            )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, assets.get_phase("plan"))


class TestNothingIsDuplicatedInTheRepoTree(unittest.TestCase):
    """PLAN-2.1 F1 point 1: "Un solo origen: nada queda duplicado en el árbol."
    A leftover copy under phases/ or adapters/ is not inert — it is a second
    source that drifts from the packaged one, which is the exact class of bug
    F6 of 2.0 spent a phase removing."""

    def test_the_old_phases_directory_is_gone(self):
        self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, "phases")))

    def test_no_pre_f1_path_is_still_tracked_by_git(self):
        """Checking the working tree is not enough, and this caught a real
        mistake: the move was committed without staging the deletion of
        phases/*.md, so those files stayed in the index. Every assertion above
        passed — they read a working tree where the files were already gone —
        while a fresh clone would have got both copies, which is the exact
        duplication this phase exists to remove. What git tracks is what a
        clone receives, so that is what gets asserted."""
        res = subprocess.run(
            ["git", "ls-files", "phases/", "adapters/"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        tracked = [line for line in res.stdout.splitlines() if line.strip()]
        self.assertEqual(
            tracked, [],
            "no pre-F1 path may still be tracked (F2 removed the last one)",
        )

    def test_no_installable_artifact_remains_under_adapters(self):
        adapters = os.path.join(REPO_ROOT, "adapters")
        if not os.path.isdir(adapters):
            return
        leftovers = []
        for dirpath, _dirnames, filenames in os.walk(adapters):
            for name in filenames:
                if name.endswith(".snippet.json") or name.endswith(".md"):
                    leftovers.append(
                        os.path.relpath(os.path.join(dirpath, name), REPO_ROOT))
        self.assertEqual(
            leftovers, [],
            "artifacts and human docs both left adapters/ in F1; F2 removed "
            "the installer that was the last thing in there",
        )


class TestHumanDocsMovedToDocs(unittest.TestCase):
    """PLAN-2.1 F1 point 4: PERMISSIONS.md and VERIFY.md are documentation, not
    installable artifacts, so they move to docs/ instead of into the wheel."""

    def test_every_host_permissions_doc_lives_under_docs(self):
        for host in EXPECTED_HOST_FILES:
            path = os.path.join(REPO_ROOT, "docs", "adapters", host, "PERMISSIONS.md")
            self.assertTrue(os.path.exists(path), f"docs/adapters/{host}/PERMISSIONS.md is missing")

    def test_verify_checklist_lives_under_docs(self):
        self.assertTrue(
            os.path.exists(os.path.join(REPO_ROOT, "docs", "adapters", "VERIFY.md")))

    def test_readme_links_the_moved_docs(self):
        for name in ("README.md", "README.es.md"):
            with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as f:
                text = f.read()
            with self.subTest(readme=name):
                self.assertIn("docs/adapters/", text)
                # The lookbehind matters: without it the pattern also matches
                # inside the *correct* docs/adapters/... path, and the test
                # fails on the very fix it is supposed to accept.
                self.assertNotRegex(
                    text, re.compile(r"(?<!docs/)adapters/\*?/?[a-z-]*/?PERMISSIONS\.md"),
                    f"{name} still links PERMISSIONS.md at its pre-F1 path",
                )


if __name__ == "__main__":
    unittest.main()
