"""Shared configuration for the OpenToolHub Python tools.

Configuration is read from environment variables. A repository-root .env file
is loaded first when present, so local settings do not need to be exported by
hand. No third-party packages are required.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file without overriding real env vars."""
    env_path = path or ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else default.resolve()


def _int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip() or str(default)
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from exc


DATA_DIR = _path_from_env("OPEN_TOOL_HUB_DATA_DIR", ROOT / "data")
SITE_DIR = _path_from_env("OPEN_TOOL_HUB_SITE_DIR", ROOT / "site")
SITE_URL = (
    os.environ.get("OPEN_TOOL_HUB_SITE_URL", "").strip()
    or "https://ghana-gpt.github.io/opentoolhub/"
).rstrip("/") + "/"
REPOSITORY_URL = (
    os.environ.get("OPEN_TOOL_HUB_REPOSITORY_URL", "").strip()
    or "https://github.com/ghana-gpt/opentoolhub"
).rstrip("/")
SCHEMA_VERSION = "1.0.0"
HOST = os.environ.get("OPEN_TOOL_HUB_HOST", "").strip() or "127.0.0.1"
PORT = _int_from_env("OPEN_TOOL_HUB_PORT", 8000)

#: Address for the optional local AI proxy (scripts/ai_proxy.py). Loopback by
#: default: the proxy can spend the user's provider credits, so it should not
#: be reachable from a network unless the user opts in with --allow-remote.
AI_HOST = os.environ.get("OPEN_TOOL_HUB_AI_HOST", "").strip() or "127.0.0.1"
AI_PORT = _int_from_env("OPEN_TOOL_HUB_AI_PORT", 8787)
