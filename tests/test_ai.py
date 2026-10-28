"""Tests for the optional local AI layer.

Nothing here needs an external network, a key, or a running model: provider HTTP
calls go through an injected transport, the proxy tests use a throwaway server on
port 0 with a stubbed chain, and ``TransportTests`` drives the real stdlib client
against a loopback stub so timeouts and HTTP errors are proven rather than
assumed. Real end-to-end proof against a running provider lives in the opt-in
``tests/test_ai_live.py``; ``docs/local-ai.md`` documents both.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ai_chat  # noqa: E402
import ai_config  # noqa: E402
import ai_providers  # noqa: E402
import ai_proxy  # noqa: E402
from ai_providers import (  # noqa: E402
    AIChain,
    AIError,
    AllProvidersFailed,
    AnthropicProvider,
    ConfigError,
    MAX_ERROR_CHARS,
    Message,
    OllamaProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    PROVIDER_CLASSES,
    ProviderError,
    ProviderNotReady,
    ProviderSpec,
    QwenProvider,
    UnknownProvider,
    build_provider,
    http_post_json,
    redact,
)

FAKE_KEY = "sk-test-key-do-not-log-123456"
DOCS = ai_proxy.DOCS_PATH


def spec(provider_id: str, kind: str, **overrides: Any) -> ProviderSpec:
    values: dict[str, Any] = {
        "id": provider_id,
        "kind": kind,
        "model": "test-model",
        "base_url": "http://127.0.0.1:9/v1",
        "api_key_env": "TEST_API_KEY",
        "timeout": 1.0,
        "max_tokens": 32,
    }
    values.update(overrides)
    return ProviderSpec(**values)


class RecordingTransport:
    """Records requests and returns a queued payload or raises a queued error."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append(
            {"url": url, "headers": headers, "body": body, "timeout": timeout}
        )
        if not self.responses:
            raise AssertionError("transport called more times than expected")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@contextlib.contextmanager
def clean_ai_env(**overrides: str):
    """Drop every OPEN_TOOL_HUB_AI_* variable, then apply overrides."""
    saved = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("OPEN_TOOL_HUB_AI_")
    }
    for key in saved:
        del os.environ[key]
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key in [k for k in os.environ if k.startswith("OPEN_TOOL_HUB_AI_")]:
            del os.environ[key]
        os.environ.update(saved)


class RegistryTests(unittest.TestCase):
    def test_every_documented_kind_builds_a_provider(self):
        expected = {
            "ollama": OllamaProvider,
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "deepseek": PROVIDER_CLASSES["deepseek"],
            "qwen": QwenProvider,
            "openai-compatible": OpenAICompatibleProvider,
        }
        for kind, provider_class in expected.items():
            with self.subTest(kind=kind):
                provider = build_provider(spec("p", kind), env={})
                self.assertIsInstance(provider, provider_class)
                self.assertEqual(provider.kind, kind)

    def test_unknown_kind_names_the_known_kinds(self):
        with self.assertRaises(UnknownProvider) as caught:
            build_provider(spec("p", "mystery"), env={})
        message = str(caught.exception)
        self.assertIn("mystery", message)
        for kind in PROVIDER_CLASSES:
            self.assertIn(kind, message)

    def test_hosted_kinds_require_a_key_and_local_kinds_do_not(self):
        self.assertTrue(build_provider(spec("a", "openai"), env={}).requires_api_key)
        self.assertTrue(
            build_provider(spec("a", "anthropic"), env={}).requires_api_key
        )
        self.assertFalse(
            build_provider(spec("a", "ollama", api_key_env=""), env={}).requires_api_key
        )
        self.assertFalse(
            build_provider(
                spec("a", "openai-compatible", api_key_env=""), env={}
            ).requires_api_key
        )


class ReadinessTests(unittest.TestCase):
    def test_missing_model_is_reported(self):
        provider = build_provider(spec("p", "ollama", model=""), env={})
        ready, reason = provider.readiness()
        self.assertFalse(ready)
        self.assertIn("model", reason)

    def test_missing_key_names_the_variable_not_a_value(self):
        provider = build_provider(spec("p", "openai"), env={})
        ready, reason = provider.readiness()
        self.assertFalse(ready)
        self.assertIn("TEST_API_KEY", reason)

    def test_key_present_makes_hosted_provider_ready(self):
        provider = build_provider(spec("p", "openai"), env={"TEST_API_KEY": FAKE_KEY})
        self.assertEqual(provider.readiness(), (True, "ready"))

    def test_complete_on_unready_provider_raises_before_calling_out(self):
        transport = RecordingTransport()
        provider = build_provider(spec("p", "anthropic"), env={}, transport=transport)
        with self.assertRaises(ProviderNotReady):
            provider.complete([Message("user", "hi")])
        self.assertEqual(transport.calls, [])


class OllamaAdapterTests(unittest.TestCase):
    def test_request_and_response_round_trip(self):
        transport = RecordingTransport(
            {
                "message": {"role": "assistant", "content": " Accra is coastal. "},
                "prompt_eval_count": 11,
                "eval_count": 7,
            }
        )
        provider = build_provider(
            spec("local", "ollama", base_url="http://127.0.0.1:11434/"),
            env={},
            transport=transport,
        )
        completion = provider.complete([Message("user", "Weather?")])
        call = transport.calls[0]
        self.assertEqual(call["url"], "http://127.0.0.1:11434/api/chat")
        self.assertNotIn("Authorization", call["headers"])
        self.assertEqual(call["body"]["model"], "test-model")
        self.assertFalse(call["body"]["stream"])
        self.assertEqual(call["body"]["options"], {"num_predict": 32})
        self.assertEqual(
            call["body"]["messages"], [{"role": "user", "content": "Weather?"}]
        )
        self.assertEqual(completion.text, "Accra is coastal.")
        self.assertEqual(completion.provider_id, "local")
        self.assertEqual(completion.kind, "ollama")
        self.assertEqual(
            completion.usage, {"prompt_eval_count": 11, "eval_count": 7}
        )

    def test_missing_message_field_is_a_clear_error(self):
        transport = RecordingTransport({"unexpected": True})
        provider = build_provider(spec("local", "ollama"), env={}, transport=transport)
        with self.assertRaises(ProviderError) as caught:
            provider.complete([Message("user", "hi")])
        self.assertIn("message.content", str(caught.exception))


class OpenAICompatibleAdapterTests(unittest.TestCase):
    def test_bearer_header_and_choices_parsing(self):
        transport = RecordingTransport(
            {
                "choices": [{"message": {"content": "Use Open-Meteo."}}],
                "usage": {"total_tokens": 12},
            }
        )
        provider = build_provider(
            spec("cloud", "openai", base_url="https://api.example.com/v1"),
            env={"TEST_API_KEY": FAKE_KEY},
            transport=transport,
        )
        completion = provider.complete(
            [Message("system", "Be brief."), Message("user", "Weather API?")]
        )
        call = transport.calls[0]
        self.assertEqual(call["url"], "https://api.example.com/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertEqual(call["body"]["max_tokens"], 32)
        self.assertEqual(len(call["body"]["messages"]), 2)
        self.assertEqual(completion.text, "Use Open-Meteo.")
        self.assertEqual(completion.usage, {"total_tokens": 12})

    def test_content_parts_are_joined(self):
        transport = RecordingTransport(
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "Hello "},
                                {"type": "text", "text": "world"},
                            ]
                        }
                    }
                ]
            }
        )
        provider = build_provider(
            spec("lm", "openai-compatible", api_key_env=""),
            env={},
            transport=transport,
        )
        completion = provider.complete([Message("user", "hi")])
        self.assertEqual(completion.text, "Hello world")
        self.assertNotIn("Authorization", transport.calls[0]["headers"])

    def test_missing_choices_is_a_clear_error(self):
        transport = RecordingTransport({"error": {"message": "nope"}})
        provider = build_provider(
            spec("cloud", "openai"), env={"TEST_API_KEY": "k"}, transport=transport
        )
        with self.assertRaises(ProviderError) as caught:
            provider.complete([Message("user", "hi")])
        self.assertIn("choices", str(caught.exception))

    def test_empty_answer_is_rejected(self):
        transport = RecordingTransport({"choices": [{"message": {"content": "  "}}]})
        provider = build_provider(
            spec("cloud", "openai"), env={"TEST_API_KEY": "k"}, transport=transport
        )
        with self.assertRaises(ProviderError) as caught:
            provider.complete([Message("user", "hi")])
        self.assertIn("empty", str(caught.exception))


