# OpenToolHub

OpenToolHub turns a project idea into a concrete build path:

**idea → use case → categories → stack → template → worked example**

The catalog is versioned JSON, validated in CI and consumed by two clients: a
static site with no backend and a Python recommender that uses only the
standard library. There are no fakes in the catalog: every API links to its
official site and docs, and every template and example path exists in this
repository.

## What the project actually does

- Keeps eleven builder-focused use cases, each with a stack, categories, templates,
  and a worked example.
- Resolves a plain-language goal ("travel app", "civic tool") to one use case
  using ids, names, aliases, and keywords from `data/`.
- Shows the real trade-offs: auth type, pricing model, integration complexity,
  and data freshness for every API.
- Ships a static site that works without a server language, plus a CLI that
  prints either readable text or JSON.
- Treats AI as optional and local: a terminal command and a loopback-only panel
  can ask your own Ollama or hosted provider about the catalog, with no key in
  the repository and no backend on the published site.
- Refuses to guess silently: unknown queries exit with code `2`, name every
  valid use case, and list the closest partial matches. Typos of five or more
  characters still resolve through one-edit fuzzy matching.

## Quick start

Requirements: Python 3.10 or newer (CI uses 3.12). No third-party packages.

```bash
python3 scripts/validate.py --strict
python3 -m unittest discover -s tests -v
python3 scripts/build_site.py --serve
```

Then open <http://127.0.0.1:8000/>. The last command validates nothing by
itself, so run the validator first when you have edited data.

`make` wraps the same commands if you prefer:

```bash
make check   # validate, test, stage, and verify the artifact
make serve   # stage, then serve locally
```

`build_site.py` copies `data/*.json` into `site/data/` because browsers cannot
load files outside the directory they are served from. `site/data/` is generated
and gitignored. To check whether the staged copy is current without writing:

```bash
python3 scripts/build_site.py --check
```

## Recommender CLI

```bash
# Human-readable path
python3 scripts/recommend.py "travel app"

# Exact id
python3 scripts/recommend.py public-health-platform

# Machine-readable output
python3 scripts/recommend.py --json "civic tool"

# Every use case
python3 scripts/recommend.py --list
```

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | A recommendation or list was printed |
| `1` | Data files could not be loaded |
| `2` | Missing or unknown query |

An ambiguous match still exits `0` but prints the alternatives and a hint to use
a more specific phrase or an id.

## Optional local AI

The site never calls a model. If you want an assistant over the catalog while
you work locally, the AI layer is opt-in, stdlib-only, and provider-agnostic:

```bash
# Ollama on this machine: no key, no account.
ollama pull phi3:mini
export OPEN_TOOL_HUB_AI_PROVIDERS=local
export OPEN_TOOL_HUB_AI_LOCAL_KIND=ollama
export OPEN_TOOL_HUB_AI_LOCAL_MODEL=phi3:mini

python3 scripts/ai_chat.py --list
python3 scripts/ai_chat.py --json "Name three public weather APIs with no key."

# The same providers in the browser, over a loopback-only endpoint.
python3 scripts/ai_proxy.py      # http://127.0.0.1:8787/ai.html
```

Ollama, OpenAI, Anthropic, DeepSeek, Qwen, and any OpenAI-compatible server
(vLLM, LM Studio, llama.cpp) are supported. Order several providers and the
first ready one that answers wins; an unready provider is skipped with a reason
rather than a stack trace.

Two rules keep this safe: keys are read from environment variables named in the
configuration (a config file may name the variable, never hold the value), and
the proxy binds `127.0.0.1`, requires a JSON body, and checks `Origin`. On GitHub
Pages there is no `/api/ai/` route, so `ai.html` shows setup instructions and
nothing else changes. See [docs/local-ai.md](docs/local-ai.md) for the
variables, the JSON config format, the route contract, and troubleshooting.

## Site

| Page | Purpose |
| --- | --- |
| `index.html` | Idea, area, and experience form; renders a path from the data |
| `use-cases.html` | Search and filter every use case |
| `use-case.html?id=…` | One path with stacks, API links, templates, and its example |
| `stacks.html` | Tool combinations with difficulty and per-slot APIs |
| `templates.html` | Starter and variant templates, linked to repository files |
| `template.html?id=…` | One template with build order, APIs, a worked example, related templates, and a copyable brief |
| `apis.html` | API catalog with category, pricing, auth, and freshness details |
| `ai.html` | Optional local AI panel; shows setup steps unless `scripts/ai_proxy.py` is running |

