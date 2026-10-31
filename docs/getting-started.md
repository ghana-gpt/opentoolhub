# Getting started

This guide is for running OpenToolHub locally and making a first change. No
third-party packages are required.

## Requirements

- Python 3.10 or newer (CI uses 3.12)
- Git
- A modern browser for the static site

## 1. Get the repository

```bash
git clone https://github.com/ghana-gpt/opentoolhub.git
cd opentoolhub
```

## 2. Verify the data and code

```bash
python3 scripts/validate.py --strict
python3 -m unittest discover -s tests -v
```

The validator prints every error and warning, then a count. `--strict` makes
warnings fail, which is what CI uses. The test suite covers data invariants,
recommender ranking, aliases, CLI exit codes, and static-site integrity.

## 3. Try the recommender

```bash
python3 scripts/recommend.py "travel app"
python3 scripts/recommend.py --list
python3 scripts/recommend.py --json "civic tool"
```

Unknown queries exit with code `2` and list valid use cases. Ambiguous queries
still return a result but print alternatives and suggest a more specific phrase
or an id.

## 4. Preview the site

```bash
python3 scripts/build_site.py --serve
```

Open <http://127.0.0.1:8000/>. The command copies `data/*.json` into
`site/data/`, then serves `site/` with caching disabled. `make serve` is a
shorter equivalent, and `make check` runs the validator, tests, staging build,
and stale-copy check in one command.

Do not open the HTML files directly from disk. Browsers block `fetch()` for
`file://` URLs, and the pages will show a "Catalog unavailable" message with the
serve command.

### What to try

- Submit an idea with one or more areas and change the experience level.
- Reload the page: the form state is stored in the URL.
- Open a use case and follow its template and example links.
- Break a filter on purpose and confirm the empty state and "Clear filters".

## 5. Try a runnable starter

`templates/public-data-dashboard/` is a complete app, not just a brief. It reads
a committed World Bank snapshot and needs no key, backend, or install step:

```bash
cd templates/public-data-dashboard
make serve   # http://127.0.0.1:8000/
make test    # Node 20+; 20 tests
```

`make fetch` re-pulls the snapshot from `https://api.worldbank.org/v2` and
rewrites `app/data/indicators.json`. From the repository root, run
`make starter-test` to execute the Node suites of every template that ships
one. The starter's own README explains the file layout and what to change first.

## 6. Make a change

For a data change, start with [data-model.md](data-model.md). A minimal edit is
adding an API and referencing it from an existing stack slot:

1. Edit `data/apis.json` with a real `url` and `docs_url`.
2. Add the API id to a `tools[].api_ids` list in `data/stacks.json`.
3. Make sure the API belongs to that slot's category.
4. Run the validator and tests.
5. Re-stage the site and reload the affected page.

For a site change, edit the HTML and the matching module under `site/js/`.
`tests/test_site.py` checks that local assets exist, scripts are modules, and
every `qs("#id")` selector has a matching element on the page.

For a recommender change, edit `scripts/recommend.py` and add a test in
`tests/test_recommend.py`. Ranking must stay data-driven: no use case ids or
answers should be hardcoded in the matching logic.

## 7. Publish to GitHub Pages

In **Settings → Pages**, set **Source** to **GitHub Actions**. Push to `main`
and the “Deploy OpenToolHub to GitHub Pages” workflow validates the data, tests
it, stages `site/data/`, verifies the artifact, and deploys `site/`.

The site is then at <https://ghana-gpt.github.io/opentoolhub/>. Do not deploy the
repository root or a branch folder: `site/data/` is generated and only exists
after `scripts/build_site.py` runs. [deployment.md](deployment.md) covers local
artifact checks, workflow permissions, and subpath failures.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Catalog unavailable" in the browser | Run `python3 scripts/build_site.py --serve` instead of opening the file directly |
| `site/data is out of date` | Run `python3 scripts/build_site.py` |
| Port 8000 is busy | Set `OPEN_TOOL_HUB_PORT=8080` before `--serve` |
| Validator reports a path error | Create the missing template or example file, or fix the path |
| Tests fail after editing JSON | Fix the validator errors first; ranking tests use the same files |
| GitHub Pages shows no data | The artifact must be built from `site/` after `build_site.py`; see [deployment.md](deployment.md) |

`OPEN_TOOL_HUB_HOST` and `OPEN_TOOL_HUB_PORT` are read by `scripts/config.py`.
See `.env.example` for the supported names.

## Next reading

- [Deployment and GitHub Pages](deployment.md)
- [Architecture](architecture.md)
- [Data model](data-model.md)
- [Contributing](../CONTRIBUTING.md)
- [Roadmap](../ROADMAP.md)
