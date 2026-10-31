# Public data dashboard starter

A runnable starter: a country/indicator dashboard over **real World Bank open
data**, shipped with a committed snapshot so it works with no API key, no
backend, and no network.

Part of [OpenToolHub](../../README.md). The catalog entry lives in
`data/templates.json`; this folder is the working app.

## Run it

```bash
cd templates/public-data-dashboard
python3 -m http.server 8000 --directory app
# open http://127.0.0.1:8000/
```

`make serve` runs the same command, `make test` runs the Node suite, and
`make fetch` refreshes the snapshot. Any static server works; opening
`app/index.html` from the filesystem does not, because browsers block `fetch`
of the JSON snapshot over `file://`.

No install step, no build step, no dependencies. Python 3, Node 20+ for the
tests, and a browser are enough.

## What it does

- Pick one of four countries (Ghana, Kenya, India, Brazil) and one of six
  World Bank indicators (population, GDP per capita, urbanisation, electricity
  access, internet use, life expectancy).
- Read the latest published value, the change since the first available year,
  the highest year, and the country's rank against the others in the snapshot.
- Inspect the trend line and the full year-by-year table; gaps in the source
  stay visible instead of being interpolated.
- Download the current indicator as CSV, or copy a link that reopens the same
  country/indicator view (`?country=KEN&indicator=SP.DYN.LE00.IN`).

Everything is computed in the browser from `app/data/indicators.json`.

## Layout

```text
templates/public-data-dashboard/
├── app/
│   ├── index.html            # markup and accessible structure
│   ├── styles.css            # hand-written CSS, no framework
│   ├── app.js                # DOM wiring, rendering, CSV export
│   ├── dashboard.js          # pure helpers (formatting, chart maths, CSV)
│   └── data/indicators.json  # committed snapshot: 4 countries x 6 indicators
├── scripts/
│   └── fetch_data.py         # refresh the snapshot from the World Bank API
└── tests/
    ├── dashboard.test.mjs    # pure-function tests
    └── app.test.mjs          # boots app.js against a small DOM stub
```

## Refresh the data

```bash
python3 scripts/fetch_data.py
```

The script pulls 2015–2024 for every country/indicator pair from
`https://api.worldbank.org/v2`, writes `app/data/indicators.json`, and prints a
per-indicator summary plus the new file size. It needs outbound HTTPS but no
key. Reload the page afterwards; nothing else changes.

## Test it

```bash
node --test tests/*.test.mjs
```

Twenty tests, no dependencies: the pure helpers (formatting, gap handling,
ranking, chart geometry, CSV) and a smoke test that runs the real `app.js`
against a minimal DOM stub and asserts that the page renders, reacts to the
selects, honours URL parameters, downloads CSV, and shows a readable error when
the snapshot is missing. Node 20+ is required for `node:test` and ESM.

## Data, licence, and attribution

- Source: World Bank Open Data, `data.worldbank.org`, licensed CC BY 4.0.
- Attribution: "World Bank Open Data (CC BY 4.0)" — already shown in the app's
  "Data and method" panel and stored in the snapshot's `source` block.
- The snapshot records `generated_at`, the exact API root, and a per-indicator
  `source_url`, so any number on screen can be traced back to its series.
- Some World Bank series lag by a year; a missing value means "not published",
  not zero, and the UI says so.

Check the provider's current terms before shipping a public deployment.

## Make it yours

- **Different countries:** edit `COUNTRIES` in `scripts/fetch_data.py`, re-run
  it, and the selects/ranking pick the new list up from the snapshot.
- **Different indicators:** add an entry to `INDICATORS` with a World Bank
  indicator code, a `unit`, and a `format` (`integer`, `currency`,
  `decimal1`, `decimal2`). Unknown formats fall back to one decimal.
- **Different provider:** keep the snapshot shape
  (`countries[]`, `indicators[].series[countryId][year]`, `years[]`,
  `source{}`) and only rewrite the fetch script. The UI never talks to a
  provider directly, which is what makes it offline-capable and easy to cache.
- **Add a map or second chart:** `dashboard.js` exports `chartGeometry`, so a
  second SVG can reuse the same coordinate maths instead of pulling in a
  charting library.

## Limitations

- Four countries and ten years by design; it is a starter, not an ETL pipeline.
- The "rank" compares only the countries in the snapshot, on the newest year
  all of them report — not the full World Bank ranking.
- Values are shown as published: no inflation adjustment, no per-capita
  normalisation beyond what the indicator itself already does.
- No persistence, no accounts, no server-side caching.