The builder keeps its state in the URL (`q`, `areas`, `level`), and the catalog
pages keep filters in the URL too, so a view can be linked or reloaded. All
rendered text passes through an HTML escaper; user input is never inserted as
markup. The site makes no network requests except for the staged JSON files;
`ai.html` additionally asks the local proxy for `/api/ai/status`, a route that
does not exist on Pages, in which case it renders setup instructions.

The deployed site also exposes the catalog for scripts and AI agents:
`/data/catalog.json` is a one-request manifest with counts, file URLs, schema
pointers, relationships, and the shared recommendation contract; `/data/*.json`
contains the same validated records; `/schema.json` defines every file; and
`llms.txt` describes the routes and fields. Every page publishes canonical,
Open Graph, Twitter card, and schema.org JSON-LD metadata, while `sitemap.xml`
and `robots.txt` cover crawlers.

## Deploy

GitHub Pages publishes the `site/` directory with the staged data. In the
repository, set **Settings → Pages → Source** to **GitHub Actions**; the
“Deploy OpenToolHub to GitHub Pages” workflow runs on pushes to `main`, builds
`site/data/`, verifies the artifact, and deploys it. The public URL is
<https://ghana-gpt.github.io/opentoolhub/>. See
[deployment.md](docs/deployment.md) for local checks, the exact artifact
contents, and troubleshooting.

## Repository layout

```text
.
├── data/                      # Validated JSON: the single source of truth
│   ├── apis.json
│   ├── categories.json
│   ├── examples.json
│   ├── stacks.json
│   ├── templates.json
│   └── use-cases.json
├── docs/                      # Architecture, data model, guides
├── examples/                  # Worked walkthroughs referenced by examples.json
├── scripts/
│   ├── build_site.py          # Stage site/data, check staleness, serve locally
│   ├── config.py              # Paths and host/port settings
│   ├── ai_providers.py        # Optional AI adapters, chain, redaction
│   ├── ai_config.py           # AI config from env and a git-ignored JSON file
│   ├── ai_proxy.py            # Serve site/ plus /api/ai/status and /api/ai/chat
│   ├── ai_chat.py             # One-prompt AI CLI
│   ├── recommend.py           # Stdlib recommender and CLI
│   └── validate.py            # Schema, reference, and path validation
├── site/
│   ├── *.html                 # One page per view
│   ├── js/                    # ES modules: data access, UI, page controllers
│   ├── styles.css
│   ├── llms.txt               # Agent-facing catalog map
│   ├── schema.json            # JSON Schema for all six data files
│   ├── social-card.png        # Open Graph / Twitter preview image
│   ├── robots.txt
│   ├── sitemap.xml
│   └── data/                  # Generated by build_site.py (gitignored)
├── templates/                 # Starter projects referenced by templates.json
├── tests/                     # Data, recommender, CLI, static-site, and AI tests
├── ai-providers.example.json  # Copy to ai-providers.local.json (gitignored)
├── Makefile                   # build, serve, validate, test, check, clean
└── .github/workflows/         # CI and GitHub Pages deployment
```

## Documentation

- [Data model](docs/data-model.md) — fields, enums, cross-references, and
  invariants enforced by the validator.
- [Architecture](docs/architecture.md) — how the data, CLI, and static site fit
  together.
- [Getting started](docs/getting-started.md) — local workflow and first tasks.
- [Deployment](docs/deployment.md) — local build commands, GitHub Pages setup,
  and subpath troubleshooting.
- [Optional local AI](docs/local-ai.md) — provider kinds, configuration, the CLI
  and proxy routes, and troubleshooting.
- [Contributing an AI provider](docs/contributing-ai-providers.md) — the adapter
  contract and the tests a new provider needs.
- [Contributing](CONTRIBUTING.md) — what makes a good data or template change.

## Validate before you push

```bash
make check
```

That is equivalent to running the validator with `--strict`, the test suite,
the staging build, and the staged-copy check. CI runs the same checks on every
pull request, then performs a recommender smoke test. The Pages workflow
validates the data, runs the tests, syntax-checks the JavaScript, stages it,
verifies the artifact, and deploys `site/` only after those steps pass.

## Live site

<https://ghana-gpt.github.io/opentoolhub/>

## License

MIT. See [LICENSE](LICENSE).
