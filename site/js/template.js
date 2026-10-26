/** Render one starter template as an actionable build brief. */

import {
  loadData,
  stacksForUseCase,
  apisForStack,
  examplesForUseCase,
} from "./data.js";
import {
  qs,
  escapeHtml,
  setBusy,
  setReady,
  showError,
  readParams,
  categoryLinks,
  statusBadge,
  difficultyBadge,
  repoLink,
  useCaseLink,
  pill,
  countLabel,
} from "./ui.js";
import { renderStackCard, renderExampleCard } from "./render.js";

function humanize(value) {
  const text = String(value ?? "").replace(/[-_]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Not stated";
}

function renderNotFound(detail, message) {
  setReady(detail);
  detail.innerHTML = `
    <div class="state state-error" role="alert">
      <h1>Template not found</h1>
      <p>${escapeHtml(message)}</p>
      <p><a class="button secondary" href="templates.html">Browse all templates</a></p>
    </div>`;
}

/**
 * An ordered, provider-agnostic plan. Every step is something a builder can do
 * today with the linked documentation; nothing here claims that runnable
 * application code already exists in the repository.
 */
function buildSteps(useCase, stacks, apis) {
  const primary = stacks[0];
  const authKinds = [...new Set(apis.map((api) => humanize(api.auth)))].join(", ");
  return [
    {
      title: "Read the written brief",
      detail:
        "The template README sets out the problem, the primary screen, and the stack slots before any code is written.",
    },
    {
      title: "Confirm API access and terms",
      detail: apis.length
        ? `You will call ${countLabel(
            apis.length,
            "API"
          )}. Access types: ${authKinds}. Check pricing and terms at each provider's documentation before you build.`
        : "No API is registered for this template yet, so start from the use case and pick a stack.",
    },
    {
      title: "Start with one vertical slice",
      detail: primary
        ? `Wire the smallest slice of "${primary.name}" first: one data source, one screen, one honest empty state. Add the other tools once that slice works.`
        : "Pick a single data source and one screen before adding anything else.",
    },
    {
      title: "Make the goal visible on screen",
      detail: `The screen exists to answer one question: ${useCase.goal}`,
    },
    {
      title: "Design the failure path",
      detail:
        "Provider timeouts, rate limits, and empty responses are normal. Ship a timeout, a retry, and a visible fallback before you ship polish.",
    },
    {
      title: "Record freshness and attribution",
      detail:
        "Note each provider's data freshness and licensing where users can see it, and update the template's freshness line when you review the stack.",
    },
  ];
}
function buildBrief(template, useCase, categories, stacks, apis, steps) {
  return {
    template: {
      id: template.id,
      name: template.name,
      status: template.status,
      brief: template.path,
    },
    use_case: { id: useCase.id, name: useCase.name, goal: useCase.goal },
    categories: categories.map((category) => ({
      id: category.id,
      name: category.name,
    })),
    stacks: stacks.map((stack) => ({
      id: stack.id,
      name: stack.name,
      difficulty: stack.difficulty,
      tools: stack.tools.map((tool) => ({
        slot: tool.slot,
        category: tool.category,
        api_ids: tool.api_ids,
      })),
    })),
    apis: apis.map((api) => ({
      id: api.id,
      name: api.name,
      url: api.url,
      docs_url: api.docs_url,
      auth: api.auth,
      pricing: api.pricing,
      data_freshness: api.data_freshness,
      integration_complexity: api.integration_complexity,
    })),
    checklist: steps.map((step) => step.title),
    note: "Generated from the OpenToolHub catalog. Verify provider terms before shipping.",
  };
}

function updateMetadata(template, useCase, categories) {
  const canonical = qs('link[rel="canonical"]');
  const siteUrl = canonical
    ? new URL(".", canonical.href).href
    : new URL("./", window.location.href).href;
  const url = `${siteUrl}template.html?id=${encodeURIComponent(template.id)}`;
  const title = `${template.name} starter | OpenToolHub`;
  const description = `${template.description} A build brief for the ${
    useCase.name
  } use case with ${countLabel(categories.length, "area")} and the APIs to call.`;

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
  for (const selector of [
    'meta[name="description"]',
    'meta[property="og:description"]',
    'meta[name="twitter:description"]',
  ]) {
    setContent(selector, description);
  }
  for (const selector of [
    'meta[property="og:title"]',
    'meta[name="twitter:title"]',
  ]) {
    setContent(selector, title);
  }
  setContent('meta[property="og:url"]', url);
  setContent('meta[property="og:type"]', "article");

  const node = qs("#template-structured-data");
  if (!node) {
    return;
  }
  node.textContent = JSON.stringify(
    {
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
          "description": description,
          "isPartOf": { "@id": `${siteUrl}#website` },
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
              "name": "Templates",
              "item": `${siteUrl}templates.html`,
            },
            {
              "@type": "ListItem",
              "position": 3,
              "name": template.name,
              "item": url,
            },
          ],
        },
      ],
    },
    null,
    2
  );
}

