"""Provider abstraction for the optional local AI layer.

OpenToolHub is a static site. Nothing in ``site/`` imports this module, and the
published site never needs it. It exists so a developer can run the site
locally *with* an AI provider of their own choosing and their own keys, and so
the same prompt works against a laptop Ollama server or a hosted API.

Design rules, in order of importance:

1. No secret is ever read from the repository. A provider spec names the
   *environment variable* that holds the key (``api_key_env``); the value comes
   from the process environment or a git-ignored ``.env`` file.
2. Adding a provider is one small class plus one registry entry.
3. Every failure is reported as a sentence a human can act on, and errors are
   redacted before they reach a terminal, a log, or a browser.
4. Only the Python standard library is used, like the rest of ``scripts/``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

__all__ = [
    "AIChain",
    "AIError",
    "AllProvidersFailed",
    "AnthropicProvider",
    "Attempt",
    "ChainResult",
    "Completion",
    "DEFAULT_API_KEY_ENV",
    "DEFAULT_BASE_URLS",
    "DeepSeekProvider",
    "KINDS",
    "Message",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "PROVIDER_CLASSES",
    "Provider",
    "ProviderError",
    "ProviderNotReady",
    "ProviderSpec",
    "QwenProvider",
    "UnknownProvider",
    "available_kinds",
    "build_provider",
    "normalize_messages",
    "redact",
]

#: Kinds the registry knows how to build. Order is the documented order.
KINDS = (
    "ollama",
    "openai",
    "anthropic",
    "deepseek",
    "qwen",
    "openai-compatible",
)

#: Endpoint used when a spec does not set one. Hosted defaults are public,
#: documented base URLs; none of them contains a key.
DEFAULT_BASE_URLS: dict[str, str] = {
    "ollama": "http://127.0.0.1:11434",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openai-compatible": "",
}

#: Environment variable that conventionally holds the key for each kind.
#: ``openai-compatible`` is blank on purpose: local servers usually need none.
DEFAULT_API_KEY_ENV: dict[str, str] = {
    "ollama": "",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "openai-compatible": "",
}

MAX_ERROR_CHARS = 400


class AIError(RuntimeError):
    """Base class for problems the AI layer reports to a human."""


class ProviderError(AIError):
    """A provider was called and the call failed."""


class ProviderNotReady(AIError):
    """A provider is configured but cannot run yet (missing key or model)."""


class UnknownProvider(AIError):
    """A caller asked for a provider id that is not configured."""


class AllProvidersFailed(AIError):
    """Every provider in the fallback chain failed."""

    def __init__(self, attempts: Sequence["Attempt"]) -> None:
        self.attempts = list(attempts)
        detail = "; ".join(
            f"{attempt.provider_id}: {attempt.error or 'unknown error'}"
            for attempt in self.attempts
            if attempt.status != "ok"
        )
        super().__init__(
            "No AI provider answered. " + (detail or "No provider was attempted.")
        )


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace any configured key with ``***`` so errors stay safe to print."""
    result = str(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            result = result.replace(secret, "***")
    return result


def normalize_messages(messages: Sequence[Any]) -> list["Message"]:
    """Accept ``Message`` objects, ``{"role", "content"}`` dicts, or
    ``(role, content)`` pairs and return a normalized list."""
    normalized: list[Message] = []
    for item in messages:
        if isinstance(item, Message):
            normalized.append(item)
        elif isinstance(item, Mapping):
            normalized.append(
                Message(str(item.get("role", "user")), str(item.get("content", "")))
            )
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            normalized.append(Message(str(item[0]), str(item[1])))
        else:
            raise AIError(
                "messages must be Message objects, dicts, or (role, content) pairs"
            )
    if not normalized:
        raise AIError("at least one message is required")
    return normalized


@dataclass(frozen=True)
class Message:
    """One chat message. ``role`` is ``system``, ``user``, or ``assistant``."""

    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ProviderSpec:
    """Everything needed to reach one provider, minus the secret itself."""

    id: str
    kind: str
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    timeout: float = 60.0
    max_tokens: int = 512
    label: str = ""

    def display_name(self) -> str:
        return self.label or self.id


@dataclass(frozen=True)
class Completion:
    """A single successful answer plus where it came from."""

    text: str
    provider_id: str
    kind: str
    model: str
    latency_ms: int = 0
    usage: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "text": self.text,
            "provider_id": self.provider_id,
            "kind": self.kind,
            "model": self.model,
            "latency_ms": self.latency_ms,
        }
        if self.usage:
            payload["usage"] = self.usage
        return payload


