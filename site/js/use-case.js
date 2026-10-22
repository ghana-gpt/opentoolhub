/** Render one use case with its stacks, APIs, templates, and example. */

import {
  loadData,
  stacksForUseCase,
  templatesForUseCase,
  examplesForUseCase,
} from "./data.js";
import {
  qs,
  escapeHtml,
  setBusy,
  showError,
  readParams,
  categoryLinks,
  repoLink,
  statusBadge,
} from "./ui.js";
import { renderStackCard, renderUseCaseCard } from "./render.js";

function renderNotFound(detail, message) {
  detail.innerHTML = `
    <div class="state state-error" role="alert">
      <h1>Use case not found</h1>
      <p>${escapeHtml(message)}</p>
      <p><a class="button secondary" href="use-cases.html">Browse all use cases</a></p>
    </div>`;
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

  document.title = `${useCase.name} | OpenToolHub`;
  if (crumb) {
    crumb.textContent = useCase.name;
  }

  const stacks = stacksForUseCase(useCase, data);
  const templates = templatesForUseCase(useCase, data);
  const examples = examplesForUseCase(useCase, data);

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
    </header>

    <div class="detail-grid">
      <section class="panel">
        <h2>Stack${stacks.length === 1 ? "" : "s"}</h2>
        ${stacks
          .map((stack) =>
            renderStackCard(stack, data, { detailed: true, showUseCase: false })
          )
          .join("")}
      </section>

      <aside class="panel">
        <h2>Start here</h2>
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
}

init();