function relatedTemplates(template, data) {
  return data.templates
    .filter((other) => other.id !== template.id)
    .map((other) => ({
      template: other,
      shared: other.category_ids.filter((id) =>
        template.category_ids.includes(id)
      ).length,
    }))
    .filter((entry) => entry.shared > 0)
    .sort(
      (left, right) =>
        right.shared - left.shared ||
        left.template.name.localeCompare(right.template.name)
    )
    .slice(0, 3)
    .map((entry) => entry.template);
}

function renderApiBrief(api) {
  return `
    <li class="api-inline">
      <a class="api-name" href="${escapeHtml(api.url)}" rel="noopener">${escapeHtml(
        api.name
      )}</a>
      ${pill(humanize(api.auth))}
      <span class="api-meta">${escapeHtml(humanize(api.pricing))} · ${escapeHtml(
        humanize(api.integration_complexity)
      )} integration · ${escapeHtml(humanize(api.data_freshness))} data</span>
      <br /><span class="muted small">${escapeHtml(api.description)}</span>
      <br /><span class="small"><a class="text-link" href="${escapeHtml(
        api.docs_url
      )}" rel="noopener">Official docs</a></span>
    </li>`;
}
async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.position = "absolute";
  field.style.left = "-9999px";
  document.body.append(field);
  field.select();
  const copied = document.execCommand?.("copy");
  field.remove();
  if (!copied) {
    throw new Error("Clipboard access is unavailable in this browser.");
  }
}

