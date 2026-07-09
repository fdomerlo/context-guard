"""Tests for guard.manifest — load/save with atomic writes."""

import json
import os
import sys
import tempfile
import unittest

# Allow importing the guard package from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from guard.manifest import load_manifest, save_manifest
from guard.errors import ManifestCorruptError


class TestLoadManifest(unittest.TestCase):
    """Tests for load_manifest()."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_manifest_")
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_missing_file_returns_none(self):
        """load_manifest returns None when no manifest file exists."""
        result = load_manifest("ctx-test")
        self.assertIsNone(result)

    def test_valid_json_loads(self):
        """load_manifest parses a well-formed manifest.json correctly."""
        from guard.paths import get_paths
        p = get_paths("ctx-test")
        os.makedirs(os.path.dirname(p["manifest"]), exist_ok=True)
        data = {"context_name": "ctx-test", "lock": {"held": True}}
        with open(p["manifest"], "w") as f:
            json.dump(data, f)

        result = load_manifest("ctx-test")
        self.assertEqual(result, data)

    def test_corrupt_json_raises_manifest_corrupt(self):
        """load_manifest raises ManifestCorruptError on invalid JSON."""
        from guard.paths import get_paths
        p = get_paths("ctx-test")
        os.makedirs(os.path.dirname(p["manifest"]), exist_ok=True)
        with open(p["manifest"], "w") as f:
            f.write("{not valid json!!!")

        with self.assertRaises(ManifestCorruptError):
            load_manifest("ctx-test")

    def test_empty_file_raises_manifest_corrupt(self):
        """An empty file is invalid JSON and should raise ManifestCorruptError."""
        from guard.paths import get_paths
        p = get_paths("ctx-test")
        os.makedirs(os.path.dirname(p["manifest"]), exist_ok=True)
        with open(p["manifest"], "w") as f:
            f.write("")

        with self.assertRaises(ManifestCorruptError):
            load_manifest("ctx-test")


class TestSaveManifest(unittest.TestCase):
    """Tests for save_manifest()."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.mkdtemp(prefix="guard_test_manifest_")
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_creates_directories_and_writes(self):
        """save_manifest creates parent dirs and writes the manifest."""
        from guard.paths import get_paths
        data = {"context_name": "ctx-test", "status": "ok"}
        save_manifest("ctx-test", data)

        p = get_paths("ctx-test")
        self.assertTrue(os.path.exists(p["manifest"]))
        with open(p["manifest"], "r") as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_atomic_write_via_tmp_rename(self):
        """save_manifest uses tmp+rename — no .tmp file should remain."""
        from guard.paths import get_paths
        data = {"key": "value"}
        save_manifest("ctx-test", data)

        p = get_paths("ctx-test")
        tmp_path = p["manifest"] + ".tmp"
        self.assertFalse(os.path.exists(tmp_path),
                         "Temporary file should be removed after atomic rename")
        self.assertTrue(os.path.exists(p["manifest"]))

    def test_overwrite_existing_manifest(self):
        """save_manifest overwrites an existing manifest atomically."""
        data_v1 = {"version": 1}
        data_v2 = {"version": 2}
        save_manifest("ctx-test", data_v1)
        save_manifest("ctx-test", data_v2)

        result = load_manifest("ctx-test")
        self.assertEqual(result["version"], 2)

    def test_roundtrip_preserves_data(self):
        """save then load preserves all data."""
        data = {
            "context_name": "ctx-test",
            "lock": {"held": True, "ttl_seconds": 1800},
            "reference_docs": ["a.md", "b.md"],
            "files_in_scope": [],
        }
        save_manifest("ctx-test", data)
        loaded = load_manifest("ctx-test")
        self.assertEqual(loaded, data)


if __name__ == "__main__":
    unittest.main()
