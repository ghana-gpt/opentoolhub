/**
 * Pure helpers for the open data dashboard.
 *
 * Nothing in this module touches the DOM, so the same functions that render
 * the page can be exercised with Node:
 *
 *   node --input-type=module -e "import('./dashboard.js').then(m => ...)"
 */

const FORMATTERS = {
  integer: new Intl.NumberFormat("en", { maximumFractionDigits: 0 }),
  currency: new Intl.NumberFormat("en", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }),
  decimal1: new Intl.NumberFormat("en", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }),
  decimal2: new Intl.NumberFormat("en", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }),
};

export function formatValue(value, format = "decimal1") {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "No data";
  }
  const formatter = FORMATTERS[format] ?? FORMATTERS.decimal1;
  return formatter.format(value);
}

export function formatDelta(value, format) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "No comparable data";
  }
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatValue(Math.abs(value), format)}`;
}

export function findIndicator(data, indicatorId) {
  return data.indicators.find((item) => item.id === indicatorId) ?? data.indicators[0];
}

export function findCountry(data, countryId) {
  return data.countries.find((item) => item.id === countryId) ?? data.countries[0];
}

/** One point per year, with nulls kept so gaps are visible instead of hidden. */
export function seriesFor(indicator, countryId, years) {
  const series = indicator.series[countryId] ?? {};
  return years.map((year) => {
    const raw = series[String(year)];
    const value = typeof raw === "number" && Number.isFinite(raw) ? raw : null;
    return { year, value };
  });
}

export function presentPoints(points) {
  return points.filter((point) => point.value !== null);
}

export function latestPoint(points) {
  return [...presentPoints(points)].sort((a, b) => b.year - a.year)[0] ?? null;
}

export function firstPoint(points) {
  return [...presentPoints(points)].sort((a, b) => a.year - b.year)[0] ?? null;
}

/** Change between the first and last available year, not the calendar range. */
export function changeBetween(points) {
  const first = firstPoint(points);
  const last = latestPoint(points);
  if (!first || !last || first.year === last.year) {
    return null;
  }
  return {
    from: first,
    to: last,
    absolute: last.value - first.value,
    percent: first.value === 0 ? null : ((last.value - first.value) / first.value) * 100,
  };
}

export function peakPoint(points) {
  return presentPoints(points).reduce(
    (best, point) => (best === null || point.value > best.value ? point : best),
    null
  );
}

/**
 * Compare the selected country with the others for the newest year every
 * country reports, so the ranking is not distorted by missing values.
 */
export function comparison(data, indicator, selectedCountryId, years) {
  const rows = data.countries.map((country) => {
    const points = presentPoints(seriesFor(indicator, country.id, years));
    const latest = points[points.length - 1] ?? null;
    return { ...country, year: latest?.year ?? null, value: latest?.value ?? null };
  });
  const sharedYear = Math.min(
    ...rows.filter((row) => row.year !== null).map((row) => row.year)
  );
  return {
    year: Number.isFinite(sharedYear) ? sharedYear : null,
    rows: rows.sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity)),
    selectedCountryId,
  };
}

/** Map points to SVG coordinates; gaps break the line rather than bridging it. */
export function chartGeometry(points, { width = 640, height = 260, padding = 36 } = {}) {
  const values = presentPoints(points).map((point) => point.value);
  const innerWidth = width - padding * 2;
  const innerHeight = height - padding * 2;
  const step = points.length > 1 ? innerWidth / (points.length - 1) : 0;

  const segments = [];
  let current = [];
  const markers = [];
  if (values.length === 0) {
    return {
      width,
      height,
      padding,
      innerWidth,
      innerHeight,
      min: null,
      max: null,
      segments,
      markers,
      zeroLine: null,
    };
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  points.forEach((point, index) => {
    if (point.value === null) {
      if (current.length) {
        segments.push(current);
        current = [];
      }
      return;
    }
    const x = padding + step * index;
    const y = padding + innerHeight - ((point.value - min) / span) * innerHeight;
    const coords = { x: Number(x.toFixed(2)), y: Number(y.toFixed(2)), ...point };
    current.push(coords);
    markers.push(coords);
  });
  if (current.length) {
    segments.push(current);
  }

  return {
    width,
    height,
    padding,
    innerWidth,
    innerHeight,
    min,
    max,
    segments,
    markers,
    zeroLine: initialZeroLine({ min, max, padding, innerHeight }),
  };
}

function initialZeroLine({ min, max, padding, innerHeight }) {
  if (min > 0 || max < 0) {
    return null;
  }
  const span = max - min || 1;
  return Number((padding + innerHeight - ((0 - min) / span) * innerHeight).toFixed(2));
}

export function toCsv(data, indicator, years) {
  const header = ["country", "country_id", ...years.map(String)];
  const lines = [header.join(",")];
  for (const country of data.countries) {
    const cells = years.map((year) => {
      const value = indicator.series[country.id]?.[String(year)];
      return typeof value === "number" ? String(value) : "";
    });
    lines.push([JSON.stringify(country.name), country.id, ...cells].join(","));
  }
  return `${lines.join("\n")}\n`;
}
