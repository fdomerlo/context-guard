"""F5: 'README.es.md espejo' (PLAN.md 0.2/F5). Split from test_readme.py so
the English README lands as its own green commit before the mirror exists."""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(REPO_ROOT, "README.md")
README_ES_PATH = os.path.join(REPO_ROOT, "README.es.md")

SPANISH_INDICATORS = ["á", "é", "í", "ó", "ú", "ñ", "¿", "¡"]


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class TestSpanishMirror(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(README_ES_PATH), "README.es.md is missing")
        self.text = _read(README_ES_PATH)

    def test_is_substantively_spanish(self):
        spanish_count = sum(self.text.lower().count(c) for c in SPANISH_INDICATORS)
        self.assertGreater(spanish_count, 30, "README.es.md reads as an English file, not a mirror")

    def test_links_back_to_the_english_original(self):
        self.assertIn("README.md", self.text)

    def test_carries_the_same_section_structure(self):
        """A mirror that drops sections silently is worse than no mirror: it
        looks complete and is not."""
        en_headers = re.findall(r"^##\s+.+$", _read(README_PATH), re.MULTILINE)
        es_headers = re.findall(r"^##\s+.+$", self.text, re.MULTILINE)
        self.assertEqual(
            len(en_headers), len(es_headers),
            f"README.md has {len(en_headers)} ## sections, README.es.md has {len(es_headers)}",
        )


if __name__ == "__main__":
    unittest.main()
