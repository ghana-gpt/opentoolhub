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

import difflib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

import config

from ai_providers import (
    AIChain,
    ConfigError,
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URLS,
    PROVIDER_CLASSES,
    ProviderSpec,
    Transport,
    build_provider,
    check_provider_id,
)

DEFAULT_CONFIG_NAME = "ai-providers.local.json"
ENV_PREFIX = "OPEN_TOOL_HUB_AI_"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_TOKENS = 512

#: Field names that would put a secret in a file. They are rejected loudly.
SECRET_FIELDS = ("api_key", "apikey", "key", "token", "secret", "password")

#: Every field a provider entry may set. Anything else is a typo: accepting it
#: would leave the author believing a setting took effect when it did not.
PROVIDER_FIELDS = (
    "id",
    "label",
    "kind",
    "model",
    "base_url",
    "api_key_env",
    "timeout",
    "max_tokens",
    "enabled",
)

#: Top-level keys. A key that starts with ``$`` is metadata (``$comment``,
#: ``$schema``) and is always allowed, so a file can document itself.
TOP_LEVEL_FIELDS = ("providers",)


def env_prefix(provider_id: str) -> str:
    """``my-local`` → ``OPEN_TOOL_HUB_AI_MY_LOCAL_``."""
    return ENV_PREFIX + provider_id.upper().replace("-", "_").replace(".", "_") + "_"


