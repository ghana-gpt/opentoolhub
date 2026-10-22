"""Repository-level data checks, mirroring the validator used by CI."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate  # noqa: E402


class DataValidationTests(unittest.TestCase):
    maxDiff = None

    def test_no_errors(self):
        errors, _ = validate.validate_repository(ROOT / "data", ROOT)
        self.assertEqual(errors, [])

    def test_no_warnings(self):
        _, warnings = validate.validate_repository(ROOT / "data", ROOT)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
