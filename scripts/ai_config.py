"""Resolve AI provider configuration from the environment and local files.

Precedence, highest first:

1. Environment variables (including a git-ignored ``.env`` file, loaded by
   ``scripts/config.py``).
2. ``ai-providers.local.json`` (git-ignored) or the file named by
   ``OPEN_TOOL_HUB_AI_CONFIG``.

Nothing here reads a key *value* from a file. A file may only name the
environment variable that holds the key, so a committed config file can never
leak a credential.

Environment variables, per provider id (``ID`` upper-cased, ``-`` becomes
``_``) — for the provider id ``local``:

``OPEN_TOOL_HUB_AI_LOCAL_KIND``        adapter kind (``ollama``, ``openai``, …)
``OPEN_TOOL_HUB_AI_LOCAL_MODEL``       model name, e.g. ``phi3:mini``
``OPEN_TOOL_HUB_AI_LOCAL_BASE_URL``    endpoint override
``OPEN_TOOL_HUB_AI_LOCAL_API_KEY_ENV`` name of the variable holding the key
``OPEN_TOOL_HUB_AI_LOCAL_TIMEOUT``     seconds, default 60
``OPEN_TOOL_HUB_AI_LOCAL_MAX_TOKENS``  default 512
``OPEN_TOOL_HUB_AI_LOCAL_ENABLED``     ``0``/``false`` disables the provider
``OPEN_TOOL_HUB_AI_LOCAL_LABEL``       display name in the UI

Global variables:

``OPEN_TOOL_HUB_AI_PROVIDERS``  comma-separated ids; this is the fallback order
``OPEN_TOOL_HUB_AI_CONFIG``     path to the local JSON config file
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import config

from ai_providers import (
    AIChain,
    AIError,
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URLS,
    PROVIDER_CLASSES,
    ProviderSpec,
    Transport,
    build_provider,
)

DEFAULT_CONFIG_NAME = "ai-providers.local.json"
ENV_PREFIX = "OPEN_TOOL_HUB_AI_"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_TOKENS = 512

#: Field names that would put a secret in a file. They are rejected loudly.
SECRET_FIELDS = ("api_key", "apikey", "key", "token", "secret", "password")


def env_prefix(provider_id: str) -> str:
    """``my-local`` → ``OPEN_TOOL_HUB_AI_MY_LOCAL_``."""
    return ENV_PREFIX + provider_id.upper().replace("-", "_").replace(".", "_") + "_"


def _env(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def _float(value: str, source: str) -> float:
    try:
        return float(value)
    except ValueError:
        raise AIError(f"{source} must be a number, got {value!r}") from None


def _int(value: str, source: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise AIError(f"{source} must be an integer, got {value!r}") from None


def _bool(value: str, source: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise AIError(f"{source} must be true/false, got {value!r}")


def config_path(env: Mapping[str, str] | None = None) -> Path | None:
    """Return the config file to read, or ``None`` when there is none.

    An explicitly requested file that does not exist is an error: a typo in
    ``OPEN_TOOL_HUB_AI_CONFIG`` should not silently disable the AI layer.
    """
    source = env if env is not None else os.environ
    explicit = _env(source, f"{ENV_PREFIX}CONFIG")
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = (config.ROOT / path).resolve()
        if not path.is_file():
            raise AIError(f"{ENV_PREFIX}CONFIG points at a missing file: {path}")
        return path
    default = config.ROOT / DEFAULT_CONFIG_NAME
    return default if default.is_file() else None


def _reject_secret_fields(entry: Mapping[str, Any], path: Path) -> None:
    for field_name in entry:
        if str(field_name).strip().lower() in SECRET_FIELDS:
            raise AIError(
                f"{path} sets {field_name!r} for provider "
                f"{entry.get('id')!r}. Do not store keys in files. Put the key "
                "in an environment variable and name that variable with "
                "'api_key_env' instead."
            )


def load_config_entries(
    path: Path | None, env: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Read provider entries from a JSON file and shape-check them."""
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AIError(f"{path} is not valid JSON: {exc}") from None
    if isinstance(payload, dict):
        entries = payload.get("providers", [])
    else:
        entries = payload
    if not isinstance(entries, list):
        raise AIError(f"{path} must contain a 'providers' list")
    cleaned: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise AIError(f"{path} has a provider entry that is not an object")
        _reject_secret_fields(entry, path)
        if not str(entry.get("id", "")).strip():
            raise AIError(f"{path} has a provider entry without an id")
        cleaned.append(dict(entry))
    return cleaned


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _bool(str(value), "enabled")


