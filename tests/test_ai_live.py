"""Opt-in live validation against a real, locally configured AI provider.

The hermetic suite in ``tests/test_ai.py`` never touches a model. This module is
the opposite: it proves that a real provider answers over the same code paths the
CLI and the proxy use, and that a broken one fails cleanly. It is skipped unless
``OPEN_TOOL_HUB_AI_LIVE=1`` is set, so a fresh clone and GitHub Actions stay
offline:

    OPEN_TOOL_HUB_AI_LIVE=1 python3 -m unittest tests.test_ai_live -v
    make ai-live

A skip is not a pass: it means no model was asked. Configure a provider first,
as described in ``docs/local-ai.md``. Nothing here needs a hosted key: a local
Ollama server is enough, and no prompt is written to disk by these tests.
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
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ai_chat  # noqa: E402
import ai_config  # noqa: E402
import ai_proxy  # noqa: E402
from ai_providers import (  # noqa: E402
    AIChain,
    AllProvidersFailed,
    Message,
    ProviderNotReady,
)

LIVE = (os.environ.get("OPEN_TOOL_HUB_AI_LIVE") or "").strip().lower() not in {
    "",
    "0",
    "false",
    "no",
}
SKIP_REASON = (
    "live provider check skipped: set OPEN_TOOL_HUB_AI_LIVE=1 with a provider "
    "configured (see docs/local-ai.md)"
)

#: Generous enough for a small model on a laptop; a hung provider still fails.
CHECK_TIMEOUT = 240.0


def live_chain() -> AIChain:
    """The chain a developer actually configured: env vars plus the local file."""
    try:
        chain = ai_config.build_chain()
    except Exception as exc:  # a broken local config should skip, not error out
        raise unittest.SkipTest(f"no usable AI configuration: {exc}") from None
    if not chain.ready():
        reasons = "; ".join(
            f"{provider.spec.id}: {provider.readiness()[1]}" for provider in chain
        )
        raise unittest.SkipTest(f"no AI provider is ready ({reasons or 'none set'})")
    return chain


def provider_env(base_url: str, *, timeout: float) -> dict[str, str]:
    """Environment for one probe provider, without touching the real environment."""
    provider = live_chain().ready()[0]
    return {
        "OPEN_TOOL_HUB_AI_PROVIDERS": "probe",
        "OPEN_TOOL_HUB_AI_PROBE_KIND": provider.spec.kind,
        "OPEN_TOOL_HUB_AI_PROBE_MODEL": provider.spec.model,
        "OPEN_TOOL_HUB_AI_PROBE_BASE_URL": base_url,
        "OPEN_TOOL_HUB_AI_PROBE_TIMEOUT": str(timeout),
    }


def free_port() -> int:
    """A loopback port nobody is listening on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class LiveProviderTests(unittest.TestCase):
    """Ask a real model, then prove the failure paths stay clean."""

    @classmethod
    def setUpClass(cls) -> None:
        if not LIVE:
            raise unittest.SkipTest(SKIP_REASON)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name)
        (self.site / "ai.html").write_text(
            "<!doctype html><title>ai</title>", encoding="utf-8"
        )

    # -- the provider answers ---------------------------------------------
    def test_the_configured_provider_reports_itself_ready(self):
        described = live_chain().describe()
        self.assertTrue(described["configured"])
        self.assertGreaterEqual(described["ready_count"], 1)
        for provider in described["providers"]:
            self.assertNotIn("api_key", provider, "status must never carry a key")
            self.assertTrue(provider["ready"] or provider["reason"])

    def test_the_cli_check_round_trip_is_machine_readable(self):
        buffer = io.StringIO()
        started = time.monotonic()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = ai_chat.main(["--check", "--json"])
        elapsed = time.monotonic() - started
        self.assertEqual(code, 0, buffer.getvalue())
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["model"])
        self.assertEqual(payload["provider"], payload["attempts"][0]["provider_id"])
        self.assertEqual(payload["attempts"][0]["status"], "ok")
        self.assertTrue(payload["reply"].strip())
        self.assertLess(elapsed, CHECK_TIMEOUT)

    def test_a_real_prompt_returns_text_from_the_model(self):
        started = time.monotonic()
        result = live_chain().complete(
            [Message("user", "Reply with the single word: ready")]
        )
        completion = result.completion
        self.assertTrue(completion.text.strip())
        self.assertEqual(completion.provider_id, result.attempts[-1].provider_id)
        self.assertEqual(result.attempts[-1].status, "ok")
        self.assertGreaterEqual(completion.latency_ms, 0)
        self.assertLess(time.monotonic() - started, CHECK_TIMEOUT)

    # -- the proxy serves the same answer ---------------------------------
    def serve(self, builder: Any = None) -> tuple[str, type]:
        handler = ai_proxy.make_handler(builder or live_chain)
        handler.log_message = lambda *args, **kwargs: None
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(handler, directory=str(self.site))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}", handler

    def call(
        self,
        base: str,
        path: str,
        *,
        method: str = "GET",
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        data = json.dumps(body).encode() if body is not None else None
        hdrs = dict(headers or {})
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            base + path, data=data, headers=hdrs, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def test_the_proxy_status_and_chat_use_the_real_provider(self):
        base, _ = self.serve()
        status, described = self.call(base, "/api/ai/status")
        self.assertEqual(status, 200)
        self.assertEqual(described["mode"], "local-ai")
        self.assertGreaterEqual(described["ready_count"], 1)

        status, payload = self.call(
            base,
            "/api/ai/chat",
            method="POST",
            body={"prompt": "Reply with the single word: ready"},
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["mode"], "local-ai")
        self.assertTrue(payload["completion"]["text"].strip())
        self.assertEqual(payload["attempts"][0]["status"], "ok")

    def test_the_proxy_still_refuses_a_foreign_origin(self):
        base, _ = self.serve()
        status, payload = self.call(
            base,
            "/api/ai/chat",
            method="POST",
            body={"prompt": "hello"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "origin not allowed")

    def test_the_prompt_is_never_echoed_into_the_access_log(self):
        base, handler = self.serve()
        logged: list[str] = []
        # log_message reaches the instance first, so parts[0] is the handler.
        handler.log_message = lambda *parts: logged.append(
            " ".join(str(part) for part in parts[1:])
        )
        prompt = "canary-prompt-8f3a2b"
        self.call(base, "/api/ai/chat", method="POST", body={"prompt": prompt})
        self.assertTrue(logged, "the proxy should log the request line")
        self.assertNotIn(prompt, "\n".join(logged))

    # -- failure and timeout stay clean -----------------------------------
    def test_an_unreachable_provider_fails_with_a_readable_reason(self):
        env = provider_env(f"http://127.0.0.1:{free_port()}", timeout=2.0)
        chain = ai_config.build_chain(env=env, use_default_config=False)
        with self.assertRaises(AllProvidersFailed) as caught:
            chain.complete([Message("user", "hello")])
        reasons = json.dumps(
            [attempt.as_dict() for attempt in caught.exception.attempts]
        )
        self.assertIn("could not reach", reasons)

    def test_a_timeout_against_a_real_provider_is_reported_not_hung(self):
        base_url = live_chain().ready()[0].spec.base_url
        probe = ai_config.build_chain(
            env=provider_env(base_url, timeout=0.001), use_default_config=False
        )
        started = time.monotonic()
        with self.assertRaises(AllProvidersFailed) as caught:
            probe.complete([Message("user", "hello")])
        self.assertLess(time.monotonic() - started, 30.0)
        self.assertIn("could not reach", str(caught.exception))

    def test_a_missing_model_is_reported_before_any_request(self):
        base_url = live_chain().ready()[0].spec.base_url
        env = provider_env(base_url, timeout=5.0)
        env["OPEN_TOOL_HUB_AI_PROBE_MODEL"] = ""
        chain = ai_config.build_chain(env=env, use_default_config=False)
        provider = chain.by_id("probe")
        ready, reason = provider.readiness()
        self.assertFalse(ready)
        self.assertEqual(reason, "no model configured")
        with self.assertRaises(ProviderNotReady):
            provider.complete([Message("user", "hello")])

    def test_a_dead_provider_returns_json_502_from_the_proxy(self):
        env = provider_env(f"http://127.0.0.1:{free_port()}", timeout=2.0)
        base, _ = self.serve(
            lambda: ai_config.build_chain(env=env, use_default_config=False)
        )
        status, payload = self.call(
            base, "/api/ai/chat", method="POST", body={"prompt": "hello"}
        )
        self.assertEqual(status, 502, payload)
        self.assertEqual(payload["error"], "no provider answered")
        self.assertIn("could not reach", json.dumps(payload["attempts"]))

    def test_the_static_page_is_unaffected_by_the_provider(self):
        base, _ = self.serve()
        with urllib.request.urlopen(base + "/ai.html", timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"title", response.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)

