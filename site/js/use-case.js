/** Render one use case with its stacks, APIs, templates, and example. */

import {
  loadData,
  stacksForUseCase,
  templatesForUseCase,
  examplesForUseCase,
  apisForStack,
} from "./data.js";
import {
  qs,
  escapeHtml,
  setBusy,
  setReady,
  showError,
  readParams,
  categoryLinks,
  difficultyBadge,
  repoLink,
  statusBadge,
} from "./ui.js";
import { renderStackCard, renderUseCaseCard } from "./render.js";

function renderNotFound(detail, message) {
  setReady(detail);
  detail.innerHTML = `
    <div class="state state-error" role="alert">
      <h1>Use case not found</h1>
      <p>${escapeHtml(message)}</p>
      <p><a class="button secondary" href="use-cases.html">Browse all use cases</a></p>
    </div>`;
}

function updateMetadata(useCase, stacks, data) {
  const canonical = qs('link[rel="canonical"]');
  const siteUrl = canonical
    ? new URL(".", canonical.href).href
    : new URL("./", window.location.href).href;
  const url = `${siteUrl}use-case.html?id=${encodeURIComponent(useCase.id)}`;
  const title = `${useCase.name} | OpenToolHub`;

  document.title = title;
  const setContent = (selector, value) => {
    const element = qs(selector);
    if (element) {
      element.setAttribute("content", value);
    }
  };
  if (canonical) {
    canonical.setAttribute("href", url);
  }
  const descriptionTags = [
    'meta[name="description"]',
    'meta[property="og:description"]',
    'meta[name="twitter:description"]',
  ];
  for (const selector of descriptionTags) {
    setContent(selector, useCase.summary);
  }
  const titleTags = [
    'meta[property="og:title"]',
    'meta[name="twitter:title"]',
  ];
  for (const selector of titleTags) {
    setContent(selector, title);
  }
  setContent('meta[property="og:url"]', url);
  setContent('meta[property="og:type"]', "article");

  const categories = useCase.categories
    .map((id) => data.categoryById.get(id))
    .filter(Boolean);
  const apis = new Map();
  for (const stack of stacks) {
    for (const api of apisForStack(stack, data)) {
      apis.set(api.id, api);
    }
  }
  const structuredData = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebSite",
        "@id": `${siteUrl}#website`,
        "url": siteUrl,
        "name": "OpenToolHub",
      },
      {
        "@type": "WebPage",
        "@id": `${url}#page`,
        "url": url,
        "name": title,
        "description": useCase.summary,
        "isPartOf": { "@id": `${siteUrl}#website` },
        "mainEntity": { "@id": `${url}#article` },
      },
      {
        "@type": "TechArticle",
        "@id": `${url}#article`,
        "headline": useCase.name,
        "description": useCase.summary,
        "about": categories.map((category) => ({
          "@type": "Thing",
          "name": category.name,
        })),
        "mentions": [...apis.values()].map((api) => ({
          "@type": "SoftwareApplication",
          "name": api.name,
          "url": api.url,
        })),
        "mainEntityOfPage": { "@id": `${url}#page` },
      },
      {
        "@type": "BreadcrumbList",
        "itemListElement": [
          {
            "@type": "ListItem",
            "position": 1,
            "name": "OpenToolHub",
            "item": siteUrl,
          },
          {
            "@type": "ListItem",
            "position": 2,
            "name": "Use cases",
            "item": `${siteUrl}use-cases.html`,
          },
          {
            "@type": "ListItem",
            "position": 3,
            "name": useCase.name,
            "item": url,
          },
        ],
      },
    ],
  };
  let script = qs("#use-case-structured-data");
  if (!script) {
    script = document.createElement("script");
    script.type = "application/ld+json";
    script.id = "use-case-structured-data";
    document.head.append(script);
  }
  script.textContent = JSON.stringify(structuredData).replace(/</g, "\\u003c");
}

function renderRelated(useCase, data) {
  const related = data.useCases
    .filter((candidate) => candidate.id !== useCase.id)
    .map((candidate) => ({
      useCase: candidate,
      overlap: candidate.categories.filter((id) =>
        useCase.categories.includes(id)
      ).length,
    }))
    .filter((item) => item.overlap > 0)
    .sort(
      (left, right) =>
        right.overlap - left.overlap ||
        left.useCase.name.localeCompare(right.useCase.name)
    )
    .slice(0, 3);
  if (!related.length) {
    return "";
  }
  return `
    <section class="section">
      <div class="section-head">
        <span class="eyebrow">Keep exploring</span>
        <h2>Related use cases</h2>
      </div>
      <div class="grid three">
        ${related
          .map(({ useCase: candidate }) => renderUseCaseCard(candidate, data))
          .join("")}
      </div>
    </section>`;
}

