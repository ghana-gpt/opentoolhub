# Optional local AI

OpenToolHub does not need AI, and the published site never calls a model. The
catalog, the recommender, and every page keep working with no key, no server,
and no network request beyond the staged JSON.

This page documents the optional layer for people who want an assistant on top
of the catalog while working locally: a terminal chat command and a loopback
proxy that powers `site/ai.html` during development. You choose the provider,
you run it, and your key never leaves your machine.

## What the layer is, and what it is not

| It is | It is not |
| --- | --- |
| Three stdlib-only modules in `scripts/` | A dependency of the static site |
| A way to ask an Ollama, OpenAI, Anthropic, DeepSeek, Qwen, or OpenAI-compatible model about the catalog | A hosted service, a crawler, or a training pipeline |
| Loopback by default, with origin and body guards | Reachable from your network unless you pass `--allow-remote` |
| Key-from-environment only | A place where a key is ever written to a file, a log, or a response |

Nothing in `site/` imports Python. `site/ai.html` talks to
`scripts/ai_proxy.py` when you start it, and shows setup instructions when you
do not. On GitHub Pages there is no `/api/ai/` route, so the page stays in
setup mode by design.

## The moving parts

| File | Role |
| --- | --- |
| [`scripts/ai_providers.py`](../scripts/ai_providers.py) | Adapter interface, `Message`/`Completion`/`AIChain`, the provider registry, redaction |
| [`scripts/ai_config.py`](../scripts/ai_config.py) | Reads `OPEN_TOOL_HUB_AI_*` variables and an optional git-ignored JSON file |
| [`scripts/ai_proxy.py`](../scripts/ai_proxy.py) | Serves `site/` and adds `GET /api/ai/status` and `POST /api/ai/chat` |
| [`scripts/ai_chat.py`](../scripts/ai_chat.py) | One-prompt CLI with the same configuration |
| [`site/ai.html`](../site/ai.html) | Local-only panel that reads the two routes |
| [`ai-providers.example.json`](../ai-providers.example.json) | Copy to `ai-providers.local.json` (gitignored) |

## Quick start with Ollama

Ollama runs on your machine, needs no key, and is the shortest path to a working
answer.

```bash
# 1. Install Ollama, then pull a model that fits your machine.
ollama pull phi3:mini
ollama serve                     # usually already running on 127.0.0.1:11434

# 2. Point the chain at it for this shell (or put the same lines in .env).
export OPEN_TOOL_HUB_AI_PROVIDERS=local
export OPEN_TOOL_HUB_AI_LOCAL_KIND=ollama
export OPEN_TOOL_HUB_AI_LOCAL_MODEL=phi3:mini

# 3. Check readiness. No network call, no model load.
python3 scripts/ai_chat.py --list
```

```text
Configured providers (fallback order):
  local        ollama             phi3:mini                ready
Order: local
```

```bash
# 4. Ask one question.
python3 scripts/ai_chat.py "Name three public weather APIs with no key."
```

The answer goes to standard output; a one-line provenance note
(`provider / model / latency / attempts`) goes to standard error, so
`python3 scripts/ai_chat.py ... > answer.txt` captures only the answer. Add
`--json` for a machine-readable envelope with the full attempt trail.

```bash
# 5. Optional: the same provider in the browser.
python3 scripts/ai_proxy.py
# Then open http://127.0.0.1:8787/ai.html
```

`ai_proxy.py` stages `data/*.json` into `site/data/` first (skip with
`--no-stage`) and serves the same `site/` that `build_site.py --serve` serves,
plus the two JSON routes.

## Provider kinds

