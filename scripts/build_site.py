#!/usr/bin/env python3
"""Stage the JSON data for the static site and serve it locally.

The site is plain HTML/JS with no build step. Browsers cannot fetch files
outside the directory they are served from, so this script mirrors data/*.json
into site/data/, emits a machine-readable catalog manifest, and can serve site/
with the Python standard library.

Usage:
    python3 scripts/build_site.py            # stage data into site/data
    python3 scripts/build_site.py --check    # fail if site/data is stale
    python3 scripts/build_site.py --serve    # stage, then serve site/
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Type

from config import (
    DATA_DIR,
    HOST,
    PORT,
    REPOSITORY_URL,
    SCHEMA_VERSION,
    SITE_DIR,
    SITE_URL,
)
from recommend import (
    FUZZY_MIN_WEIGHT,
    FUZZY_WEIGHT,
    KEYWORD_SCORE_FLOOR,
    KEYWORD_SCORE_SPAN,
    MAX_KEYWORD_SCORE,
    MIN_COVERAGE,
    MIN_KEYWORD_SCORE,
    STEM_RULES,
    STOPWORDS,
)

CATALOG_FILE = "catalog.json"
CATALOG_FILES = (
    "categories",
    "use-cases",
    "stacks",
    "apis",
    "templates",
    "examples",
)
ENTITY_TYPES = {
    "categories": "Category",
    "use-cases": "UseCase",
    "stacks": "Stack",
    "apis": "API",
    "templates": "Template",
    "examples": "Example",
}


class NoCacheHandler(SimpleHTTPRequestHandler):
    """Development handler that never lets the browser cache JSON or HTML."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def build_catalog_manifest(sources: list[Path]) -> dict[str, Any]:
    """Build a deterministic entry point for machine consumers.

    The manifest does not replace the six source files: it records their public
    URLs, schemas, counts, relationships, and recommendation contract, and
    embeds the same validated records for clients that prefer one request.
    """
    by_name = {source.stem: source for source in sources}
    missing = sorted(set(CATALOG_FILES) - set(by_name))
    if missing:
        raise ValueError("missing catalog data file(s): " + ", ".join(missing))

    entities: dict[str, list[dict]] = {}
    for name in CATALOG_FILES:
        payload = json.loads(by_name[name].read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"{by_name[name].name} must contain a JSON array")
        entities[name] = payload

    files = {
        name: {
            "url": f"{SITE_URL}data/{name}.json",
            "schema": f"{SITE_URL}schema.json#/$defs/{ENTITY_TYPES[name]}File",
            "count": len(entities[name]),
            "id_field": "id",
        }
        for name in CATALOG_FILES
    }
    relationships = [
        {
            "from": "use-cases",
            "field": "categories",
            "to": "categories",
            "cardinality": "many-to-many",
        },
        {
            "from": "use-cases",
            "field": "stack_ids",
            "to": "stacks",
            "cardinality": "many-to-many",
        },
        {
            "from": "use-cases",
            "field": "template_ids",
            "to": "templates",
            "cardinality": "many-to-many",
        },
        {
            "from": "use-cases",
            "field": "example",
            "to": "examples",
            "cardinality": "one-to-one",
        },
        {
            "from": "stacks",
            "field": "use_case",
            "to": "use-cases",
            "cardinality": "many-to-one",
        },
        {
            "from": "stacks",
            "field": "tools[].api_ids",
            "to": "apis",
            "cardinality": "many-to-many",
        },
        {
            "from": "apis",
            "field": "category_ids",
            "to": "categories",
            "cardinality": "many-to-many",
        },
        {
            "from": "templates",
            "field": "use_case_ids",
            "to": "use-cases",
            "cardinality": "many-to-many",
        },
        {
            "from": "templates",
            "field": "category_ids",
            "to": "categories",
            "cardinality": "many-to-many",
        },
        {
            "from": "examples",
            "field": "use_case",
            "to": "use-cases",
            "cardinality": "many-to-one",
        },
    ]

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "name": "OpenToolHub",
        "description": (
            "A static, builder-first catalog that maps project goals to use "
            "cases, stacks, public APIs, templates, and worked examples."
        ),
        "url": SITE_URL,
        "repository": REPOSITORY_URL,
        "license": f"{REPOSITORY_URL}/blob/main/LICENSE",
        "generated_by": "scripts/build_site.py",
        "data_model": {
            "url": f"{SITE_URL}schema.json",
            "version": SCHEMA_VERSION,
            "format": "JSON Schema draft 2020-12",
        },
        "counts": {name: len(entities[name]) for name in CATALOG_FILES},
        "files": files,
        "relationships": relationships,
        "entry_points": {
            "home": f"{SITE_URL}index.html",
            "use_cases": f"{SITE_URL}use-cases.html",
            "use_case": f"{SITE_URL}use-case.html?id={{id}}",
            "stacks": f"{SITE_URL}stacks.html",
            "templates": f"{SITE_URL}templates.html",
            "apis": f"{SITE_URL}apis.html",
            "llms": f"{SITE_URL}llms.txt",
        },
        "recommendation": {
            "engine": "deterministic-lexical-v2",
            "mode": "offline; no backend and no model call",
            "fields": [
                "id",
                "name",
                "summary",
                "goal",
                "aliases",
                "keywords",
                "personas",
                "category names and aliases",
                "stack names, best_for, and tool slots",
                "template names",
            ],
            "field_weights": {
                "name and aliases": 4,
                "keywords": 3,
                "summary, goal, category names and aliases, stack names, "
                "template names": 2,
                "personas, stack best_for, tool slots": 1,
            },
            "exact_match_fields": ["id", "name", "aliases"],
            "normalization": (
                "Unicode NFKD, ASCII, lowercase, non-alphanumeric runs to spaces"
            ),
            "stemming": {
                "rules": [
                    f"{suffix} -> {replacement}" for suffix, replacement in STEM_RULES
                ],
                "plurals": "ies -> y, -sses -> -ss, other trailing s removed",
                "endings": "ing and ed removed after the -ise rules",
            },
            "stopwords": sorted(STOPWORDS),
            "scoring": {
                "id_exact": 100,
                "name_exact": 95,
                "alias_exact": 90,
                "keyword": (
                    f"{KEYWORD_SCORE_FLOOR} + round({KEYWORD_SCORE_SPAN} * coverage "
                    "* (0.6 + 0.4 * rarity)), capped at "
                    f"{MAX_KEYWORD_SCORE}, dropped below {MIN_KEYWORD_SCORE}"
                ),
                "coverage": (
                    "idf-weighted matched field weight divided by the maximum "
                    "idf-weighted weight available for the query tokens"
                ),
                "idf": (
                    "log(1 + use_cases / document_frequency); unseen terms are 1"
                ),
                "gate": (
                    f"coverage >= {MIN_COVERAGE}, or a single distinctive term "
                    "(field weight >= 3 shared by at most 2 use cases)"
                ),
                "fuzzy": (
                    "one edit or adjacent transposition for tokens of 5+ characters, "
                    f"field weight >= {FUZZY_MIN_WEIGHT}, weighted at {FUZZY_WEIGHT}"
                ),
            },
            "fallback": {
                "no_match": (
                    "NoMatchError carries every use case id plus the closest partial "
                    "matches; the browser lists those as closest use cases"
                ),
                "disambiguation": (
                    "needs_disambiguation when the best score is below 90 and a "
                    "runner-up is within 5 points"
                ),
            },
            "tie_break": "score descending, then lowercase name ascending",
        },
        "entities": entities,
    }
    return manifest