class AnthropicAdapterTests(unittest.TestCase):
    def test_system_prompt_is_hoisted_and_key_header_is_used(self):
        transport = RecordingTransport(
            {
                "content": [
                    {"type": "text", "text": "Part one. "},
                    {"type": "text", "text": "Part two."},
                ],
                "usage": {"input_tokens": 5, "output_tokens": 9},
            }
        )
        provider = build_provider(
            spec("claude", "anthropic", base_url="https://api.anthropic.com/v1"),
            env={"TEST_API_KEY": FAKE_KEY},
            transport=transport,
        )
        completion = provider.complete(
            [Message("system", "Be brief."), Message("user", "Weather?")]
        )
        call = transport.calls[0]
        self.assertEqual(call["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(call["headers"]["x-api-key"], FAKE_KEY)
        self.assertEqual(call["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(call["body"]["system"], "Be brief.")
        self.assertEqual(call["body"]["max_tokens"], 32)
        self.assertEqual(
            call["body"]["messages"], [{"role": "user", "content": "Weather?"}]
        )
        self.assertEqual(completion.text, "Part one. Part two.")
        self.assertEqual(completion.usage, {"input_tokens": 5, "output_tokens": 9})

    def test_missing_content_list_is_a_clear_error(self):
        transport = RecordingTransport({"error": {"message": "bad request"}})
        provider = build_provider(
            spec("claude", "anthropic"), env={"TEST_API_KEY": "k"}, transport=transport
        )
        with self.assertRaises(ProviderError) as caught:
            provider.complete([Message("user", "hi")])
        self.assertIn("content list", str(caught.exception))


class RedactionTests(unittest.TestCase):
    def test_redact_hides_the_configured_key(self):
        message = f"HTTP 401 from https://x.test with {FAKE_KEY} rejected"
        self.assertNotIn(FAKE_KEY, redact(message, [FAKE_KEY]))
        self.assertIn("***", redact(message, [FAKE_KEY]))

    def test_short_values_are_left_alone(self):
        self.assertEqual(redact("abc", ["abc"]), "abc")

    def test_error_text_from_a_transport_is_redacted(self):
        transport = RecordingTransport(
            ProviderError(f"HTTP 401 from https://api.test: key {FAKE_KEY} invalid")
        )
        provider = build_provider(
            spec("cloud", "openai"), env={"TEST_API_KEY": FAKE_KEY}, transport=transport
        )
        with self.assertRaises(ProviderError) as caught:
            provider.complete([Message("user", "hi")])
        self.assertNotIn(FAKE_KEY, str(caught.exception))


class ChainTests(unittest.TestCase):
    def _chain(self, *providers):
        return AIChain(list(providers))

    def test_falls_back_to_the_next_provider_after_a_failure(self):
        first = build_provider(
            spec("local", "ollama"),
            env={},
            transport=RecordingTransport(ProviderError("could not reach it")),
        )
        second = build_provider(
            spec("cloud", "openai"),
            env={"TEST_API_KEY": FAKE_KEY},
            transport=RecordingTransport(
                {"choices": [{"message": {"content": "from cloud"}}]}
            ),
        )
        result = self._chain(first, second).complete([Message("user", "hi")])
        self.assertEqual(result.completion.text, "from cloud")
        self.assertEqual(
            [(attempt.provider_id, attempt.status) for attempt in result.attempts],
            [("local", "error"), ("cloud", "ok")],
        )
        self.assertIn("could not reach it", result.attempts[0].error)

    def test_unready_providers_are_skipped_not_called(self):
        transport = RecordingTransport()
        unready = build_provider(spec("cloud", "openai"), env={}, transport=transport)
        ready = build_provider(
            spec("local", "ollama"),
            env={},
            transport=RecordingTransport({"message": {"content": "local answer"}}),
        )
        result = self._chain(unready, ready).complete([Message("user", "hi")])
        self.assertEqual(result.completion.provider_id, "local")
        self.assertEqual(result.attempts[0].status, "skipped")
        self.assertIn("TEST_API_KEY", result.attempts[0].error)
        self.assertEqual(transport.calls, [])

    def test_all_failures_raise_with_every_reason(self):
        chain = self._chain(
            build_provider(
                spec("a", "ollama"),
                env={},
                transport=RecordingTransport(ProviderError("first down")),
            ),
            build_provider(
                spec("b", "ollama"),
                env={},
                transport=RecordingTransport(ProviderError("second down")),
            ),
        )
        with self.assertRaises(AllProvidersFailed) as caught:
            chain.complete([Message("user", "hi")])
        message = str(caught.exception)
        self.assertIn("first down", message)
        self.assertIn("second down", message)
        self.assertEqual(len(caught.exception.attempts), 2)

    def test_explicit_provider_is_tried_before_the_rest_of_the_chain(self):
        other = build_provider(
            spec("a", "ollama"),
            env={},
            transport=RecordingTransport({"message": {"content": "from a"}}),
        )
        chosen = build_provider(
            spec("b", "ollama"),
            env={},
            transport=RecordingTransport(ProviderError("b is down")),
        )
        result = self._chain(other, chosen).complete(
            [Message("user", "hi")], provider_id="b"
        )
        self.assertEqual(result.completion.text, "from a")
        self.assertEqual(
            [(attempt.provider_id, attempt.status) for attempt in result.attempts],
            [("b", "error"), ("a", "ok")],
        )

    def test_explicit_provider_without_fallback_stops_after_it(self):
        second = build_provider(
            spec("b", "ollama"),
            env={},
            transport=RecordingTransport({"message": {"content": "unused"}}),
        )
        first = build_provider(
            spec("a", "ollama"),
            env={},
            transport=RecordingTransport(ProviderError("down")),
        )
        with self.assertRaises(AllProvidersFailed):
            self._chain(first, second).complete(
                [Message("user", "hi")], provider_id="a", fallback=False
            )

    def test_unknown_provider_lists_configured_ids(self):
        chain = self._chain(
            build_provider(
                spec("known", "ollama"), env={}, transport=RecordingTransport()
            )
        )
        with self.assertRaises(UnknownProvider) as caught:
            chain.complete([Message("user", "hi")], provider_id="nope")
        self.assertIn("known", str(caught.exception))

    def test_explicit_unready_provider_fails_loudly(self):
        chain = self._chain(build_provider(spec("cloud", "openai"), env={}))
        with self.assertRaises(ProviderNotReady):
            chain.complete([Message("user", "hi")], provider_id="cloud")

    def test_empty_chain_reports_no_configuration(self):
        with self.assertRaises(AllProvidersFailed) as caught:
            AIChain([]).complete([Message("user", "hi")])
        self.assertIn("no AI providers", str(caught.exception))

    def test_describe_never_contains_the_key(self):
        chain = self._chain(
            build_provider(spec("cloud", "openai"), env={"TEST_API_KEY": FAKE_KEY}),
            build_provider(spec("local", "ollama"), env={}),
        )
        payload = json.dumps(chain.describe())
        self.assertNotIn(FAKE_KEY, payload)
        described = chain.describe()
        self.assertEqual(described["order"], ["cloud", "local"])
        self.assertEqual(described["ready_count"], 2)


    def test_fallback_used_ignores_providers_that_were_never_called(self):
        chain = self._chain(
            build_provider(spec("cloud", "openai"), env={}),
            build_provider(
                spec("local", "ollama"),
                env={},
                transport=RecordingTransport({"message": {"content": "hi"}}),
            ),
        )
        result = chain.complete([Message("user", "hi")])
        self.assertEqual(
            [attempt.status for attempt in result.attempts], ["skipped", "ok"]
        )
        # one provider answered and the other was never asked: no fallback
        self.assertFalse(result.fallback_used)

    def test_fallback_used_is_true_when_a_provider_really_failed(self):
        chain = self._chain(
            build_provider(
                spec("a", "ollama"),
                env={},
                transport=RecordingTransport(ProviderError("down")),
            ),
            build_provider(
                spec("b", "ollama"),
                env={},
                transport=RecordingTransport({"message": {"content": "hi"}}),
            ),
        )
        result = chain.complete([Message("user", "hi")])
        self.assertTrue(result.fallback_used)


class ConfigTests(unittest.TestCase):

    def write_config(self, payload: Any, directory: Path) -> Path:
        path = directory / "ai-providers.local.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_nothing_configured_yields_an_empty_chain(self):
        chain = ai_config.build_chain(env={}, use_default_config=False)
        self.assertEqual(len(chain), 0)
        described = chain.describe()
        self.assertFalse(described["configured"])
        self.assertEqual(described["providers"], [])

    def test_env_only_provider_uses_kind_defaults(self):
        env = {
            "OPEN_TOOL_HUB_AI_PROVIDERS": "local",
            "OPEN_TOOL_HUB_AI_LOCAL_KIND": "ollama",
            "OPEN_TOOL_HUB_AI_LOCAL_MODEL": "phi3:mini",
        }
        chain = ai_config.build_chain(env=env, use_default_config=False)
        self.assertEqual(chain.order(), ["local"])
        described = chain.describe()["providers"][0]
        self.assertEqual(described["kind"], "ollama")
        self.assertEqual(described["base_url"], "http://127.0.0.1:11434")
        self.assertTrue(described["ready"])

    def test_hosted_kind_defaults_point_at_public_documentation_urls(self):
        env = {
            "OPEN_TOOL_HUB_AI_PROVIDERS": "ds,qw,oa",
            "OPEN_TOOL_HUB_AI_DS_KIND": "deepseek",
            "OPEN_TOOL_HUB_AI_DS_MODEL": "deepseek-chat",
            "OPEN_TOOL_HUB_AI_QW_KIND": "qwen",
            "OPEN_TOOL_HUB_AI_QW_MODEL": "qwen-plus",
            "OPEN_TOOL_HUB_AI_OA_KIND": "openai",
            "OPEN_TOOL_HUB_AI_OA_MODEL": "gpt-4o-mini",
        }
        chain = ai_config.build_chain(env=env, use_default_config=False)
        described = {item["id"]: item for item in chain.describe()["providers"]}
        self.assertEqual(chain.order(), ["ds", "qw", "oa"])
        self.assertEqual(described["ds"]["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(described["ds"]["api_key_env"], "DEEPSEEK_API_KEY")
        self.assertEqual(
            described["qw"]["base_url"],
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.assertEqual(described["oa"]["api_key_env"], "OPENAI_API_KEY")
        # Ready only when the key variable is actually set in the same env.
        self.assertFalse(described["oa"]["ready"])

    def test_env_overrides_a_file_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_config(
                {
                    "providers": [
                        {
                            "id": "home",
                            "kind": "openai-compatible",
                            "model": "old-model",
                            "base_url": "http://127.0.0.1:1234/v1",
                        }
                    ]
                },
                Path(tmp),
            )
            chain = ai_config.build_chain(
                env={"OPEN_TOOL_HUB_AI_HOME_MODEL": "new-model"}, path=path
            )
            entry = chain.providers[0].spec
            self.assertEqual(entry.model, "new-model")
            self.assertEqual(entry.base_url, "http://127.0.0.1:1234/v1")

    def test_disabled_provider_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_config(
                {
                    "providers": [
                        {"id": "off", "kind": "ollama", "model": "x", "enabled": False},
                        {"id": "on", "kind": "ollama", "model": "y"},
                    ]
                },
                Path(tmp),
            )
            self.assertEqual(ai_config.build_chain(env={}, path=path).order(), ["on"])

    def test_env_disable_wins_over_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_config(
                {"providers": [{"id": "x", "kind": "ollama", "model": "y"}]},
                Path(tmp),
            )
            chain = ai_config.build_chain(
                env={"OPEN_TOOL_HUB_AI_X_ENABLED": "false"}, path=path
            )
            self.assertEqual(chain.order(), [])

    def test_a_file_may_not_hold_a_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_config(
                {
                    "providers": [
                        {
                            "id": "x",
                            "kind": "openai",
                            "model": "y",
                            "api_key": "secret",
                        }
                    ]
                },
                Path(tmp),
            )
            with self.assertRaises(ConfigError) as caught:
                ai_config.build_chain(env={}, path=path)
            message = str(caught.exception)
            self.assertIn("api_key_env", message)
            # the value that was wrongly stored must not be echoed back
            self.assertNotIn("'secret'", message)
            self.assertNotIn(": secret", message)

    def test_key_is_read_from_the_named_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_config(
                {
                    "providers": [
                        {
                            "id": "cloud",
                            "kind": "openai",
                            "model": "m",
                            "api_key_env": "MY_OWN_VAR",
                        }
                    ]
                },
                Path(tmp),
            )
            chain = ai_config.build_chain(env={"MY_OWN_VAR": FAKE_KEY}, path=path)
            self.assertTrue(chain.providers[0].ready)
            self.assertNotIn(FAKE_KEY, json.dumps(chain.describe()))

    def test_missing_explicit_config_file_is_an_error(self):
        with self.assertRaises(ConfigError) as caught:
            ai_config.config_path({"OPEN_TOOL_HUB_AI_CONFIG": "/nope/missing.json"})
        self.assertIn("missing", str(caught.exception))

    def test_config_problems_are_distinguishable_from_call_failures(self):
        # The proxy answers 503 for one and 400/502 for the other, so the type
        # has to be part of the contract rather than a convention.
        self.assertTrue(issubclass(ConfigError, AIError))
        self.assertFalse(issubclass(ProviderError, ConfigError))
        self.assertFalse(issubclass(AllProvidersFailed, ConfigError))
        for env in (
            {"OPEN_TOOL_HUB_AI_PROVIDERS": "x"},
            {
                "OPEN_TOOL_HUB_AI_PROVIDERS": "x",
                "OPEN_TOOL_HUB_AI_X_KIND": "telepathy",
                "OPEN_TOOL_HUB_AI_X_MODEL": "m",
            },
            {
                "OPEN_TOOL_HUB_AI_PROVIDERS": "x",
                "OPEN_TOOL_HUB_AI_X_KIND": "ollama",
                "OPEN_TOOL_HUB_AI_X_MODEL": "m",
                "OPEN_TOOL_HUB_AI_X_TIMEOUT": "soon",
            },
        ):
            with self.assertRaises(ConfigError):
                ai_config.build_chain(env=env, use_default_config=False)

    def test_duplicate_ids_in_the_providers_variable_are_rejected(self):
        env = {
            "OPEN_TOOL_HUB_AI_PROVIDERS": "a,a",
            "OPEN_TOOL_HUB_AI_A_KIND": "ollama",
            "OPEN_TOOL_HUB_AI_A_MODEL": "m",
        }
        with self.assertRaises(AIError) as caught:
            ai_config.build_chain(env=env, use_default_config=False)
        self.assertIn("more than once", str(caught.exception))

    def test_providers_variable_can_select_and_order_file_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_config(
                {
                    "providers": [
                        {"id": "a", "kind": "ollama", "model": "m"},
                        {"id": "b", "kind": "ollama", "model": "m"},
                    ]
                },
                Path(tmp),
            )
            chain = ai_config.build_chain(
                env={"OPEN_TOOL_HUB_AI_PROVIDERS": "b"}, path=path
            )
            self.assertEqual(chain.order(), ["b"])

    def test_unknown_kind_in_config_is_reported_with_known_kinds(self):
        env = {
            "OPEN_TOOL_HUB_AI_PROVIDERS": "x",
            "OPEN_TOOL_HUB_AI_X_KIND": "telepathy",
            "OPEN_TOOL_HUB_AI_X_MODEL": "m",
        }
        with self.assertRaises(ConfigError) as caught:
            ai_config.build_chain(env=env, use_default_config=False)
        self.assertIn("telepathy", str(caught.exception))
        self.assertIn("ollama", str(caught.exception))

    def test_missing_kind_is_reported(self):
        with self.assertRaises(ConfigError) as caught:
            ai_config.build_chain(
                env={"OPEN_TOOL_HUB_AI_PROVIDERS": "x"}, use_default_config=False
            )
        self.assertIn("KIND", str(caught.exception))

    def test_bad_numbers_are_reported_with_the_variable_name(self):
        env = {
            "OPEN_TOOL_HUB_AI_PROVIDERS": "x",
            "OPEN_TOOL_HUB_AI_X_KIND": "ollama",
            "OPEN_TOOL_HUB_AI_X_MODEL": "m",
            "OPEN_TOOL_HUB_AI_X_TIMEOUT": "soon",
        }
        with self.assertRaises(AIError) as caught:
            ai_config.build_chain(env=env, use_default_config=False)
        self.assertIn("OPEN_TOOL_HUB_AI_X_TIMEOUT", str(caught.exception))


class ConfigFileValidationTests(unittest.TestCase):
    """A typo in a git-ignored file is a ``ConfigError``, never a traceback.

    ``ValueError`` and ``TypeError`` from a JSON value used to escape the config
    layer, where nobody caught them: the CLI printed a traceback and
    ``ai_proxy.py`` died before it bound its port, so one bad ``"timeout"`` took
    the whole static site down. Every malformed value is now a ``ConfigError``,
    which the proxy turns into a ``503`` while it keeps serving pages.
    """

    def build(
        self, entry: dict[str, Any], env: dict[str, str] | None = None
    ) -> AIChain:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ai_config.DEFAULT_CONFIG_NAME
            path.write_text(json.dumps({"providers": [entry]}), encoding="utf-8")
            return ai_config.build_chain(env=env or {}, path=path)

    def assert_config_error(
        self,
        entry: dict[str, Any],
        needle: str,
        env: dict[str, str] | None = None,
    ) -> str:
        with self.assertRaises(ConfigError) as caught:
            self.build(entry, env)
        message = str(caught.exception)
        self.assertIn(needle, message)
        # the message has to say where the value lives
        self.assertIn(ai_config.DEFAULT_CONFIG_NAME, message)
        return message

    def test_a_file_timeout_that_is_not_a_number_names_the_file(self):
        message = self.assert_config_error(
            {"id": "x", "kind": "ollama", "model": "m", "timeout": "soon"},
            "must be a number",
        )
        self.assertIn("'soon'", message)
        self.assertIn("'x'", message)

    def test_empty_values_are_rejected_rather_than_coerced(self):
        for field_name in ("timeout", "max_tokens"):
            for value in (None, True, False):
                with self.subTest(field=field_name, value=value):
                    self.assert_config_error(
                        {"id": "x", "kind": "ollama", "model": "m", field_name: value},
                        "must be",
                    )

    def test_a_file_timeout_must_be_positive(self):
        for value in (0, -5):
            with self.subTest(value=value):
                self.assert_config_error(
                    {"id": "x", "kind": "ollama", "model": "m", "timeout": value},
                    "greater than 0 seconds",
                )

    def test_a_file_max_tokens_must_be_a_positive_whole_number(self):
        for value, needle in ((0, "at least 1"), (-3, "at least 1"), (2.5, "integer")):
            with self.subTest(value=value):
                self.assert_config_error(
                    {"id": "x", "kind": "ollama", "model": "m", "max_tokens": value},
                    needle,
                )

    def test_whole_numbers_in_a_file_are_accepted(self):
        chain = self.build(
            {
                "id": "x",
                "kind": "ollama",
                "model": "m",
                "timeout": 120,
                "max_tokens": 64,
            }
        )
        entry = chain.providers[0].spec
        self.assertEqual(entry.timeout, 120.0)
        self.assertEqual(entry.max_tokens, 64)


    def test_an_environment_timeout_must_be_positive_too(self):
        with self.assertRaises(ConfigError) as caught:
            ai_config.build_chain(
                env={
                    "OPEN_TOOL_HUB_AI_PROVIDERS": "x",
                    "OPEN_TOOL_HUB_AI_X_KIND": "ollama",
                    "OPEN_TOOL_HUB_AI_X_MODEL": "m",
                    "OPEN_TOOL_HUB_AI_X_TIMEOUT": "0",
                },
                use_default_config=False,
            )
        self.assertIn("greater than 0 seconds", str(caught.exception))

    def test_a_duplicate_id_in_a_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ai_config.DEFAULT_CONFIG_NAME
            path.write_text(
                json.dumps(
                    {
                        "providers": [
                            {"id": "x", "kind": "ollama", "model": "first"},
                            {"id": "x", "kind": "ollama", "model": "second"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as caught:
                ai_config.build_chain(env={}, path=path)
            message = str(caught.exception)
            self.assertIn("more than once", message)
            self.assertIn("'x'", message)

    def test_a_file_that_is_not_utf8_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ai_config.DEFAULT_CONFIG_NAME
            path.write_bytes(b'{"providers": [{"id": "x", "label": "caf\xe9"}]}')
            with self.assertRaises(ConfigError) as caught:
                ai_config.build_chain(env={}, path=path)
            self.assertIn("UTF-8", str(caught.exception))

    def test_a_path_that_cannot_be_read_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path, needle in (
                (root, "could not read"),
                (root / "missing.json", "does not exist"),
            ):
                with self.subTest(path=path):
                    with self.assertRaises(ConfigError) as caught:
                        ai_config.build_chain(env={}, path=path)
                    self.assertIn(needle, str(caught.exception))

    def test_a_base_url_must_be_http_or_https(self):
        for value in ("api.example.com/v1", "ftp://example.com/v1", "http://"):
            with self.subTest(value=value):
                self.assert_config_error(
                    {
                        "id": "x",
                        "kind": "openai-compatible",
                        "model": "m",
                        "base_url": value,
                    },
                    "must be an http",
                )

    def test_a_base_url_may_not_smuggle_a_credential(self):
        message = self.assert_config_error(
            {
                "id": "x",
                "kind": "openai-compatible",
                "model": "m",
                "base_url": f"https://user:{FAKE_KEY}@api.example.com/v1",
            },
            "must not embed a credential",
        )
        # the URL is not echoed, so the key cannot reach a log or a browser
        self.assertNotIn(FAKE_KEY, message)

    def test_an_environment_base_url_is_validated_too(self):
        with self.assertRaises(ConfigError) as caught:
            ai_config.build_chain(
                env={
                    "OPEN_TOOL_HUB_AI_PROVIDERS": "x",
                    "OPEN_TOOL_HUB_AI_X_KIND": "ollama",
                    "OPEN_TOOL_HUB_AI_X_MODEL": "m",
                    "OPEN_TOOL_HUB_AI_X_BASE_URL": "127.0.0.1:11434",
                },
                use_default_config=False,
            )
        message = str(caught.exception)
        self.assertIn("must be an http", message)
        # the message names the variable the value came from, not a file
        self.assertIn("OPEN_TOOL_HUB_AI_X_BASE_URL", message)

    def test_an_environment_base_url_may_not_smuggle_a_credential_either(self):
        with self.assertRaises(ConfigError) as caught:
            ai_config.build_chain(
                env={
                    "OPEN_TOOL_HUB_AI_PROVIDERS": "x",
                    "OPEN_TOOL_HUB_AI_X_KIND": "openai-compatible",
                    "OPEN_TOOL_HUB_AI_X_MODEL": "m",
                    "OPEN_TOOL_HUB_AI_X_BASE_URL": (
                        f"https://user:{FAKE_KEY}@api.example.com/v1"
                    ),
                },
                use_default_config=False,
            )
        message = str(caught.exception)
        self.assertIn("must not embed a credential", message)
        self.assertIn("OPEN_TOOL_HUB_AI_X_BASE_URL", message)
        self.assertNotIn(FAKE_KEY, message)


class StubHTTPHandler(BaseHTTPRequestHandler):


    """A loopback server that answers ``POST`` with a canned route table.

    ``routes`` maps a path to ``(status, payload, delay)``; ``payload`` may be
    bytes or a callable that receives the handler (so a route can echo a header
    back, which is how the redaction test proves the key really travelled).
    """

    routes: dict[str, tuple[int, Any, float]] = {}
    requests: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        type(self).requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": json.loads(raw.decode("utf-8") or "{}"),
            }
        )
        status, payload, delay = type(self).routes.get(
            self.path, (404, b'{"error":"no route"}', 0.0)
        )
        if callable(payload):
            payload = payload(self)
        if delay:
            time.sleep(delay)
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:  # the client already gave up (the timeout test)
            pass

    def log_message(self, format: str, *args: Any) -> None:
        pass


class TransportTests(unittest.TestCase):
    """The real ``http_post_json`` socket path, against a loopback stub.

    The adapter tests inject a transport, which leaves the actual client — time
    limits, HTTP error mapping, response parsing — unproven. These tests drive
    it end to end over a real socket on port 0.
    """

    def setUp(self) -> None:
        StubHTTPHandler.routes = {}
        StubHTTPHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), StubHTTPHandler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def route(
        self, path: str, *, status: int = 200, payload: Any = None, delay: float = 0.0
    ) -> str:
        StubHTTPHandler.routes[path] = (status, payload, delay)
        return self.base + path

    @staticmethod
    def closed_port() -> int:
        """A port nobody listens on, so a connection is refused immediately."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    # -- happy path --------------------------------------------------------
    def test_a_json_post_returns_the_parsed_object(self):
        url = self.route("/ok", payload={"message": {"content": "hello"}})
        payload = http_post_json(
            url, {"Content-Type": "application/json"}, {"model": "m"}, 5.0
        )
        self.assertEqual(payload, {"message": {"content": "hello"}})
        seen = StubHTTPHandler.requests[-1]
        self.assertEqual(seen["path"], "/ok")
        self.assertEqual(seen["headers"]["Content-Type"], "application/json")
        self.assertEqual(seen["body"], {"model": "m"})

    def test_a_provider_completes_through_the_real_transport(self):
        self.route(
            "/chat/completions",
            payload={
                "choices": [{"message": {"content": "real answer"}}],
                "usage": {"total_tokens": 7},
            },
        )
        provider = build_provider(
            spec("local", "openai-compatible", base_url=self.base, timeout=5.0),
            env={},
        )
        completion = provider.complete([Message("user", "hi")])
        self.assertEqual(completion.text, "real answer")
        self.assertEqual(completion.usage, {"total_tokens": 7})
        self.assertGreaterEqual(completion.latency_ms, 0)

    # -- failure shapes ----------------------------------------------------
    def test_an_http_error_names_the_status_and_bounds_the_detail(self):
        url = self.route("/fail", status=401, payload={"error": "denied " * 200})
        with self.assertRaises(ProviderError) as caught:
            http_post_json(url, {}, {"model": "m"}, 5.0)
        message = str(caught.exception)
        self.assertIn(f"HTTP 401 from {url}", message)
        self.assertLessEqual(
            len(message), len(f"HTTP 401 from {url}: ") + MAX_ERROR_CHARS
        )

    def test_a_non_json_reply_is_a_clear_error(self):
        url = self.route("/html", payload=b"<html>nope</html>")
        with self.assertRaises(ProviderError) as caught:
            http_post_json(url, {}, {}, 5.0)
        self.assertIn("returned a non-JSON response", str(caught.exception))
        self.assertIn(url, str(caught.exception))

    def test_json_that_is_not_an_object_is_rejected(self):
        url = self.route("/array", payload=b"[1, 2, 3]")
        with self.assertRaises(ProviderError) as caught:
            http_post_json(url, {}, {}, 5.0)
        self.assertIn("returned JSON that is not an object", str(caught.exception))

    def test_a_closed_port_reports_that_the_server_is_unreachable(self):
        url = f"http://127.0.0.1:{self.closed_port()}/v1/chat/completions"
        with self.assertRaises(ProviderError) as caught:
            http_post_json(url, {}, {"model": "m"}, 1.0)
        self.assertIn(f"could not reach {url}", str(caught.exception))

    def test_a_slow_server_times_out_without_hanging(self):
        url = self.route(
            "/slow", payload={"message": {"content": "too late"}}, delay=1.0
        )
        started = time.monotonic()
        with self.assertRaises(ProviderError) as caught:
            http_post_json(url, {}, {}, 0.2)
        elapsed = time.monotonic() - started
        self.assertIn("could not reach", str(caught.exception))
        self.assertLess(elapsed, 0.9, f"the timeout took {elapsed:.2f}s")

    def test_a_slow_provider_is_an_error_not_a_hang(self):
        self.route("/api/chat", payload={"message": {"content": "late"}}, delay=1.0)
        provider = build_provider(
            spec("local", "ollama", base_url=self.base, timeout=0.2), env={}
        )
        started = time.monotonic()
        with self.assertRaises(ProviderError):
            provider.complete([Message("user", "hi")])
        self.assertLess(time.monotonic() - started, 0.9)

    # -- secrets -----------------------------------------------------------
    def test_the_key_is_redacted_before_it_reaches_a_caller(self):
        """The server sees the bearer token; nothing the caller sees contains it."""

        def echo_auth(handler: BaseHTTPRequestHandler) -> bytes:
            return json.dumps(
                {"error": "bad token " + (handler.headers.get("Authorization") or "")}
            ).encode()

        self.route("/chat/completions", status=500, payload=echo_auth)
        chain = AIChain(
            [
                build_provider(
                    spec(
                        "cloud",
                        "openai",
                        base_url=self.base,
                        timeout=5.0,
                        api_key_env="TEST_API_KEY",
                    ),
                    env={"TEST_API_KEY": FAKE_KEY},
                )
            ]
        )
        with self.assertRaises(AllProvidersFailed) as caught:
            chain.complete([Message("user", "hi")])
        visible = str(caught.exception) + json.dumps(
            [attempt.as_dict() for attempt in caught.exception.attempts]
        )
        self.assertIn("HTTP 500", visible)
        self.assertNotIn(FAKE_KEY, visible)
        self.assertIn("***", visible)
        self.assertEqual(
            StubHTTPHandler.requests[-1]["headers"].get("Authorization"),
            f"Bearer {FAKE_KEY}",
            "the stub must have received the key, or this proves nothing",
        )


class ProxyTests(unittest.TestCase):
    """Drive the real request handler over a throwaway loopback server."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name)
        for name, title in (("index.html", "home"), ("ai.html", "ai")):
            (self.site / name).write_text(
                f"<!doctype html><title>{title}</title>", encoding="utf-8"
            )

    def serve(self, chain: Any, **options: Any) -> str:
        builder = chain if callable(chain) else (lambda: chain)
        handler = ai_proxy.make_handler(builder, **options)
        handler.log_message = lambda *args, **kwargs: None  # quiet test output
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(handler, directory=str(self.site)),
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def call(
        self,
        base: str,
        path: str,
        *,
        method: str = "GET",
        body: Any = None,
        raw: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        hdrs = dict(headers or {})
        data = raw
        if data is None and body is not None:
            data = json.dumps(body).encode("utf-8")
        if data is not None and "Content-Type" not in hdrs:
            hdrs["Content-Type"] = "application/json"
        request = urllib.request.Request(
            base + path, data=data, headers=hdrs, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, self.parse(response.read())
        except urllib.error.HTTPError as error:
            return error.code, self.parse(error.read())

    @staticmethod
    def parse(payload: bytes) -> Any:
        if not payload:
            return {}
        try:
            return json.loads(payload.decode("utf-8"))
        except ValueError:
            return payload.decode("utf-8", "replace")

    def ollama(self, *texts: str) -> AIChain:
        transport = RecordingTransport(
            *[{"message": {"content": text}} for text in texts]
        )
        return AIChain(
            [build_provider(spec("local", "ollama"), env={}, transport=transport)]
        )

    # -- status ------------------------------------------------------------
    def test_status_reports_setup_mode_when_nothing_is_configured(self):
        base = self.serve(ai_config.build_chain(env={}, use_default_config=False))
        status, payload = self.call(base, "/api/ai/status")
        self.assertEqual(status, 200)
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["mode"], "setup")
        self.assertEqual(payload["docs"], ai_proxy.DOCS_PATH)
        self.assertEqual(payload["page"], "ai.html")
        self.assertTrue((self.site / payload["page"]).is_file())

    def test_status_lists_providers_without_the_key(self):
        chain = AIChain(
            [
                build_provider(
                    spec("cloud", "openai"), env={"TEST_API_KEY": FAKE_KEY}
                ),
                build_provider(spec("local", "ollama"), env={}),
            ]
        )
        base = self.serve(chain)
        status, payload = self.call(base, "/api/ai/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "local-ai")
        self.assertEqual(payload["order"], ["cloud", "local"])
        self.assertEqual(payload["ready_count"], 2)
        self.assertNotIn(FAKE_KEY, json.dumps(payload))

    def test_status_surfaces_a_configuration_error_instead_of_crashing(self):
        def broken() -> AIChain:
            raise AIError("bad config: OPEN_TOOL_HUB_AI_X_KIND is unset")

        base = self.serve(broken)
        status, payload = self.call(base, "/api/ai/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "setup")
        self.assertIn("KIND", payload["error"])

    # -- static files ------------------------------------------------------
    def test_static_pages_are_served_alongside_the_api(self):
        base = self.serve(self.ollama("unused"))
        status, page = self.call(base, "/ai.html")
        self.assertEqual(status, 200)
        self.assertIn("ai", page)

    # -- chat --------------------------------------------------------------
    def test_chat_returns_the_answer_and_the_attempt_trail(self):
        base = self.serve(self.ollama("Three weather APIs: Open-Meteo, ..."))
        status, payload = self.call(
            base, "/api/ai/chat", method="POST", body={"prompt": "weather APIs?"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "local-ai")
        self.assertEqual(
            payload["completion"]["text"], "Three weather APIs: Open-Meteo, ..."
        )
        self.assertEqual(payload["completion"]["provider_id"], "local")
        self.assertEqual(payload["attempts"][0]["status"], "ok")

    def test_chat_passes_the_system_prompt_through(self):
        transport = RecordingTransport({"message": {"content": "ok"}})
        chain = AIChain(
            [build_provider(spec("local", "ollama"), env={}, transport=transport)]
        )
        base = self.serve(chain)
        status, _ = self.call(
            base,
            "/api/ai/chat",
            method="POST",
            body={"prompt": "hi", "system": "Be terse."},
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            transport.calls[0]["body"]["messages"],
            [
                {"role": "system", "content": "Be terse."},
                {"role": "user", "content": "hi"},
            ],
        )

    def test_chat_uses_an_explicit_provider(self):
        chain = AIChain(
            [
                build_provider(
                    spec("a", "ollama"),
                    env={},
                    transport=RecordingTransport({"message": {"content": "from a"}}),
                ),
                build_provider(
                    spec("b", "ollama"),
                    env={},
                    transport=RecordingTransport({"message": {"content": "from b"}}),
                ),
            ]
        )
        base = self.serve(chain)
        status, payload = self.call(
            base, "/api/ai/chat", method="POST", body={"prompt": "hi", "provider": "b"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["completion"]["text"], "from b")

    def test_unknown_provider_is_a_400(self):
        base = self.serve(self.ollama("unused"))
        status, payload = self.call(
            base, "/api/ai/chat", method="POST", body={"prompt": "hi", "provider": "no"}
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "unknown provider")
        self.assertIn("local", payload["detail"])

    def test_not_ready_provider_is_a_409(self):
        chain = AIChain([build_provider(spec("cloud", "openai"), env={})])
        base = self.serve(chain)
        status, payload = self.call(
            base,
            "/api/ai/chat",
            method="POST",
            body={"prompt": "hi", "provider": "cloud"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "provider not ready")
        self.assertIn("TEST_API_KEY", payload["detail"])

    def test_every_provider_failing_is_a_502_with_reasons(self):
        chain = AIChain(
            [
                build_provider(
                    spec("a", "ollama"),
                    env={},
                    transport=RecordingTransport(ProviderError("connection refused")),
                )
            ]
        )
        base = self.serve(chain)
        status, payload = self.call(
            base, "/api/ai/chat", method="POST", body={"prompt": "hi"}
        )
        self.assertEqual(status, 502)
        self.assertEqual(payload["error"], "no provider answered")
        self.assertIn("connection refused", payload["attempts"][0]["error"])

    def test_a_broken_config_is_a_503_and_leaves_the_site_up(self):
        def broken() -> AIChain:
            raise ConfigError("provider 'local' has unknown kind 'nope'")

        base = self.serve(broken)
        status, payload = self.call(
            base, "/api/ai/chat", method="POST", body={"prompt": "hi"}
        )
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"], "ai is misconfigured")
        self.assertIn("unknown kind", payload["detail"])
        self.assertEqual(payload["docs"], DOCS)

        # the misconfiguration is the operator's problem, not the page's
        status, page = self.call(base, "/ai.html")
        self.assertEqual(status, 200)
        self.assertIn("ai", page)
        status, described = self.call(base, "/api/ai/status")
        self.assertEqual(status, 200)
        self.assertEqual(described["mode"], "setup")
        self.assertIn("unknown kind", described["error"])

    def test_a_broken_config_is_never_reported_as_a_client_error(self):
        def broken() -> AIChain:
            raise ConfigError("OPEN_TOOL_HUB_AI_X_TIMEOUT must be a number")

        base = self.serve(broken)
        status, _ = self.call(
            base, "/api/ai/chat", method="POST", body={"prompt": "hi"}
        )
        self.assertNotEqual(status, 400)
        self.assertEqual(status, 503)

    def test_a_malformed_config_file_is_a_503_and_the_site_stays_up(self):
        """The real path: a typo in the JSON file, served by the real config layer."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ai_config.DEFAULT_CONFIG_NAME
            path.write_text(
                json.dumps(
                    {
                        "providers": [
                            {
                                "id": "local",
                                "kind": "ollama",
                                "model": "m",
                                "timeout": "soon",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            base = self.serve(partial(ai_config.build_chain, env={}, path=path))

            status, page = self.call(base, "/ai.html")
            self.assertEqual(status, 200)
            self.assertIn("ai", page)

            status, described = self.call(base, "/api/ai/status")
            self.assertEqual(status, 200)
            self.assertEqual(described["mode"], "setup")
            self.assertIn("must be a number", described["error"])

            status, payload = self.call(
                base, "/api/ai/chat", method="POST", body={"prompt": "hi"}
            )
            self.assertEqual(status, 503, payload)
            self.assertEqual(payload["error"], "ai is misconfigured")
            self.assertIn("must be a number", payload["detail"])
            self.assertEqual(payload["docs"], DOCS)

    def test_a_failing_transport_never_leaks_the_key(self):
        chain = AIChain(
            [
                build_provider(
                    spec("cloud", "openai"),
                    env={"TEST_API_KEY": FAKE_KEY},
                    transport=RecordingTransport(
                        ProviderError(f"401 unauthorized for {FAKE_KEY}")
                    ),
                )
            ]
        )
        base = self.serve(chain)
        status, payload = self.call(
            base, "/api/ai/chat", method="POST", body={"prompt": "hi"}
        )
        self.assertEqual(status, 502)
        self.assertNotIn(FAKE_KEY, json.dumps(payload))

    # -- request validation ------------------------------------------------
    def test_chat_requires_a_json_content_type(self):
        base = self.serve(self.ollama("unused"))
        status, payload = self.call(
            base,
            "/api/ai/chat",
            method="POST",
            raw=b'{"prompt": "hi"}',
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(status, 415)
        self.assertEqual(payload["error"], "unsupported media type")

    def test_chat_rejects_a_form_post(self):
        base = self.serve(self.ollama("unused"))
        status, _ = self.call(
            base,
            "/api/ai/chat",
            method="POST",
            raw=b"prompt=hi",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 415)

    def test_chat_rejects_invalid_json(self):
        base = self.serve(self.ollama("unused"))
        status, payload = self.call(base, "/api/ai/chat", method="POST", raw=b"{nope")
        self.assertEqual(status, 400)
        self.assertIn("valid JSON", payload["error"])

    def test_chat_rejects_a_non_object_body(self):
        base = self.serve(self.ollama("unused"))
        status, payload = self.call(
            base, "/api/ai/chat", method="POST", raw=b'["hi"]'
        )
        self.assertEqual(status, 400)
        self.assertIn("JSON object", payload["error"])

    def test_chat_rejects_an_empty_body(self):
        base = self.serve(self.ollama("unused"))
        status, payload = self.call(
            base,
            "/api/ai/chat",
            method="POST",
            raw=b"",
            headers={"Content-Type": "application/json", "Content-Length": "0"},
        )
        self.assertEqual(status, 400)
        self.assertIn("empty", payload["error"])

    def test_chat_rejects_a_missing_or_blank_prompt(self):
        base = self.serve(self.ollama("unused"))
        for body in ({}, {"prompt": ""}, {"prompt": "   "}, {"prompt": 7}):
            with self.subTest(body=body):
                status, payload = self.call(
                    base, "/api/ai/chat", method="POST", body=body
                )
                self.assertEqual(status, 400)
                self.assertIn("prompt", payload["error"])

    def test_chat_rejects_an_overlong_prompt(self):
        base = self.serve(self.ollama("unused"))
        status, payload = self.call(
            base,
            "/api/ai/chat",
            method="POST",
            body={"prompt": "x" * (ai_proxy.MAX_PROMPT_CHARS + 1)},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "prompt is too long")

    def test_chat_rejects_an_oversize_body(self):
        base = self.serve(self.ollama("unused"))
        status, payload = self.call(
            base,
            "/api/ai/chat",
            method="POST",
            raw=b"x" * (ai_proxy.MAX_BODY_BYTES + 16),
        )
        self.assertEqual(status, 413)
        self.assertEqual(payload["error"], "request body too large")

    def test_chat_rejects_a_non_string_provider_or_system(self):
        base = self.serve(self.ollama("unused"))
        for body in (
            {"prompt": "hi", "provider": 1},
            {"prompt": "hi", "system": ["x"]},
        ):
            with self.subTest(body=body):
                status, _ = self.call(base, "/api/ai/chat", method="POST", body=body)
                self.assertEqual(status, 400)

    def test_get_on_the_chat_route_is_405(self):
        base = self.serve(self.ollama("unused"))
        status, payload = self.call(base, "/api/ai/chat")
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"], "method not allowed")

    def test_unknown_api_routes_are_404(self):
        base = self.serve(self.ollama("unused"))
        for path in ("/api/ai/nothing", "/api/ai/status/extra"):
            with self.subTest(path=path):
                status, payload = self.call(base, path)
                self.assertEqual(status, 404)
                self.assertEqual(payload["error"], "unknown AI route")

    def test_post_outside_the_api_prefix_is_405(self):
        base = self.serve(self.ollama("unused"))
        status, payload = self.call(base, "/ai.html", method="POST", body={"a": 1})
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"], "unknown route")

    # -- origin guard ------------------------------------------------------
    def test_a_foreign_origin_is_rejected_on_both_routes(self):
        base = self.serve(self.ollama("unused"))
        for path, method, body in (
            ("/api/ai/status", "GET", None),
            ("/api/ai/chat", "POST", {"prompt": "steal"}),
        ):
            with self.subTest(path=path):
                status, payload = self.call(
                    base,
                    path,
                    method=method,
                    body=body,
                    headers={"Origin": "http://evil.example"},
                )
                self.assertEqual(status, 403)
                self.assertEqual(payload["error"], "origin not allowed")

    def test_a_null_origin_is_rejected(self):
        base = self.serve(self.ollama("unused"))
        status, _ = self.call(base, "/api/ai/status", headers={"Origin": "null"})
        self.assertEqual(status, 403)

    def test_its_own_loopback_origin_is_allowed(self):
        base = self.serve(self.ollama("unused"))
        status, payload = self.call(base, "/api/ai/status", headers={"Origin": base})
        self.assertEqual(status, 200)
        self.assertEqual(payload["page"], "ai.html")

    def test_allow_remote_trusts_the_host_it_was_reached_on(self):
        base = self.serve(self.ollama("unused"), allow_remote=True)
        status, _ = self.call(
            base,
            "/api/ai/status",
            headers={"Host": "demo.test:8080", "Origin": "http://demo.test:8080"},
        )
        self.assertEqual(status, 200)
        status, _ = self.call(
            base,
            "/api/ai/status",
            headers={"Host": "demo.test:8080", "Origin": "http://other.test:8080"},
        )
        self.assertEqual(status, 403)


class CliTests(unittest.TestCase):
    def run_cli(self, argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        """Run the CLI with a hermetic env: one empty, explicit config file."""
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ai_config.DEFAULT_CONFIG_NAME
            path.write_text(json.dumps({"providers": []}), encoding="utf-8")
            full = dict(env)
            full["OPEN_TOOL_HUB_AI_CONFIG"] = str(path)
            with mock.patch.dict(os.environ, full, clear=True):
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = ai_chat.main(argv)
        return code, out.getvalue(), err.getvalue()


    def test_list_without_configuration_exits_zero_and_points_at_the_docs(self):
        code, out, err = self.run_cli(["--list"], {})
        self.assertEqual(code, 0)
        self.assertIn("Configured providers", out)
        self.assertIn(DOCS, out)
        self.assertEqual(err, "")

    def test_list_json_is_machine_readable(self):
        code, out, _ = self.run_cli(["--list", "--json"], {})
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["ready_count"], 0)

    def test_list_shows_an_unready_provider_without_its_key(self):
        env = {
            "OPEN_TOOL_HUB_AI_PROVIDERS": "cloud",
            "OPEN_TOOL_HUB_AI_CLOUD_KIND": "openai",
            "OPEN_TOOL_HUB_AI_CLOUD_MODEL": "gpt-4o-mini",
        }
        code, out, _ = self.run_cli(["--list"], env)
        self.assertEqual(code, 0)
        self.assertIn("cloud", out)
        self.assertIn("OPENAI_API_KEY", out)
        self.assertIn("No provider is ready", out)

    def test_a_configured_key_flips_readiness_without_being_printed(self):
        env = {
            "OPEN_TOOL_HUB_AI_PROVIDERS": "cloud",
            "OPEN_TOOL_HUB_AI_CLOUD_KIND": "openai",
            "OPEN_TOOL_HUB_AI_CLOUD_MODEL": "gpt-4o-mini",
            "OPENAI_API_KEY": FAKE_KEY,
        }
        code, out, _ = self.run_cli(["--list", "--json"], env)
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["ready_count"], 1)
        self.assertNotIn(FAKE_KEY, out)

    def test_prompt_without_configuration_exits_three(self):
        code, _, err = self.run_cli(["hello"], {})
        self.assertEqual(code, 3)
        self.assertIn("no AI providers are configured", err)
        self.assertIn(DOCS, err)

    def test_prompt_with_only_unready_providers_exits_three(self):
        env = {
            "OPEN_TOOL_HUB_AI_PROVIDERS": "cloud",
            "OPEN_TOOL_HUB_AI_CLOUD_KIND": "openai",
            "OPEN_TOOL_HUB_AI_CLOUD_MODEL": "gpt-4o-mini",
        }
        code, _, err = self.run_cli(["hello"], env)
        self.assertEqual(code, 3)
        self.assertIn("none is ready", err)

    def test_check_without_configuration_exits_three(self):
        code, _, err = self.run_cli(["--check"], {})
        self.assertEqual(code, 3)
        self.assertIn("no AI providers are configured", err)

    def test_no_fallback_without_a_provider_is_a_usage_error(self):
        # Before this group existed the command raised a bare AIError and left
        # Python to print a traceback with exit 1, which is not one of the
        # documented codes.
        code, out, err = self.run_cli(["--no-fallback", "--check"], {})
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("--no-fallback needs --provider", err)
        self.assertNotIn("Traceback", err)

    def test_no_fallback_without_a_provider_is_a_usage_error_for_a_prompt_too(self):
        code, _, err = self.run_cli(["--no-fallback", "hello"], {})
        self.assertEqual(code, 2)
        self.assertIn("--provider", err)

    def test_check_json_does_not_claim_a_fallback_that_never_happened(self):
        transport = RecordingTransport({"message": {"content": "ready"}})
        chain = AIChain(
            [
                build_provider(spec("local", "ollama"), env={}, transport=transport),
                # configured but unready: recorded as "skipped", never called
                build_provider(spec("cloud", "openai"), env={}),
            ]
        )
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ai_chat, "build_chain", return_value=chain):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = ai_chat.main(["--check", "--json"])
        self.assertEqual(code, 0, err.getvalue())
        payload = json.loads(out.getvalue())
        self.assertEqual(
            [attempt["status"] for attempt in payload["attempts"]], ["skipped", "ok"]
        )
        self.assertFalse(payload["fallback_used"])

    def run_check_cli(
        self, *payloads: Any, argv: list[str] | None = None
    ) -> tuple[int, str, str, RecordingTransport]:
        """Run ``--check`` against an injected Ollama transport (no network)."""
        transport = RecordingTransport(*payloads)
        provider = OllamaProvider(
            spec("local", "ollama", base_url="http://127.0.0.1:11434"),
            transport=transport,
        )
        chain = AIChain([provider])
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ai_chat, "build_chain", return_value=chain):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = ai_chat.main(argv or ["--check"])
        return code, out.getvalue(), err.getvalue(), transport

    def test_check_makes_one_real_request_and_reports_the_answer(self):
        code, out, err, transport = self.run_check_cli(
            {"message": {"role": "assistant", "content": "Ready."}}
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("OK: local / test-model", out)
        self.assertIn("Ready.", out)
        self.assertEqual(len(transport.calls), 1)
        self.assertTrue(transport.calls[0]["url"].endswith("/api/chat"))
        self.assertEqual(
            transport.calls[0]["body"]["messages"][0]["content"], ai_chat.CHECK_PROMPT
        )

    def test_check_json_is_machine_readable(self):
        code, out, _, _ = self.run_check_cli(
            {"message": {"role": "assistant", "content": "ready"}},
            argv=["--check", "--json"],
        )
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["provider"], "local")
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["reply"], "ready")
        self.assertFalse(payload["fallback_used"])
        self.assertIsInstance(payload["latency_ms"], int)
        self.assertEqual(len(payload["attempts"]), 1)
        self.assertEqual(payload["attempts"][0]["provider_id"], "local")
        self.assertEqual(payload["attempts"][0]["status"], "ok")

    def test_check_exits_four_when_the_only_provider_fails(self):
        code, out, err, _ = self.run_check_cli(ProviderError("boom"))
        self.assertEqual(code, 4)
        self.assertEqual(out, "")
        self.assertIn("No AI provider answered", err)

    def test_unknown_provider_exits_two(self):
        env = {
            "OPEN_TOOL_HUB_AI_PROVIDERS": "local",
            "OPEN_TOOL_HUB_AI_LOCAL_KIND": "ollama",
            "OPEN_TOOL_HUB_AI_LOCAL_MODEL": "phi3:mini",
        }
        code, _, err = self.run_cli(["--provider", "nope", "hello"], env)
        self.assertEqual(code, 2)
        self.assertIn("unknown provider", err)

    def test_a_broken_config_exits_two_with_a_readable_message(self):
        env = {"OPEN_TOOL_HUB_AI_PROVIDERS": "x"}
        code, _, err = self.run_cli(["--list"], env)
        self.assertEqual(code, 2)
        self.assertIn("KIND", err)

    def test_the_helper_module_refuses_a_remote_bind_without_the_flag(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                ai_proxy.main(["--host", "0.0.0.0", "--no-stage"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("--allow-remote", err.getvalue())

    def test_provider_lines_explain_an_empty_chain(self):
        lines = ai_proxy.provider_lines({"providers": [], "ready_count": 0})
        text = "\n".join(lines)
        self.assertIn("No AI providers are configured", text)
        self.assertIn("static site works", text)

    def test_provider_lines_flag_a_chain_where_nothing_is_ready(self):
        described = {
            "providers": [
                {
                    "id": "cloud",
                    "kind": "openai",
                    "model": "gpt-4o-mini",
                    "ready": False,
                    "reason": "missing API key in $OPENAI_API_KEY",
                }
            ],
            "ready_count": 0,
        }
        text = "\n".join(ai_proxy.provider_lines(described))
        self.assertIn("not ready", text)
        self.assertIn("OPENAI_API_KEY", text)
        self.assertIn(DOCS, text)


class HygieneTests(unittest.TestCase):
    """The AI layer stays optional, stdlib-only, and free of stored secrets."""

    AI_SCRIPTS = ("ai_providers.py", "ai_config.py", "ai_chat.py", "ai_proxy.py")
    LOCAL_MODULES = {"ai_providers", "ai_config", "ai_chat", "ai_proxy", "config", "build_site"}

    def test_the_page_ships_with_its_module(self):
        self.assertTrue((ROOT / "site" / "ai.html").is_file())
        self.assertTrue((ROOT / "site" / "js" / "ai.js").is_file())

    def test_the_ai_scripts_import_only_stdlib_and_their_neighbours(self):
        import ast

        for name in self.AI_SCRIPTS:
            source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=name)
            roots: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    roots.add(node.module.split(".")[0])
            unexpected = roots - set(sys.stdlib_module_names) - self.LOCAL_MODULES
            self.assertEqual(unexpected, set(), f"{name} imports {sorted(unexpected)}")

    def test_no_script_carries_a_literal_key(self):
        import re

        pattern = re.compile(r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
        for name in self.AI_SCRIPTS:
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIsNone(pattern.search(text), f"{name} looks like it holds a key")

    def test_the_example_config_is_inert_and_keyless(self):
        example = ROOT / "ai-providers.example.json"
        chain = ai_config.build_chain(
            env={}, path=example, use_default_config=False
        )
        self.assertEqual(chain.providers, [])
        payload = json.loads(example.read_text(encoding="utf-8"))
        self.assertTrue(payload["providers"])
        for provider in payload["providers"]:
            self.assertFalse(provider["enabled"])
            self.assertNotIn("api_key", provider)
            for field_name in provider:
                self.assertNotIn(
                    field_name.strip().lower(), ai_config.SECRET_FIELDS, provider["id"]
                )

    def test_the_env_example_documents_the_layer_without_a_value(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("OPEN_TOOL_HUB_AI_PROVIDERS", text)
        self.assertIn("docs/local-ai.md", text)
        self.assertIn("\n# OPENAI_API_KEY=\n", text)

    def test_the_proxy_drops_a_client_that_stalls_mid_request(self):
        # Without a socket timeout a half-sent body holds a worker thread for
        # as long as the client keeps the connection open.
        self.assertIsInstance(ai_proxy.CLIENT_TIMEOUT_SECONDS, int)
        self.assertGreater(ai_proxy.CLIENT_TIMEOUT_SECONDS, 0)
        self.assertEqual(
            ai_proxy.AIRequestHandler.timeout, ai_proxy.CLIENT_TIMEOUT_SECONDS
        )

    def test_config_error_is_part_of_the_public_surface(self):
        self.assertIn("ConfigError", ai_providers.__all__)
        self.assertIn("ConfigError", dir(ai_providers))

