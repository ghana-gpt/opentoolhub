"""Static site consistency checks.

These tests do not need a browser. They catch the failures that matter for a
static site: missing assets, non-module scripts, JS selectors that point at
elements a page does not contain, and broken relative imports.
"""

from __future__ import annotations

import json
import re
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SITE_URL = "https://ghana-gpt.github.io/opentoolhub/"

PAGE_SCRIPTS = {
    "index.html": "js/home.js",
    "use-cases.html": "js/use-cases.js",
    "use-case.html": "js/use-case.js",
    "stacks.html": "js/stacks.js",
    "templates.html": "js/templates.js",
    "apis.html": "js/apis.js",
}

EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#", "data:")


class PageParser(HTMLParser):
    """Collect ids, local references, script sources, and basic document data."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.refs: list[str] = []
        self.scripts: list[tuple[str, str]] = []
        self.aria_controls: list[tuple[str, str]] = []
        self.live_regions: set[str] = set()
        self.lang = ""
        self.has_main = False
        self.title = ""
        self.description = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "html":
            self.lang = values.get("lang", "")
        if tag == "main":
            self.has_main = True
        if tag == "title":
            self._in_title = True
        if tag == "meta" and values.get("name") == "description":
            self.description = values.get("content", "")
        if values.get("id"):
            self.ids.add(values["id"])
        if values.get("aria-live"):
            self.live_regions.add(values.get("id", ""))
        for target in values.get("aria-controls", "").split():
            self.aria_controls.append((values.get("id", tag), target))
        if tag == "script" and values.get("src"):
            self.scripts.append((values["src"], values.get("type", "")))
        for attribute in ("href", "src"):
            target = values.get(attribute, "")
            if not target or target.startswith(EXTERNAL_PREFIXES):
                continue
            self.refs.append(target.split("#")[0].split("?")[0])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def parse_page(name: str) -> PageParser:
    parser = PageParser()
    parser.feed((SITE / name).read_text(encoding="utf-8"))
    parser.close()
    return parser


class SiteTests(unittest.TestCase):
    maxDiff = None

    def test_pages_exist(self):
        for page in PAGE_SCRIPTS:
            with self.subTest(page=page):
                self.assertTrue((SITE / page).is_file(), f"missing {page}")

    def test_document_basics(self):
        for page in PAGE_SCRIPTS:
            with self.subTest(page=page):
                parsed = parse_page(page)
                self.assertEqual(parsed.lang, "en")
                self.assertTrue(parsed.title.strip(), "missing <title>")
                self.assertTrue(parsed.description.strip(), "missing meta description")
                self.assertTrue(parsed.has_main, "missing <main>")

    def test_local_assets_and_links_exist(self):
        for page in PAGE_SCRIPTS:
            parsed = parse_page(page)
            with self.subTest(page=page):
                for reference in parsed.refs:
                    self.assertTrue(
                        (SITE / reference).is_file(),
                        f"{page} references missing {reference}",
                    )

    def test_scripts_are_modules(self):
        for page, expected in PAGE_SCRIPTS.items():
            parsed = parse_page(page)
            with self.subTest(page=page):
                self.assertEqual(len(parsed.scripts), 1)
                source, kind = parsed.scripts[0]
                self.assertEqual(source, expected)
                self.assertEqual(kind, "module")

    def test_js_selectors_have_targets(self):
        selector = re.compile(r"""(?:qs|querySelector)\(\s*["']#([A-Za-z0-9_-]+)""")
        for page, script in PAGE_SCRIPTS.items():
            parsed = parse_page(page)
            code = (SITE / script).read_text(encoding="utf-8")
            with self.subTest(page=page):
                for element_id in sorted(set(selector.findall(code))):
                    self.assertIn(
                        element_id,
                        parsed.ids,
                        f"{script} selects #{element_id}, absent from {page}",
                    )

    def test_area_filters_and_catalog_context(self):
        expected = {
            "index.html": {
                "catalog-stats",
                "area-section",
                "area-directory",
                "featured-use-cases",
            },
            "use-cases.html": {
                "category-filter",
                "use-cases-grid",
                "use-cases-count",
            },
            "stacks.html": {
                "stack-category-filter",
                "stack-grid",
                "stack-count",
            },
            "templates.html": {
                "template-category-filter",
                "template-grid",
                "template-count",
            },
            "apis.html": {
                "api-category-filter",
                "api-grid",
                "api-count",
            },
        }
        for page, ids in expected.items():
            parsed = parse_page(page)
            with self.subTest(page=page):
                self.assertTrue(
                    ids.issubset(parsed.ids),
                    f"{page} is missing {sorted(ids - parsed.ids)}",
                )
                self.assertTrue(
                    parsed.live_regions,
                    f"{page} has no aria-live result count",
                )

    def test_aria_controls_resolve(self):
        for page in (
            "index.html",
            "use-cases.html",
            "stacks.html",
            "templates.html",
            "apis.html",
        ):
            parsed = parse_page(page)
            with self.subTest(page=page):
                self.assertTrue(parsed.aria_controls, f"{page} has no aria-controls")
                for owner, target in parsed.aria_controls:
                    self.assertIn(
                        target,
                        parsed.ids,
                        f"{page}: {owner} controls missing #{target}",
                    )

    def test_refs_are_subpath_safe(self):
        """Pages serves the site under /<repo>/, so do not use root-absolute URLs."""
        for page in PAGE_SCRIPTS:
            parsed = parse_page(page)
            for reference in parsed.refs:
                with self.subTest(page=page, reference=reference):
                    self.assertFalse(
                        reference.startswith(("/", "\\")),
                        f"{page} uses root-absolute URL {reference}",
                    )
        for script in sorted((SITE / "js").glob("*.js")):
            code = script.read_text(encoding="utf-8")
            for target in re.findall(r"""fetch\(\s*[`"']([^`"']+)""", code):
                with self.subTest(script=script.name, target=target):
                    self.assertFalse(
                        target.startswith("/"),
                        f"{script.name} fetches root-absolute {target}",
                    )

    def test_module_imports_resolve(self):
        for script in sorted((SITE / "js").glob("*.js")):
            code = script.read_text(encoding="utf-8")
            for specifier in re.findall(r"""from\s+["'](\.[^"']+)["']""", code):
                with self.subTest(script=script.name, specifier=specifier):
                    self.assertTrue(
                        (script.parent / specifier).is_file(),
                        f"{script.name} imports missing {specifier}",
                    )

    def test_discovery_files_exist(self):
        for name in (".nojekyll", "llms.txt", "robots.txt", "sitemap.xml"):
            with self.subTest(name=name):
                self.assertTrue((SITE / name).is_file(), f"missing site/{name}")

    def test_sitemap_entries_resolve(self):
        root = ET.parse(SITE / "sitemap.xml").getroot()
        namespace = {"sitemap": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locations = [
            node.text or ""
            for node in root.findall("sitemap:url/sitemap:loc", namespace)
        ]
        self.assertGreaterEqual(len(locations), len(PAGE_SCRIPTS))
        for location in locations:
            with self.subTest(location=location):
                self.assertTrue(location.startswith(SITE_URL))
                relative = location[len(SITE_URL) :].split("?")[0].split("#")[0]
                self.assertTrue((SITE / (relative or "index.html")).is_file())

        use_cases = json.loads(
            (ROOT / "data" / "use-cases.json").read_text(encoding="utf-8")
        )
        for use_case in use_cases:
            expected = f"{SITE_URL}use-case.html?id={use_case['id']}"
            with self.subTest(use_case=use_case["id"]):
                self.assertIn(expected, locations)

    def test_llms_txt_maps_pages_and_catalog(self):
        text = (SITE / "llms.txt").read_text(encoding="utf-8")
        for page in PAGE_SCRIPTS:
            needle = f"{SITE_URL}{page}"
            if page == "use-case.html":
                needle += "?id="
            self.assertIn(needle, text)
        for name in (
            "categories",
            "use-cases",
            "stacks",
            "apis",
            "templates",
            "examples",
        ):
            self.assertIn(f"{SITE_URL}data/{name}.json", text)

    def test_no_legacy_entrypoint(self):
        self.assertFalse((SITE / "app.js").exists())
        for page in PAGE_SCRIPTS:
            parsed = parse_page(page)
            sources = " ".join(source for source, _ in parsed.scripts)
            self.assertNotIn("app.js", sources)


if __name__ == "__main__":
    unittest.main()