def provider_ids(
    env: Mapping[str, str], entries: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Return the configured ids in fallback order.

    ``OPEN_TOOL_HUB_AI_PROVIDERS`` selects and orders; without it the file
    order is used. An id that is only in the environment is allowed, so a user
    can define a provider without touching any file.
    """
    raw = _env(env, f"{ENV_PREFIX}PROVIDERS")
    ids: list[str] = []
    if raw:
        ids = [part.strip() for part in raw.split(",") if part.strip()]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise AIError(
                f"{ENV_PREFIX}PROVIDERS lists {', '.join(duplicates)} more than once"
            )
    else:
        ids = [str(entry.get("id", "")).strip() for entry in entries.values()]
    for provider_id in ids:
        has_env_kind = bool(_env(env, env_prefix(provider_id) + "KIND"))
        if provider_id not in entries and not has_env_kind:
            known = ", ".join(entries) or "none configured in a file"
            raise AIError(
                f"provider {provider_id!r} is listed in "
                f"{ENV_PREFIX}PROVIDERS but has no config entry and no "
                f"{env_prefix(provider_id)}KIND. Known ids: {known}"
            )
    return ids


def spec_for(
    provider_id: str,
    entry: Mapping[str, Any] | None,
    env: Mapping[str, str],
) -> ProviderSpec | None:
    """Merge file entry, environment overrides, and kind defaults."""
    entry = entry or {}
    prefix = env_prefix(provider_id)

    enabled_raw = _env(env, prefix + "ENABLED")
    enabled = (
        _bool(enabled_raw, prefix + "ENABLED")
        if enabled_raw
        else _coerce_bool(entry.get("enabled", True))
    )
    if not enabled:
        return None

    kind = _env(env, prefix + "KIND") or str(entry.get("kind", "")).strip()
    if not kind:
        raise AIError(
            f"provider {provider_id!r} has no kind. Set {prefix}KIND to one of: "
            + ", ".join(sorted(PROVIDER_CLASSES))
        )
    kind = kind.lower()
    if kind not in PROVIDER_CLASSES:
        raise AIError(
            f"provider {provider_id!r} has unknown kind {kind!r}. Known kinds: "
            + ", ".join(sorted(PROVIDER_CLASSES))
        )

    model = _env(env, prefix + "MODEL") or str(entry.get("model", "")).strip()
    base_url = (
        _env(env, prefix + "BASE_URL")
        or str(entry.get("base_url", "")).strip()
        or DEFAULT_BASE_URLS.get(kind, "")
    )
    api_key_env = (
        _env(env, prefix + "API_KEY_ENV")
        or str(entry.get("api_key_env", "")).strip()
        or DEFAULT_API_KEY_ENV.get(kind, "")
    )

    timeout_raw = _env(env, prefix + "TIMEOUT")
    timeout = (
        _float(timeout_raw, prefix + "TIMEOUT")
        if timeout_raw
        else float(entry.get("timeout", DEFAULT_TIMEOUT))
    )
    max_tokens_raw = _env(env, prefix + "MAX_TOKENS")
    max_tokens = (
        _int(max_tokens_raw, prefix + "MAX_TOKENS")
        if max_tokens_raw
        else int(entry.get("max_tokens", DEFAULT_MAX_TOKENS))
    )
    label = _env(env, prefix + "LABEL") or str(entry.get("label", "")).strip()

    return ProviderSpec(
        id=provider_id,
        kind=kind,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key_env=api_key_env,
        timeout=timeout,
        max_tokens=max_tokens,
        label=label,
    )


def build_chain(
    *,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    path: Path | None = None,
    use_default_config: bool = True,
) -> AIChain:
    """Build the configured provider chain.

    Returns an empty chain when nothing is configured. That is the normal state
    of a fresh clone and of the published site: the static site works and the
    AI panel explains how to enable providers.
    """
    source = env if env is not None else os.environ
    resolved = path if path is not None else (
        config_path(source) if use_default_config else None
    )
    entries = load_config_entries(resolved, source)
    by_id: dict[str, Mapping[str, Any]] = {
        str(entry["id"]).strip(): entry for entry in entries
    }
    ids = provider_ids(source, by_id)
    providers = []
    for provider_id in ids:
        spec = spec_for(provider_id, by_id.get(provider_id), source)
        if spec is None:
            continue
        providers.append(build_provider(spec, env=source, transport=transport))
    return AIChain(providers)


