"""Static site consistency checks.

These tests do not need a browser. They catch the failures that matter for a
static site: missing assets, non-module scripts, JS selectors that point at
elements a page does not contain, and broken relative imports.
"""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

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
        self.lang = ""
        self.has_main = False
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "html":
            self.lang = values.get("lang", "")
        if tag == "main":
            self.has_main = True
        if tag == "title":
            self._in_title = True
        if values.get("id"):
            self.ids.add(values["id"])
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

    def test_module_imports_resolve(self):
        for script in sorted((SITE / "js").glob("*.js")):
            code = script.read_text(encoding="utf-8")
            for specifier in re.findall(r"""from\s+["'](\.[^"']+)["']""", code):
                with self.subTest(script=script.name, specifier=specifier):
                    self.assertTrue(
                        (script.parent / specifier).is_file(),
                        f"{script.name} imports missing {specifier}",
                    )

    def test_no_legacy_entrypoint(self):
        self.assertFalse((SITE / "app.js").exists())
        for page in PAGE_SCRIPTS:
            parsed = parse_page(page)
            sources = " ".join(source for source, _ in parsed.scripts)
            self.assertNotIn("app.js", sources)


if __name__ == "__main__":
    unittest.main()
