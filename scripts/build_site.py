#!/usr/bin/env python3
"""Stage the JSON data for the static site and serve it locally.

The site is plain HTML/JS with no build step. Browsers cannot fetch files
outside the directory they are served from, so this script mirrors data/*.json
into site/data/ and can serve site/ with the Python standard library.

Usage:
    python3 scripts/build_site.py            # stage data into site/data
    python3 scripts/build_site.py --check    # fail if site/data is stale
    python3 scripts/build_site.py --serve    # stage, then serve site/
"""

from __future__ import annotations

import argparse
import shutil
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type

from config import DATA_DIR, HOST, PORT, SITE_DIR


class NoCacheHandler(SimpleHTTPRequestHandler):
    """Development handler that never lets the browser cache JSON or HTML."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def stage(check_only: bool = False) -> int:
    """Copy data/*.json into site/data and remove stale copies."""
    if not DATA_DIR.is_dir():
        print(f"error: data directory not found: {DATA_DIR}", file=sys.stderr)
        return 1

    sources = sorted(DATA_DIR.glob("*.json"))
    if not sources:
        print(f"error: no JSON files found in {DATA_DIR}", file=sys.stderr)
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
        for existing in sorted(target.glob("*.json")):
            if existing.name not in expected:
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
