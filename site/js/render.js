/** Reusable card and list markup. Every value is escaped before insertion. */

import {
  escapeHtml,
  categoryLinks,
  difficultyBadge,
  statusBadge,
  useCaseLink,
  repoLink,
  pill,
  countLabel,
} from "./ui.js";
import { stacksForUseCase, templatesForUseCase, apisForStack } from "./data.js";

const LABELS = {
  none: "No auth",
  "api-key": "API key",
  token: "Token",
  free: "Free",
  "free-tier": "Free tier",
  paid: "Paid",
  low: "Low",
  medium: "Medium",
  high: "High",
};

function humanize(value) {
  return LABELS[value] ?? value;
}

export function renderUseCaseCard(useCase, data) {
  const stacks = stacksForUseCase(useCase, data);
  const templates = templatesForUseCase(useCase, data);
  const primary = stacks[0];
  return `
    <article class="card">
      <div class="card-top">${pill(useCase.id)}</div>
      <h3>${useCaseLink(useCase, useCase.name, "card-title")}</h3>
      <p>${escapeHtml(useCase.summary)}</p>
      <div class="tag-list">${categoryLinks(useCase.categories, data)}</div>
      ${
        primary
          ? `<p class="card-stack muted small">Starting stack:
              <a class="meta-link" href="stacks.html#stack-${encodeURIComponent(
                primary.id
              )}">${escapeHtml(primary.name)}</a>
            </p>`
          : ""
      }
      <div class="meta-row">
        <span>${escapeHtml(countLabel(stacks.length, "stack"))}</span>
        <span>${escapeHtml(countLabel(templates.length, "template"))}</span>
      </div>
      <p class="card-action">${useCaseLink(
        useCase,
        "See the stack and example →",
        "text-link",
        `Open the ${useCase.name} path`
      )}</p>
    </article>`;
}

export function renderApiInline(api) {
  return `
    <li class="api-inline">
      <a class="api-name" href="${escapeHtml(api.url)}" rel="noopener">${escapeHtml(
        api.name
      )}</a>
      <span class="api-meta">${escapeHtml(humanize(api.auth))} · ${escapeHtml(
        humanize(api.pricing)
      )}</span>
    </li>`;
}

export function renderToolList(stack, data) {
  return `
    <ul class="tool-list">
      ${stack.tools
        .map((tool) => {
          const category = data.categoryById.get(tool.category);
          const apis = tool.api_ids
            .map((id) => data.apiById.get(id))
            .filter(Boolean);
          return `
            <li class="tool">
              <div class="tool-head">
                <span class="tool-slot">${escapeHtml(tool.slot)}</span>
                <span class="tool-category">${escapeHtml(
                  category ? category.name : tool.category
                )}</span>
              </div>
              <ul class="api-inline-list">
                ${apis.map(renderApiInline).join("")}
              </ul>
            </li>`;
        })
        .join("")}
    </ul>`;
}

export function renderStackCard(
  stack,
  data,
  { detailed = false, showUseCase = true } = {}
) {
  const useCase = data.useCaseById.get(stack.use_case);
  return `
    <article class="card stack-card" id="stack-${escapeHtml(stack.id)}">
      <div class="card-top">
        ${difficultyBadge(stack.difficulty)}
        ${
          showUseCase && useCase
            ? useCaseLink(useCase, "Part of " + useCase.name, "meta-link")
            : ""
        }
      </div>
      <h3>${escapeHtml(stack.name)}</h3>
      <p>${escapeHtml(stack.notes)}</p>
      <div class="tag-list stack-tags">${categoryLinks(stack.categories, data)}</div>
      ${
        detailed
          ? renderToolList(stack, data)
          : `<p class="muted small">${escapeHtml(
              countLabel(stack.tools.length, "tool slot")
            )} · ${escapeHtml(countLabel(apisForStack(stack, data).length, "API"))}</p>`
      }
      <div class="tag-list">${stack.best_for
        .map((item) => pill(item))
        .join("")}</div>
    </article>`;
}

export function renderApiCard(api, data) {
  return `
    <article class="card api-card">
      <div class="card-top">
        ${pill(humanize(api.pricing), "pricing")}
        ${pill(humanize(api.auth), "auth")}
      </div>
      <h3><a class="card-title" href="${escapeHtml(api.url)}" rel="noopener">${escapeHtml(
        api.name
      )}</a></h3>
      <p>${escapeHtml(api.description)}</p>
      <div class="tag-list">${categoryLinks(api.category_ids, data)}</div>
      <dl class="fact-grid">
        <div><dt>Best for</dt><dd>${escapeHtml(api.best_for.join(", "))}</dd></div>
        <div><dt>Integration</dt><dd>${escapeHtml(humanize(api.integration_complexity))}</dd></div>
        <div><dt>Data freshness</dt><dd>${escapeHtml(humanize(api.data_freshness))}</dd></div>
      </dl>
      <details class="details">
        <summary>Licensing and access</summary>
        <p>${escapeHtml(api.licensing_notes)}</p>
      </details>
      <p class="card-action"><a class="text-link" href="${escapeHtml(
        api.docs_url
      )}" rel="noopener">Read the docs →</a></p>
    </article>`;
}

export function renderTemplateCard(template, data) {
  const useCases = template.use_case_ids
    .map((id) => data.useCaseById.get(id))
    .filter(Boolean);
  return `
    <article class="card">
      <div class="card-top">
        ${statusBadge(template.status)}
        ${pill(template.tags[0] ?? "template")}
      </div>
      <h3>${escapeHtml(template.name)}</h3>
      <p>${escapeHtml(template.description)}</p>
      <div class="tag-list">${categoryLinks(template.category_ids, data)}</div>
      <p class="muted small">Built for: ${useCases
        .map((useCase) => useCaseLink(useCase, useCase.name, "meta-link"))
        .join(", ") || "unassigned"}</p>
      <p class="card-action">${repoLink(template.path, "Open the starter →")}</p>
    </article>`;
}

export function renderExampleCard(example) {
  return `
    <article class="card">
      <h3>${escapeHtml(example.title)}</h3>
      <p>${escapeHtml(example.summary)}</p>
      <p class="card-action">${repoLink(example.path, "Read the walkthrough →")}</p>
    </article>`;
}
