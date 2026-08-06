"""PLAN-2.5 F1: parsing a phased PLAN-N.md into the structure cg new
--from-plan will materialize as changes.

The parser reads documents written by humans and by the disciplined-scaffold
template, so the tests cover both languages the repo actually produces plans
in, and a plan that ignores the template's sub-blocks entirely."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.errors import EXIT_VALIDATION, GuardError
from context_guard.guard.plan_import import parse_plan

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    return os.path.join(FIXTURES, name)


class TestParseSpanishPlan(unittest.TestCase):
    """A real plan from this repo, in Spanish, with the template's sub-block
    labels translated — the shape the human actually writes."""

    def setUp(self):
        self.plan = parse_plan(fixture("plan_es.md"))

    def test_title_comes_from_the_h1(self):
        self.assertIn("Continuación automática", self.plan.title)

    def test_one_sentence_objective_is_the_prose_under_the_title(self):
        self.assertIn("dogfooding real", self.plan.objective)
        # The objective stops at the first section heading — it must not
        # swallow the diagnosis section.
        self.assertNotIn("Diagnóstico", self.plan.objective)

    def test_finds_every_phase(self):
        self.assertEqual([p.id for p in self.plan.phases], ["F1", "F2", "F3"])

    def test_phase_name_excludes_the_id(self):
        self.assertEqual(
            self.plan.phases[0].name,
            "Continuación automática en la misma sesión (Sonnet)",
        )

    def test_phase_body_is_the_prose_before_the_first_sub_block(self):
        body = self.plan.phases[0].body
        self.assertIn("Step 6", body)
        self.assertNotIn("**Tests:**", body)

    def test_spanish_sub_block_labels_are_recognized(self):
        f2 = self.plan.phases[1]
        self.assertIn("Candidato A", f2.spec)
        self.assertIn("extender el test", f2.tests)
        self.assertIn("validó en vivo", f2.acceptance)

    def test_a_phase_section_stops_at_the_next_phase(self):
        self.assertNotIn("Disparadores", self.plan.phases[0].body)

    def test_trailing_non_phase_sections_are_not_phases(self):
        # "Fuera de scope" and "Criterios de aceptación" follow F3 but are
        # not F-blocks; F3 must not absorb them either.
        self.assertNotIn("Fuera de scope", self.plan.phases[2].body)


class TestParseEnglishTemplatePlan(unittest.TestCase):
    """A plan generated from disciplined-scaffold's PLAN.md.template."""

    def setUp(self):
        self.plan = parse_plan(fixture("plan_en.md"))

    def test_title_and_objective(self):
        self.assertIn("Retry budget", self.plan.title)
        self.assertIn("bounded retry budget", self.plan.objective)

    def test_finds_every_phase(self):
        self.assertEqual([p.id for p in self.plan.phases], ["F1", "F2"])

    def test_english_sub_block_labels_are_recognized(self):
        f1 = self.plan.phases[0]
        self.assertIn("max_attempts", f1.spec)
        self.assertIn("dead-letter queue exactly once", f1.tests)
        self.assertIn("No message is retried more than", f1.acceptance)

    def test_the_templates_boilerplate_sentence_stays_with_the_tests_block(self):
        # The template's Tests: label carries a fixed instruction sentence on
        # the same line. Dropping it would silently truncate the block.
        self.assertIn("adversarial test first", self.plan.phases[0].tests)


class TestToleratesPlansThatIgnoreTheTemplate(unittest.TestCase):
    """"Un bloque faltante no es error, devuelve vacío." A plan that skips
    sub-blocks is the common case for short cycles, not a malformed file."""

    def setUp(self):
        self.plan = parse_plan(fixture("plan_sparse.md"))

    def test_phase_with_no_sub_blocks_still_parses(self):
        f1 = self.plan.phases[0]
        self.assertIn("Just prose", f1.body)
        self.assertEqual(f1.spec, "")
        self.assertEqual(f1.tests, "")
        self.assertEqual(f1.acceptance, "")

    def test_missing_tests_block_is_empty_not_an_exception(self):
        f2 = self.plan.phases[1]
        self.assertIn("Rename the config key", f2.spec)
        self.assertEqual(f2.tests, "")
        self.assertIn("old key still resolves", f2.acceptance)


class TestAFileWithNoPhasesIsAnError(unittest.TestCase):
    """A document with no F-block is not a plan. Returning zero phases would
    let cg new --from-plan report success having created nothing."""

    def test_raises_plan_no_phases(self):
        path = fixture("plan_no_phases.md")
        with self.assertRaises(GuardError) as ctx:
            parse_plan(path)
        self.assertIn("FAIL|PLAN_NO_PHASES|", ctx.exception.message)
        self.assertIn(path, ctx.exception.message)

    def test_prose_mentioning_f1_inline_does_not_count_as_a_phase(self):
        # The fixture says "F1" in a sentence; only a heading declares a phase.
        with self.assertRaises(GuardError):
            parse_plan(fixture("plan_no_phases.md"))

    def test_exit_code_is_validation(self):
        with self.assertRaises(GuardError) as ctx:
            parse_plan(fixture("plan_no_phases.md"))
        self.assertEqual(ctx.exception.exit_code, EXIT_VALIDATION)


class TestMissingFile(unittest.TestCase):
    def test_a_missing_plan_is_reported_not_traced(self):
        with self.assertRaises(GuardError) as ctx:
            parse_plan(fixture("does_not_exist.md"))
        self.assertIn("FAIL|PLAN_NOT_FOUND|", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
