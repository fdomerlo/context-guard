"""Unit tests for phase, task, acceptance criteria and verification helpers in manifest.py."""

import os
import shutil
import tempfile
import unittest

from context_guard.guard.manifest import (
    add_phase,
    all_phases_complete,
    create_initial_manifest,
    get_active_phase,
    get_phase,
    get_phase_tasks,
    get_phases,
    is_phase_complete,
    load_manifest,
    save_manifest,
    set_active_phase,
    update_acceptance_in_phase,
    update_phase_status,
    update_task_in_phase,
)


class TestManifestPhases(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_phases_")
        os.chdir(self._tmpdir)
        self.context = self._tmpdir

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_initial_manifest_with_phases(self):
        phases = [
            {
                "id": "F1",
                "name": "Initial Setup",
                "spec": "Scaffold DB schema",
                "tasks": [{"id": "1.1", "description": "Create migration", "status": "pending"}],
                "acceptance_criteria": [{"id": "ac-1", "description": "Migrates cleanly", "completed": False}],
                "verification": {"command": "pytest", "status": "pending"},
            },
            {
                "id": "F2",
                "name": "Endpoints",
                "tasks": [],
                "acceptance_criteria": [],
            }
        ]
        m = create_initial_manifest(
            self.context,
            change="test-change",
            requirement="Setup Auth",
            objective="Build OAuth2",
            phases=phases,
        )
        self.assertEqual(m["change_name"], "test-change")
        self.assertEqual(m["requirement"], "Setup Auth")
        self.assertEqual(m["objective"], "Build OAuth2")
        self.assertEqual(len(m["phases"]), 2)
        self.assertEqual(m["active_phase_id"], "F1")

    def test_get_and_set_phases(self):
        m = create_initial_manifest(self.context, "change1")
        self.assertEqual(get_phases(m), [])
        self.assertIsNone(get_active_phase(m))

        p1 = add_phase(m, {
            "id": "F1",
            "name": "Phase 1",
            "spec": "Spec 1",
            "tasks": [{"id": "1.1", "description": "T1", "status": "pending"}],
            "acceptance_criteria": [{"id": "ac-1", "description": "A1", "completed": False}],
        })
        self.assertEqual(p1["id"], "F1")
        self.assertEqual(m["active_phase_id"], "F1")
        self.assertEqual(get_active_phase(m)["id"], "F1")

        p2 = add_phase(m, {
            "id": "F2",
            "name": "Phase 2",
            "tasks": [{"id": "2.1", "description": "T2", "status": "pending"}],
        })
        self.assertEqual(len(get_phases(m)), 2)
        self.assertEqual(get_phase(m, "F2")["name"], "Phase 2")
        self.assertIsNone(get_phase(m, "F99"))

        set_active_phase(m, "F2")
        self.assertEqual(m["active_phase_id"], "F2")
        self.assertEqual(get_active_phase(m)["id"], "F2")

        with self.assertRaises(ValueError):
            set_active_phase(m, "F99")

    def test_task_and_acceptance_updates(self):
        m = create_initial_manifest(self.context, "change1")
        add_phase(m, {
            "id": "F1",
            "tasks": [
                {"id": "1.1", "description": "Task 1", "status": "pending"},
                {"id": "1.2", "description": "Task 2", "status": "pending"},
            ],
            "acceptance_criteria": [
                {"id": "ac-1", "description": "Crit 1", "completed": False},
                {"id": "ac-2", "description": "Crit 2", "completed": False},
            ],
        })

        self.assertFalse(is_phase_complete(m, "F1"))

        # Claim and complete task 1.1
        self.assertTrue(update_task_in_phase(m, "1.1", "claimed", agent_id="agent-123"))
        tasks = get_phase_tasks(m, "F1")
        self.assertEqual(tasks[0]["status"], "claimed")
        self.assertEqual(tasks[0]["claimed_by"], "agent-123")

        update_task_in_phase(m, "1.1", "done")
        self.assertFalse(is_phase_complete(m, "F1"))

        # Complete task 1.2
        update_task_in_phase(m, "1.2", "done")
        self.assertFalse(is_phase_complete(m, "F1"))

        # Complete acceptance criteria
        self.assertTrue(update_acceptance_in_phase(m, "ac-1", True))
        self.assertFalse(is_phase_complete(m, "F1"))
        self.assertTrue(update_acceptance_in_phase(m, "ac-2", True))
        self.assertTrue(is_phase_complete(m, "F1"))

        # Test phase status and auto-advance of active phase
        add_phase(m, {"id": "F2", "tasks": []})
        self.assertFalse(all_phases_complete(m))
        update_phase_status(m, "F1", "completed")
        self.assertEqual(m["active_phase_id"], "F2")
        update_phase_status(m, "F2", "completed")
        self.assertTrue(all_phases_complete(m))

    def test_save_and_load_phases_roundtrip(self):
        m = create_initial_manifest(self.context, "mychange")
        add_phase(m, {
            "id": "F1",
            "name": "Phase One",
            "spec": "Detailed spec",
            "tasks": [{"id": "1.1", "description": "First task", "status": "done"}],
            "acceptance_criteria": [{"id": "ac-1", "description": "Check this", "completed": True}],
            "verification": {"command": "pytest", "status": "passed"},
        })
        save_manifest(self.context, m, "mychange")

        loaded = load_manifest(self.context, "mychange")
        self.assertIsNotNone(loaded)
        self.assertEqual(len(get_phases(loaded)), 1)
        phase = get_phase(loaded, "F1")
        self.assertEqual(phase["spec"], "Detailed spec")
        self.assertTrue(is_phase_complete(loaded, "F1"))


if __name__ == "__main__":
    unittest.main()
