// Run with: node --test tests/
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  chartGeometry,
  changeBetween,
  comparison,
  findCountry,
  findIndicator,
  formatDelta,
  formatValue,
  latestPoint,
  peakPoint,
  presentPoints,
  seriesFor,
  toCsv,
} from "../app/dashboard.js";

const snapshot = JSON.parse(
  await readFile(new URL("../app/data/indicators.json", import.meta.url), "utf8")
);

const indicator = snapshot.indicators.find((item) => item.id === "SP.POP.TOTL");

test("the committed snapshot is shaped the way the app expects", () => {
  assert.equal(snapshot.countries.length, 4);
  assert.equal(snapshot.indicators.length, 6);
  assert.deepEqual(
    snapshot.countries.map((country) => country.id),
    ["GHA", "KEN", "IND", "BRA"]
  );
  assert.deepEqual(
    snapshot.years,
    [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]
  );
  for (const item of snapshot.indicators) {
    assert.ok(item.format, `${item.id} needs a format`);
    assert.ok(item.unit, `${item.id} needs a unit`);
    for (const country of snapshot.countries) {
      assert.ok(item.series[country.id], `${item.id} is missing ${country.id}`);
    }
  }
});

test("formatValue handles integers, currency, decimals, and gaps", () => {
  assert.equal(formatValue(1234567, "integer"), "1,234,567");
  assert.equal(formatValue(1234.5, "currency"), "$1,235");
  assert.equal(formatValue(12.34, "decimal1"), "12.3");
  assert.equal(formatValue(12.345, "decimal2"), "12.35");
  assert.equal(formatValue(null, "integer"), "No data");
  assert.equal(formatValue(undefined, "integer"), "No data");
  assert.equal(formatValue(Number.NaN, "integer"), "No data");
  assert.equal(formatValue(5, "unknown-format"), "5.0");
});

test("formatDelta keeps the sign visible", () => {
  assert.equal(formatDelta(1200, "integer"), "+1,200");
  assert.equal(formatDelta(-3.5, "decimal1"), "−3.5");
  assert.equal(formatDelta(0, "integer"), "0");
  assert.equal(formatDelta(null, "integer"), "No comparable data");
});

test("lookups fall back to the first entry", () => {
  assert.equal(findIndicator(snapshot, "SP.POP.TOTL").id, "SP.POP.TOTL");
  assert.equal(findIndicator(snapshot, "nope").id, snapshot.indicators[0].id);
  assert.equal(findCountry(snapshot, "KEN").name, "Kenya");
  assert.equal(findCountry(snapshot, "XXX").id, snapshot.countries[0].id);
});

test("seriesFor keeps one point per year and preserves gaps", () => {
  const points = seriesFor(indicator, "GHA", [2015, 2016, 2024]);
  assert.deepEqual(
    points.map((point) => point.year),
    [2015, 2016, 2024]
  );
  assert.ok(points.every((point) => typeof point.value === "number"));
});

test("gaps become nulls instead of being skipped", () => {
  const sparse = { id: "X", series: { GHA: { 2015: 10, 2017: 12 } } };
  const points = seriesFor(sparse, "GHA", [2015, 2016, 2017]);
  assert.deepEqual(
    points.map((point) => point.value),
    [10, null, 12]
  );
  assert.equal(presentPoints(points).length, 2);
  assert.equal(seriesFor(sparse, "KEN", [2015]).at(0).value, null);
});

test("latestPoint, firstPoint, and peakPoint ignore gaps", () => {
  const points = [
    { year: 2015, value: 10 },
    { year: 2016, value: null },
    { year: 2017, value: 14 },
    { year: 2018, value: 12 },
  ];
  assert.deepEqual(latestPoint(points), { year: 2018, value: 12 });
  assert.deepEqual(peakPoint(points), { year: 2017, value: 14 });
  assert.equal(latestPoint([{ year: 2015, value: null }]), null);
  assert.equal(peakPoint([]), null);
});

test("changeBetween measures the published window, not the calendar window", () => {
  const change = changeBetween([
    { year: 2015, value: null },
    { year: 2016, value: 200 },
    { year: 2017, value: null },
    { year: 2018, value: 250 },
  ]);
  assert.equal(change.from.year, 2016);
  assert.equal(change.to.year, 2018);
  assert.equal(change.absolute, 50);
  assert.equal(change.percent, 25);
  assert.equal(changeBetween([{ year: 2015, value: 1 }]), null);
  assert.equal(
    changeBetween([
      { year: 2015, value: 0 },
      { year: 2016, value: 2 },
    ]).percent,
    null
  );
});

