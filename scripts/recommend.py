#!/usr/bin/env python3
"""Recommend an OpenToolHub stack from a plain-language goal.

All recommendations come from the JSON files in data/. The module performs no
network calls and contains no pre-written answers.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import DATA_DIR

STOPWORDS = frozenset(
    "a an and any app application are around best build building can compare "
    "compared comparison create do does find finder for from get good great "
    "help how i in into is it like looking make me my near nearby need needs "
    "new of on or please show shows simple some that the their them there this "
    "to tool tools us use used using versus vs want we where which who why "
    "will with you your".split()
)

# Field weights and scoring constants. They are mirrored by site/js/data.js so
# the browser builder and the CLI rank the same catalog the same way.
MAX_TOKEN_WEIGHT = 4
MIN_COVERAGE = 0.5
KEYWORD_SCORE_FLOOR = 50
KEYWORD_SCORE_SPAN = 38
MAX_KEYWORD_SCORE = 88
FUZZY_WEIGHT = 0.8
MIN_KEYWORD_SCORE = 55
FUZZY_MIN_WEIGHT = 3

# British and plural spellings are reduced to one form before comparison.
STEM_RULES = (
    ("isations", "ize"),
    ("izations", "ize"),
    ("isation", "ize"),
    ("ization", "ize"),
    ("ising", "ize"),
    ("izing", "ize"),
    ("ised", "ize"),
    ("ized", "ize"),
    ("ises", "ize"),
    ("izes", "ize"),
    ("ise", "ize"),
    ("ize", "ize"),
)


class NoMatchError(LookupError):
    """Raised when no use case matches the query."""

    def __init__(
        self,
        query: str,
        suggestions: list[str],
        closest: list[dict[str, Any]] | None = None,
    ) -> None:
        self.query = query
        self.suggestions = suggestions
        self.closest = closest or []
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


def stem(token: str) -> str:
    """Reduce a token to one form so plurals and -ise spellings still match."""
    word = token
    if len(word) <= 3:
        return word
    for suffix, replacement in STEM_RULES:
        if word.endswith(suffix):
            word = word[: -len(suffix)] + replacement
            break
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("sses"):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 3:
        word = word[:-1]
    if word.endswith("ing") and len(word) > 5:
        word = word[:-3]
        if len(word) > 2 and word[-1] == word[-2]:
            word = word[:-1]
    elif word.endswith("ed") and len(word) > 4:
        word = word[:-2]
    return word


def tokenize(text: str) -> list[str]:
    """Return stopword-filtered, stemmed search tokens."""
    return [stem(word) for word in normalize(text).split() if word not in STOPWORDS]


def _add_terms(weights: dict[str, int], text: str, weight: int) -> None:
    """Record every token of text at the given field weight."""
    for token in tokenize(text):
        if weights.get(token, 0) < weight:
            weights[token] = weight


def _use_case_weights(use_case: dict, data: dict[str, Any]) -> dict[str, int]:
    """Weight every searchable term by the field that contains it."""
    weights: dict[str, int] = {}
    _add_terms(weights, use_case["name"], 4)
    for alias in use_case["aliases"]:
        _add_terms(weights, alias, 4)
    for keyword in use_case["keywords"]:
        _add_terms(weights, keyword, 3)
    _add_terms(weights, use_case["summary"], 2)
    _add_terms(weights, use_case["goal"], 2)
    for persona in use_case["personas"]:
        _add_terms(weights, persona, 1)
    for category_id in use_case["categories"]:
        category = data["category_by_id"].get(category_id)
        if category:
            _add_terms(weights, category["name"], 2)
            for alias in category["aliases"]:
                _add_terms(weights, alias, 2)
    for stack_id in use_case["stack_ids"]:
        stack = data["stack_by_id"].get(stack_id)
        if stack:
            _add_terms(weights, stack["name"], 2)
            for text in stack["best_for"]:
                _add_terms(weights, text, 1)
            for tool in stack["tools"]:
                _add_terms(weights, tool["slot"], 1)
    for template_id in use_case["template_ids"]:
        template = data["template_by_id"].get(template_id)
        if template:
            _add_terms(weights, template["name"], 2)
    return weights


def _build_index(data: dict[str, Any]) -> dict[str, Any]:
    """Index term weights per use case plus document frequency per term."""
    weights = {
        use_case["id"]: _use_case_weights(use_case, data)
        for use_case in data["use_cases"]
    }
    document_frequency: dict[str, int] = {}
    for terms in weights.values():
        for term in terms:
            document_frequency[term] = document_frequency.get(term, 0) + 1
    return {
        "weights": weights,
        "df": document_frequency,
        "count": max(len(weights), 1),
    }


def _idf(term: str, index: dict[str, Any]) -> float:
    """Rarer terms carry more weight; unseen terms count as generic filler."""
    frequency = index["df"].get(term, 0)
    if not frequency:
        return 1.0
    return math.log(1 + index["count"] / frequency)


def _within_one_edit(left: str, right: str) -> bool:
    """True when the two strings differ by at most one edit or swap."""
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    start = 0
    limit = min(len(left), len(right))
    while start < limit and left[start] == right[start]:
        start += 1
    end_left = len(left)
    end_right = len(right)
    while (
        end_left > start
        and end_right > start
        and left[end_left - 1] == right[end_right - 1]
    ):
        end_left -= 1
        end_right -= 1
    remainder_left = left[start:end_left]
    remainder_right = right[start:end_right]
    if len(remainder_left) <= 1 and len(remainder_right) <= 1:
        return True
    return (
        len(remainder_left) == 2
        and len(remainder_right) == 2
        and remainder_left == remainder_right[::-1]
    )


def _fuzzy_term(term: str, vocabulary: Any) -> str | None:
    """Return the single vocabulary term one edit away, if exactly one exists."""
    if len(term) < 5:
        return None
    matches = [
        candidate for candidate in vocabulary if _within_one_edit(term, candidate)
    ]
    return matches[0] if len(matches) == 1 else None


def _evidence(
    use_case_id: str, query_tokens: list[str], index: dict[str, Any]
) -> tuple[float, list[str], bool]:
    """Return (coverage, matched terms, whether every match was fuzzy)."""
    weights = index["weights"][use_case_id]
    total = 0.0
    matched_weight = 0.0
    matched: list[str] = []
    exact_matches = 0
    for token in query_tokens:
        token_idf = _idf(token, index)
        total += token_idf * MAX_TOKEN_WEIGHT
        if token in weights:
            exact_matches += 1
            matched.append(token)
            matched_weight += token_idf * weights[token]
            continue
        candidate = _fuzzy_term(
            token,
            (term for term, weight in weights.items() if weight >= FUZZY_MIN_WEIGHT),
        )
        if candidate is not None:
            matched.append(candidate)
            matched_weight += token_idf * weights[candidate] * FUZZY_WEIGHT
    coverage = matched_weight / total if total else 0.0
    return coverage, matched, bool(matched) and exact_matches == 0


def _score(
    use_case: dict,
    query: str,
    query_tokens: list[str],
    index: dict[str, Any],
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

    coverage, matched, fuzzy_only = _evidence(use_case["id"], query_tokens, index)
    # One hit inside a multi-word phrase is weak evidence, unless the term is a
    # rare keyword or name match that almost no other use case shares.
    if len(matched) < 2 and len(query_tokens) > 1:
        weights = index["weights"][use_case["id"]]
        distinctive = any(
            weights[term] >= 3 and index["df"].get(term, 0) <= 2 for term in matched
        )
        if not distinctive:
            return 0, "none"
    elif coverage < MIN_COVERAGE:
        return 0, "none"
    rarity = max(1 - index["df"].get(term, 0) / index["count"] for term in matched)
    strength = coverage * (0.6 + 0.4 * rarity)
    score = min(
        MAX_KEYWORD_SCORE,
        KEYWORD_SCORE_FLOOR + int(round(KEYWORD_SCORE_SPAN * strength)),
    )
    if score < MIN_KEYWORD_SCORE:
        return 0, "none"
    return score, "fuzzy" if fuzzy_only else "keywords"


def rank(query: str, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return matching use cases ordered by score, then name."""
    data = data or load_data()
    query_tokens = tokenize(query)
    index = _build_index(data)
    ranked: list[dict[str, Any]] = []
    for use_case in data["use_cases"]:
        score, matched_by = _score(use_case, query, query_tokens, index)
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