async function init() {
  const detail = qs("#use-case-detail");
  const crumb = qs("#use-case-crumb");
  if (!detail) {
    return;
  }

  setBusy(detail, "Loading use case…");

  let data;
  try {
    data = await loadData();
  } catch (error) {
    showError(detail, error);
    return;
  }

  const { id } = readParams(["id"]);
  const useCase = data.useCaseById.get(id.trim());
  if (!useCase) {
    renderNotFound(
      detail,
      id
        ? `No use case with the id "${id}" is registered.`
        : "Add ?id=<use-case-id> to the URL to open a specific use case."
    );
    return;
  }

  const stacks = stacksForUseCase(useCase, data);
  const templates = templatesForUseCase(useCase, data);
  const examples = examplesForUseCase(useCase, data);
  const apiIds = new Set(
    stacks.flatMap((stack) =>
      apisForStack(stack, data).map((api) => api.id)
    )
  );
  updateMetadata(useCase, stacks, data);
  if (crumb) {
    crumb.textContent = useCase.name;
  }
  const primary = stacks[0];

  detail.innerHTML = `
    <header class="page-header">
      <span class="eyebrow">Use case</span>
      <h1>${escapeHtml(useCase.name)}</h1>
      <p class="lead">${escapeHtml(useCase.summary)}</p>
      <p class="muted"><strong>Goal:</strong> ${escapeHtml(useCase.goal)}</p>
      <div class="tag-list">${categoryLinks(useCase.categories, data)}</div>
      <p class="small muted">Built for: ${useCase.personas
        .map((persona) => escapeHtml(persona))
        .join(", ")}</p>
      <dl class="fact-grid detail-facts" aria-label="Path at a glance">
        <div><dt>Difficulty</dt><dd>${
          primary ? difficultyBadge(primary.difficulty) : "Not rated"
        }</dd></div>
        <div><dt>Stacks</dt><dd>${stacks.length}</dd></div>
        <div><dt>APIs</dt><dd>${apiIds.size}</dd></div>
        <div><dt>Templates</dt><dd>${templates.length}</dd></div>
        <div><dt>Examples</dt><dd>${examples.length}</dd></div>
      </dl>
    </header>

    <div class="detail-grid">
      <section class="panel" id="stacks" aria-labelledby="stacks-title">
        <h2 id="stacks-title">Stack${stacks.length === 1 ? "" : "s"}</h2>
        ${
          stacks.length
            ? stacks
                .map((stack) =>
                  renderStackCard(stack, data, {
                    detailed: true,
                    showUseCase: false,
                  })
                )
                .join("")
            : `<p class="muted">No stack is registered for this use case yet. <a class="text-link" href="stacks.html">Browse every stack</a>.</p>`
        }
      </section>

      <aside class="panel" id="start-here" aria-labelledby="start-here-title">
        <h2 id="start-here-title">Start here</h2>
        ${
          templates.length
            ? `<ul class="link-list">${templates
                .map(
                  (template) =>
                    `<li>${repoLink(template.path, template.name)} ${statusBadge(
                      template.status
                    )}<br /><span class="muted small">${escapeHtml(
                      template.description
                    )}</span></li>`
                )
                .join("")}</ul>`
            : `<p class="muted">No template is registered for this use case.</p>`
        }
        <h3>Worked example</h3>
        ${
          examples.length
            ? `<ul class="link-list">${examples
                .map(
                  (example) =>
                    `<li>${repoLink(example.path, example.title)}<br /><span class="muted small">${escapeHtml(
                      example.summary
                    )}</span></li>`
                )
                .join("")}</ul>`
            : `<p class="muted">No example is registered for this use case.</p>`
        }
        <h3>Use it from the CLI</h3>
        <pre><code>python3 scripts/recommend.py ${escapeHtml(useCase.id)}</code></pre>
        <p class="small muted">
          Prefer browsing?
          <a class="text-link" href="use-cases.html">Browse every use case</a>
          or run <code>python3 scripts/recommend.py --list</code>.
        </p>
      </aside>
    </div>

    ${renderRelated(useCase, data)}`;
  setReady(detail);
}

init();
