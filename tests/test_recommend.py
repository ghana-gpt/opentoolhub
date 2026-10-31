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

    def test_stemming_matches_plurals(self):
        result = recommend.build_recommendation("city dashboards", DATA)
        self.assertEqual(result["use_case"]["id"], "city-dashboard")
        self.assertEqual(result["matched_by"], "keywords")
        self.assertGreaterEqual(result["score"], recommend.MIN_KEYWORD_SCORE)
        self.assertLessEqual(result["score"], recommend.MAX_KEYWORD_SCORE)

    def test_british_and_american_spellings_collapse(self):
        self.assertEqual(
            recommend.stem("visualisations"), recommend.stem("visualization")
        )
        self.assertEqual(recommend.stem("visualise"), recommend.stem("visualization"))
        result = recommend.build_recommendation("vaccinations", DATA)
        self.assertEqual(result["use_case"]["id"], "public-health-platform")

    def test_stopwords_are_dropped_before_scoring(self):
        self.assertEqual(
            recommend.tokenize("Build an app for my city dashboards"),
            recommend.tokenize("city dashboards"),
        )

    def test_typo_still_matches(self):
        result = recommend.build_recommendation("travle app", DATA)
        self.assertEqual(result["use_case"]["id"], "travel-planner")
        self.assertEqual(result["matched_by"], "fuzzy")
        self.assertLess(result["score"], 90)

    def test_transposition_typo_still_matches(self):
        result = recommend.build_recommendation("fligths to rome", DATA)
        self.assertEqual(result["use_case"]["id"], "travel-planner")
        self.assertEqual(result["matched_by"], "fuzzy")

    def test_within_one_edit(self):
        self.assertTrue(recommend._within_one_edit("city", "ctiy"))
        self.assertTrue(recommend._within_one_edit("travel", "travle"))
        self.assertTrue(recommend._within_one_edit("travel", "trave"))
        self.assertFalse(recommend._within_one_edit("travel", "trouble"))

    def test_short_tokens_are_not_fuzzy_matched(self):
        self.assertIsNone(recommend._fuzzy_term("cit", {"city"}))

    def test_generic_terms_are_never_fuzzy_matched(self):
        self.assertIn("tracker", recommend.GENERIC_TERMS)
        self.assertIsNone(recommend._fuzzy_term("tracker", {"tracker"}))

    def test_generic_terms_are_capped_in_every_field(self):
        index = recommend._build_index(DATA)
        self.assertEqual(
            index["weights"]["public-health-platform"]["tracker"],
            recommend.GENERIC_WEIGHT,
        )

    def test_generic_term_cannot_carry_a_two_word_query(self):
        with self.assertRaises(recommend.NoMatchError):
            recommend.build_recommendation("fitness tracker", DATA)

    def test_single_distinctive_term_needs_enough_coverage(self):
        # "farmer" is distinctive, but one term of five is too little of the
        # query for a confident answer.
        with self.assertRaises(recommend.NoMatchError):
            recommend.build_recommendation(
                "crop insurance claims for smallholder farmers", DATA
            )

    def test_single_generic_word_does_not_match(self):
        # "app for my business" reduces to one low-signal word, so the engine
        # refuses rather than listing four unrelated dashboards.
        with self.assertRaises(recommend.NoMatchError) as caught:
            recommend.build_recommendation("app for my business", DATA)
        self.assertTrue(caught.exception.closest)

    def test_phrase_query_matches_the_use_case_that_covers_most_terms(self):
        result = recommend.build_recommendation(
            "weather app for farmers in northern Ghana", DATA
        )
        self.assertEqual(result["use_case"]["id"], "climate-resilience")
        self.assertEqual(result["matched_by"], "keywords")

    def test_phrase_query_ignores_generic_terms(self):
        result = recommend.build_recommendation("farmers market prices", DATA)
        self.assertEqual(result["use_case"]["id"], "community-food-access")

    def test_local_service_query_resolves_to_the_city_dashboard(self):
        result = recommend.build_recommendation(
            "reporting broken streetlights to local government", DATA
        )
        self.assertEqual(result["use_case"]["id"], "city-dashboard")

    def test_fuzzy_matching_ignores_known_catalog_words(self):
        # "flood" is a real catalog term, so it must not fuzzy-match "food" in
        # another use case just because the two are one edit apart.
        query = "flood alerts for riverside villages"
        result = recommend.build_recommendation(query, DATA)
        self.assertEqual(result["use_case"]["id"], "climate-resilience")
        self.assertEqual(result["matched_by"], "keywords")
        ranked_ids = [item["use_case"]["id"] for item in recommend.rank(query, DATA)]
        self.assertEqual(ranked_ids, ["climate-resilience"])

    def test_fuzzy_only_match_scores_below_the_exact_spelling(self):
        exact = recommend.build_recommendation("flights to rome", DATA)
        typo = recommend.build_recommendation("fligths to rome", DATA)
        self.assertEqual(exact["matched_by"], "keywords")
        self.assertEqual(typo["matched_by"], "fuzzy")
        self.assertEqual(exact["use_case"]["id"], typo["use_case"]["id"])
        self.assertLess(typo["score"], exact["score"])

    def test_single_distinctive_keyword_matches(self):
        result = recommend.build_recommendation("food bank locator", DATA)
        self.assertEqual(result["use_case"]["id"], "community-food-access")

    def test_ambiguous_keyword_is_flagged(self):
        result = recommend.build_recommendation("dashboard", DATA)
        self.assertTrue(result["needs_disambiguation"])
        self.assertTrue(result["alternatives"])
        best = result["score"]
        self.assertLess(best, 90)
        self.assertGreaterEqual(result["alternatives"][0]["score"], best - 5)

    def test_unknown_query_lists_suggestions(self):
        with self.assertRaises(recommend.NoMatchError) as caught:
            recommend.build_recommendation("quantum welding torch", DATA)
        self.assertEqual(
            caught.exception.suggestions,
            [use_case["id"] for use_case in DATA["use_cases"]],
        )
        self.assertEqual(caught.exception.closest, [])

    def test_unknown_query_offers_closest_matches(self):
        with self.assertRaises(recommend.NoMatchError) as caught:
            recommend.build_recommendation("stock market prices", DATA)
        closest = caught.exception.closest
        self.assertTrue(closest)
        self.assertLessEqual(len(closest), 3)
        for item in closest:
            self.assertIn(item["id"], DATA["use_case_by_id"])
            self.assertTrue(item["matched"])
            self.assertGreater(item["coverage"], 0)

    def test_suggest_orders_by_evidence(self):
        closest = recommend.suggest("dashboard", DATA, limit=2)
        self.assertEqual(len(closest), 2)
        keys = [(-len(item["matched"]), -item["coverage"]) for item in closest]
        self.assertEqual(keys, sorted(keys))

    def test_rank_orders_by_score_then_name(self):
        ranked = recommend.rank("dashboard", DATA)
        self.assertGreaterEqual(len(ranked), 2)
        keys = [(-item["score"], item["use_case"]["name"].lower()) for item in ranked]
        self.assertEqual(keys, sorted(keys))

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
        self.assertNotIn("Closest matches:", completed.stderr)

    def test_unknown_query_prints_closest_matches(self):
        completed = run_cli("stock market prices")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("No use case matched", completed.stderr)
        self.assertIn("Closest matches:", completed.stderr)

    def test_typo_query_json_reports_fuzzy_match(self):
        completed = run_cli("--json", "travle app")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["use_case"]["id"], "travel-planner")
        self.assertEqual(payload["matched_by"], "fuzzy")

    def test_missing_query_exit_code(self):
        completed = run_cli()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("provide a goal", completed.stderr)


if __name__ == "__main__":
    unittest.main()
