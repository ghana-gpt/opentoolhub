# Architecture

OpenToolHub is a static, data-driven catalog. There is no application server,
database, or build framework. The only runtime dependencies are Python's
standard library for the scripts and a modern browser for the site.

## Design rules

1. **`data/` is the single source of truth.** Pages and the CLI render what the
   JSON contains. No recommendation, stack, or API description is hardcoded in
   JavaScript or Python.
2. **Every reference must resolve.** A stack API id, template path, example
   path, category, and use case link are all checked by
   `scripts/validate.py`. CI fails on errors and warnings.
3. **The browser gets public data only.** `site/` contains HTML, CSS, JS, and a
   generated copy of `data/`. There are no API keys, tokens, or server calls.
4. **Unknown input is not guessed silently.** The recommender reports the
   closest alternatives and exits with a distinct code.
5. **One behavior, two clients.** The site and CLI both match on ids, names,
   aliases, and keywords from the same files, so a query behaves consistently.

## Components

### Data layer (`data/`)

Six JSON arrays with cross-references: `categories`, `use-cases`, `stacks`,
`apis`, `templates`, and `examples`. The schema and invariants are documented in
[data-model.md](data-model.md).

### Validator (`scripts/validate.py`)

Loads the files, checks required fields and types, kebab-case ids, enums,
duplicate ids, cross-references, and filesystem paths. It also rejects
unregistered use cases and categories that no use case or API uses. Run it with
`--strict` so warnings fail the build.

### Recommender (`scripts/recommend.py`)

Indexes the data by field weight, normalizes text (lowercase, accents,
punctuation), removes filler words, stems plurals and `-ise` spellings, and
scores candidates:

| Match | Score |
| --- | --- |
| Exact id | 100 |
| Exact name | 95 |
| Exact alias | 90 |
| Weighted keyword match | 55–88 |

Keyword scores combine idf-weighted field coverage with term rarity
(`50 + round(38 * coverage * (0.6 + 0.4 * rarity))`), so a rare keyword in a
name or alias outranks filler shared by every use case. Low-signal catalog words
such as "data", "local", "tracker", "planner", and "price" are indexed at weight
2, are never fuzzy-matched, and never count as distinctive evidence, so "fitness
tracker" returns no match instead of the nearest dashboard. A candidate must
cover 45% of the query, or one distinctive term (weight 3 or more, shared by at
most two use cases, not generic) must cover 25% of it on its own. Tokens of five
or more characters also match within one edit or adjacent transposition, scored
at 0.8 of their field weight and 0.85 of the keyword score when nothing matched
exactly, so `travle` still finds `travel` without outranking a real keyword. A
token that already exists somewhere in the catalog is treated as a real word,
not a typo, so `flood` never fuzzy-matches `food`.

A score below 90 with a runner-up within 5 points sets
`needs_disambiguation` and includes alternatives. When nothing clears the
threshold, the CLI prints the closest partial matches and the browser lists them
as "Closest use cases". The result resolves stack
tools to full API records, templates, examples, and a short rationale. The CLI
exposes text, `--json`, and `--list` modes.

### Static site (`site/`)

Plain ES modules with no framework:

- `js/data.js` loads and indexes JSON, normalizes text, and provides lookups.
- `js/ui.js` holds escaping, URL-state, and badge helpers.
- `js/render.js` contains reusable card and tool markup.
- One controller per page: `home.js`, `use-cases.js`, `use-case.js`,
  `stacks.js`, `templates.js`, `template.js`, and `apis.js`.

Browsers cannot fetch `../data/*.json` from a served `site/` directory, so
`scripts/build_site.py` copies the files to `site/data/` and `--check` detects a
stale copy. The same script serves `site/` with cache disabled for local work.
It also emits `site/data/catalog.json`, a deterministic manifest that links every
array to its checked-in `site/schema.json` fragment and records counts, entity
relationships, and the browser/CLI recommendation contract. The six source
arrays remain canonical; the manifest is a discovery layer for agents and other
one-request clients.

Each page's static head carries canonical, Open Graph, Twitter card, and
schema.org JSON-LD metadata. Collection pages publish a `CollectionPage` and
`ItemList`, the home page publishes a `DataCatalog`, and the two detail
controllers replace the generic metadata after loading the JSON:
`use-case.js` publishes the resolved use case's canonical URL and `TechArticle`,
while `template.js` publishes a `WebPage` plus a three-level `BreadcrumbList`
(site, templates index, template) for the requested template.

### Deployment

GitHub Pages publishes the `site/` directory, not the repository root.
`.github/workflows/pages.yml` validates the data, runs the tests, stages
`site/data/`, verifies the artifact, and uploads it with the official Pages
actions. Because `site/data/` is generated and gitignored, the build step is
mandatory on every deployment. Page URLs and fetches are relative so the same
artifact works at `http://127.0.0.1:8000/` and under the `/opentoolhub/` Pages
prefix. See [deployment.md](deployment.md) for commands and troubleshooting.

### Tests and CI

`tests/` covers data validation, ranking and aliases, CLI exit codes and JSON,
and static-site integrity (assets, module scripts, selectors, and imports).
GitHub Actions runs validation with `--strict`, the test suite, staging plus
`--check`, a recommender smoke test, and JavaScript syntax checks. A separate
workflow deploys the validated `site/` directory to GitHub Pages.

## Request flow

```text
browser
  └─ index.html → js/home.js
       └─ loadData()
            └─ fetch site/data/{categories,use-cases,stacks,apis,templates,examples}.json
                 └─ score + render path + template/example links

terminal
  └─ python3 scripts/recommend.py "travel app"
       └─ load_data() → score → build_recommendation() → text or JSON
```

## Boundaries

- The project does not host APIs, proxy requests, or store credentials.
- It does not claim live pricing or uptime; the licensing notes and links are a
  starting point that must be verified with each provider.
- It does not generate templates. A template entry is only valid when its path
  exists in `templates/`.
- Search is deterministic keyword matching, not a model call.
