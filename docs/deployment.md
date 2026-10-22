# Local preview and GitHub Pages

OpenToolHub is a static site. Python validates and stages the catalog, but it is
not a runtime dependency: the published artifact is only HTML, CSS, JavaScript,
and JSON.

```text
data/*.json  --validate-->  data/  --build_site.py-->  site/data/
site/*.html, site/js/, site/styles.css             -->  site/
                                                        |
                                                        v
                                            GitHub Pages artifact (site/)
```

## Local commands

From the repository root:

```bash
python3 scripts/validate.py --strict
python3 -m unittest discover -s tests -v
python3 scripts/build_site.py
python3 scripts/build_site.py --check
python3 scripts/build_site.py --serve
```

Open <http://127.0.0.1:8000/>. The last command stages the data and serves
`site/` with browser caching disabled.

The same workflow is available through `make`:

```bash
make check   # validate, test, stage, and verify the artifact
make serve   # stage, then serve on http://127.0.0.1:8000/
```

`OPEN_TOOL_HUB_HOST` and `OPEN_TOOL_HUB_PORT` change the preview address; see
`.env.example`.

Do not open `site/index.html` from the filesystem. Browsers block `fetch()` on
`file://` URLs, so the pages cannot load the JSON catalog that way.

## Verify the artifact

A Pages deployment must contain both the pages and the generated data:

```bash
python3 scripts/build_site.py
test -f site/index.html
test -f site/404.html
test -f site/data/use-cases.json
test -f site/llms.txt
```

To inspect exactly what would be uploaded:

```bash
python3 scripts/build_site.py
tar -czf /tmp/opentoolhub-site.tgz -C site .
tar -tzf /tmp/opentoolhub-site.tgz | grep '^data/'
```

The second command must list `categories.json`, `use-cases.json`, `stacks.json`,
`apis.json`, `templates.json`, and `examples.json`.

## Publish with GitHub Pages

1. Push to the `main` branch.
2. In the GitHub repository, open **Settings → Pages**.
3. Under **Build and deployment → Source**, choose **GitHub Actions**.
4. Open the **Actions** tab and confirm the “Deploy OpenToolHub to GitHub Pages”
   workflow succeeds.
5. Open <https://ghana-gpt.github.io/opentoolhub/>.

Do not choose “Deploy from a branch” with the repository root or `data/` as the
folder. That serves source files without running the build, which is what makes
`site/data` disappear and produces “Catalog unavailable” in the browser. If you
ever deploy a branch folder directly, it must be `site/` with staged data
committed, and that is not the supported workflow.

### What the workflow does

`.github/workflows/pages.yml` runs on pushes to `main` and manual dispatches:

1. Checks out the repository and installs Python 3.12.
2. Runs `validate.py --strict` and the test suite.
3. Runs `build_site.py` to create `site/data/*.json`.
4. Runs `build_site.py --check` and verifies the required files exist.
5. Uploads the `site/` directory as the Pages artifact.
6. Deploys it with the official `actions/deploy-pages` action.

`site/data/` is gitignored because it is generated. The workflow creates it in
the runner before `actions/upload-pages-artifact` runs, and the artifact includes
the working-tree files even though Git does not track them.

The workflow uses `permissions: pages: write`, `id-token: write`, and the
`github-pages` environment supplied by `actions/deploy-pages`.

## Why the site survives the `/opentoolhub/` subpath

GitHub Pages project sites are served below a repository prefix. Page links,
stylesheets, module imports, and JSON fetches are therefore relative
(`styles.css`, `data/use-cases.json`), never root-absolute (`/styles.css`).
`tests/test_site.py` enforces that rule.

The artifact root is `site/`, so the deployed URL is:

```text
https://ghana-gpt.github.io/opentoolhub/           -> site/index.html
https://ghana-gpt.github.io/opentoolhub/data/*.json -> staged catalog
```

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| “Catalog unavailable”, network panel shows `data/*.json` 404 | The deployed artifact has no `site/data/`. Confirm the workflow ran `build_site.py` and uploaded `site/`, not the repository root. |
| Pages deploy fails with “Get Pages site failed” | Set **Settings → Pages → Source** to **GitHub Actions** once. |
| A page loads without CSS or JavaScript | A root-absolute URL (`/styles.css`) was introduced. Use relative URLs; run `make test`. |
| Deployment succeeded but content is old | Check the latest workflow run for the pushed commit; Pages deployments are queued per `main`. |
| Local page cannot load JSON | Use `build_site.py --serve`, not `file://`. |
| `site/data is out of date` | Run `python3 scripts/build_site.py`. |

## Related reading

- [Architecture](architecture.md)
- [Getting started](getting-started.md)
- [Data model](data-model.md)
