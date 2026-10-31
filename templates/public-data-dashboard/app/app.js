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
  seriesFor,
  toCsv,
} from "./dashboard.js";

const DATA_URL = "data/indicators.json";
const SVG_NS = "http://www.w3.org/2000/svg";
const state = { data: null, countryId: null, indicatorId: null };

const el = (id) => document.getElementById(id);

function parseState(data) {
  const params = new URLSearchParams(window.location.search);
  const country = params.get("country");
  const indicator = params.get("indicator");
  state.indicatorId = data.indicators.some((item) => item.id === indicator)
    ? indicator
    : data.default_indicator ?? data.indicators[0].id;
  state.countryId = data.countries.some((item) => item.id === country)
    ? country
    : data.default_country ?? data.countries[0].id;
}

function syncUrl() {
  const params = new URLSearchParams();
  params.set("country", state.countryId);
  params.set("indicator", state.indicatorId);
  window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
}

function fillSelect(select, items, value, labelFor) {
  select.replaceChildren(
    ...items.map((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = labelFor(item);
      option.selected = item.id === value;
      return option;
    })
  );
  select.disabled = false;
}

function setStatus(message) {
  const status = el("status");
  status.hidden = message === "";
  status.textContent = message;
}

function showError(message) {
  const box = el("error");
  box.hidden = false;
  box.textContent = message;
  setStatus("");
}

function svgNode(name, attributes = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    node.setAttribute(key, String(value));
  }
  return node;
}

function renderChart(indicator, country, points) {
  const svg = el("chart");
  svg.replaceChildren();
  const geometry = chartGeometry(points);
  const { width, height, padding, innerHeight, innerWidth, min, max } = geometry;

  if (geometry.markers.length === 0) {
    const note = svgNode("text", {
      x: width / 2,
      y: height / 2,
      "text-anchor": "middle",
      class: "chart-empty",
    });
    note.textContent = "No published values for this selection";
    svg.append(note);
    el("chart-desc").textContent = note.textContent;
    return;
  }

  for (let step = 0; step <= 3; step += 1) {
    const y = padding + (innerHeight / 3) * step;
    svg.append(
      svgNode("line", {
        x1: padding,
        x2: padding + innerWidth,
        y1: y,
        y2: y,
        class: "grid",
      })
    );
  }

  if (geometry.zeroLine !== null) {
    svg.append(
      svgNode("line", {
        x1: padding,
        x2: padding + innerWidth,
        y1: geometry.zeroLine,
        y2: geometry.zeroLine,
        class: "zero",
      })
    );
  }

  for (const segment of geometry.segments) {
    svg.append(
      svgNode("polyline", {
        points: segment.map((point) => `${point.x},${point.y}`).join(" "),
        class: "series",
      })
    );
  }

  const fmt = indicator.format;
  for (const marker of geometry.markers) {
    const dot = svgNode("circle", { cx: marker.x, cy: marker.y, r: 3.5, class: "dot" });
    const title = svgNode("title");
    title.textContent = `${marker.year}: ${formatValue(marker.value, fmt)}`;
    dot.append(title);
    svg.append(dot);
  }

  const label = (x, y, text, anchor, cls) => {
    const node = svgNode("text", { x, y, "text-anchor": anchor, class: cls });
    node.textContent = text;
    svg.append(node);
    return node;
  };

  label(padding, padding - 12, formatValue(max, fmt), "start", "axis-label");
  label(padding, padding + innerHeight + 18, formatValue(min, fmt), "start", "axis-label");

  const years = points.map((point) => point.year);
  const ticks = [years[0], years[Math.floor(years.length / 2)], years[years.length - 1]];
  ticks.forEach((year, index) => {
    const x = padding + (innerWidth / (years.length - 1 || 1)) * years.indexOf(year);
    label(x, padding + innerHeight + 18, String(year), index === 0 ? "start" : index === 2 ? "end" : "middle", "axis-label");
  });

  const latest = latestPoint(points);
  const first = points.find((point) => point.value !== null);
  el("chart-desc").textContent =
    `Line chart of ${indicator.name} for ${country.name}, ` +
    `${first.year} to ${latest.year}. Lowest ${formatValue(min, fmt)} in the window, ` +
    `highest ${formatValue(max, fmt)}, latest ${formatValue(latest.value, fmt)} in ${latest.year}.`;
  el("chart-legend").textContent =
    `${country.name} · ${indicator.name} · ${indicator.unit}. Gaps mean the provider has no published value for that year.`;
}


function renderTable(indicator, country, points) {
  const fmt = indicator.format;
  el("table-subtitle").textContent = `${country.name} · ${indicator.name} (${indicator.unit})`;
  el("table-body").replaceChildren(
    ...[...points].reverse().map((point) => {
      const row = document.createElement("tr");
      if (point.value === null) {
        row.className = "is-missing";
      }
      const year = document.createElement("th");
      year.scope = "row";
      year.textContent = String(point.year);
      const value = document.createElement("td");
      value.textContent =
        point.value === null ? "Not published" : formatValue(point.value, fmt);
      row.append(year, value);
      return row;
    })
  );
  el("table-panel").hidden = false;
}

