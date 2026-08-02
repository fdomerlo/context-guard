"""PLAN-2.1 F1 point 5: the packaging test, written as the spec for the bug
that motivates the phase.

`[tool.hatch.build.targets.wheel] packages = ["context_guard"]` says nothing
about non-Python files, and no test ever opened a built artifact — so the
wheel could ship without the phases and snippets and the whole suite would
still be green. Everything here operates on real built artifacts, and the
clean-venv case is the acceptance criterion read literally: the assets resolve
"sin acceso al repo".

Skipped when `build` is not installed so a bare checkout stays green; CI
installs it (see test_ci_runs_the_packaging_test), which is where these must
never be allowed to skip silently.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

from tests.test_assets import EXPECTED_DATA_FILES, SNIPPETS

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CI_WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")

HAS_BUILD = importlib.util.find_spec("build") is not None


@unittest.skipUnless(HAS_BUILD, "the `build` package is required (pip install build)")
class BuiltArtifactCase(unittest.TestCase):
    """Builds the wheel and sdist once for the whole class — `python -m build`
    provisions an isolated build environment, which is far too slow to repeat
    per test method."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="guard_packaging_")
        cls.dist = os.path.join(cls._tmpdir, "dist")
        res = subprocess.run(
            [sys.executable, "-m", "build", "--outdir", cls.dist, REPO_ROOT],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            raise unittest.SkipTest(f"python -m build failed:\n{res.stdout}\n{res.stderr}")
        cls.wheel = cls._one(cls.dist, ".whl")
        cls.sdist = cls._one(cls.dist, ".tar.gz")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    @staticmethod
    def _one(directory, suffix):
        matches = [f for f in os.listdir(directory) if f.endswith(suffix)]
        if len(matches) != 1:
            raise AssertionError(f"expected exactly one {suffix} in {directory}, got {matches}")
        return os.path.join(directory, matches[0])

    def wheel_names(self):
        with zipfile.ZipFile(self.wheel) as zf:
            return set(zf.namelist())

    def sdist_names(self):
        with tarfile.open(self.sdist) as tf:
            # Strip the "<name>-<version>/" prefix every sdist member carries.
            return {m.name.split("/", 1)[1] for m in tf.getmembers()
                    if m.isfile() and "/" in m.name}


class TestWheelCarriesTheData(BuiltArtifactCase):
    def test_every_embedded_artifact_is_inside_the_wheel(self):
        names = self.wheel_names()
        for relpath in sorted(EXPECTED_DATA_FILES):
            with self.subTest(asset=relpath):
                self.assertIn(f"context_guard/_data/{relpath}", names)

    def test_wheel_ships_no_bytecode(self):
        for name in self.wheel_names():
            self.assertFalse(name.endswith(".pyc"), f"{name} is compiled bytecode")
            self.assertNotIn("__pycache__", name)

    def test_wheel_does_not_ship_the_human_docs(self):
        """F1 point 4 moved PERMISSIONS.md and VERIFY.md to docs/ precisely
        because they are not installation artifacts. A copy riding inside the
        wheel would be the second source of truth the move eliminated."""
        for name in self.wheel_names():
            basename = name.rsplit("/", 1)[-1]
            self.assertNotIn(basename, ("PERMISSIONS.md", "VERIFY.md"))


class TestSdistCarriesTheData(BuiltArtifactCase):
    """F1 point 3: "verificar AMBOS targets". hatchling selects sdist contents
    by a different mechanism than wheel contents, so a wheel that works proves
    nothing about the sdist — and the sdist is what a `pip install` from source
    on an unsupported platform builds from."""

    def test_every_embedded_artifact_is_inside_the_sdist(self):
        names = self.sdist_names()
        for relpath in sorted(EXPECTED_DATA_FILES):
            with self.subTest(asset=relpath):
                self.assertIn(f"context_guard/_data/{relpath}", names)


class TestTheInstalledWheelWorksOnACleanMachine(BuiltArtifactCase):
    """Two acceptance criteria, both read verbatim, sharing one built wheel
    and one clean venv because provisioning them twice doubles the slowest
    test in the suite for no extra coverage.

    F1: "wheel instalado en venv limpio resuelve los tres assets de fase y
    todos los snippets sin acceso al repo".

    The subprocess runs with a working directory outside the repo and no
    PYTHONPATH, so the only copy of context_guard reachable is the one pip
    unpacked from the wheel. Installed with --no-deps: `mcp` is irrelevant to
    asset resolution, and pulling it would make the test need the network."""

    PROBE = """
import json, sys
from context_guard.guard import assets
out = {"phases": {}, "snippets": {}}
for name in ("plan", "execute", "verify"):
    out["phases"][name] = assets.get_phase(name)
for host, snippet in %(snippets)r:
    out["snippets"]["%%s/%%s" %% (host, snippet)] = assets.read_snippet(host, snippet)
out["hosts"] = {h: sorted(r for r, _ in assets.iter_host_files(h))
                for h in ("claude-code", "opencode", "antigravity")}
json.dump(out, sys.stdout)
"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.venv = os.path.join(cls._tmpdir, "venv")
        subprocess.run([sys.executable, "-m", "venv", cls.venv], check=True,
                       capture_output=True)
        cls.python = os.path.join(cls.venv, "bin", "python")
        if not os.path.exists(cls.python):  # Windows layout
            cls.python = os.path.join(cls.venv, "Scripts", "python.exe")
        res = subprocess.run(
            [cls.python, "-m", "pip", "install", "--no-deps", "--quiet", cls.wheel],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            raise unittest.SkipTest(f"could not install the wheel:\n{res.stderr}")

    def _probe(self):
        program = self.PROBE % {"snippets": tuple(SNIPPETS)}
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as outside:
            res = subprocess.run(
                [self.python, "-c", program],
                cwd=outside, env=env, capture_output=True, text=True,
            )
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_the_installed_wheel_is_not_the_repo_checkout(self):
        """Guards the guard: if the probe were somehow importing the repo copy,
        every assertion below would pass while proving nothing."""
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as outside:
            res = subprocess.run(
                [self.python, "-c",
                 "import context_guard, sys; sys.stdout.write(context_guard.__file__)"],
                cwd=outside, env=env, capture_output=True, text=True,
            )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(
            res.stdout.startswith(REPO_ROOT + os.sep),
            f"the clean venv imported the repo checkout at {res.stdout}",
        )

    def test_all_three_phases_resolve(self):
        phases = self._probe()["phases"]
        for name in ("plan", "execute", "verify"):
            with open(os.path.join(REPO_ROOT, "context_guard", "_data", "phases",
                                   f"{name}.md"), encoding="utf-8") as f:
                self.assertEqual(phases[name], f.read())

    def test_every_snippet_resolves_and_parses(self):
        snippets = self._probe()["snippets"]
        for host, name in SNIPPETS:
            with self.subTest(host=host, snippet=name):
                json.loads(snippets[f"{host}/{name}"])

    def test_every_host_file_is_enumerable(self):
        hosts = self._probe()["hosts"]
        self.assertIn("commands/cg-new.md", hosts["claude-code"])
        self.assertIn("rules/context-guard.md", hosts["antigravity"])

    def test_the_antigravity_skill_travels_in_the_wheel(self):
        """PLAN-2.2 F1: "la skill viaja en el wheel". Called out separately
        from the set comparison above because this is a nested directory —
        `skills/context-guard/SKILL.md` — and the failure mode is a build
        backend that flattens or drops a level nobody thought to check."""
        hosts = self._probe()["hosts"]
        self.assertIn("skills/context-guard/SKILL.md", hosts["antigravity"])

    # --- F2: "pip install <wheel> && cg setup deja los tres hosts
    # configurados" on a simulated clean machine ---

    def _cg(self, *args, home=None):
        cg = os.path.join(os.path.dirname(self.python), "cg")
        if not os.path.exists(cg):
            cg = os.path.join(os.path.dirname(self.python), "cg.exe")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["HOME"] = home
        with tempfile.TemporaryDirectory() as outside:
            return subprocess.run([cg, *args], cwd=outside, env=env,
                                  capture_output=True, text=True)

    def _fake_machine(self):
        """A HOME with the three hosts' config directories already present, so
        `cg setup` detects all of them without being told."""
        home = tempfile.mkdtemp(prefix="guard_clean_machine_")
        self.addCleanup(shutil.rmtree, home, True)
        os.makedirs(os.path.join(home, ".config", "opencode"))
        os.makedirs(os.path.join(home, ".gemini"))
        return home

    def test_cg_setup_configures_all_three_hosts(self):
        home = self._fake_machine()
        res = self._cg("setup", home=home)
        self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
        for relpath in (".claude/commands/cg-new.md",
                        ".claude/settings.json",
                        ".config/opencode/commands/cg-new.md",
                        ".config/opencode/opencode.json",
                        ".gemini/config/hooks.json",
                        # PLAN-2.2 acceptance criterion 2: on a clean HOME the
                        # three hosts must each end up with a *discoverable*
                        # entry point. Antigravity's is this skill; the hook
                        # above is enforcement, which nobody discovers.
                        ".gemini/config/skills/context-guard/SKILL.md"):
            with self.subTest(path=relpath):
                self.assertTrue(os.path.exists(os.path.join(home, relpath)),
                                f"{relpath} was not configured by cg setup")

    def test_a_second_setup_run_changes_nothing(self):
        home = self._fake_machine()
        self.assertEqual(self._cg("setup", home=home).returncode, 0)
        first = {p: open(os.path.join(dp, n), encoding="utf-8", errors="replace").read()
                 for dp, _d, fs in os.walk(home) for n in fs
                 for p in [os.path.relpath(os.path.join(dp, n), home)]}
        self.assertEqual(self._cg("setup", home=home).returncode, 0)
        second = {p: open(os.path.join(dp, n), encoding="utf-8", errors="replace").read()
                  for dp, _d, fs in os.walk(home) for n in fs
                  for p in [os.path.relpath(os.path.join(dp, n), home)]}
        self.assertEqual(second, first)

    def test_cg_new_makes_a_virgin_project_operable(self):
        """"cg new demo --context <proyecto-virgen> deja el proyecto operable"
        — operable meaning the phase files the installed commands point at are
        actually there."""
        home = self._fake_machine()
        project = tempfile.mkdtemp(prefix="guard_virgin_project_")
        self.addCleanup(shutil.rmtree, project, True)
        res = self._cg("new", "demo", "--context", project, home=home)
        self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
        for name in ("plan.md", "execute.md", "verify.md"):
            self.assertTrue(
                os.path.exists(os.path.join(project, ".context-guard", "phases", name)),
                f".context-guard/phases/{name} is missing from a fresh project")


class TestPackagingTestRunsInCI(unittest.TestCase):
    """F1 point 5: "Este test corre en CI". Locally it skips when `build` is
    missing; if CI never installs `build`, the whole file skips there too and
    the phase's only real proof silently stops running."""

    def setUp(self):
        with open(CI_WORKFLOW, encoding="utf-8") as f:
            self.text = f.read()

    def test_ci_installs_build(self):
        """Checked as a chain, because that is how it can break: CI installs
        the dev extra, and the dev extra is what pulls in `build`. Asserting
        only one half lets the other be dropped without a test failing."""
        self.assertRegex(self.text, r"pip install[^\n]*\[dev\]")
        with open(os.path.join(REPO_ROOT, "pyproject.toml"), encoding="utf-8") as f:
            pyproject = f.read()
        dev_extra = re.search(r"^dev\s*=\s*\[([^\]]*)\]", pyproject, re.MULTILINE)
        self.assertIsNotNone(dev_extra, "pyproject.toml declares no dev extra")
        self.assertIn("build", dev_extra.group(1))

    def test_ci_runs_on_this_branch(self):
        """The 2.2 work happens on v2.2, so none of this would have run on a
        push until the trigger includes it."""
        self.assertIn("v2.2", self.text)


if __name__ == "__main__":
    unittest.main()
