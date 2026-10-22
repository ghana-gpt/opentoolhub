"""Tests for the data-driven recommender and its CLI contract."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import recommend  # noqa: E402

DATA = recommend.load_data()
SCRIPT = ROOT / "scripts" / "recommend.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class RankingTests(unittest.TestCase):
    def test_every_use_case_resolves_by_id(self):
        for use_case in DATA["use_cases"]:
            with self.subTest(use_case=use_case["id"]):
                result = recommend.build_recommendation(use_case["id"], DATA)
                self.assertEqual(result["use_case"]["id"], use_case["id"])
                self.assertEqual(result["matched_by"], "id")
                self.assertEqual(result["score"], 100)

    def test_every_use_case_resolves_by_name(self):
        for use_case in DATA["use_cases"]:
            with self.subTest(use_case=use_case["id"]):
                result = recommend.build_recommendation(use_case["name"], DATA)
                self.assertEqual(result["use_case"]["id"], use_case["id"])
                # Names such as "City dashboard" normalize to the same tokens as
                # the id "city-dashboard", so either match type is exact.
                self.assertIn(result["matched_by"], {"id", "name"})

    def test_every_alias_resolves(self):
        for use_case in DATA["use_cases"]:
            for alias in use_case["aliases"]:
                owner = {
                    candidate["id"]
                    for candidate in DATA["use_cases"]
                    if alias in candidate["aliases"]
                }
                with self.subTest(alias=alias):
                    result = recommend.build_recommendation(alias, DATA)
                    self.assertEqual(result["matched_by"], "alias")
                    self.assertIn(result["use_case"]["id"], owner)

    def test_keyword_query(self):
        result = recommend.build_recommendation("city neighborhood alerts", DATA)
        self.assertEqual(result["use_case"]["id"], "city-dashboard")
        self.assertEqual(result["matched_by"], "keywords")

    def test_unknown_query_lists_suggestions(self):
        with self.assertRaises(recommend.NoMatchError) as caught:
            recommend.build_recommendation("quantum welding torch", DATA)
        self.assertEqual(
            caught.exception.suggestions,
            [use_case["id"] for use_case in DATA["use_cases"]],
        )

    def test_empty_query_does_not_match(self):
        with self.assertRaises(recommend.NoMatchError):
            recommend.build_recommendation("   ", DATA)


class ResultTests(unittest.TestCase):
    def test_result_is_fully_resolved(self):
        result = recommend.build_recommendation("public health", DATA)
        self.assertTrue(result["stacks"])
        self.assertTrue(result["templates"])
        self.assertTrue(result["examples"])
        self.assertTrue(result["rationale"])

        expected_api_ids: list[str] = []
        for stack in result["stacks"]:
            self.assertTrue(stack["tools"])
            for tool in stack["tools"]:
                self.assertTrue(tool["apis"])
                for api in tool["apis"]:
                    self.assertIn(tool["category"], api["category_ids"])
                    if api["id"] not in expected_api_ids:
                        expected_api_ids.append(api["id"])
        self.assertEqual(result["api_ids"], expected_api_ids)

        for template in result["templates"]:
            self.assertIn(result["use_case"]["id"], template["use_case_ids"])
        for example in result["examples"]:
            self.assertEqual(example["use_case"], result["use_case"]["id"])

    def test_result_is_json_serializable(self):
        result = recommend.build_recommendation("travel planning", DATA)
        payload = json.loads(json.dumps(result))
        self.assertEqual(payload["use_case"]["id"], "travel-planner")

    def test_exact_match_is_not_ambiguous(self):
        result = recommend.build_recommendation("travel-planner", DATA)
        self.assertFalse(result["needs_disambiguation"])
        self.assertEqual(result["alternatives"], [])


class CliTests(unittest.TestCase):
    def test_json_output(self):
        completed = run_cli("--json", "mvp")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["use_case"]["id"], "startup-mvp")
        self.assertEqual(payload["matched_by"], "alias")

    def test_list_output(self):
        completed = run_cli("--list")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for use_case in DATA["use_cases"]:
            self.assertIn(use_case["id"], completed.stdout)

    def test_unknown_query_exit_code(self):
        completed = run_cli("quantum welding torch")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("No use case matched", completed.stderr)

    def test_missing_query_exit_code(self):
        completed = run_cli()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("provide a goal", completed.stderr)


if __name__ == "__main__":
    unittest.main()
