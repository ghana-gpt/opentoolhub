"""Serve the static site locally with an optional AI endpoint alongside it.

``python3 scripts/ai_proxy.py`` serves ``site/`` exactly like
``build_site.py --serve`` and adds two JSON endpoints:

``GET  /api/ai/status``  which providers are configured and whether they are ready
``POST /api/ai/chat``    ``{"prompt": "...", "provider": "optional-id"}``

Why a proxy and not a browser-side call: a browser-side call would have to ship
the key to the visitor. Here the key stays in this process, on this machine.
The published GitHub Pages site has no backend and never calls these routes; if
they are missing, ``site/js/ai.js`` renders setup instructions instead.

Safety defaults:

- binds ``127.0.0.1`` and refuses other hosts unless ``--allow-remote`` is given;
- ``POST`` requires ``Content-Type: application/json`` and a bounded body, so a
  cross-site form post cannot reach a provider;
- ``Origin`` must be this loopback origin (or, with ``--allow-remote``, the
  request's own host);
- a client that stalls mid-request is dropped after ``CLIENT_TIMEOUT_SECONDS``
  instead of pinning a worker thread;
- request bodies are never logged and keys never leave the process.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from http.server import ThreadingHTTPServer
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlsplit

import config
from ai_config import build_chain
from ai_providers import (
    AIChain,
    AIError,
    AllProvidersFailed,
    ConfigError,
    Message,
    ProviderNotReady,
    UnknownProvider,
)
from build_site import NoCacheHandler, stage

API_PREFIX = "/api/ai/"
STATUS_PATH = "/api/ai/status"
CHAT_PATH = "/api/ai/chat"
DOCS_PATH = "docs/local-ai.md"
MAX_BODY_BYTES = 64 * 1024
MAX_PROMPT_CHARS = 4000
#: Seconds a client may stall mid-request before the connection is dropped.
#: Without it a half-sent body holds a worker thread forever; the proxy is a
#: development server, so a short timeout costs nothing real.
CLIENT_TIMEOUT_SECONDS = 30
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
LOOPBACK_BIND = "127.0.0.1"
DEFAULT_PORT = config.AI_PORT

ChainBuilder = Callable[[], AIChain]


def is_loopback(host: str) -> bool:
    return host.strip().lower() in LOOPBACK_HOSTS


class AIRequestHandler(NoCacheHandler):
    """Static file handler plus the two AI routes.

    ``chain_builder`` is a class attribute so a test (or a future embedding)
    can supply a chain without touching the environment.
    """

    chain_builder: ChainBuilder = staticmethod(build_chain)
    allowed_origins: frozenset[str] | None = None
    allow_remote = False
    timeout = CLIENT_TIMEOUT_SECONDS
    #: Set while answering a ``HEAD`` request: headers are sent, body is not.
    head_only = False

    # -- helpers -----------------------------------------------------------
    def _chain(self) -> AIChain:
        builder = type(self).chain_builder
        return builder()

    def _send_json(
        self,
        status: int,
        payload: Mapping[str, Any],
        *,
        allow: str | None = None,
    ) -> None:
        body = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if allow:
            # RFC 9110 requires Allow on a 405, and it is how a client learns
            # which method the route does take.
            self.send_header("Allow", allow)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not self.head_only:
            self.wfile.write(body)

    def _origin_allowed(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return True  # curl, or a non-browser client
        if origin == "null":
            return False
        if type(self).allowed_origins is not None:
            return origin in type(self).allowed_origins
        parsed = urlsplit(origin)
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if is_loopback(host):
            server_port = self.server.server_address[1]
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            return origin_port == server_port
        if type(self).allow_remote:
            host_header = (self.headers.get("Host") or "").strip().lower()
            header_host = host_header.rsplit(":", 1)[0].strip("[]")
            return bool(header_host) and host == header_host
        return False

    def _guard_origin(self) -> bool:
        if self._origin_allowed():
            return True
        self._send_json(
            403,
            {
                "error": "origin not allowed",
                "detail": (
                    "Open the AI page from this proxy's own address, or start "
                    "it with --allow-remote for non-loopback hosts."
                ),
            },
        )
        return False

    def _status_payload(self) -> dict[str, Any]:
        try:
            described = self._chain().describe()
        except AIError as exc:
            described = {
                "configured": False,
                "ready_count": 0,
                "order": [],
                "providers": [],
                "error": str(exc),
            }
        described["mode"] = "local-ai" if described.get("ready_count") else "setup"
        described["docs"] = DOCS_PATH
        described["page"] = "ai.html"
        return described

    # -- routing -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        path = urlsplit(self.path).path
        if path == STATUS_PATH:
            if not self._guard_origin():
                return
            self._send_json(200, self._status_payload())
            return
        if path == CHAT_PATH:
            self._send_json(
                405,
                {
                    "error": "method not allowed",
                    "detail": "POST a JSON body instead.",
                },
                allow="POST",
            )
            return
        if path.startswith(API_PREFIX):
            self._send_json(404, {"error": "unknown AI route", "path": path})
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib naming
        if urlsplit(self.path).path.startswith(API_PREFIX):
            # The stdlib only answers HEAD for files, so a HEAD on a route that
            # exists used to report 404. Answer it exactly like the GET and let
            # ``_send_json`` drop the body, which is what HEAD asks for. The
            # flag is cleared afterwards: a handler instance is reused for every
            # request on a keep-alive connection.
            self.head_only = True
            try:
                self.do_GET()
            finally:
                self.head_only = False
            return
        super().do_HEAD()

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        path = urlsplit(self.path).path
        if path == STATUS_PATH:
            # The route exists; POST is just not how it is read. Saying 404
            # here would send a client looking for a typo in the path.
            self._send_json(
                405,
                {
                    "error": "method not allowed",
                    "detail": "Read the status with GET.",
                },
                allow="GET, HEAD",
            )
            return
        if path != CHAT_PATH:
            self._send_json(
                404 if path.startswith(API_PREFIX) else 405,
                {"error": "unknown route", "path": path},
            )
            return
        if not self._guard_origin():
            return
        self._handle_chat()

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib naming
        path = urlsplit(self.path).path
        allow = {STATUS_PATH: "GET, HEAD", CHAT_PATH: "POST"}.get(path)
        if allow is None:
            self._reject_method()
            return
        # No CORS headers: the page is served from this origin, and a browser
        # preflight from anywhere else must keep failing.
        self.send_response(204)
        self.send_header("Allow", allow)
        self.end_headers()

    def _reject_method(self) -> None:
        """Answer an unimplemented method in JSON instead of HTML."""
        path = urlsplit(self.path).path
        if path.startswith(API_PREFIX):
            self._send_json(
                405,
                {
                    "error": "method not allowed",
                    "detail": "GET /api/ai/status and POST /api/ai/chat only.",
                },
                allow="GET, HEAD, POST",
            )
            return
        self._send_json(
            405,
            {"error": "unknown route", "path": path},
            allow="GET, HEAD",
        )

    def do_PUT(self) -> None:  # noqa: N802 - stdlib naming
        self._reject_method()

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib naming
        self._reject_method()

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib naming
        self._reject_method()

    def _read_chat_payload(self) -> dict[str, Any] | None:
        content_type = (self.headers.get("Content-Type") or "").split(";")[0]
        if content_type.strip().lower() != "application/json":
            self._send_json(
                415,
                {
                    "error": "unsupported media type",
                    "detail": "Send Content-Type: application/json.",
                },
            )
            return None
        raw_length = (self.headers.get("Content-Length") or "").strip()
        try:
            length = int(raw_length)
        except ValueError:
            self._send_json(
                411, {"error": "length required", "detail": "Set Content-Length."}
            )
            return None
        if length <= 0:
            self._send_json(400, {"error": "empty request body"})
            return None
        if length > MAX_BODY_BYTES:
            self._send_json(
                413,
                {
                    "error": "request body too large",
                    "detail": f"Limit is {MAX_BODY_BYTES} bytes.",
                },
            )
            return None
        try:
            raw = self.rfile.read(length)
        except TimeoutError:
            # A client that promises a body and then stalls would otherwise tie
            # up this thread for CLIENT_TIMEOUT_SECONDS and receive an empty
            # reply. Answer it, then close: the request stream is desynchronised
            # and cannot be reused for the next request on this connection.
            self.close_connection = True
            self._send_json(
                408,
                {
                    "error": "request body timed out",
                    "detail": (
                        f"Nothing arrived within {CLIENT_TIMEOUT_SECONDS} seconds."
                    ),
                },
            )
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send_json(400, {"error": "request body must be valid JSON"})
            return None
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "request body must be a JSON object"})
            return None
        return payload

    def _handle_chat(self) -> None:
        payload = self._read_chat_payload()
        if payload is None:
            return

        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            self._send_json(400, {"error": "prompt must be a non-empty string"})
            return
        if len(prompt) > MAX_PROMPT_CHARS:
            self._send_json(
                400,
                {
                    "error": "prompt is too long",
                    "detail": f"Limit is {MAX_PROMPT_CHARS} characters.",
                },
            )
            return
        provider_id = payload.get("provider")
        if provider_id is not None and not isinstance(provider_id, str):
            self._send_json(400, {"error": "provider must be a string"})
            return
        system = payload.get("system")
        if system is not None and not isinstance(system, str):
            self._send_json(400, {"error": "system must be a string"})
            return

        messages: list[Message] = []
        if system and system.strip():
            messages.append(Message("system", system.strip()))
        messages.append(Message("user", prompt.strip()))

        try:
            result = self._chain().complete(
                messages, provider_id=(provider_id or "").strip()
            )
        except UnknownProvider as exc:
            self._send_json(400, {"error": "unknown provider", "detail": str(exc)})
            return
        except ProviderNotReady as exc:
            self._send_json(409, {"error": "provider not ready", "detail": str(exc)})
            return
        except AllProvidersFailed as exc:
            self._send_json(
                502,
                {
                    "error": "no provider answered",
                    "detail": str(exc),
                    "attempts": [attempt.as_dict() for attempt in exc.attempts],
                },
            )
            return
        except ConfigError as exc:
            # 503: the request was fine, the local setup is not. Saying 400 here
            # would blame the caller for a file they may not even own.
            self._send_json(
                503,
                {
                    "error": "ai is misconfigured",
                    "detail": str(exc),
                    "docs": DOCS_PATH,
                },
            )
            return
        except AIError as exc:
            self._send_json(400, {"error": "ai request failed", "detail": str(exc)})
            return

        body = result.as_dict()
        body["mode"] = "local-ai"
        self._send_json(200, body)

    def log_message(self, format: str, *args: Any) -> None:
        """Log method, path, and status only — never a prompt or a header."""
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def make_handler(
    chain_builder: ChainBuilder | None = None,
    *,
    allowed_origins: Iterable[str] | None = None,
    allow_remote: bool = False,
) -> type[AIRequestHandler]:
    """Build a handler class with an injected chain, for tests and embedding."""

    class BoundHandler(AIRequestHandler):
        pass

    if chain_builder is not None:
        BoundHandler.chain_builder = staticmethod(chain_builder)
    if allowed_origins is not None:
        BoundHandler.allowed_origins = frozenset(allowed_origins)
    BoundHandler.allow_remote = allow_remote
    return BoundHandler


def provider_lines(described: Mapping[str, Any]) -> list[str]:
    """Render the provider table printed at startup and by ``ai_chat --list``."""
    providers = described.get("providers") or []
    if not providers:
        return [
            "No AI providers are configured.",
            "The static site works as usual; the AI page will show setup steps.",
        ]
    lines = []
    for provider in providers:
        mark = "ready" if provider.get("ready") else "not ready"
        model = provider.get("model") or "(no model)"
        detail = provider.get("reason", "")
        suffix = f" — {detail}" if not provider.get("ready") and detail else ""
        lines.append(
            f"  {provider['id']:<12} {provider['kind']:<18} {model:<24} {mark}{suffix}"
        )
    if described.get("ready_count") == 0:
        lines.append("  No provider is ready yet; see " + DOCS_PATH)
    return lines


def serve(
    *,
    host: str = LOOPBACK_BIND,
    port: int = DEFAULT_PORT,
    allow_remote: bool = False,
    chain_builder: ChainBuilder | None = None,
    stage_data: bool = True,
) -> int:
    """Serve ``site/`` plus the AI routes until interrupted."""
    if stage_data and stage() != 0:
        return 1

    builder = chain_builder or build_chain
    handler = make_handler(builder, allow_remote=allow_remote)
    bound = partial(handler, directory=str(config.SITE_DIR))
    try:
        server = ThreadingHTTPServer((host, port), bound)
    except OSError as exc:
        print(
            f"error: could not serve {config.SITE_DIR} on {host}:{port}: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        described = builder().describe()
    except AIError as exc:
        described = {"providers": [], "ready_count": 0, "error": str(exc)}

    print(f"Serving {config.SITE_DIR} at http://{host}:{port}/")
    print(f"AI page: http://{host}:{port}/ai.html")
    print("Providers:")
    for line in provider_lines(described):
        print(line)
    if described.get("error"):
        print(f"config error: {described['error']}", file=sys.stderr)
    print("Keys stay in this process. Nothing is uploaded by OpenToolHub.")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Serve the static site locally and add an optional /api/ai/ endpoint "
            "that talks to a provider configured on this machine."
        )
    )
    parser.add_argument(
        "--host",
        default=config.AI_HOST,
        help=f"Bind address (default {LOOPBACK_BIND}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.AI_PORT,
        help=f"Port to listen on (default {config.AI_PORT}).",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Permit a non-loopback bind. Off by default: the endpoint can spend "
        "your provider credits.",
    )
    parser.add_argument(
        "--no-stage",
        action="store_true",
        help="Skip copying data/*.json into site/data first.",
    )
    args = parser.parse_args(argv)

    if not is_loopback(args.host) and not args.allow_remote:
        parser.error(
            f"refusing to bind {args.host!r} without --allow-remote "
            f"({DOCS_PATH} explains the trade-off)"
        )
    try:
        return serve(
            host=args.host,
            port=args.port,
            allow_remote=args.allow_remote,
            stage_data=not args.no_stage,
        )
    except AIError as exc:
        # A configuration problem is a setup mistake, not "every provider
        # failed": the same code the CLI uses keeps the two apart.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())




