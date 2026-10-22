#!/usr/bin/env python3
"""Recommend an OpenToolHub stack from a plain-language goal.

All recommendations come from the JSON files in data/. The module performs no
network calls and contains no pre-written answers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import DATA_DIR

STOPWORDS = frozenset(
    "a an and app application build building create for from i in into my of on "
    "or the to tool tools using want with".split()
)


class NoMatchError(LookupError):
    """Raised when no use case matches the query."""

    def __init__(self, query: str, suggestions: list[str]) -> None:
        self.query = query
        self.suggestions = suggestions
        available = ", ".join(suggestions)
        super().__init__(
            f"No use case matched {query!r}. Available use cases: {available}"
        )


@lru_cache(maxsize=1)
def load_data(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Load and index the data files once per process."""
    def read(name: str) -> list[dict]:
        path = data_dir / f"{name}.json"
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError(f"{path} must contain a JSON array")
        return payload

    categories = read("categories")
    use_cases = read("use-cases")
    stacks = read("stacks")
    apis = read("apis")
    templates = read("templates")
    examples = read("examples")
    return {
        "categories": categories,
        "use_cases": use_cases,
        "stacks": stacks,
        "apis": apis,
        "templates": templates,
        "examples": examples,
        "category_by_id": {item["id"]: item for item in categories},
        "use_case_by_id": {item["id"]: item for item in use_cases},
        "stack_by_id": {item["id"]: item for item in stacks},
        "api_by_id": {item["id"]: item for item in apis},
        "template_by_id": {item["id"]: item for item in templates},
    }


def normalize(text: str) -> str:
    """Lowercase, strip accents, and collapse punctuation to single spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def tokenize(text: str) -> list[str]:
    return [word for word in normalize(text).split() if word not in STOPWORDS]


def _search_document(use_case: dict, data: dict[str, Any]) -> str:
    pieces = [
        use_case["name"],
        use_case["summary"],
        use_case["goal"],
        *use_case["aliases"],
        *use_case["keywords"],
        *use_case["personas"],
    ]
    for category_id in use_case["categories"]:
        category = data["category_by_id"].get(category_id)
        if category:
            pieces.extend([category["name"], *category["aliases"]])
    for stack_id in use_case["stack_ids"]:
        stack = data["stack_by_id"].get(stack_id)
        if stack:
            pieces.extend([stack["name"], *stack["best_for"]])
            pieces.extend(tool["slot"] for tool in stack["tools"])
    for template_id in use_case["template_ids"]:
        template = data["template_by_id"].get(template_id)
        if template:
            pieces.append(template["name"])
    return " ".join(pieces)


def _score(
    use_case: dict,
    query: str,
    query_tokens: list[str],
    data: dict[str, Any],
) -> tuple[int, str]:
    normalized_query = normalize(query)
    if normalized_query == normalize(use_case["id"]):
        return 100, "id"
    if normalized_query == normalize(use_case["name"]):
        return 95, "name"
    if any(normalized_query == normalize(alias) for alias in use_case["aliases"]):
        return 90, "alias"
    if not query_tokens:
        return 0, "none"

    document_tokens = set(tokenize(_search_document(use_case, data)))
    matched = [token for token in query_tokens if token in document_tokens]
    if not matched:
        return 0, "none"
    if len(matched) == len(query_tokens):
        name_tokens = set(tokenize(use_case["name"]))
        bonus = 5 if set(query_tokens) <= name_tokens else 0
        return min(89, 80 + bonus), "keywords"

    ratio = len(matched) / len(query_tokens)
    if ratio < 0.5:
        return 0, "none"
    return 40 + int(ratio * 40), "keywords"


def rank(query: str, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return matching use cases ordered by score, then name."""
    data = data or load_data()
    query_tokens = tokenize(query)
    ranked: list[dict[str, Any]] = []
    for use_case in data["use_cases"]:
        score, matched_by = _score(use_case, query, query_tokens, data)
        if score:
            ranked.append(
                {
                    "use_case": use_case,
                    "score": score,
                    "matched_by": matched_by,
                }
            )
    ranked.sort(key=lambda item: (-item["score"], item["use_case"]["name"].lower()))
    return ranked