| `kind` | Endpoint | Key variable | Notes |
| --- | --- | --- | --- |
| `ollama` | `http://127.0.0.1:11434` | none | Native `/api/chat`, `stream: false` |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | `/chat/completions` |
| `anthropic` | `https://api.anthropic.com/v1` | `ANTHROPIC_API_KEY` | `/messages`; `system` is hoisted out of the message list |
| `deepseek` | `https://api.deepseek.com/v1` | `DEEPSEEK_API_KEY` | OpenAI-compatible contract |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` | DashScope compatible mode |
| `openai-compatible` | none — set `base_url` | none by default | vLLM, LM Studio, llama.cpp, gateways |

Base URLs are public, documented defaults; a `base_url` in the config wins.
A hosted kind is "ready" only when its key variable is set. Readiness is
computed locally, so `--list` and `/api/ai/status` never touch the network or
load a model.

Adding a kind is one small class plus one registry line; see
[contributing-ai-providers.md](contributing-ai-providers.md).

## Configuration

Precedence, highest first:

1. environment variables, including a git-ignored `.env` loaded by
   `scripts/config.py`;
2. `ai-providers.local.json` in the repository root, or the file named by
   `OPEN_TOOL_HUB_AI_CONFIG`.

A relative `OPEN_TOOL_HUB_AI_CONFIG` path is resolved from the repository root.
Naming a file that does not exist is an error rather than a silent "no AI",
because a typo should not look like an empty configuration.

### Global variables

| Variable | Meaning |
| --- | --- |
| `OPEN_TOOL_HUB_AI_PROVIDERS` | Comma-separated provider ids; this is the fallback order |
| `OPEN_TOOL_HUB_AI_CONFIG` | Path to the local JSON config file |
| `OPEN_TOOL_HUB_AI_HOST` | Bind address for `ai_proxy.py` (default `127.0.0.1`) |
| `OPEN_TOOL_HUB_AI_PORT` | Port for `ai_proxy.py` (default `8787`) |

Without `OPEN_TOOL_HUB_AI_PROVIDERS`, the order is the order of the entries in
the JSON file. An id may also exist only in the environment, as in the Ollama
quick start above.

### Per-provider variables

For the provider id `local`, the prefix is `OPEN_TOOL_HUB_AI_LOCAL_` (uppercase,
`-` and `.` become `_`):

| Suffix | Meaning | Default |
| --- | --- | --- |
| `KIND` | Adapter kind from the table above | required |
| `MODEL` | Model name, e.g. `phi3:mini` | `""` (not ready) |
| `BASE_URL` | Endpoint override | the kind's default |
| `API_KEY_ENV` | Name of the variable that holds the key | the kind's convention |
| `TIMEOUT` | Per-request timeout in seconds | `60` |
| `MAX_TOKENS` | Output token cap | `512` |
| `ENABLED` | `0`/`false`/`no`/`off` disables the provider | enabled |
| `LABEL` | Display name in the panel and tables | the provider id |

Numbers and booleans are parsed, not guessed: `TIMEOUT=soon` fails with a
message that names the variable.

### The JSON file

```json
{
  "providers": [
    {
      "id": "local",
      "label": "Ollama on this machine",
      "kind": "ollama",
      "model": "phi3:mini",
      "timeout": 120,
      "max_tokens": 512,
      "enabled": true
    }
  ]
}
```

A bare list is accepted too. Each entry needs `id`; `kind`, `model`, `base_url`,
`api_key_env`, `timeout`, `max_tokens`, `label`, and `enabled` are optional.
Environment variables override file values field by field, so a committed or
shared file can hold the shape while `.env` holds the machine-specific parts.

### Keys never live in files

A config file may only name the variable that holds a key:

```json
{ "id": "cloud", "kind": "openai", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY" }
```

An entry that sets `api_key`, `apikey`, `key`, `token`, `secret`, or `password`
is rejected with an error that explains the rule, so a mistaken commit fails
loudly instead of leaking. The key value is read from the environment and kept
on the provider instance; it is redacted to `***` in every error message before
that message reaches a terminal, a log line, or the browser.

## Fallback order

A chain tries providers in order and stops at the first answer:

- providers that are not ready are recorded as `skipped` and never called;
- an error on one provider is recorded with its reason and the next is tried;
- if every provider fails, the command exits with a summary of each attempt;
- `--provider id` moves that provider to the front and fails loudly when the id
  is unknown or not ready;
- `--no-fallback` uses only `--provider` and never continues down the chain.

Local first is usually the right order: it costs nothing and keeps prompts on
your machine. A hosted provider second means an offline Ollama, or a model that
does not fit in memory, degrades to a working answer instead of an error.

## `ai_chat.py`

```bash
python3 scripts/ai_chat.py --list                    # configured providers, readiness
python3 scripts/ai_chat.py --list --json             # the same, machine-readable
python3 scripts/ai_chat.py "Summarise this idea"     # one prompt
echo "read from stdin" | python3 scripts/ai_chat.py -
python3 scripts/ai_chat.py --system "Be terse." "hi"  # per-request system prompt
python3 scripts/ai_chat.py --provider local --no-fallback "hi"
```

| Exit code | Meaning |
| --- | --- |
| `0` | An answer, a listing, or `--json` output was printed |
| `2` | Bad usage, a broken config, an unknown provider, or a provider that is not ready |
| `3` | No provider is configured, or none is ready — the normal state of a fresh clone |
| `4` | Providers were configured but every one of them failed |

Exit code `3` is not an error to fix: the static site works without the AI
layer, and the message points at this page.

## `ai_proxy.py`

```bash
python3 scripts/ai_proxy.py                 # http://127.0.0.1:8787/
python3 scripts/ai_proxy.py --port 8790
python3 scripts/ai_proxy.py --no-stage      # when site/data/ is already current
python3 scripts/ai_proxy.py --host 0.0.0.0 --allow-remote   # read the box below first
```

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/ai/status` | `GET` | Providers, readiness reasons, fallback order, docs link. Never a key. |
| `/api/ai/chat` | `POST` | `{"prompt": "...", "provider": "optional-id", "system": "optional"}` |

`POST` replies with `completion` (text, provider, kind, model, latency, usage)
and `attempts` (one entry per provider tried, including skips). Errors are JSON
with a short `error` and a human `detail`:

| Status | When |
| --- | --- |
| `400` | Invalid JSON, an empty or over-long prompt, an unknown provider |
| `403` | `Origin` is not this proxy's own origin |
| `405` | `GET /api/ai/chat`, or `POST` outside `/api/ai/` |
| `409` | The requested provider is configured but not ready |
| `413` | Body over 64 KiB |
| `415` | `Content-Type` is not `application/json` |
| `502` | Every provider was tried and failed; the attempts carry the reasons |

Safety defaults are on purpose:

- the server binds `127.0.0.1` and refuses any other host unless
  `--allow-remote` is passed, because the endpoint can spend your credits;
- `POST` requires a JSON content type, a bounded `Content-Length`, a body under
  64 KiB, and a prompt under 4000 characters, so a cross-site form post cannot
  reach a provider;
- `Origin` must be the proxy's own origin (or, with `--allow-remote`, the host
  the request was addressed to), and `Origin: null` is rejected;
