#!/usr/bin/env python3

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def recommend(use_case_id: str):
    use_cases = load_json(DATA_DIR / "use-cases.json")
    stacks = load_json(DATA_DIR / "stacks.json")
    apis = {api["id"]: api for api in load_json(DATA_DIR / "apis.json")}

    selected = next((item for item in use_cases if item["id"] == use_case_id), None)
    if not selected:
        raise ValueError(f"Use case '{use_case_id}' not found.")

    matches = [stack for stack in stacks if stack["use_case"] == use_case_id]
    result = {
        "use_case": selected,
        "recommended_stacks": matches,
        "api_details": [apis[a] for a in [api_id for stack in matches for api_id in stack["recommended_apis"]]],
    }
    return result


if __name__ == "__main__":
    print("OpenToolHub recommendation demo")
    for case in ["travel-planner", "city-dashboard", "research-assistant"]:
        print(f"\n=== {case} ===")
        result = recommend(case)
        print(json.dumps({
            "use_case": result["use_case"]["name"],
            "stacks": [stack["name"] for stack in result["recommended_stacks"]],
            "api_count": len(result["api_details"])
        }, indent=2))
