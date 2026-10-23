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
- Refuses to guess silently: unknown queries exit with a useful message and a
  list of valid use cases.

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

## Site

| Page | Purpose |
| --- | --- |
| `index.html` | Idea, area, and experience form; renders a path from the data |
| `use-cases.html` | Search and filter every use case |
| `use-case.html?id=…` | One path with stacks, API links, templates, and its example |
| `stacks.html` | Tool combinations with difficulty and per-slot APIs |
| `templates.html` | Starter and variant templates, linked to repository files |
| `apis.html` | API catalog with category, pricing, auth, and freshness details |

The builder keeps its state in the URL (`q`, `areas`, `level`), and the catalog
pages keep filters in the URL too, so a view can be linked or reloaded. All
rendered text passes through an HTML escaper; user input is never inserted as
markup. The site makes no network requests except for the staged JSON files.

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
├── tests/                     # Data, recommender, CLI, and static-site tests
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
- [Contributing](CONTRIBUTING.md) — what makes a good data or template change.

## Validate before you push

```bash
make check
```

That is equivalent to running the validator with `--strict`, the test suite,
the staging build, and the staged-copy check. CI runs the same checks on every
pull request, then performs a recommender smoke test. The Pages workflow
validates and tests the data, stages it, verifies the artifact, and deploys
`site/` only after those steps pass.

## Live site

<https://ghana-gpt.github.io/opentoolhub/>

## License

MIT. See [LICENSE](LICENSE).