def manifest_bytes(sources: list[Path]) -> bytes:
    """Serialize the catalog manifest deterministically for staging/checks."""
    payload = build_catalog_manifest(sources)
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def stage(check_only: bool = False) -> int:
    """Copy data/*.json into site/data, write catalog.json, and remove stale copies."""
    if not DATA_DIR.is_dir():
        print(f"error: data directory not found: {DATA_DIR}", file=sys.stderr)
        return 1

    sources = sorted(DATA_DIR.glob("*.json"))
    if not sources:
        print(f"error: no JSON files found in {DATA_DIR}", file=sys.stderr)
        return 1

    try:
        catalog = manifest_bytes(sources)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: could not build catalog manifest: {exc}", file=sys.stderr)
        return 1

    target = SITE_DIR / "data"
    expected = {source.name for source in sources}
    changed: list[str] = []

    try:
        target.mkdir(parents=True, exist_ok=True)
        for source in sources:
            destination = target / source.name
            if not destination.is_file() or destination.read_bytes() != source.read_bytes():
                changed.append(source.name)
                if not check_only:
                    shutil.copyfile(source, destination)
        catalog_path = target / CATALOG_FILE
        if not catalog_path.is_file() or catalog_path.read_bytes() != catalog:
            changed.append(CATALOG_FILE)
            if not check_only:
                catalog_path.write_bytes(catalog)
        for existing in sorted(target.glob("*.json")):
            if existing.name not in expected and existing.name != CATALOG_FILE:
                changed.append(f"stale:{existing.name}")
                if not check_only:
                    existing.unlink()
    except OSError as exc:
        print(f"error: could not stage data: {exc}", file=sys.stderr)
        return 1

    if check_only:
        if changed:
            print(
                "error: site/data is out of date: " + ", ".join(changed),
                file=sys.stderr,
            )
            print("Run: python3 scripts/build_site.py", file=sys.stderr)
            return 1
        print("site/data is up to date.")
        return 0

    print(f"Staged {len(sources)} JSON file(s) in {target}")
    if changed:
        print("Updated: " + ", ".join(changed))
    return 0


def serve(handler: Type[SimpleHTTPRequestHandler] = NoCacheHandler) -> int:
    """Serve site/ on HOST:PORT until interrupted."""
    if stage() != 0:
        return 1

    bound = partial(handler, directory=str(SITE_DIR))
    try:
        server = ThreadingHTTPServer((HOST, PORT), bound)
    except OSError as exc:
        print(f"error: could not serve {SITE_DIR} on {HOST}:{PORT}: {exc}", file=sys.stderr)
        return 1

    print(f"Serving {SITE_DIR} at http://{HOST}:{PORT}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage JSON data for the static site and serve it locally."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if site/data differs from data/ (used by CI).",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Stage data, then serve site/ until interrupted.",
    )
    args = parser.parse_args(argv)

    if args.check and args.serve:
        parser.error("--check and --serve cannot be combined")
    if args.serve:
        return serve()
    return stage(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