@dataclass
class Attempt:
    """One provider's turn in a fallback chain.

    ``status`` is ``ok``, ``error``, or ``skipped`` (configured but not ready,
    so the chain never called it).
    """

    provider_id: str
    status: str
    error: str = ""
    latency_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider_id": self.provider_id,
            "status": self.status,
        }
        if self.error:
            payload["error"] = self.error
        if self.latency_ms:
            payload["latency_ms"] = self.latency_ms
        return payload


@dataclass
class ChainResult:
    """The winning completion plus the audit trail of every attempt."""

    completion: Completion
    attempts: list[Attempt] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "completion": self.completion.as_dict(),
            "attempts": [attempt.as_dict() for attempt in self.attempts],
        }


#: ``(url, headers, body, timeout) -> parsed JSON``. Tests inject a fake.
Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


def http_post_json(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> dict[str, Any]:
    """POST JSON with the standard library and return the parsed response.

    Error messages name the URL and the status but never echo request headers,
    which is where the credential travels.
    """
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # pragma: no cover - defensive
            detail = ""
        detail = " ".join(detail.split())[:MAX_ERROR_CHARS]
        raise ProviderError(
            f"HTTP {exc.code} from {url}" + (f": {detail}" if detail else "")
        ) from None
    except urllib.error.URLError as exc:
        raise ProviderError(f"could not reach {url}: {exc.reason}") from None
    except (TimeoutError, OSError) as exc:
        raise ProviderError(f"could not reach {url}: {exc}") from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProviderError(f"{url} returned a non-JSON response") from None
    if not isinstance(payload, dict):
        raise ProviderError(f"{url} returned JSON that is not an object")
    return payload


class Provider:
    """Common interface every adapter implements.

    Subclasses define ``kind``, ``requires_api_key``, ``build_request``, and
    ``parse_response``. ``complete`` is shared: it validates readiness, calls
    the transport, and wraps the text in a ``Completion``.
    """

    kind = ""
    requires_api_key = False

    def __init__(
        self,
        spec: ProviderSpec,
        *,
        api_key: str = "",
        transport: Transport | None = None,
    ) -> None:
        self.spec = spec
        self._api_key = api_key or ""
        self._transport: Transport = transport or http_post_json

    # -- readiness ---------------------------------------------------------
    def readiness(self) -> tuple[bool, str]:
        """Return ``(ready, reason)`` without touching the network."""
        if not self.spec.model:
            return False, "no model configured"
        if not self.spec.base_url:
            return False, "no base_url configured"
        if self.requires_api_key and not self._api_key:
            return False, f"missing API key in ${self.spec.api_key_env}"
        return True, "ready"

    @property
    def ready(self) -> bool:
        return self.readiness()[0]

    def secrets(self) -> list[str]:
        return [self._api_key] if self._api_key else []

    # -- adapter hooks -----------------------------------------------------
    def build_request(
        self, messages: Sequence[Message]
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        raise NotImplementedError

    def parse_response(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError

    # -- shared behaviour --------------------------------------------------
    def complete(self, messages: Sequence[Any]) -> Completion:
        normalized = normalize_messages(messages)
        ready, reason = self.readiness()
        if not ready:
            raise ProviderNotReady(f"provider {self.spec.id!r} is not ready: {reason}")
        url, headers, body = self.build_request(normalized)
        started = time.monotonic()
        try:
            payload = self._transport(url, headers, body, float(self.spec.timeout))
        except AIError as exc:
            raise ProviderError(redact(str(exc), self.secrets())) from None
        latency = int((time.monotonic() - started) * 1000)
        text, usage = self.parse_response(payload)
        if not text.strip():
            raise ProviderError(f"provider {self.spec.id!r} returned an empty answer")
        return Completion(
            text=text.strip(),
            provider_id=self.spec.id,
            kind=self.kind,
            model=self.spec.model,
            latency_ms=latency,
            usage=usage or None,
        )

    def describe(self) -> dict[str, Any]:
        """Public, secret-free description used by the CLI and the proxy."""
        ready, reason = self.readiness()
        return {
            "id": self.spec.id,
            "label": self.spec.display_name(),
            "kind": self.kind,
            "model": self.spec.model,
            "base_url": self.spec.base_url,
            "requires_api_key": self.requires_api_key,
            "api_key_env": self.spec.api_key_env if self.requires_api_key else "",
            "ready": ready,
            "reason": reason,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} id={self.spec.id!r} model={self.spec.model!r}>"


def _openai_style_text(payload: dict[str, Any], origin: str) -> str:
    """Pull text out of an OpenAI-shaped ``choices[0].message.content``.

    Some compatible servers return a list of content parts instead of a string;
    both shapes are handled because "OpenAI-compatible" is a loose promise.
    """
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError(
            f"{origin} returned JSON without choices[0].message.content"
        ) from None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
        ]
        return "".join(parts)
    raise ProviderError(f"{origin} returned content in an unsupported shape")


class OllamaProvider(Provider):
    """Ollama's native ``/api/chat`` endpoint. No key by default."""

    kind = "ollama"
    requires_api_key = False

    def build_request(
        self, messages: Sequence[Message]
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = f"{self.spec.base_url.rstrip('/')}/api/chat"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body: dict[str, Any] = {
            "model": self.spec.model,
            "messages": [message.as_dict() for message in messages],
            "stream": False,
        }
        if self.spec.max_tokens:
            body["options"] = {"num_predict": int(self.spec.max_tokens)}
        return url, headers, body

    def parse_response(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        message = payload.get("message")
        if not isinstance(message, dict) or "content" not in message:
            raise ProviderError("Ollama returned JSON without a message.content field")
        usage = {
            key: payload[key]
            for key in ("prompt_eval_count", "eval_count")
            if isinstance(payload.get(key), int)
        }
        return str(message.get("content", "")), usage


class OpenAICompatibleProvider(Provider):
    """The ``/chat/completions`` contract used by OpenAI, DeepSeek, Qwen
    (DashScope compatible mode), vLLM, LM Studio, llama.cpp, and others."""

    kind = "openai-compatible"
    requires_api_key = False

    def build_request(
        self, messages: Sequence[Message]
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = f"{self.spec.base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body: dict[str, Any] = {
            "model": self.spec.model,
            "messages": [message.as_dict() for message in messages],
        }
        if self.spec.max_tokens:
            body["max_tokens"] = int(self.spec.max_tokens)
        return url, headers, body

    def parse_response(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        text = _openai_style_text(payload, f"provider {self.spec.id!r}")
        usage = payload.get("usage")
        return text, usage if isinstance(usage, dict) else {}


class HostedOpenAIProvider(OpenAICompatibleProvider):
    """A hosted provider that speaks the OpenAI contract and needs a key."""

    requires_api_key = True


class OpenAIProvider(HostedOpenAIProvider):
    kind = "openai"


class DeepSeekProvider(HostedOpenAIProvider):
    kind = "deepseek"


class QwenProvider(HostedOpenAIProvider):
    kind = "qwen"


class AnthropicProvider(Provider):
    """Anthropic Messages API: ``system`` is a top-level field, not a message."""

    kind = "anthropic"
    requires_api_key = True
    API_VERSION = "2023-06-01"

    def build_request(
        self, messages: Sequence[Message]
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = f"{self.spec.base_url.rstrip('/')}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": self.API_VERSION,
        }
        system = "\n\n".join(
            message.content for message in messages if message.role == "system"
        )
        conversation = [
            message.as_dict() for message in messages if message.role != "system"
        ]
        body: dict[str, Any] = {
            "model": self.spec.model,
            "max_tokens": int(self.spec.max_tokens or 512),
            "messages": conversation or [{"role": "user", "content": ""}],
        }
        if system:
            body["system"] = system
        return url, headers, body

    def parse_response(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        blocks = payload.get("content")
        if not isinstance(blocks, list):
            raise ProviderError("Anthropic returned JSON without a content list")
        text = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        usage = payload.get("usage")
        return text, usage if isinstance(usage, dict) else {}


#: The registry. Adding a provider is a class plus a line here.
PROVIDER_CLASSES: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "deepseek": DeepSeekProvider,
    "qwen": QwenProvider,
    "openai-compatible": OpenAICompatibleProvider,
}


def available_kinds() -> list[str]:
    return list(PROVIDER_CLASSES)


def build_provider(
    spec: ProviderSpec,
    *,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> Provider:
    """Build the adapter for ``spec.kind`` and resolve its key from the env.

    The key value is read here and kept on the instance only. It is never
    written to a config file, a log line, or a response body.
    """
    source = env if env is not None else os.environ
    kind = (spec.kind or "").strip().lower()
    provider_class = PROVIDER_CLASSES.get(kind)
    if provider_class is None:
        raise UnknownProvider(
            f"unknown provider kind {spec.kind!r}; known kinds: "
            + ", ".join(sorted(PROVIDER_CLASSES))
        )
    api_key = ""
    if spec.api_key_env:
        api_key = (source.get(spec.api_key_env) or "").strip()
    return provider_class(spec, api_key=api_key, transport=transport)


class AIChain:
    """An ordered list of providers with explicit selection and fallback."""

    def __init__(self, providers: Sequence[Provider]) -> None:
        self.providers: list[Provider] = list(providers)

    def __len__(self) -> int:
        return len(self.providers)

    def __iter__(self):
        return iter(self.providers)

    def by_id(self, provider_id: str) -> Provider:
        for provider in self.providers:
            if provider.spec.id == provider_id:
                return provider
        known = ", ".join(provider.spec.id for provider in self.providers) or "none"
        raise UnknownProvider(
            f"unknown provider {provider_id!r}; configured providers: {known}"
        )

    def order(self) -> list[str]:
        return [provider.spec.id for provider in self.providers]

    def ready(self) -> list[Provider]:
        return [provider for provider in self.providers if provider.ready]

    def describe(self) -> dict[str, Any]:
        """Secret-free status for ``--list``, the proxy, and the browser."""
        return {
            "configured": bool(self.providers),
            "ready_count": len(self.ready()),
            "order": self.order(),
            "providers": [provider.describe() for provider in self.providers],
        }

    def complete(
        self,
        messages: Sequence[Any],
        *,
        provider_id: str = "",
        fallback: bool = True,
    ) -> ChainResult:
        """Answer with ``provider_id`` when given, then the rest in order.

        An explicit ``provider_id`` is tried first and fails loudly if it is
        unknown or not ready. With ``fallback=False`` only that provider is
        tried; with ``fallback=True`` the remaining ready providers follow.
        """
        if not self.providers:
            raise AllProvidersFailed(
                [Attempt("(none)", "error", "no AI providers are configured")]
            )

        if provider_id:
            first = self.by_id(provider_id)
            ready, reason = first.readiness()
            if not ready:
                raise ProviderNotReady(
                    f"provider {provider_id!r} is not ready: {reason}"
                )
            queue = [first]
            if fallback:
                queue.extend(
                    provider
                    for provider in self.ready()
                    if provider.spec.id != provider_id
                )
        else:
            if not fallback:
                raise AIError("provider_id is required when fallback is disabled")
            queue = self.ready()

        queued_ids = {provider.spec.id for provider in queue}
        attempts: list[Attempt] = []
        for provider in self.providers:
            if provider.spec.id in queued_ids:
                continue
            ready, reason = provider.readiness()
            attempts.append(
                Attempt(
                    provider.spec.id,
                    "skipped",
                    reason if not ready else "not selected",
                )
            )

        for provider in queue:
            try:
                completion = provider.complete(messages)
            except AIError as exc:
                attempts.append(
                    Attempt(
                        provider.spec.id,
                        "error",
                        redact(str(exc), provider.secrets()),
                    )
                )
                continue
            attempts.append(Attempt(provider.spec.id, "ok", "", completion.latency_ms))
            return ChainResult(completion=completion, attempts=attempts)

        raise AllProvidersFailed(attempts)





