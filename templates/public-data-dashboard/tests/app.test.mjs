// Boots the real app.js against a tiny DOM stub so rendering bugs surface
// without a browser. Run with: node --test tests/*.test.mjs
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const snapshotText = await readFile(
  new URL("../app/data/indicators.json", import.meta.url),
  "utf8"
);

class StubElement {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.className = "";
    this.removed = false;
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  replaceChildren(...nodes) {
    this.children = [...nodes];
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes[name];
  }

  addEventListener(type, handler) {
    (this.listeners[type] ??= []).push(handler);
  }

  dispatch(type) {
    for (const handler of this.listeners[type] ?? []) {
      handler({ target: this, preventDefault() {} });
    }
  }

  click() {
    this.dispatch("click");
  }

  remove() {
    this.removed = true;
  }
}

function installDom({ search = "", fetchImpl } = {}) {
  const registry = new Map();
  const body = new StubElement("body");
  const document = {
    body,
    getElementById(id) {
      if (!registry.has(id)) {
        registry.set(id, new StubElement("div"));
      }
      return registry.get(id);
    },
    createElement(tag) {
      return new StubElement(tag);
    },
    createElementNS(_ns, tag) {
      return new StubElement(tag);
    },
  };
  const location = {
    pathname: "/app/index.html",
    search,
    href: `http://127.0.0.1:8000/app/index.html${search}`,
  };
  const history = {
    lastUrl: null,
    replaceState(_state, _title, url) {
      this.lastUrl = url;
    },
  };
  const clipboard = { copied: null };

  globalThis.document = document;
  globalThis.window = { location, history };
  Object.defineProperty(globalThis, "navigator", {
    value: {
      clipboard: {
        async writeText(text) {
          clipboard.copied = text;
        },
      },
    },
    configurable: true,
    writable: true,
  });
  globalThis.URL.createObjectURL = () => "blob:stub";
  globalThis.URL.revokeObjectURL = () => {};
  globalThis.fetch =
    fetchImpl ??
    (async () => ({
      ok: true,
      status: 200,
      async json() {
        return JSON.parse(snapshotText);
      },
    }));

  // Mirror the `hidden` attributes the real markup ships with, so the tests can
  // prove that rendering (not the stub) made a panel visible.
  for (const id of ["error", "summary", "chart-panel", "table-panel", "compare-panel"]) {
    document.getElementById(id).hidden = true;
  }

  return { document, registry, body, location, history, clipboard };
}


test("the page renders real data and reacts to the controls", async () => {
  const dom = installDom();
  await import("../app/app.js?case=happy-path");
  await settle();

  const { registry, history, clipboard } = dom;
  const text = (id) => registry.get(id)?.textContent;
  const select = registry.get("country-select");
  const indicators = registry.get("indicator-select");

  assert.equal(
    registry.get("error").hidden,
    true,
    `no error banner on success (got: ${registry.get("error").textContent})`
  );
  assert.equal(registry.get("status").hidden, true, "status clears after load");
  assert.equal(select.disabled, false);
  assert.equal(select.children.length, 4, "one option per country");
  assert.equal(indicators.children.length, 6, "one option per indicator");
  assert.equal(registry.get("summary").hidden, false);
  assert.equal(registry.get("chart-panel").hidden, false);
  assert.equal(registry.get("table-panel").hidden, false);
  assert.equal(registry.get("compare-panel").hidden, false);

  assert.equal(text("kpi-latest"), "34,427,414");
  assert.match(text("kpi-latest-meta"), /^in 2024 · people$/);
  assert.match(text("kpi-change"), /^\+/);
  assert.equal(text("kpi-peak"), "34,427,414");
  assert.match(text("kpi-rank"), /^#4 of 4$/, "Ghana is the smallest of the four");

  const chart = registry.get("chart");
  assert.ok(chart.children.length > 10, "chart draws grid, line, dots, labels");
  assert.equal(
    chart.children.filter((child) => child.tagName === "circle").length,
    10,
    "one marker per published year"
  );
  assert.equal(registry.get("table-body").children.length, 10);
  assert.equal(registry.get("compare-body").children.length, 4);
  assert.equal(registry.get("source-list").children.length, 16);
  assert.match(
    registry.get("indicator-link").getAttribute("aria-label"),
    /Population, total/
  );
  assert.equal(history.lastUrl, "/app/index.html?country=GHA&indicator=SP.POP.TOTL");

  indicators.value = "SP.DYN.LE00.IN";
  indicators.dispatch("change");
  assert.match(text("kpi-latest-meta"), /^in 2024 · years$/);
  assert.equal(
    history.lastUrl,
    "/app/index.html?country=GHA&indicator=SP.DYN.LE00.IN"
  );

  select.value = "KEN";
  select.dispatch("change");
  assert.equal(history.lastUrl, "/app/index.html?country=KEN&indicator=SP.DYN.LE00.IN");
  assert.match(registry.get("chart-desc").textContent, /Kenya/);

  registry.get("download-csv").dispatch("click");
  const link = dom.body.children.find((node) => node.download);
  assert.match(link.download, /^SP\.DYN\.LE00\.IN-\d{4}-\d{2}-\d{2}\.csv$/);
  assert.equal(link.removed, true, "the temporary download link is cleaned up");
  assert.match(text("status"), /^Downloaded SP\.DYN\.LE00\.IN-/);

  registry.get("copy-link").dispatch("click");
  await settle();
  assert.equal(clipboard.copied, dom.location.href);
});

test("the page explains a missing snapshot instead of failing silently", async () => {
  const dom = installDom({
    fetchImpl: async () => ({ ok: false, status: 404 }),
  });
  await import("../app/app.js?case=missing-snapshot");
  await settle();

  const box = dom.registry.get("error");
  assert.equal(box.hidden, false);
  assert.match(box.textContent, /HTTP 404/);
  assert.match(box.textContent, /python3 -m http\.server 8000/);
  assert.equal(dom.registry.get("status").hidden, true);
});

test("the page honours country and indicator from the URL", async () => {
  const dom = installDom({ search: "?country=BRA&indicator=EG.ELC.ACCS.ZS" });
  await import("../app/app.js?case=deeplink");
  await settle();

  const select = dom.registry.get("country-select");
  const indicators = dom.registry.get("indicator-select");
  assert.equal(select.children.find((option) => option.selected).value, "BRA");
  assert.equal(
    indicators.children.find((option) => option.selected).value,
    "EG.ELC.ACCS.ZS"
  );
  assert.match(dom.registry.get("chart-legend").textContent, /Brazil/);
  assert.equal(dom.history.lastUrl, "/app/index.html?country=BRA&indicator=EG.ELC.ACCS.ZS");
});

test("an unknown query parameter falls back to the snapshot default", async () => {
  const dom = installDom({ search: "?country=ZZZ&indicator=NOPE" });
  await import("../app/app.js?case=fallback");
  await settle();

  assert.equal(
    dom.history.lastUrl,
    "/app/index.html?country=GHA&indicator=SP.POP.TOTL"
  );
});

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
