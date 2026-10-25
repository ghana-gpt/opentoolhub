# Contributing an AI provider

The optional local AI layer keeps "add a provider" to one small class and one
registry line. This page is the contract that class has to honour. Read
[local-ai.md](local-ai.md) first for what the layer does and how users configure
it.

## Rules that are not negotiable

1. **Standard library only.** No SDKs, no `requests`, no new entries in a
   requirements file. The rest of `scripts/` has no dependencies and the AI
   layer stays that way.
2. **No key ever comes from a file or the repository.** A `ProviderSpec` names
   the environment variable (`api_key_env`); the value is read once in
   `build_provider` and kept on the instance.
3. **Errors are sentences a human can act on.** Name the provider, the URL, and
   the status. Never echo headers or the key; `ProviderError` messages are
   redacted, but do not rely on it.
4. **No network in tests.** Adapters take a `transport` callable; tests inject a
   fake and assert on the request instead of calling a real endpoint.
5. **Readiness is local and cheap.** `readiness()` must not perform I/O, so
   `--list` and `/api/ai/status` stay instant and offline-safe.

## The interface

`Provider` in [`scripts/ai_providers.py`](../scripts/ai_providers.py) defines the
contract. A subclass sets two class attributes and implements two methods:

| Member | Purpose |
| --- | --- |
| `kind` | The value users put in `kind`; must match the registry key |
| `requires_api_key` | `True` when the adapter cannot work without a key |
| `build_request(messages)` | Return `(url, headers, body)` for one completion |
| `parse_response(payload)` | Return `(text, usage)` from the parsed JSON |

Everything else is inherited: `readiness()`, `complete()` (readiness check,
transport call, latency, empty-answer guard), `describe()`, `secrets()`, and
`__repr__`. `messages` is a sequence of `Message(role, content)` with roles
`system`, `user`, and `assistant`.

```python
class ExampleProvider(Provider):
    """Serve the vendor's /v1/complete contract."""

    kind = "example"
    requires_api_key = True

    def build_request(
        self, messages: Sequence[Message]
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = f"{self.spec.base_url.rstrip('/')}/complete"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        body: dict[str, Any] = {
            "model": self.spec.model,
            "prompt": messages[-1].content,
            "max_tokens": int(self.spec.max_tokens or 512),
        }
        return url, headers, body

    def parse_response(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        text = payload.get("output")
        if not isinstance(text, str):
            raise ProviderError(
                "example returned JSON without an 'output' string"
            )
        usage = payload.get("usage")
        return text, usage if isinstance(usage, dict) else {}
```

Register it in four places, all in `scripts/ai_providers.py`:

```python
KINDS = (..., "example")
DEFAULT_BASE_URLS["example"] = "https://api.example.com/v1"
DEFAULT_API_KEY_ENV["example"] = "EXAMPLE_API_KEY"
PROVIDER_CLASSES["example"] = ExampleProvider
```

`KINDS` is the documented order; `PROVIDER_CLASSES` is what
`build_provider` and the config loader actually use. Unknown kinds fail with a
message that lists every registered kind, so a missing registry line is
immediately visible.

## Tests to add

Add a class to [`tests/test_ai.py`](../tests/test_ai.py), next to the existing
adapter tests. Reuse `spec()` and `RecordingTransport`; the transport records
`url`, `headers`, `body`, and `timeout`, and can return a queued payload or
raise a queued exception.

Cover, at minimum:

1. the URL, headers, and body shape, including the auth header your kind uses;
2. the `max_tokens` field when it is set, and its absence when it is not;
3. a successful `complete()` returning text, provider id, kind, model, and
   usage;
4. a malformed payload raising `ProviderError` with an actionable message;
5. readiness: missing model, missing key, and a ready provider;
6. that the key never appears in a failure message after redaction.

The registry test asserts every documented kind builds a provider, so update
`expected` in `RegistryTests.test_every_documented_kind_builds_a_provider` too.

```bash
python3 -m unittest tests.test_ai -v
make check
```

## Documentation to update

- `docs/local-ai.md`: one row in the kinds table (endpoint, key variable,
  notes).
- `ai-providers.example.json`: only if the kind is a sensible default example;
  keep every entry `"enabled": false` so a copy is inert.
- `.env.example`: the per-provider variables a user would copy, as comments.

## Review checklist

- [ ] `python3 scripts/validate.py --strict` passes.
- [ ] `python3 -m unittest discover -s tests` passes, with no network access.
- [ ] `grep -n "sk-" tests/test_ai.py` finds only the fake key.
- [ ] The adapter never logs, prints, or returns the key.
- [ ] `--list` works with the new kind unconfigured, and mentions what is
      missing.
- [ ] Failure messages name the provider and the URL, not a stack trace.
- [ ] The published site is unaffected: no file in `site/` imports Python.
