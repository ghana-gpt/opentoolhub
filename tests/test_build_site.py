"""Tests for the static-site staging step used by Pages and local preview."""

from __future__ import annotations

import io
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
        (self.data / "use-cases.json").write_text('{"items": []}\n', encoding="utf-8")
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
            '{"items": []}\n',
        )
        self.assertFalse((target / "removed.json").exists())
        self.assertIn("Staged 1 JSON file", output)

    def test_check_detects_stale_copy_without_overwriting_it(self):
        code, _, _ = self.run_stage()
        self.assertEqual(code, 0)
        target = self.site / "data" / "use-cases.json"
        original = target.read_bytes()

        (self.data / "use-cases.json").write_text('{"items": [1]}\n', encoding="utf-8")
        code, _, errors = self.run_stage(check_only=True)

        self.assertEqual(code, 1)
        self.assertIn("site/data is out of date", errors)
        self.assertEqual(target.read_bytes(), original)

    def test_missing_data_directory_fails_cleanly(self):
        shutil.rmtree(self.data)
        code, _, errors = self.run_stage()
        self.assertEqual(code, 1)
        self.assertIn("data directory not found", errors)

    def test_empty_data_directory_fails_cleanly(self):
        (self.data / "use-cases.json").unlink()
        code, _, errors = self.run_stage()
        self.assertEqual(code, 1)
        self.assertIn("no JSON files found", errors)


if __name__ == "__main__":
    unittest.main()
