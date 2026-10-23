"""Documentation consistency checks.

Markdown is part of the product: the README is the entry point, and data-model
links are how contributors find the rules. These tests catch links that point at
deleted files and a data README that drifts from the directory it describes.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#")


def markdown_files() -> list[Path]:
    """Every Markdown file in the repository, excluding generated/VCS folders."""
    blocked = {".git", "__pycache__", "node_modules", "site"}
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not blocked.intersection(path.parts) and path.is_file()
    )


class DocumentationTests(unittest.TestCase):
    maxDiff = None

    def test_relative_links_resolve(self):
        files = markdown_files()
        self.assertTrue(files, "no Markdown files found")
        checked = 0
        for document in files:
            text = document.read_text(encoding="utf-8")
            for raw_target in LINK.findall(text):
                target = raw_target.strip("<>")
                if not target or target.startswith(EXTERNAL_PREFIXES):
                    continue
                target = target.split("#", 1)[0]
                if not target:
                    continue
                checked += 1
                with self.subTest(document=document.relative_to(ROOT), target=target):
                    resolved = (document.parent / target).resolve()
                    self.assertTrue(
                        resolved.exists(),
                        f"{document.relative_to(ROOT)} links to missing {target}",
                    )
        self.assertGreater(checked, 0, "no relative Markdown links found")

    def test_no_references_to_removed_docs(self):
        for document in markdown_files():
            text = document.read_text(encoding="utf-8")
            with self.subTest(document=document.relative_to(ROOT)):
                self.assertNotIn(
                    "architecture-overview",
                    text,
                    "reference to the removed docs/architecture-overview.md",
                )

    def test_data_model_documents_the_machine_contract(self):
        text = (ROOT / "docs" / "data-model.md").read_text(encoding="utf-8")
        for needle in (
            "catalog.json",
            "schema.json",
            "JSON Schema draft 2020-12",
            "deterministic-lexical-v1",
            "CollectionPage",
            "TechArticle",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_data_readme_lists_every_json_file(self):
        readme = (ROOT / "data" / "README.md").read_text(encoding="utf-8")
        for path in sorted((ROOT / "data").glob("*.json")):
            with self.subTest(file=path.name):
                self.assertIn(path.name, readme, f"data/README.md omits {path.name}")


if __name__ == "__main__":
    unittest.main()
