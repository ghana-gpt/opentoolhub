/** Home page: turn an idea, areas, and experience level into a concrete path. */

import {
  loadData,
  buildSearchIndex,
  scoreUseCases,
  suggestUseCases,
  stacksForUseCase,
  templatesForUseCase,
  examplesForUseCase,
} from "./data.js";
import {
  qs,
  qsa,
  escapeHtml,
  showError,
  setBusy,
  showEmpty,
  readParams,
  updateParams,
  categoryLinks,
  difficultyBadge,
  repoLink,
  countLabel,
  setReady,
} from "./ui.js";
import { renderUseCaseCard, renderToolList } from "./render.js";

const LEVELS = new Set(["low", "medium", "high"]);

function fitNote(difficulty, level) {
  if (difficulty === level) {
    return `Rated ${difficulty} difficulty, matching your selection.`;
  }
  if (level === "low" && difficulty !== "low") {
    return `Rated ${difficulty} difficulty; expect a longer build than a starter project.`;
  }
  if (level === "high" && difficulty === "low") {
    return "Rated low difficulty, so you can validate quickly before adding advanced sources.";
  }
  return `Rated ${difficulty} difficulty; you selected ${level}.`;
}

function renderIdeaSuggestions(data, input) {
  const container = qs("#idea-suggestions");
  const suggestions = data.useCases.map((useCase) => useCase.aliases[0]).filter(Boolean);
  container.innerHTML = suggestions
    .map(
      (suggestion) =>
        `<button type="button" class="chip" data-idea="${escapeHtml(
          suggestion
        )}">${escapeHtml(suggestion)}</button>`
    )
    .join("");
  container.addEventListener("click", (event) => {
    const button = event.target.closest("[data-idea]");
    if (!button) {
      return;
    }
    input.value = button.dataset.idea;
    input.focus();
  });
}

function renderCategoryOptions(data, selected) {
  const used = new Set(data.useCases.flatMap((useCase) => useCase.categories));
  qs("#category-options").innerHTML = data.categories
    .filter((category) => used.has(category.id))
    .map(
      (category) => `
        <label class="chip-check">
          <input type="checkbox" name="area" value="${escapeHtml(category.id)}" ${
            selected.includes(category.id) ? "checked" : ""
          } />
          <span>${escapeHtml(category.name)}</span>
        </label>`
    )
    .join("");
}

function renderCatalogStats(data) {
  const stats = [
    ["Use cases", data.useCases.length],
    ["Stacks", data.stacks.length],
    ["Templates", data.templates.length],
    ["APIs", data.apis.length],
  ];
  qs("#catalog-stats").innerHTML = stats
    .map(
      ([label, value]) => `
        <div>
          <dt>${escapeHtml(label)}</dt>
          <dd>${escapeHtml(value)}</dd>
        </div>`
    )
    .join("");
}

function renderAreaDirectory(data) {
  const section = qs("#area-section");
  const container = qs("#area-directory");
  if (!section || !container) {
    return;
  }
  const entries = data.categories
    .map((category) => {
      const useCaseCount = data.useCases.filter((useCase) =>
        useCase.categories.includes(category.id)
      ).length;
      const apiCount = data.apis.filter((api) =>
        api.category_ids.includes(category.id)
      ).length;
      return { category, useCaseCount, apiCount };
    })
    .filter(({ useCaseCount, apiCount }) => useCaseCount || apiCount);
  if (!entries.length) {
    return;
  }
  container.innerHTML = entries
    .map(
      ({ category, useCaseCount, apiCount }) => `
        <a class="area-card" href="use-cases.html?category=${encodeURIComponent(
          category.id
        )}" aria-label="Browse ${escapeHtml(
          countLabel(useCaseCount, "use case")
        )} in ${escapeHtml(category.name)}">
          <span class="area-name">${escapeHtml(category.name)}</span>
          <span class="area-count">${escapeHtml(
            countLabel(useCaseCount, "use case")
          )} · ${escapeHtml(countLabel(apiCount, "API"))}</span>
          <span class="area-arrow" aria-hidden="true">→</span>
        </a>`
    )
    .join("");
  section.hidden = false;
}

function scrollBehavior() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";
}

function renderPath(useCase, level, data) {
  const stacks = stacksForUseCase(useCase, data);
  const templates = templatesForUseCase(useCase, data);
  const examples = examplesForUseCase(useCase, data);
  const primary = stacks[0];

  return `
    <article class="path-result">
      <div class="path-head">
        <div>
          <span class="eyebrow">Best match</span>
          <h3>${escapeHtml(useCase.name)}</h3>
          <p>${escapeHtml(useCase.summary)}</p>
        </div>
        ${difficultyBadge(primary ? primary.difficulty : "medium")}
      </div>
      <p class="muted"><strong>Goal:</strong> ${escapeHtml(useCase.goal)}</p>
      <div class="tag-list">${categoryLinks(useCase.categories, data)}</div>

      <h4>1. Stack</h4>
      ${stacks
        .map(
          (stack) => `
            <section class="stack-block">
              <h5>${escapeHtml(stack.name)}</h5>
              <p>${escapeHtml(stack.notes)}</p>
              <p class="small muted">${escapeHtml(fitNote(stack.difficulty, level))}</p>
              ${renderToolList(stack, data)}
            </section>`
        )
        .join("")}

      <h4>2. Start from a template</h4>
      ${
        templates.length
          ? `<ul class="link-list">${templates
              .map(
                (template) =>
                  `<li>${repoLink(template.path, template.name)} <span class="muted small">(${escapeHtml(
                    template.status
                  )})</span></li>`
              )
              .join("")}</ul>`
          : `<p class="muted">No starter template is registered for this use case yet.</p>`
      }

      <h4>3. Follow a worked example</h4>
      ${
        examples.length
          ? `<ul class="link-list">${examples
              .map(
                (example) =>
                  `<li>${repoLink(example.path, example.title)} — <span class="muted">${escapeHtml(
                    example.summary
                  )}</span></li>`
              )
              .join("")}</ul>`
          : `<p class="muted">No worked example is registered for this use case yet.</p>`
      }

      <p class="card-action">
        <a class="button primary" href="use-case.html?id=${encodeURIComponent(
          useCase.id
        )}">Open the full path</a>
      </p>
    </article>`;
}