async function init() {
  const detail = qs("#template-detail");
  const crumb = qs("#template-crumb");
  const status = qs("#brief-status");
  if (!detail) {
    return;
  }

  setBusy(detail, "Loading template…");

  let data;
  try {
    data = await loadData();
  } catch (error) {
    showError(detail, error);
    return;
  }

  const params = readParams(["id"]);
  const requestedId = (params.id || "").trim();
  const template = requestedId
    ? data.templateById.get(requestedId) ?? null
    : data.templates[0] ?? null;
  if (!template) {
    renderNotFound(
      detail,
      requestedId
        ? `No template in the catalog has the id "${requestedId}".`
        : "The catalog has no templates yet."
    );
    return;
  }

  const useCase = template.use_case_ids
    .map((id) => data.useCaseById.get(id))
    .find(Boolean);
  if (!useCase) {
    renderNotFound(
      detail,
      `${template.name} is not linked to a use case, so there is no brief to assemble.`
    );
    return;
  }

  const categories = template.category_ids
    .map((id) => data.categoryById.get(id))
    .filter(Boolean);
  const stacks = stacksForUseCase(useCase, data);
  const apis = [
    ...new Map(
      stacks
        .flatMap((stack) => apisForStack(stack, data))
        .map((api) => [api.id, api])
    ).values(),
  ];
  const examples = examplesForUseCase(useCase, data);
  const steps = buildSteps(useCase, stacks, apis);
  const brief = buildBrief(template, useCase, categories, stacks, apis, steps);
  const briefText = JSON.stringify(brief, null, 2);
  const related = relatedTemplates(template, data);
  const primary = stacks[0];

  updateMetadata(template, useCase, categories);
  if (crumb) {
    crumb.textContent = template.name;
  }

  detail.innerHTML = `    <header class="page-header">
      <span class="eyebrow">Starter template</span>
      <h1>${escapeHtml(template.name)}</h1>
      <p class="lead">${escapeHtml(template.description)}</p>
      <p>${statusBadge(template.status)} ${template.tags
        .map((tag) => pill(tag))
        .join(" ")}</p>
      <div class="tag-list">${categoryLinks(
        template.category_ids,
        data,
        "templates"
      )}</div>
      <p class="muted">Built from the ${useCaseLink(
        useCase,
        useCase.name
      )} use case.</p>
      <dl class="fact-grid detail-facts" aria-label="Starter at a glance">
        <div><dt>Difficulty</dt><dd>${
          primary ? difficultyBadge(primary.difficulty) : "Not rated"
        }</dd></div>
        <div><dt>Stacks</dt><dd>${stacks.length}</dd></div>
        <div><dt>APIs</dt><dd>${apis.length}</dd></div>
        <div><dt>Areas</dt><dd>${categories.length}</dd></div>
        <div><dt>Build steps</dt><dd>${steps.length}</dd></div>
      </dl>
      <div class="cta-row">
        <a class="button primary" href="#build-order">See the build order</a>
        ${repoLink(
          template.path,
          "Read the full brief",
          "button secondary",
          `Read the ${template.name} brief in the repository`
        )}
      </div>
    </header>

    <div class="detail-grid">
      <section class="panel" id="what" aria-labelledby="what-title">
        <h2 id="what-title">What you are building</h2>
        <p>${escapeHtml(useCase.summary)}</p>
        <p><strong>Goal:</strong> ${escapeHtml(useCase.goal)}</p>
        <p class="muted small">Built for: ${useCase.personas
          .map((persona) => escapeHtml(persona))
          .join(", ")}</p>
        ${
          primary
            ? `<h3>Stacks in this brief</h3>${stacks
                .map((stack) =>
                  renderStackCard(stack, data, {
                    detailed: true,
                    showUseCase: false,
                  })
                )
                .join("")}`
            : `<p class="muted">No stack is registered for this use case yet. <a class="text-link" href="stacks.html">Browse every stack</a>.</p>`
        }
      </section>

      <aside class="panel" id="build-order" aria-labelledby="build-order-title">
        <h2 id="build-order-title">Build order</h2>
        <p class="small muted">
          A written plan, not generated code. Each step points at the provider
          documentation you need.
        </p>
        <ol class="link-list">
          ${steps
            .map(
              (step) =>
                `<li><strong>${escapeHtml(step.title)}</strong><br /><span class="muted small">${escapeHtml(
                  step.detail
                )}</span></li>`
            )
            .join("")}
        </ol>
        <p class="small muted">
          Prefer the terminal?
          <code>python3 scripts/recommend.py ${escapeHtml(useCase.id)}</code>
        </p>
      </aside>
    </div>

    <section class="panel" id="apis" aria-labelledby="apis-title">
      <h2 id="apis-title">APIs to call</h2>
      <p class="small muted">
        Access, pricing, integration effort, and update cadence come from the
        catalog. Confirm both pricing and terms at the provider before shipping.
      </p>
      ${
        apis.length
          ? `<ul class="link-list">${apis.map(renderApiBrief).join("")}</ul>`
          : `<p class="muted">No API is registered for this starter yet. <a class="text-link" href="apis.html">Browse every API</a>.</p>`
      }
    </section>

    <section class="panel" id="copy-brief" aria-labelledby="copy-brief-title">
      <h2 id="copy-brief-title">Copy the brief</h2>
      <p class="small muted">
        Paste this into an issue, a README, or your own editor. It contains
        catalog identifiers and links only, so review it before you share it.
      </p>
      <div class="cta-row">
        <button type="button" class="button secondary" data-copy-brief>
          Copy brief as JSON
        </button>
        <a class="button secondary" href="data/templates.json">Raw template data</a>
      </div>
      <pre class="brief-code" tabindex="0" role="region" aria-label="Build brief JSON"><code>${escapeHtml(
        briefText
      )}</code></pre>
    </section>

    <section class="panel" id="examples" aria-labelledby="examples-title">
      <h2 id="examples-title">Worked example</h2>
      ${
        examples.length
          ? examples.map(renderExampleCard).join("")
          : `<p class="muted">No worked example is registered for this use case yet. <a class="text-link" href="use-cases.html">Browse every use case</a>.</p>`
      }
    </section>

    ${
      related.length
        ? `<section class="panel" id="related" aria-labelledby="related-title">
             <h2 id="related-title">Related templates</h2>
             <ul class="link-list">
               ${related
                 .map(
                   (other) =>
                     `<li><a class="text-link" href="template.html?id=${encodeURIComponent(
                       other.id
                     )}">${escapeHtml(other.name)}</a> ${statusBadge(
                       other.status
                     )}<br /><span class="muted small">${escapeHtml(
                       other.description
                     )}</span></li>`
                 )
                 .join("")}
             </ul>
           </section>`
        : ""
    }`;

  // Keep the copy result next to the button, not at the foot of the page.
  const copyPanel = qs("#copy-brief");
  if (copyPanel && status) {
    copyPanel.append(status);
  }

  setReady(detail);

  detail.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-brief]");
    if (!button || !status) {
      return;
    }
    let copied = false;
    try {
      await copyText(briefText);
      status.textContent = `Copied the ${template.name} brief as JSON.`;
      copied = true;
    } catch (error) {
      status.textContent = `Copy failed: ${
        error instanceof Error ? error.message : String(error)
      } Select the JSON above and copy it manually.`;
    }
    if (copied) {
      const label = button.textContent;
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = label;
      }, 2000);
    }
  });
}

init();