def _env(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def _float(value: Any, source: str) -> float:
    """Coerce a number that came from an environment variable or a JSON file.

    A ``bool`` is rejected on purpose: Python would happily turn JSON ``true``
    into ``1.0`` and a one-second timeout is never what the author meant.
    ``nan`` and ``inf`` are rejected too: ``float("nan")`` parses cleanly here
    and then fails inside ``urllib`` as "Invalid value NaN", which is a
    traceback rather than a sentence, and an infinite timeout would hang the
    command forever instead of giving up.
    """
    if isinstance(value, bool) or value is None:
        raise ConfigError(f"{source} must be a number, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{source} must be a number, got {value!r}") from None
    if not math.isfinite(number):
        raise ConfigError(f"{source} must be a finite number, got {value!r}")
    return number


def _int(value: Any, source: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ConfigError(f"{source} must be an integer, got {value!r}")
    if isinstance(value, float) and not value.is_integer():
        raise ConfigError(f"{source} must be an integer, got {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{source} must be an integer, got {value!r}") from None


def _bool(value: str, source: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{source} must be true/false, got {value!r}")


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
            raise ConfigError(f"{ENV_PREFIX}CONFIG points at a missing file: {path}")
        return path
    default = config.ROOT / DEFAULT_CONFIG_NAME
    return default if default.is_file() else None


def _reject_secret_fields(entry: Mapping[str, Any], path: Path) -> None:
    for field_name in entry:
        if str(field_name).strip().lower() in SECRET_FIELDS:
            raise ConfigError(
                f"{path} sets {field_name!r} for provider "
                f"{entry.get('id')!r}. Do not store keys in files. Put the key "
                "in an environment variable and name that variable with "
                "'api_key_env' instead."
            )


def _closest(name: Any, allowed: Sequence[str]) -> str:
    """Render ``name``, with a suggestion when it is close to a real field."""
    match = difflib.get_close_matches(str(name), list(allowed), n=1)
    return f"{name!r} (did you mean {match[0]!r}?)" if match else repr(name)


def _reject_unknown_fields(entry: Mapping[str, Any], path: Path) -> None:
    """Reject a field name that is not part of the schema.

    Ignoring one is the worst option: ``"enabeld": false`` would leave the
    provider enabled, and ``"timout": 10`` would leave the timeout at its
    default, while both look applied to whoever wrote the file.
    """
    unknown = [
        key
        for key in entry
        if str(key) not in PROVIDER_FIELDS
        and not str(key).startswith("$")
        and str(key).strip().lower() not in SECRET_FIELDS
    ]
    if not unknown:
        return
    raise ConfigError(
        f"{path} sets unknown field(s) for provider {entry.get('id')!r}: "
        + ", ".join(_closest(key, PROVIDER_FIELDS) for key in unknown)
        + ". Known fields: "
        + ", ".join(PROVIDER_FIELDS)
        + "."
    )


def load_config_entries(
    path: Path | None, env: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Read provider entries from a JSON file and shape-check them."""
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{path} does not exist") from None
    except UnicodeDecodeError:
        raise ConfigError(f"{path} is not valid UTF-8 text") from None
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc.strerror or exc}") from None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from None
    if isinstance(payload, dict):
        unknown_top = [
            key
            for key in payload
            if str(key) not in TOP_LEVEL_FIELDS and not str(key).startswith("$")
        ]
        if unknown_top:
            raise ConfigError(
                f"{path} has unknown top-level key(s): "
                + ", ".join(_closest(key, TOP_LEVEL_FIELDS) for key in unknown_top)
                + ". Expected a 'providers' list; a key that starts with '$' is "
                "treated as a comment."
            )
        if "providers" not in payload:
            raise ConfigError(
                f'{path} has no "providers" list. Write {{"providers": [...]}} '
                "or a bare JSON array of entries."
            )
        entries = payload["providers"]
    else:
        entries = payload
    if not isinstance(entries, list):
        raise ConfigError(f"{path} must contain a 'providers' list")
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfigError(f"{path} has a provider entry that is not an object")
        _reject_secret_fields(entry, path)
        _reject_unknown_fields(entry, path)
        provider_id = check_provider_id(entry.get("id", ""), source=str(path))
        if provider_id in seen:
            # Two entries with one id would silently make the last one win,
            # which is the kind of quiet surprise a config file should never
            # have. The environment variable path already rejects duplicates.
            raise ConfigError(f"{path} defines provider {provider_id!r} more than once")
        seen.add(provider_id)
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
        ids = [
            check_provider_id(part, source=f"{ENV_PREFIX}PROVIDERS")
            for part in raw.split(",")
            if part.strip()
        ]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ConfigError(
                f"{ENV_PREFIX}PROVIDERS lists {', '.join(duplicates)} more than once"
            )
    else:
        ids = [str(entry.get("id", "")).strip() for entry in entries.values()]
    for provider_id in ids:
        has_env_kind = bool(_env(env, env_prefix(provider_id) + "KIND"))
        if provider_id not in entries and not has_env_kind:
            known = ", ".join(entries) or "none configured in a file"
            raise ConfigError(
                f"provider {provider_id!r} is listed in "
                f"{ENV_PREFIX}PROVIDERS but has no config entry and no "
                f"{env_prefix(provider_id)}KIND. Known ids: {known}"
            )
    return ids


def _checked_base_url(value: str, source: str) -> str:
    """Reject a base URL that is not http(s) or that hides a credential.

    ``describe()`` shows this value to a browser, and the layer promises that a
    key never reaches a page. A URL such as
    ``https://user:sk-...@host/v1`` would break that promise, so it is a
    configuration error rather than a silent leak. The URL itself is never
    echoed in the credential case, so the key cannot reach a log either.
    """
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError(
            f"{source}: base_url must be an http:// or https:// URL, got {value!r}"
        )
    if parsed.username or parsed.password:
        raise ConfigError(
            f"{source}: base_url must not embed a credential. Put the key in an "
            "environment variable and name that variable with 'api_key_env'."
        )
    return value.rstrip("/")


def spec_for(
    provider_id: str,
    entry: Mapping[str, Any] | None,
    env: Mapping[str, str],
    path: Path | None = None,
) -> ProviderSpec | None:
    """Merge file entry, environment overrides, and kind defaults.

    Every value is validated here, whether it came from an environment variable
    or from the JSON file, so a typo in a file is reported as a ``ConfigError``
    with the same clarity as a typo in a shell. ``path`` only makes the message
    name the file; it is optional so the function stays usable on its own.
    """
    entry = entry or {}
    prefix = env_prefix(provider_id)
    where = f"provider {provider_id!r}" + (f" in {path}" if path is not None else "")

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
        raise ConfigError(
            f"provider {provider_id!r} has no kind. Set {prefix}KIND to one of: "
            + ", ".join(sorted(PROVIDER_CLASSES))
        )
    kind = kind.lower()
    if kind not in PROVIDER_CLASSES:
        raise ConfigError(
            f"provider {provider_id!r} has unknown kind {kind!r}. Known kinds: "
            + ", ".join(sorted(PROVIDER_CLASSES))
        )

    model = _env(env, prefix + "MODEL") or str(entry.get("model", "")).strip()
    base_url_raw = _env(env, prefix + "BASE_URL")
    if base_url_raw:
        base_url_source = prefix + "BASE_URL"
        base_url = base_url_raw
    else:
        base_url_source = f"base_url for {where}"
        base_url = (
            str(entry.get("base_url", "")).strip() or DEFAULT_BASE_URLS.get(kind, "")
        )
    api_key_env = (
        _env(env, prefix + "API_KEY_ENV")
        or str(entry.get("api_key_env", "")).strip()
        or DEFAULT_API_KEY_ENV.get(kind, "")
    )

    timeout_raw = _env(env, prefix + "TIMEOUT")
    if timeout_raw:
        timeout_source = prefix + "TIMEOUT"
        timeout = _float(timeout_raw, timeout_source)
    else:
        timeout_source = f"timeout for {where}"
        timeout = _float(entry.get("timeout", DEFAULT_TIMEOUT), timeout_source)
    if timeout <= 0:
        raise ConfigError(
            f"{timeout_source} must be greater than 0 seconds, got {timeout:g}"
        )

    max_tokens_raw = _env(env, prefix + "MAX_TOKENS")
    if max_tokens_raw:
        max_tokens_source = prefix + "MAX_TOKENS"
        max_tokens = _int(max_tokens_raw, max_tokens_source)
    else:
        max_tokens_source = f"max_tokens for {where}"
        default_max_tokens = entry.get("max_tokens", DEFAULT_MAX_TOKENS)
        max_tokens = _int(default_max_tokens, max_tokens_source)
    if max_tokens < 1:
        raise ConfigError(f"{max_tokens_source} must be at least 1, got {max_tokens}")

    label = _env(env, prefix + "LABEL") or str(entry.get("label", "")).strip()

    return ProviderSpec(
        id=provider_id,
        kind=kind,
        model=model,
        base_url=_checked_base_url(base_url, base_url_source),
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
        spec = spec_for(provider_id, by_id.get(provider_id), source, path=resolved)
        if spec is None:
            continue
        providers.append(build_provider(spec, env=source, transport=transport))
    return AIChain(providers)