function renderComparison(indicator, country, ranks) {
  const fmt = indicator.format;
  if (ranks.year === null) {
    el("compare-panel").hidden = true;
    return -1;
  }
  el("compare-subtitle").textContent =
    `Latest year every country reports: ${ranks.year} · ${indicator.unit}`;
  el("compare-body").replaceChildren(
    ...ranks.rows.map((row) => {
      const tr = document.createElement("tr");
      if (row.id === country.id) {
        tr.className = "is-selected";
      }
      const name = document.createElement("th");
      name.scope = "row";
      name.textContent = row.id === country.id ? `${row.name} (selected)` : row.name;
      const value = document.createElement("td");
      value.textContent = row.value === null ? "No data" : formatValue(row.value, fmt);
      tr.append(name, value);
      return tr;
    })
  );
  el("compare-panel").hidden = false;
  return ranks.rows.findIndex((row) => row.id === country.id);
}

function renderSource(data, indicator, country) {
  const entries = [
    ["Provider", data.source.name],
    ["Series", `${indicator.name} (${indicator.id})`],
    ["Unit", indicator.unit],
    ["Years in snapshot", `${data.years[0]}–${data.years[data.years.length - 1]}`],
    ["Snapshot generated", data.generated_at],
    ["License", data.source.license],
    ["Attribution", data.source.attribution],
    ["API", data.source.api],
  ];
  const list = el("source-list");
  list.replaceChildren(
    ...entries.flatMap(([term, description]) => {
      const dt = document.createElement("dt");
      dt.textContent = term;
      const dd = document.createElement("dd");
      dd.textContent = description;
      return [dt, dd];
    })
  );

  const link = el("indicator-link");
  link.href = indicator.source_url ?? data.source.site;
  link.textContent = `World Bank: ${indicator.name}`;
  link.setAttribute("aria-label", `Open the World Bank series for ${indicator.name}`);
  el("chart-subtitle").textContent = `${country.name} · ${indicator.unit}`;
}


function renderKpis(indicator, points, rankIndex, ranks) {
  const fmt = indicator.format;
  const latest = latestPoint(points);
  const change = changeBetween(points);
  const peak = peakPoint(points);

  el("kpi-latest").textContent = latest ? formatValue(latest.value, fmt) : "No data";
  el("kpi-latest-meta").textContent = latest
    ? `in ${latest.year} · ${indicator.unit}`
    : "Nothing published for the years in this snapshot";

  if (change) {
    el("kpi-change").textContent = formatDelta(change.absolute, fmt);
    const percent =
      change.percent === null ? "" : ` · ${formatDelta(change.percent, "decimal1")}%`;
    el("kpi-change-meta").textContent =
      `${change.from.year} → ${change.to.year}${percent}`;
  } else {
    el("kpi-change").textContent = "—";
    el("kpi-change-meta").textContent = "Needs at least two published years";
  }

  el("kpi-peak").textContent = peak ? formatValue(peak.value, fmt) : "No data";
  el("kpi-peak-meta").textContent = peak ? `in ${peak.year}` : "—";

  if (rankIndex >= 0) {
    el("kpi-rank").textContent = `#${rankIndex + 1} of ${ranks.rows.length}`;
    el("kpi-rank-meta").textContent = `shared year ${ranks.year}`;
  } else {
    el("kpi-rank").textContent = "—";
    el("kpi-rank-meta").textContent = "No shared year to compare";
  }
}

function render() {
  const data = state.data;
  const indicator = findIndicator(data, state.indicatorId);
  const country = findCountry(data, state.countryId);
  const points = seriesFor(indicator, country.id, data.years);
  const ranks = comparison(data, indicator, country.id, data.years);
  const rankIndex = renderComparison(indicator, country, ranks);

  renderKpis(indicator, points, rankIndex, ranks);
  renderChart(indicator, country, points);
  renderTable(indicator, country, points);
  renderSource(data, indicator, country);

  el("summary").hidden = false;
  el("chart-panel").hidden = false;
  el("download-csv").disabled = false;
  el("copy-link").disabled = false;
  setStatus("");
  syncUrl();
}

function downloadCsv() {
  const data = state.data;
  const indicator = findIndicator(data, state.indicatorId);
  const csv = toCsv(data, indicator, data.years);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const stamp = (data.generated_at ?? "").slice(0, 10) || "snapshot";
  link.href = url;
  link.download = `${indicator.id}-${stamp}.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setStatus(`Downloaded ${link.download} with ${data.countries.length} countries.`);
}

async function copyLink() {
  try {
    await navigator.clipboard.writeText(window.location.href);
    setStatus("Link copied — it reopens this exact view.");
  } catch {
    setStatus(`Copy failed. The address bar already holds this view: ${window.location.href}`);
  }
}

function bindControls() {
  el("country-select").addEventListener("change", (event) => {
    state.countryId = event.target.value;
    render();
  });
  el("indicator-select").addEventListener("change", (event) => {
    state.indicatorId = event.target.value;
    render();
  });
  el("download-csv").addEventListener("click", downloadCsv);
  el("copy-link").addEventListener("click", copyLink);
  el("controls").addEventListener("submit", (event) => event.preventDefault());
}

async function boot() {
  bindControls();
  try {
    const response = await fetch(DATA_URL, { cache: "no-cache" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} for ${DATA_URL}`);
    }
    const data = await response.json();
    if (!Array.isArray(data.indicators) || data.indicators.length === 0) {
      throw new Error("the snapshot has no indicators");
    }
    state.data = data;
    parseState(data);
    fillSelect(
      el("country-select"),
      data.countries,
      state.countryId,
      (item) => `${item.name} (${item.id})`
    );
    fillSelect(el("indicator-select"), data.indicators, state.indicatorId, (item) => item.name);
    render();
  } catch (error) {
    showError(
      `Could not load ${DATA_URL}: ${error.message}. Serve the folder over HTTP ` +
        "(python3 -m http.server 8000) rather than opening the file directly, " +
        "and check that app/data/indicators.json exists."
    );
  }
}

boot();