test("comparison ranks countries on the newest shared year", () => {
  const fake = {
    countries: [
      { id: "AAA", name: "Alpha" },
      { id: "BBB", name: "Beta" },
      { id: "CCC", name: "Gamma" },
    ],
    indicators: [],
  };
  const series = {
    id: "X",
    series: {
      AAA: { 2019: 5, 2020: 6 },
      BBB: { 2019: 7, 2020: 8 },
      CCC: { 2019: 9 },
    },
  };
  const ranked = comparison(fake, series, "AAA", [2019, 2020]);
  assert.equal(ranked.year, 2019);
  assert.deepEqual(
    ranked.rows.map((row) => row.id),
    ["CCC", "BBB", "AAA"]
  );
  assert.equal(ranked.selectedCountryId, "AAA");
});

test("comparison copes with a snapshot that has no shared year", () => {
  const fake = { countries: [{ id: "AAA", name: "Alpha" }] };
  const ranked = comparison(fake, { series: { AAA: {} } }, "AAA", [2020]);
  assert.equal(ranked.year, null);
  assert.equal(ranked.rows[0].value, null);
});


test("chartGeometry maps values inside the padded box", () => {
  const geometry = chartGeometry(
    [
      { year: 2015, value: 10 },
      { year: 2016, value: 20 },
      { year: 2017, value: 30 },
    ],
    { width: 640, height: 260, padding: 36 }
  );
  assert.equal(geometry.segments.length, 1);
  assert.equal(geometry.markers.length, 3);
  assert.equal(geometry.segments[0][0].x, 36);
  assert.equal(geometry.segments[0][2].x, 640 - 36);
  assert.equal(geometry.markers[2].y, 36);
  assert.equal(geometry.markers[0].y, 260 - 36);
  assert.equal(geometry.min, 10);
  assert.equal(geometry.max, 30);
  assert.equal(geometry.zeroLine, null);
});

test("chartGeometry breaks the line at a gap instead of bridging it", () => {
  const geometry = chartGeometry([
    { year: 2015, value: 1 },
    { year: 2016, value: null },
    { year: 2017, value: 3 },
  ]);
  assert.equal(geometry.segments.length, 2);
  assert.equal(geometry.segments[0].length, 1);
  assert.equal(geometry.segments[1].length, 1);
});

test("chartGeometry survives flat and empty series", () => {
  const flat = chartGeometry([
    { year: 2015, value: 5 },
    { year: 2016, value: 5 },
  ]);
  assert.equal(flat.markers.length, 2);
  assert.equal(flat.markers[0].y, flat.markers[1].y);

  const empty = chartGeometry([{ year: 2015, value: null }]);
  assert.equal(empty.markers.length, 0);
  assert.equal(empty.min, null);
  assert.equal(empty.zeroLine, null);
});

test("chartGeometry draws a zero line when the series crosses zero", () => {
  const geometry = chartGeometry([
    { year: 2015, value: -10 },
    { year: 2016, value: 10 },
  ]);
  assert.ok(geometry.zeroLine !== null);
  assert.ok(geometry.zeroLine > 36 && geometry.zeroLine < 224);
});

test("toCsv covers every country and year, leaving gaps blank", () => {
  const fake = {
    countries: [
      { id: "AAA", name: "Alpha" },
      { id: "BBB", name: "Beta" },
    ],
  };
  const csv = toCsv(fake, { series: { AAA: { 2019: 1.5 }, BBB: {} } }, [2019, 2020]);
  const lines = csv.trimEnd().split("\n");
  assert.equal(lines[0], "country,country_id,2019,2020");
  assert.equal(lines[1], '"Alpha",AAA,1.5,');
  assert.equal(lines[2], '"Beta",BBB,,');
});

test("toCsv works on the real snapshot for every indicator", () => {
  for (const item of snapshot.indicators) {
    const csv = toCsv(snapshot, item, snapshot.years);
    assert.equal(csv.trimEnd().split("\n").length, snapshot.countries.length + 1);
    assert.ok(csv.includes("GHA"));
  }
});