def resolve(query: str, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return ranked matches or raise NoMatchError with usable suggestions."""
    data = data or load_data()
    ranked = rank(query, data)
    if not ranked:
        raise NoMatchError(query, [item["id"] for item in data["use_cases"]])
    return ranked


def _build_rationale(
    use_case: dict, categories: list[dict], stacks: list[dict]
) -> list[str]:
    """Explain the match using only fields from the data files."""
    category_names = ", ".join(category["name"] for category in categories)
    rationale = [
        f"{use_case['name']} is documented for: {category_names}.",
        f"Goal: {use_case['goal']}",
    ]
    for stack in stacks:
        slots = []
        for tool in stack["tools"]:
            names = ", ".join(api["name"] for api in tool["apis"])
            slots.append(f"{tool['slot']} ({names})")
        rationale.append(f"{stack['name']}: " + "; ".join(slots) + ".")
    return rationale


def build_recommendation(
    query: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return a fully resolved recommendation for the best matching use case."""
    data = data or load_data()
    ranked = resolve(query, data)
    top = ranked[0]
    use_case = top["use_case"]

    categories = [data["category_by_id"][item] for item in use_case["categories"]]
    templates = [data["template_by_id"][item] for item in use_case["template_ids"]]
    examples = [
        example for example in data["examples"] if example["use_case"] == use_case["id"]
    ]

    api_ids: list[str] = []
    stacks: list[dict[str, Any]] = []
    for stack_id in use_case["stack_ids"]:
        stack = data["stack_by_id"][stack_id]
        tools = []
        for tool in stack["tools"]:
            apis = [data["api_by_id"][api_id] for api_id in tool["api_ids"]]
            tools.append(
                {
                    "slot": tool["slot"],
                    "category": tool["category"],
                    "apis": apis,
                }
            )
            for api in apis:
                if api["id"] not in api_ids:
                    api_ids.append(api["id"])
        stacks.append(
            {
                "id": stack["id"],
                "name": stack["name"],
                "categories": stack["categories"],
                "notes": stack["notes"],
                "difficulty": stack["difficulty"],
                "best_for": stack["best_for"],
                "tools": tools,
            }
        )

    alternatives = [
        {
            "id": item["use_case"]["id"],
            "name": item["use_case"]["name"],
            "score": item["score"],
        }
        for item in ranked[1:4]
    ]
    needs_disambiguation = bool(
        top["score"] < 90
        and alternatives
        and alternatives[0]["score"] >= top["score"] - 5
    )

    return {
        "query": query,
        "matched_by": top["matched_by"],
        "score": top["score"],
        "needs_disambiguation": needs_disambiguation,
        "alternatives": alternatives,
        "use_case": use_case,
        "categories": categories,
        "stacks": stacks,
        "templates": templates,
        "examples": examples,
        "api_ids": api_ids,
        "rationale": _build_rationale(use_case, categories, stacks),
    }


def format_recommendation(result: dict[str, Any]) -> str:
    use_case = result["use_case"]
    lines = [
        f"{use_case['name']} ({use_case['id']})",
        f"Matched by {result['matched_by']} | score {result['score']}",
        "",
        use_case["summary"],
        "",
        f"Goal: {use_case['goal']}",
        "Categories: " + ", ".join(item["name"] for item in result["categories"]),
        "",
    ]
    for stack in result["stacks"]:
        lines.append(f"Stack: {stack['name']} ({stack['difficulty']} difficulty)")
        for tool in stack["tools"]:
            names = ", ".join(
                f"{api['name']} ({api['pricing']}, auth: {api['auth']})"
                for api in tool["apis"]
            )
            lines.append(f"  - {tool['slot']}: {names}")
        lines.append("")
    if result["templates"]:
        lines.append("Templates:")
        lines.extend(
            f"  - {template['name']} ({template['path']})"
            for template in result["templates"]
        )
        lines.append("")
    if result["examples"]:
        lines.append("Examples:")
        lines.extend(
            f"  - {example['title']} ({example['path']})"
            for example in result["examples"]
        )
        lines.append("")
    lines.append("Why this fits:")
    lines.extend(f"  - {item}" for item in result["rationale"])
    lines.append("")
    if result["needs_disambiguation"]:
        lines.append("Other possible matches:")
        lines.extend(
            f"  - {item['name']} ({item['id']}, score {item['score']})"
            for item in result["alternatives"]
        )
        lines.append("Re-run with a more specific phrase or an id for an exact match.")
    return "\n".join(lines).rstrip()


def format_list(data: dict[str, Any]) -> str:
    lines = ["Available use cases:"]
    for use_case in data["use_cases"]:
        stacks = ", ".join(
            data["stack_by_id"][stack_id]["name"] for stack_id in use_case["stack_ids"]
        )
        lines.append(f"  {use_case['id']:<24} {use_case['name']} - {stacks}")
    lines.extend(
        [
            "",
            'Run: python3 scripts/recommend.py "travel app"',
            'JSON: python3 scripts/recommend.py --json "travel app"',
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recommend an OpenToolHub stack from a goal or use case id."
    )
    parser.add_argument(
        "query", nargs="*", help="Goal or use case id, for example 'travel app'."
    )
    parser.add_argument(
        "--list", action="store_true", help="List available use cases and stacks."
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the recommendation as JSON."
    )
    args = parser.parse_args(argv)

    try:
        data = load_data()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: could not load data: {exc}", file=sys.stderr)
        return 1

    if args.list:
        print(format_list(data))
        return 0

    query = " ".join(args.query).strip()
    if not query:
        parser.print_usage(sys.stderr)
        print("error: provide a goal or use --list.", file=sys.stderr)
        return 2

    try:
        result = build_recommendation(query, data)
    except NoMatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_recommendation(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
