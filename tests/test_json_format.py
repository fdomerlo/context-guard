"""Tests for --format json CLI output mode."""

import json
import os
import sys
import tempfile
import unittest

# Allow importing the context_guard package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_guard.guard.cli import _to_json


class TestToJson(unittest.TestCase):
    """Tests for _to_json() — pipe-delimited to JSON conversion."""

    def test_simple_success(self):
        """Simple SUCCESS|ACTION message converts to JSON."""
        result = json.loads(_to_json("SUCCESS|LOCK_ACQUIRED", 0, "claim"))
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["action"], "LOCK_ACQUIRED")
        self.assertEqual(result["command"], "claim")
        self.assertEqual(result["exit_code"], 0)

    def test_fail_with_details(self):
        """FAIL|ACTION|detail1|detail2 converts with details array."""
        result = json.loads(_to_json("FAIL|TASK_CLAIMED|agent-A", 1, "claim-task"))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["action"], "TASK_CLAIMED")
        self.assertEqual(result["details"], ["agent-A"])

    def test_key_value_format(self):
        """Key=value format (check-completion) converts to JSON."""
        msg = "source=tasks.md\ntotal=5\ncompleted=3\nall_complete=false"
        result = json.loads(_to_json(msg, 0, "check-completion"))
        self.assertEqual(result["command"], "check-completion")
        self.assertIn("sources", result)
        self.assertEqual(result["sources"][0]["source"], "tasks.md")
        self.assertEqual(result["sources"][0]["total"], 5)
        self.assertEqual(result["sources"][0]["completed"], 3)
        self.assertEqual(result["sources"][0]["all_complete"], False)

    def test_key_value_with_aggregate(self):
        """Multi-source key=value output includes aggregate fields."""
        msg = (
            "source=blockers_todo.md\n"
            "total=2\ncompleted=1\nall_complete=false\n"
            "\n"
            "source=tasks.md\n"
            "total=3\ncompleted=3\nall_complete=true\n"
            "\n"
            "aggregate_total=5\n"
            "aggregate_completed=4\n"
            "aggregate_all_complete=false"
        )
        result = json.loads(_to_json(msg, 0, "check-completion"))
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(result["aggregate_total"], 5)
        self.assertEqual(result["aggregate_completed"], 4)
        self.assertEqual(result["aggregate_all_complete"], False)

    def test_boolean_parsing(self):
        """'true'/'false' strings are converted to JSON booleans."""
        msg = "total=0\ncompleted=0\nall_complete=false"
        result = json.loads(_to_json(msg, 0))
        self.assertIs(result["all_complete"], False)

    def test_number_parsing(self):
        """Numeric strings are converted to JSON numbers."""
        msg = "total=42\ncompleted=10\nall_complete=false"
        result = json.loads(_to_json(msg, 0))
        self.assertEqual(result["total"], 42)
        self.assertEqual(result["completed"], 10)

    def test_single_word_message(self):
        """Single-word message like 'FREE' converts cleanly."""
        result = json.loads(_to_json("FREE", 0, "check-lock"))
        self.assertEqual(result["status"], "FREE")
        self.assertEqual(result["command"], "check-lock")

    def test_status_kv_format(self):
        """Status output (CONTEXT: ..., OBJECTIVE: ...) uses : separator."""
        msg = "CONTEXT: test-ctx\nOBJECTIVE: Build the thing\nPROGRESS: 3/5 tasks complete\nNEXT: 2.1 - Do stuff\nLOCK: FREE"
        # Status uses ": " not "=", so it goes through pipe-delimited path
        # Actually this will be treated as neither key=value (no =) nor pipe (no |)
        # It should still produce valid JSON
        result = json.loads(_to_json(msg, 0, "status"))
        self.assertIn("exit_code", result)

    def test_no_command(self):
        """Output without command still produces valid JSON."""
        result = json.loads(_to_json("SUCCESS|DONE", 0))
        self.assertEqual(result["status"], "SUCCESS")
        self.assertNotIn("command", result)

    def test_multiline_fail(self):
        """Multi-line FAIL output (from ValidationError) converts to JSON."""
        msg = "FAIL|MISSING|objective.md\nFAIL|TOO_LONG|snapshot.md|7000/6000"
        result = json.loads(_to_json(msg, 3, "validate"))
        # Multi-line pipe messages — first line is used
        self.assertIn("exit_code", result)
        self.assertEqual(result["exit_code"], 3)


if __name__ == "__main__":
    unittest.main()
