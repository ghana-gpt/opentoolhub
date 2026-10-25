#!/usr/bin/env python3
"""Send one prompt to the configured local AI provider from the terminal.

This is the AI equivalent of ``scripts/recommend.py``: a thin, scriptable
command that proves the provider layer works without a browser.

    python3 scripts/ai_chat.py --list
    python3 scripts/ai_chat.py "Name three public weather APIs"
    python3 scripts/ai_chat.py --provider local --json "Summarise this idea"

Exit codes:

``0``  answered
``2``  bad usage, unknown provider, or a provider that is not ready
``3``  no provider is configured at all (the normal state of a fresh clone)
``4``  providers were configured but every one of them failed
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from ai_config import build_chain
from ai_providers import (
    AIChain,
    AIError,
    AllProvidersFailed,
    Message,
    ProviderNotReady,
    UnknownProvider,
)
from ai_proxy import DOCS_PATH, provider_lines

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOT_CONFIGURED = 3
EXIT_ALL_FAILED = 4


def format_status(chain: AIChain) -> str:
    described = chain.describe()
    lines = ["Configured providers (fallback order):"]
    lines.extend(provider_lines(described))
    if described["order"]:
        lines.append("Order: " + " -> ".join(described["order"]))
    if not described["configured"]:
        lines.append("Setup: " + DOCS_PATH)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ask the locally configured AI provider one question. "
            "Keys come from the environment, never from this repository."
        )
    )
    parser.add_argument(
        "prompt", nargs="*", help="What to ask. Use '-' to read standard input."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List configured providers, their models, and readiness.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON."
    )
    parser.add_argument(
        "--provider",
        default="",
        help="Provider id to try first. Others follow unless --no-fallback.",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Use only --provider; do not continue down the chain.",
    )
    parser.add_argument(
        "--system", default="", help="Optional system prompt for this request."
    )
    args = parser.parse_args(argv)

    try:
        chain = build_chain()
    except AIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.list:
        if args.json:
            print(json.dumps(chain.describe(), indent=2, ensure_ascii=False))
        else:
            print(format_status(chain))
        return EXIT_OK

    if not len(chain):
        print(
            "error: no AI providers are configured. The static site works "
            f"without them. To enable one, see {DOCS_PATH}.",
            file=sys.stderr,
        )
        return EXIT_NOT_CONFIGURED
    if not chain.ready():
        print(
            "error: providers are configured but none is ready:",
            file=sys.stderr,
        )
        for line in provider_lines(chain.describe()):
            print(line, file=sys.stderr)
        return EXIT_NOT_CONFIGURED

    prompt = " ".join(args.prompt).strip()
    if prompt == "-" or (not prompt and not sys.stdin.isatty()):
        prompt = sys.stdin.read().strip()
    if not prompt:
        parser.print_usage(sys.stderr)
        print("error: provide a prompt or use --list.", file=sys.stderr)
        return EXIT_USAGE

    messages: list[Message] = []
    if args.system.strip():
        messages.append(Message("system", args.system.strip()))
    messages.append(Message("user", prompt))

    try:
        result = chain.complete(
            messages,
            provider_id=args.provider.strip(),
            fallback=not args.no_fallback,
        )
    except (UnknownProvider, ProviderNotReady) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except AllProvidersFailed as exc:
        print(f"error: {exc}", file=sys.stderr)
        for attempt in exc.attempts:
            print(f"  {attempt.as_dict()}", file=sys.stderr)
        return EXIT_ALL_FAILED
    except AIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        payload: dict[str, Any] = result.as_dict()
        payload["fallback_used"] = len(result.attempts) > 1
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        seen = ", ".join(
            f"{attempt.provider_id} ({attempt.status})"
            for attempt in result.attempts
        )
        print(result.completion.text)
        print(
            f"\n-- {result.completion.provider_id} / {result.completion.model}"
            f" in {result.completion.latency_ms} ms ({seen})",
            file=sys.stderr,
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