def suggest(
    query: str, data: dict[str, Any] | None = None, limit: int = 3
) -> list[dict[str, Any]]:
    """Return the closest partial matches, even when none clears the threshold."""
    data = data or load_data()
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    index = _build_index(data)
    closest: list[dict[str, Any]] = []
    for use_case in data["use_cases"]:
        coverage, matched, _fuzzy_only = _evidence(
            use_case["id"], query_tokens, index
        )
        if not matched:
            continue
        closest.append(
            {
                "id": use_case["id"],
                "name": use_case["name"],
                "matched": list(dict.fromkeys(matched)),
                "coverage": coverage,
            }
        )
    closest.sort(
        key=lambda item: (
            -len(item["matched"]),
            -item["coverage"],
            item["name"].lower(),
        )
    )
    return closest[:limit]


def resolve(query: str, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return ranked matches or raise NoMatchError with usable suggestions."""
    data = data or load_data()
    ranked = rank(query, data)
    if not ranked:
        raise NoMatchError(
            query,
            [item["id"] for item in data["use_cases"]],
            suggest(query, data),
        )
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
        if exc.closest:
            print("Closest matches:", file=sys.stderr)
            for item in exc.closest:
                terms = ", ".join(item["matched"])
                print(
                    f"  - {item['name']} ({item['id']}) matched: {terms}",
                    file=sys.stderr,
                )
        return 2

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_recommendation(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