function renderResults(matches, level, data, closest = []) {
  const section = qs("#results-section");
  const title = qs("#results-title");
  const results = qs("#results");
  section.hidden = false;

  if (!matches.length) {
    title.textContent = "No matching path yet";
    const closestMarkup = closest.length
      ? `<div class="alt-matches">
          <h3>Closest use cases</h3>
          <p class="muted">Nothing matched every word, so start from the nearest documented path:</p>
          <div class="grid three">${closest
            .map(({ useCase }) => renderUseCaseCard(useCase, data))
            .join("")}</div>
        </div>`
      : "";
    showEmpty(
      results,
      "Nothing matched those filters",
      "Try a broader idea, remove an area, or clear the filters and start again.",
      `${closestMarkup}<p class="cta-row">
        <button type="button" class="button secondary" data-action="clear">Clear filters</button>
        <a class="text-link" href="use-cases.html">Browse all use cases</a>
      </p>`
    );
  } else {
    const [{ useCase }, ...alternatives] = matches;
    title.textContent = `A path for ${useCase.name}`;
    results.innerHTML = renderPath(useCase, level, data);
    setReady(results);
    if (alternatives.length) {
      results.insertAdjacentHTML(
        "beforeend",
        `<div class="alt-matches">
          <h3>Other possible matches</h3>
          <div class="grid three">${alternatives
            .slice(0, 3)
            .map(({ useCase: alternative }) => renderUseCaseCard(alternative, data))
            .join("")}</div>
        </div>`
      );
    }
  }

  section.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
  title.focus({ preventScroll: true });
}

async function init() {
  const form = qs("#builder-form");
  const results = qs("#results");
  const section = qs("#results-section");
  const title = qs("#results-title");
  const ideaInput = qs("#idea");
  if (!form || !results || !section || !title || !ideaInput) {
    return;
  }

  section.hidden = false;
  title.textContent = "Loading the catalog";
  setBusy(results, "Loading use cases, stacks, and templates…");

  let data;
  try {
    data = await loadData();
  } catch (error) {
    title.textContent = "Catalog unavailable";
    showError(results, error);
    return;
  }

  section.hidden = true;
  setReady(results);
  title.textContent = "";
  renderIdeaSuggestions(data, ideaInput);
  renderCatalogStats(data);
  renderAreaDirectory(data);
  qs("#featured-use-cases").innerHTML = data.useCases
    .map((useCase) => renderUseCaseCard(useCase, data))
    .join("");

  const params = readParams(["q", "areas", "level"]);
  const searchIndex = buildSearchIndex(data);
  const selected = params.areas
    .split(",")
    .filter((id) => data.categoryById.has(id));
  ideaInput.value = params.q;
  renderCategoryOptions(data, selected);
  const level = LEVELS.has(params.level) ? params.level : "medium";
  const levelInput = qs(`input[name="level"][value="${level}"]`);
  if (levelInput) {
    levelInput.checked = true;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const idea = ideaInput.value.trim();
    const categories = qsa('input[name="area"]:checked').map((input) => input.value);
    const chosen = qs('input[name="level"]:checked');
    const levelValue = chosen ? chosen.value : "medium";

    if (!idea && !categories.length) {
      title.textContent = "One more detail";
      section.hidden = false;
      showEmpty(
        results,
        "Describe an idea or pick an area",
        "Add a short description or select at least one area, then build your path."
      );
      section.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
      ideaInput.focus({ preventScroll: true });
      return;
    }

    updateParams({ q: idea, areas: categories.join(","), level: levelValue });
    renderResults(
      scoreUseCases(idea, categories, data, searchIndex),
      levelValue,
      data,
      suggestUseCases(idea, data, searchIndex)
    );
  });

  form.addEventListener("reset", () => {
    window.setTimeout(() => {
      ideaInput.value = "";
      for (const area of qsa('input[name="area"]')) {
        area.checked = false;
      }
      const medium = qs('input[name="level"][value="medium"]');
      if (medium) {
        medium.checked = true;
      }
      updateParams({ q: "", areas: "", level: "" });
      section.hidden = true;
      results.innerHTML = "";
      title.textContent = "";
    }, 0);
  });

  results.addEventListener("click", (event) => {
    if (event.target.closest("[data-action='clear']")) {
      form.reset();
    }
  });

  if (params.q || selected.length) {
    renderResults(
      scoreUseCases(params.q, selected, data, searchIndex),
      level,
      data,
      suggestUseCases(params.q, data, searchIndex)
    );
  }
}

init();


