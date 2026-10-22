#!/usr/bin/env python3
"""Validate the OpenToolHub data layer and its file references.

Stdlib only. Exits with status 0 when the repository is valid and 1 when any
error is found. Warnings are reported but do not fail the run unless --strict
is passed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from config import DATA_DIR, ROOT

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LEVELS = {"low", "medium", "high"}
AUTH_TYPES = {"none", "api-key", "token"}
PRICING = {"free", "free-tier", "paid"}
STATUSES = {"starter", "variant"}

SPEC: dict[str, dict[str, type]] = {
    "categories": {
        "id": str,
        "name": str,
        "description": str,
        "tags": list,
        "best_for": list,
        "integration_complexity": str,
        "aliases": list,
    },
    "use-cases": {
        "id": str,
        "name": str,
        "summary": str,
        "goal": str,
        "aliases": list,
        "keywords": list,
        "categories": list,
        "stack_ids": list,
        "template_ids": list,
        "example": str,
        "personas": list,
    },
    "stacks": {
        "id": str,
        "use_case": str,
        "name": str,
        "categories": list,
        "tools": list,
        "notes": str,
        "difficulty": str,
        "best_for": list,
    },
    "apis": {
        "id": str,
        "name": str,
        "url": str,
        "docs_url": str,
        "category_ids": list,
        "description": str,
        "best_for": list,
        "auth": str,
        "pricing": str,
        "integration_complexity": str,
        "data_freshness": str,
        "licensing_notes": str,
        "related_tags": list,
    },
    "templates": {
        "id": str,
        "name": str,
        "description": str,
        "use_case_ids": list,
        "category_ids": list,
        "tags": list,
        "path": str,
        "status": str,
    },
    "examples": {
        "id": str,
        "use_case": str,
        "title": str,
        "path": str,
        "summary": str,
    },
}

LIST_FIELDS = {
    "categories": ("tags", "best_for", "aliases"),
    "use-cases": (
        "aliases",
        "keywords",
        "categories",
        "stack_ids",
        "template_ids",
        "personas",
    ),
    "stacks": ("categories", "best_for"),
    "apis": ("category_ids", "best_for", "related_tags"),
    "templates": ("use_case_ids", "category_ids", "tags"),
    "examples": (),
}


def _load(data_dir: Path, name: str, errors: list[str]) -> list[dict]:
    path = data_dir / f"{name}.json"
    if not path.is_file():
        errors.append(f"Missing data file: {path}")
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{path.name} is not valid JSON: {exc}")
        return []
    if not isinstance(payload, list):
        errors.append(f"{path.name} must contain a JSON array.")
        return []
    return payload


def _check_list(entity: dict, field: str, label: str, errors: list[str]) -> None:
    value = entity.get(field)
    if not isinstance(value, list) or not value:
        errors.append(f"{label}.{field} must be a non-empty list.")
        return
    if all(isinstance(item, str) and item.strip() for item in value):
        if len(set(value)) != len(value):
            errors.append(f"{label}.{field} contains duplicate values.")
        return
    errors.append(f"{label}.{field} must contain non-empty strings.")


def _basic_checks(raw: dict[str, list[dict]], errors: list[str]) -> None:
    for name, spec in SPEC.items():
        seen: set[str] = set()
        for position, entity in enumerate(raw[name]):
            label = f"{name}[{position}]"
            if not isinstance(entity, dict):
                errors.append(f"{label} must be a JSON object.")
                continue
            for field, expected_type in spec.items():
                if field not in entity:
                    errors.append(f"{label} is missing required field {field!r}.")
                elif not isinstance(entity[field], expected_type):
                    errors.append(f"{label}.{field} must be {expected_type.__name__}.")
            for field in ("id", "name"):
                value = entity.get(field)
                if isinstance(value, str) and not value.strip():
                    errors.append(f"{label}.{field} must not be empty.")
            for field in LIST_FIELDS[name]:
                _check_list(entity, field, label, errors)

            entity_id = entity.get("id")
            if not isinstance(entity_id, str) or not ID_RE.fullmatch(entity_id):
                errors.append(f"{label}.id must be kebab-case (got {entity_id!r}).")
            elif entity_id in seen:
                errors.append(f"{label}.id duplicates {entity_id!r} in {name}.json.")
            else:
                seen.add(entity_id)

            if name == "categories":
                if entity.get("integration_complexity") not in LEVELS:
                    errors.append(f"{label}.integration_complexity is not a valid level.")
            if name == "stacks" and entity.get("difficulty") not in LEVELS:
                errors.append(f"{label}.difficulty is not a valid level.")
            if name == "apis":
                if entity.get("auth") not in AUTH_TYPES:
                    errors.append(f"{label}.auth is not a supported auth type.")
                if entity.get("pricing") not in PRICING:
                    errors.append(f"{label}.pricing is not a supported pricing value.")
                for field in ("integration_complexity", "data_freshness"):
                    if entity.get(field) not in LEVELS:
                        errors.append(f"{label}.{field} is not a valid level.")
                for field in ("url", "docs_url"):
                    parsed = urlparse(entity.get(field, ""))
                    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                        errors.append(f"{label}.{field} must be an absolute http(s) URL.")
            if name == "templates" and entity.get("status") not in STATUSES:
                errors.append(f"{label}.status is not a supported status.")


def validate_repository(
    data_dir: Path = DATA_DIR, root: Path = ROOT
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for every data file and reference."""
    errors: list[str] = []
    warnings: list[str] = []

    raw = {name: _load(data_dir, name, errors) for name in SPEC}
    if errors:
        return errors, warnings
    _basic_checks(raw, errors)
    if errors:
        return errors, warnings

    index = {name: {item["id"]: item for item in raw[name]} for name in SPEC}
    categories = index["categories"]
    use_cases = index["use-cases"]
    stacks = index["stacks"]
    apis = index["apis"]
    templates = index["templates"]
    examples = index["examples"]

    def unknown(ref: str, table: dict, label: str, field: str) -> None:
        if ref not in table:
            errors.append(f"{label}.{field} references unknown id {ref!r}.")

    used_apis: set[str] = set()

    for use_case in use_cases.values():
        label = f"use-cases.{use_case['id']}"
        if not use_case["stack_ids"]:
            errors.append(f"{label}.stack_ids must reference at least one stack.")
        if not use_case["template_ids"]:
            errors.append(f"{label}.template_ids must reference at least one template.")
        for category_id in use_case["categories"]:
            unknown(category_id, categories, label, "categories")
        for stack_id in use_case["stack_ids"]:
            if stack_id not in stacks:
                errors.append(f"{label}.stack_ids references unknown id {stack_id!r}.")
            elif stacks[stack_id].get("use_case") != use_case["id"]:
                errors.append(
                    f"{label}.stack_ids includes {stack_id!r}, but that stack belongs to "
                    f"{stacks[stack_id].get('use_case')!r}."
                )
        for template_id in use_case["template_ids"]:
            template = templates.get(template_id)
            if template is None:
                errors.append(f"{label}.template_ids references unknown id {template_id!r}.")
            elif use_case["id"] not in template["use_case_ids"]:
                errors.append(
                    f"{label}.template_ids includes {template_id!r}, but that template does "
                    f"not list {use_case['id']!r} in use_case_ids."
                )
        if not (root / use_case["example"]).is_file():
            errors.append(f"{label}.example points to a missing file: {use_case['example']}")

    for stack in stacks.values():
        label = f"stacks.{stack['id']}"
        if stack["use_case"] not in use_cases:
            errors.append(f"{label}.use_case references unknown id {stack['use_case']!r}.")
        else:
            owner = use_cases[stack["use_case"]]
            if stack["id"] not in owner["stack_ids"]:
                errors.append(f"{label} is not listed in use-cases.{owner['id']}.stack_ids.")
            extra = set(stack["categories"]) - set(owner["categories"])
            if extra:
                warnings.append(f"{label} adds categories not used by its use case: {sorted(extra)}.")
        if not stack["tools"]:
            errors.append(f"{label}.tools must contain at least one tool slot.")
        for category_id in stack["categories"]:
            unknown(category_id, categories, label, "categories")

        slots: list[str] = []
        for position, tool in enumerate(stack["tools"]):
            tool_label = f"{label}.tools[{position}]"
            if not isinstance(tool, dict):
                errors.append(f"{tool_label} must be a JSON object.")
                continue
            slot = tool.get("slot")
            category_id = tool.get("category")
            api_ids = tool.get("api_ids")
            if not isinstance(slot, str) or not slot.strip():
                errors.append(f"{tool_label}.slot must be a non-empty string.")
            else:
                slots.append(slot)
            if category_id not in categories:
                errors.append(f"{tool_label}.category references unknown id {category_id!r}.")
            if not isinstance(api_ids, list) or not api_ids:
                errors.append(f"{tool_label}.api_ids must contain at least one API id.")
                continue
            if len(set(api_ids)) != len(api_ids):
                errors.append(f"{tool_label}.api_ids contains duplicate ids.")
            for api_id in api_ids:
                api = apis.get(api_id)
                if api is None:
                    errors.append(f"{tool_label}.api_ids references unknown id {api_id!r}.")
                    continue
                used_apis.add(api_id)
                if category_id not in api["category_ids"]:
                    errors.append(
                        f"{tool_label}.api_ids includes {api_id!r}, but that API is not in "
                        f"category {category_id!r}."
                    )
        if len(slots) != len(set(slots)):
            errors.append(f"{label}.tools contains duplicate slot names.")

    for template in templates.values():
        label = f"templates.{template['id']}"
        for use_case_id in template["use_case_ids"]:
            use_case = use_cases.get(use_case_id)
            if use_case is None:
                errors.append(f"{label}.use_case_ids references unknown id {use_case_id!r}.")
            elif template["id"] not in use_case["template_ids"]:
                errors.append(
                    f"{label} lists {use_case_id!r}, but that use case does not list "
                    f"{template['id']!r} in template_ids."
                )
        for category_id in template["category_ids"]:
            unknown(category_id, categories, label, "category_ids")
        if not template["path"].startswith("templates/"):
            errors.append(f"{label}.path must start with 'templates/'.")
        if not (root / template["path"]).is_file():
            errors.append(f"{label}.path points to a missing file: {template['path']}")
        if not any(
            template["id"] in use_case["template_ids"] for use_case in use_cases.values()
        ):
            errors.append(f"{label} is not referenced by any use case.")

    example_paths = {example["path"]: example for example in examples.values()}
    example_use_cases: set[str] = set()
    for example in examples.values():
        label = f"examples.{example['id']}"
        if example["use_case"] not in use_cases:
            errors.append(f"{label}.use_case references unknown id {example['use_case']!r}.")
        else:
            example_use_cases.add(example["use_case"])
        if not example["path"].startswith("examples/"):
            errors.append(f"{label}.path must start with 'examples/'.")
        if not (root / example["path"]).is_file():
            errors.append(f"{label}.path points to a missing file: {example['path']}")
        if sum(1 for item in examples.values() if item["path"] == example["path"]) > 1:
            errors.append(f"{label}.path duplicates another example path.")

    for use_case in use_cases.values():
        label = f"use-cases.{use_case['id']}"
        if use_case["id"] not in example_use_cases:
            errors.append(f"{label} has no entry in examples.json.")
        registered = example_paths.get(use_case["example"])
        if registered is None:
            errors.append(f"{label}.example is not registered in examples.json.")
        elif registered["use_case"] != use_case["id"]:
            errors.append(
                f"{label}.example is registered for a different use case "
                f"({registered['use_case']!r})."
            )

    example_root = root / "examples"
    if example_root.is_dir():
        for path in sorted(example_root.glob("*.md")):
            if path.name == "README.md":
                continue
            relative = path.relative_to(root).as_posix()
            if relative not in example_paths:
                warnings.append(f"{relative} is not registered in examples.json.")

    template_root = root / "templates"
    if template_root.is_dir():
        for child in sorted(path for path in template_root.iterdir() if path.is_dir()):
            if child.name not in templates:
                errors.append(f"templates/{child.name} has no entry in templates.json.")

    used_categories: set[str] = set()
    for use_case in use_cases.values():
        used_categories.update(use_case["categories"])
    for category in categories.values():
        category_id = category["id"]
        if category_id not in used_categories:
            errors.append(f"categories.{category_id} is not used by any use case.")
        api_count = sum(
            1 for api in apis.values() if category_id in api["category_ids"]
        )
        if api_count == 0:
            errors.append(f"categories.{category_id} has no APIs.")
        elif api_count < 2:
            warnings.append(
                f"categories.{category_id} has only one API; add an alternative."
            )

    for api_id in sorted(set(apis) - used_apis):
        warnings.append(f"apis.{api_id} is not referenced by any stack tool.")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate OpenToolHub data files.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="Directory containing the JSON data files.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root used to resolve template and example paths.",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as errors."
    )
    args = parser.parse_args(argv)

    errors, warnings = validate_repository(args.data_dir, args.root)
    print(f"Validating: {args.data_dir}")
    for message in warnings:
        print(f"warning: {message}")
    for message in errors:
        print(f"error: {message}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s).")

    if errors or (args.strict and warnings):
        print("Data is invalid.")
        return 1
    print("Data is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




