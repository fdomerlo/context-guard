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


if __name__ == "__main__":
    unittest.main()
