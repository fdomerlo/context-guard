"""PLAN-2.1 F3: the release workflow that publishes to PyPI.

This file cannot observe a real publication, so it pins the two properties
that decide whether the publication is safe rather than whether it happened:
nothing gets published without the suite passing, and no long-lived token
exists to leak.

Asserted as text, not parsed YAML: adding a YAML parser would mean a new
dependency for one test file, and the workflow's meaningful content here is
literal strings anyway.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "publish.yml")
PYPROJECT = os.path.join(REPO_ROOT, "pyproject.toml")


def package_name():
    with open(PYPROJECT, encoding="utf-8") as f:
        match = re.search(r'^name\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
    assert match, "pyproject.toml declares no package name"
    return match.group(1)


class PublishWorkflowCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(WORKFLOW),
                        ".github/workflows/publish.yml is missing")
        with open(WORKFLOW, encoding="utf-8") as f:
            self.text = f.read()


class TestPublishWorkflowShape(PublishWorkflowCase):
    def test_triggers_on_a_published_release(self):
        self.assertRegex(self.text, r"release:\s*\n\s*types:\s*\[\s*published\s*\]")

    def test_builds_with_the_same_command_the_tests_use(self):
        self.assertIn("python -m build", self.text)

    def test_publishes_through_the_official_action(self):
        self.assertIn("pypa/gh-action-pypi-publish@release/v1", self.text)


class TestNothingPublishesWithoutGreenTests(PublishWorkflowCase):
    """F3 point 1: "Job separado previo que corre la suite completa: no se
    publica con tests rojos." A build step that happens to run before the
    upload in the same job is not that guarantee — `needs:` is."""

    def test_the_publish_job_depends_on_the_test_job(self):
        self.assertRegex(self.text, r"needs:\s*\[?\s*test\s*\]?")

    def test_a_job_runs_the_full_suite(self):
        self.assertIn("python -m unittest discover -s tests", self.text)

    def test_the_suite_job_installs_the_dev_extra(self):
        """Without it the packaging tests skip, and the one check that proves
        the wheel carries its data would silently not run on the release
        that ships that wheel."""
        self.assertRegex(self.text, r"pip install[^\n]*\[dev\]")


class TestTrustedPublishingLeavesNoTokenToLeak(PublishWorkflowCase):
    """F3 point 1: Trusted Publishing, "sin tokens guardados".

    The point is not convenience. A long-lived token is a secret that can
    leak and then publishes from anywhere; OIDC binds the ability to publish
    to one workflow in one repository with the suite green. If a token ever
    reappears here, the control is gone and nothing else in this file would
    notice.
    """

    def test_the_workflow_requests_an_oidc_token(self):
        self.assertRegex(self.text, r"id-token:\s*write")

    def test_no_api_token_or_password_is_referenced(self):
        for forbidden in ("PYPI_API_TOKEN", "TWINE_PASSWORD", "password:",
                          "twine upload"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, self.text)

    def test_it_runs_in_the_environment_the_publisher_was_registered_against(self):
        """The pending publisher on PyPI names repository, workflow filename
        and environment. A mismatch on any of the three fails the upload with
        an OIDC error that reads like a permissions bug, so the environment
        name is pinned here rather than rediscovered during a release."""
        self.assertRegex(self.text, r"environment:\s*\n?\s*(name:\s*)?pypi")


class TestTheDocumentedInstallNameIsTheRealOne(unittest.TestCase):
    """The runbook records that `context-guard` may be refused by PyPI's
    similarity check and that the fallback is `context-guard-cli`. If that
    fallback is ever applied — or reverted — pyproject.toml and every
    `pip install` line in the docs have to move together. They are edited in
    different places by different people, which is exactly how they drift.
    """

    DOCS = ("README.md", "README.es.md", "TUTORIAL.es.md")

    def test_every_documented_pip_install_uses_the_declared_name(self):
        name = package_name()
        for doc in self.DOCS:
            with open(os.path.join(REPO_ROOT, doc), encoding="utf-8") as f:
                text = f.read()
            # Only installs of a published package name. Editable and local
            # installs (`pip install -e ".[dev]"`) name a path, not a
            # package, and belong to the contributor instructions.
            for args in re.findall(r"pip install ([^\n`]+)", text):
                tokens = [t for t in args.split() if not t.startswith("-")]
                if not tokens or tokens[0].startswith((".", '"', "'")) or "/" in tokens[0]:
                    continue
                with self.subTest(doc=doc, package=tokens[0]):
                    self.assertEqual(tokens[0], name)

    def test_the_pypi_badge_points_at_the_declared_name(self):
        name = package_name()
        for doc in ("README.md", "README.es.md"):
            with open(os.path.join(REPO_ROOT, doc), encoding="utf-8") as f:
                text = f.read()
            with self.subTest(doc=doc):
                self.assertIn(f"img.shields.io/pypi/v/{name}", text)


class TestInstallationIsTwoLines(unittest.TestCase):
    """F3 point 3 and the phase's whole justification: installing must stop
    requiring a clone of this repository."""

    def _install_section(self, doc, heading):
        with open(os.path.join(REPO_ROOT, doc), encoding="utf-8") as f:
            text = f.read()
        match = re.search(rf"^## {heading}$(.*?)(?=^## )", text, re.M | re.S)
        self.assertIsNotNone(match, f"{doc} has no '{heading}' section")
        return match.group(1)

    def test_the_readme_installs_from_pypi(self):
        for doc, heading in (("README.md", "Install"),
                             ("README.es.md", "Instalación")):
            section = self._install_section(doc, heading)
            with self.subTest(doc=doc):
                self.assertIn(f"pip install {package_name()}", section)
                self.assertIn("cg setup", section)

    def test_the_readme_no_longer_installs_from_a_git_url(self):
        for doc, heading in (("README.md", "Install"),
                             ("README.es.md", "Instalación")):
            section = self._install_section(doc, heading)
            with self.subTest(doc=doc):
                self.assertNotIn("git+https://github.com", section)

    def test_the_tutorial_never_asks_the_reader_to_clone(self):
        with open(os.path.join(REPO_ROOT, "TUTORIAL.es.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("git clone", text)
        self.assertNotIn("git+https://github.com", text)

    def test_the_tutorial_has_exactly_one_installation_section(self):
        """F3 point 3: "queda UNA sección de instalación". Two sections that
        each claim to be the one-time setup is how a reader ends up doing
        neither correctly."""
        with open(os.path.join(REPO_ROOT, "TUTORIAL.es.md"), encoding="utf-8") as f:
            headings = re.findall(r"^## \d+\. (.+)$", f.read(), re.M)
        installs = [h for h in headings if "nstalaci" in h]
        self.assertEqual(len(installs), 1, f"installation sections found: {installs}")


class TestTutorialCrossReferencesSurvivedRenumbering(unittest.TestCase):
    """Merging the tutorial's two installation sections shifted every later
    section number down by one, and left four "paso N" pointers aimed at the
    wrong sections — a reader following "see step 5" landed on the wrong
    place. Renumbering is the classic way prose rots silently: nothing about
    a stale but valid-looking number fails a build.
    """

    def setUp(self):
        with open(os.path.join(REPO_ROOT, "TUTORIAL.es.md"), encoding="utf-8") as f:
            self.text = f.read()
        self.sections = {
            int(n): title
            for n, title in re.findall(r"^## (\d+)\. (.+)$", self.text, re.M)
        }
        self.assertTrue(self.sections, "no numbered sections found")

    def test_every_referenced_step_exists(self):
        for n in re.findall(r"\bpaso (\d+)\b", self.text):
            with self.subTest(step=n):
                self.assertIn(int(n), self.sections)

    def test_pointers_to_the_approval_step_name_the_right_section(self):
        approval = [n for n, title in self.sections.items() if "aprobaci" in title.lower()]
        self.assertEqual(len(approval), 1, f"approval sections: {approval}")
        expected = approval[0]
        for sentence in re.split(r"(?<=[.!?])\s+", self.text):
            match = re.search(r"\bpaso (\d+)\b", sentence)
            if match and "aprobaci" in sentence.lower():
                with self.subTest(sentence=sentence[:60]):
                    self.assertEqual(
                        int(match.group(1)), expected,
                        "a pointer to the approval step names the wrong section",
                    )


class TestBacklogIsRecordedRatherThanForgotten(unittest.TestCase):
    """F3 point 4 names three things explicitly out of scope. An
    out-of-scope decision that lives only in a plan file disappears the
    moment the cycle closes."""

    def test_the_changelog_records_what_was_left_out(self):
        with open(os.path.join(REPO_ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            text = f.read()
        for item in ("get.sh", "--uninstall"):
            with self.subTest(item=item):
                self.assertIn(item, text)


if __name__ == "__main__":
    unittest.main()