- request bodies are never logged — only method, path, and status — and keys
  never appear in a response.

`--allow-remote` is for a container or a trusted LAN. Anyone who can reach the
port can spend your provider quota, so put it behind your own auth if the
machine is shared. The proxy has no other authentication.

## The AI page

`site/ai.html` asks `/api/ai/status` on load:

- **ready** — a prompt box, provider selector, and the answer with its attempt
  trail;
- **setup** — the environment variables to set and a link to this page.

Because the page uses a relative fetch (`api/ai/status`), the same file works
under the GitHub Pages subpath and under the local proxy. On Pages the route
does not exist, so the page renders the setup card and no request leaves the
browser for a model. Nothing else on the site depends on it.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `no AI providers are configured` (exit `3`) | Set `OPEN_TOOL_HUB_AI_PROVIDERS` and the per-provider variables, or create `ai-providers.local.json` |
| `missing API key in $OPENAI_API_KEY` | Export the variable, or add it to `.env`; `--list` shows which name is expected |
| `Connection refused` on `127.0.0.1:11434` | `ollama serve` is not running |
| `HTTP 404 ... model not found` | The model name does not match `ollama list`; pull it or fix `MODEL` |
| `model requires more system memory ... than is available` | The model is larger than free RAM; choose a smaller model or close other applications |
| `HTTP 401` | The key is wrong or expired; the message is redacted, so check the variable itself |
| `origin not allowed` (`403`) | Open `ai.html` from the proxy's own address, not from a file or another port |
| `could not serve ... : Address already in use` | Another process owns the port; pass `--port 8790` |
| `... must be a number, got 'soon'` | A `TIMEOUT`/`MAX_TOKENS` value is not numeric; the message names the variable |

## Checking it works

The layer is covered by `tests/test_ai.py`, which needs no network, no key, and
no running model: adapter requests go through an injected transport, and the
proxy tests start a throwaway loopback server with a stubbed chain. They cover
the registry, readiness, each adapter's request and response shape, redaction,
fallback, configuration precedence, the security guards, and the CLI exit codes.
A small hygiene group also pins the page/module pair, the inert example config,
the stdlib-only import surface of the four AI scripts, and that no script
carries a literal key.

```bash
python3 -m unittest tests.test_ai -v
```

For a manual, real-provider check, with Ollama running:

```bash
export OPEN_TOOL_HUB_AI_PROVIDERS=local
export OPEN_TOOL_HUB_AI_LOCAL_KIND=ollama
export OPEN_TOOL_HUB_AI_LOCAL_MODEL=phi3:mini
python3 scripts/ai_chat.py --list
python3 scripts/ai_chat.py --json "Say hello in five words."

python3 scripts/ai_proxy.py &
curl -s http://127.0.0.1:8787/api/ai/status
curl -s -X POST http://127.0.0.1:8787/api/ai/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Say hello in five words."}'
```

A failure here is still informative: the proxy answers `502` with the provider's
own reason (for example a model that does not fit in memory), which is exactly
the behaviour the tests pin down.

## Privacy and cost

- Prompts go only to the providers you configure. A hosted provider sees the
  prompt and your key; a local Ollama sees neither leave the machine.
- The proxy binds loopback and logs no bodies, so a prompt is not written to
  disk by OpenToolHub.
- Nothing is sent to the OpenToolHub project. There is no telemetry.
- Hosted providers bill per token. `MAX_TOKENS` and `--no-fallback` bound the
  spend of a scripted run.
- The catalog is curated by people. A model can repeat it, summarise it, or get
  it wrong; use `data/catalog.json` and the API's official documentation as the
  source of truth.




