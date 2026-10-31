"""Checks for the runnable ``public-data-dashboard`` starter.

These tests never touch the network: they validate the committed snapshot, the
snapshot shape the browser code relies on, and the parsing logic of the refresh
script with a stubbed HTTP layer.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "public-data-dashboard"
APP = TEMPLATE / "app"
SNAPSHOT = APP / "data" / "indicators.json"


def load_fetch_module():
    """Import ``templates/public-data-dashboard/scripts/fetch_data.py``."""
    path = TEMPLATE / "scripts" / "fetch_data.py"
    spec = importlib.util.spec_from_file_location("pd_dashboard_fetch_data", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # keep the template tree free of __pycache__
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


class AssetParser(HTMLParser):
    """Collect local ``src``/``href`` references from the starter's markup."""

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"src", "href"} and value:
                self.refs.append(value)


class SnapshotTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        cls.fetch = load_fetch_module()

    def test_snapshot_is_committed(self):
        self.assertTrue(SNAPSHOT.is_file(), "the starter must ship a data snapshot")
        self.assertGreater(SNAPSHOT.stat().st_size, 1000)

    def test_snapshot_matches_declared_catalog(self):
        """The snapshot and the refresh script must not drift apart."""
        self.assertEqual(self.data["countries"], self.fetch.COUNTRIES)
        self.assertEqual(
            [(item["id"], item["name"]) for item in self.data["indicators"]],
            [(item["id"], item["name"]) for item in self.fetch.INDICATORS],
        )
        years = list(range(self.fetch.START_YEAR, self.fetch.END_YEAR + 1))
        self.assertEqual(self.data["years"], years)

    def test_defaults_are_selectable(self):
        country_ids = {country["id"] for country in self.data["countries"]}
        indicator_ids = {item["id"] for item in self.data["indicators"]}
        self.assertIn(self.data["default_country"], country_ids)
        self.assertIn(self.data["default_indicator"], indicator_ids)

    def test_series_only_uses_known_countries_and_years(self):
        country_ids = {country["id"] for country in self.data["countries"]}
        years = {str(year) for year in self.data["years"]}
        for indicator in self.data["indicators"]:
            self.assertTrue(indicator["source_url"].endswith(indicator["id"]))
            self.assertIn(indicator["format"], {"integer", "currency", "decimal1", "decimal2"})
            series = indicator["series"]
            self.assertLessEqual(set(series), country_ids, indicator["id"])
            for country_id, values in series.items():
                where = f"{indicator['id']}/{country_id}"
                self.assertLessEqual(set(values), years, where)
                for year, value in values.items():
                    self.assertIsInstance(value, (int, float), f"{where}/{year}")
                    self.assertIsNotNone(value, "gaps must be absent, never null")

    def test_every_indicator_has_values(self):
        for indicator in self.data["indicators"]:
            values = sum(len(year_values) for year_values in indicator["series"].values())
            self.assertGreaterEqual(values, 20, f"{indicator['id']} looks truncated")

    def test_source_block_keeps_attribution(self):
        source = self.data["source"]
        self.assertIn("World Bank", source["name"])
        self.assertEqual(source["license"], "CC BY 4.0")
        self.assertIn("CC BY 4.0", source["attribution"])
        self.assertTrue(source["api"].startswith("https://"))
        self.assertTrue(self.data["generated_at"].endswith("+00:00"))


class FetchScriptTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.fetch = load_fetch_module()
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.output = Path(tmpdir.name) / "nested" / "indicators.json"

    def test_fetch_indicator_parses_rows_and_drops_gaps(self):
        payload = [
            {"page": 1},
            [
                {"countryiso3code": "GHA", "date": "2020", "value": 100.0},
                {"countryiso3code": "GHA", "date": "2021", "value": None},
                {"countryiso3code": "KEN", "date": "2020", "value": 42.5},
                {"countryiso3code": "", "country": {"id": "IND"}, "date": "2020", "value": 7},
                {"countryiso3code": "IND", "date": "", "value": 9},
            ],
        ]
        with mock.patch.object(self.fetch, "fetch_json", return_value=payload):
            series = self.fetch.fetch_indicator("SP.POP.TOTL")
        self.assertEqual(
            series,
            {"GHA": {"2020": 100.0}, "KEN": {"2020": 42.5}, "IND": {"2020": 7}},
        )

    def test_fetch_indicator_rejects_wrong_shape(self):
        with mock.patch.object(self.fetch, "fetch_json", return_value={"message": []}):
            with self.assertRaises(SystemExit):
                self.fetch.fetch_indicator("SP.POP.TOTL")

    def test_fetch_indicator_requires_values(self):
        with mock.patch.object(self.fetch, "fetch_json", return_value=[{"page": 1}, []]):
            with self.assertRaises(SystemExit):
                self.fetch.fetch_indicator("SP.POP.TOTL")

    def test_main_writes_a_document(self):
        sample = [{"page": 1}, [{"countryiso3code": "GHA", "date": "2020", "value": 1.5}]]
        with mock.patch.object(self.fetch, "fetch_json", return_value=sample):
            with mock.patch.object(self.fetch, "OUTPUT", self.output):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.fetch.main(), 0)
        written = json.loads(self.output.read_text(encoding="utf-8"))
        years = list(range(self.fetch.START_YEAR, self.fetch.END_YEAR + 1))
        self.assertEqual(written["years"], years)
        self.assertEqual(len(written["indicators"]), len(self.fetch.INDICATORS))
        for indicator in written["indicators"]:
            self.assertEqual(indicator["series"], {"GHA": {"2020": 1.5}})


class MarkupTests(unittest.TestCase):
    def test_local_assets_exist(self):
        parser = AssetParser()
        parser.feed((APP / "index.html").read_text(encoding="utf-8"))
        local = [
            ref
            for ref in parser.refs
            if not ref.startswith(("http://", "https://", "#", "mailto:"))
        ]
        self.assertIn("app.js", local)
        self.assertIn("styles.css", local)
        for ref in local:
            self.assertTrue((APP / ref).exists(), f"index.html references missing {ref}")

    def test_app_imports_the_pure_helpers(self):
        html = (APP / "index.html").read_text(encoding="utf-8")
        self.assertIn('type="module"', html)
        self.assertIn("dashboard.js", (APP / "app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
