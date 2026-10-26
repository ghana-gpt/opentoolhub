"""Tests for the static-site staging step used by Pages and local preview."""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_site  # noqa: E402


class BuildSiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.data = root / "data"
        self.site = root / "site"
        self.data.mkdir()
        self.site.mkdir()
        for name in build_site.CATALOG_FILES:
            (self.data / f"{name}.json").write_text("[]\n", encoding="utf-8")
        self.original_paths = (build_site.DATA_DIR, build_site.SITE_DIR)
        build_site.DATA_DIR = self.data
        build_site.SITE_DIR = self.site

    def tearDown(self):
        build_site.DATA_DIR, build_site.SITE_DIR = self.original_paths
        self.temp.cleanup()

    def run_stage(self, check_only: bool = False) -> tuple[int, str, str]:
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = build_site.stage(check_only=check_only)
        return code, output.getvalue(), errors.getvalue()

    def test_stage_copies_json_and_removes_stale_files(self):
        target = self.site / "data"
        target.mkdir()
        (target / "removed.json").write_text("[]\n", encoding="utf-8")

        code, output, _ = self.run_stage()

        self.assertEqual(code, 0)
        self.assertEqual(
            (target / "use-cases.json").read_text(encoding="utf-8"),
            "[]\n",
        )
        self.assertFalse((target / "removed.json").exists())
        self.assertIn(f"Staged {len(build_site.CATALOG_FILES)} JSON file", output)

    def test_stage_writes_a_deterministic_catalog_manifest(self):
        code, _, _ = self.run_stage()
        self.assertEqual(code, 0)
        catalog = self.site / "data" / build_site.CATALOG_FILE
        first = catalog.read_bytes()
        self.assertEqual(build_site.manifest_bytes(sorted(self.data.glob("*.json"))), first)

        self.run_stage()
        self.assertEqual(catalog.read_bytes(), first)

    def test_manifest_documents_files_schemas_counts_and_contract(self):
        code, _, _ = self.run_stage()
        self.assertEqual(code, 0)
        manifest = json.loads(
            (self.site / "data" / build_site.CATALOG_FILE).read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["schema_version"], build_site.SCHEMA_VERSION)
        self.assertEqual(manifest["recommendation"]["engine"], "deterministic-lexical-v2")
        self.assertEqual(set(manifest["files"]), set(build_site.CATALOG_FILES))
        self.assertEqual(set(manifest["entities"]), set(build_site.CATALOG_FILES))
        for name, entry in manifest["files"].items():
            self.assertEqual(entry["count"], 0)
            self.assertEqual(entry["id_field"], "id")
            self.assertTrue(entry["url"].endswith(f"data/{name}.json"))
            self.assertIn(
                f"#/$defs/{build_site.ENTITY_TYPES[name]}File",
                entry["schema"],
            )

    def test_check_detects_stale_copy_without_overwriting_it(self):
        code, _, _ = self.run_stage()
        self.assertEqual(code, 0)
        target = self.site / "data" / "use-cases.json"
        original = target.read_bytes()

        (self.data / "use-cases.json").write_text("[1]\n", encoding="utf-8")
        code, _, errors = self.run_stage(check_only=True)

        self.assertEqual(code, 1)
        self.assertIn("site/data is out of date", errors)
        self.assertEqual(target.read_bytes(), original)

    def test_check_detects_stale_manifest_without_overwriting_it(self):
        code, _, _ = self.run_stage()
        self.assertEqual(code, 0)
        catalog = self.site / "data" / build_site.CATALOG_FILE
        catalog.write_text("{}\n", encoding="utf-8")

        code, _, errors = self.run_stage(check_only=True)

        self.assertEqual(code, 1)
        self.assertIn(build_site.CATALOG_FILE, errors)
        self.assertEqual(catalog.read_text(encoding="utf-8"), "{}\n")

    def test_missing_data_directory_fails_cleanly(self):
        shutil.rmtree(self.data)
        code, _, errors = self.run_stage()
        self.assertEqual(code, 1)
        self.assertIn("data directory not found", errors)

    def test_empty_data_directory_fails_cleanly(self):
        for path in self.data.glob("*.json"):
            path.unlink()
        code, _, errors = self.run_stage()
        self.assertEqual(code, 1)
        self.assertIn("no JSON files found", errors)

    def test_incomplete_catalog_fails_cleanly(self):
        (self.data / "examples.json").unlink()
        code, _, errors = self.run_stage()
        self.assertEqual(code, 1)
        self.assertIn("missing catalog data file", errors)
        self.assertIn("examples", errors)


if __name__ == "__main__":
    unittest.main()
