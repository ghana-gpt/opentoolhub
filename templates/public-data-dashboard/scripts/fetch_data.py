#!/usr/bin/env python3
"""Refresh this starter's data snapshot from the World Bank Open Data API.

The app ships with a committed snapshot so it runs offline. Run this script
when you want newer numbers; it rewrites ``app/data/indicators.json`` and
prints a short summary.

    python3 scripts/fetch_data.py

Requires only the Python standard library. World Bank Open Data is published
under CC BY 4.0; keep the attribution in the generated file when you ship.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
OUTPUT = APP_DIR / "app" / "data" / "indicators.json"
API_ROOT = "https://api.worldbank.org/v2"
SITE_ROOT = "https://data.worldbank.org/indicator"
USER_AGENT = (
    "OpenToolHub-public-data-dashboard/1.0 "
    "(+https://github.com/ghana-gpt/opentoolhub)"
)
START_YEAR = 2015
END_YEAR = 2024

COUNTRIES = [
    {"id": "GHA", "name": "Ghana"},
    {"id": "KEN", "name": "Kenya"},
    {"id": "IND", "name": "India"},
    {"id": "BRA", "name": "Brazil"},
]

#: ``format`` tells the UI how to render a value. Keep it simple: no locale
#: guessing and no rounding beyond what the source publishes.
INDICATORS = [
    {
        "id": "SP.POP.TOTL",
        "name": "Population, total",
        "unit": "people",
        "format": "integer",
        "description": "Total population from the World Bank's population estimates.",
    },
    {
        "id": "NY.GDP.PCAP.CD",
        "name": "GDP per capita",
        "unit": "current US$",
        "format": "currency",
        "description": "Gross domestic product divided by midyear population, current US dollars.",
    },
    {
        "id": "SP.URB.TOTL.IN.ZS",
        "name": "Urban population",
        "unit": "% of total population",
        "format": "decimal1",
        "description": "People living in urban areas as a share of the total population.",
    },
    {
        "id": "EG.ELC.ACCS.ZS",
        "name": "Access to electricity",
        "unit": "% of population",
        "format": "decimal1",
        "description": "Share of the population with access to electricity.",
    },
    {
        "id": "IT.NET.USER.ZS",
        "name": "Individuals using the Internet",
        "unit": "% of population",
        "format": "decimal1",
        "description": "Share of the population that used the internet in the last three months.",
    },
    {
        "id": "SP.DYN.LE00.IN",
        "name": "Life expectancy at birth",
        "unit": "years",
        "format": "decimal1",
        "description": "Years a newborn would live under current mortality patterns.",
    },
]

SOURCES = {
    "name": "World Bank Open Data",
    "api": API_ROOT,
    "site": "https://data.worldbank.org",
    "license": "CC BY 4.0",
    "attribution": "World Bank Open Data (CC BY 4.0)",
    "notes": (
        "Values are official World Bank indicator series. Some series lag by a "
        "year, so the newest column can be empty for a country."
    ),
}


def fetch_json(url: str, attempts: int = 4, timeout: int = 30) -> object:
    """GET JSON with bounded retries; the public API is occasionally slow."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < attempts:
                wait = 2 * attempt
                print(
                    f"  retry {attempt}/{attempts - 1} in {wait}s: {error}",
                    file=sys.stderr,
                )
                time.sleep(wait)
    raise SystemExit(f"Could not fetch {url}: {last_error}")


def fetch_indicator(indicator_id: str) -> dict[str, dict[str, float]]:
    """Return ``{country_id: {year: value}}`` for one indicator."""
    country_ids = ";".join(country["id"] for country in COUNTRIES)
    query = urllib.parse.urlencode(
        {"format": "json", "per_page": 500, "date": f"{START_YEAR}:{END_YEAR}"}
    )
    url = f"{API_ROOT}/country/{country_ids}/indicator/{indicator_id}?{query}"
    payload = fetch_json(url)
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise SystemExit(f"Unexpected World Bank response for {indicator_id}: {payload!r}")

    series: dict[str, dict[str, float]] = {}
    for row in payload[1]:
        value = row.get("value")
        if value is None:
            continue
        country_id = row.get("countryiso3code") or row.get("country", {}).get("id")
        year = str(row.get("date", ""))
        if not country_id or not year:
            continue
        series.setdefault(country_id, {})[year] = value
    if not series:
        raise SystemExit(f"No values returned for {indicator_id}")
    return series


def main() -> int:
    print(
        f"Fetching {len(INDICATORS)} indicators for {len(COUNTRIES)} countries "
        f"({START_YEAR}-{END_YEAR}) from the World Bank API..."
    )
    built = []
    for indicator in INDICATORS:
        print(f"- {indicator['id']} {indicator['name']}")
        series = fetch_indicator(indicator["id"])
        values = sum(len(years) for years in series.values())
        print(f"  {values} values across {len(series)} countries")
        built.append(
            {
                **indicator,
                "source_url": f"{SITE_ROOT}/{indicator['id']}",
                "series": series,
            }
        )

    document = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "years": list(range(START_YEAR, END_YEAR + 1)),
        "default_country": "GHA",
        "default_indicator": "SP.POP.TOTL",
        "countries": COUNTRIES,
        "indicators": built,
        "source": SOURCES,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    try:
        shown = OUTPUT.relative_to(APP_DIR)
    except ValueError:  # a caller may point OUTPUT outside the starter folder
        shown = OUTPUT
    print(f"Wrote {shown} ({OUTPUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

