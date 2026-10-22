/** Home page: turn an idea, areas, and experience level into a concrete path. */

import {
  loadData,
  useCaseSearchText,
  stacksForUseCase,
  templatesForUseCase,
  examplesForUseCase,
  searchTokens,
  normalize,
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
} from "./ui.js";
import { renderUseCaseCard, renderToolList } from "./render.js";

const LEVELS = new Set(["low", "medium", "high"]);

function scoreUseCases(idea, categoryIds, data) {
  const tokens = searchTokens(idea);
  const results = [];
  for (const useCase of data.useCases) {
    const words = normalize(useCaseSearchText(useCase, data)).split(" ");
    const hits = tokens.filter((token) =>
      words.some((word) => word.startsWith(token))
    );
    if (tokens.length && hits.length !== tokens.length) {
      continue;
    }
    const overlap = categoryIds.filter((id) => useCase.categories.includes(id));
    if (categoryIds.length && !overlap.length) {
      continue;
    }
    const exactName = normalize(useCase.name) === normalize(idea);
    const exactAlias = useCase.aliases.some(
      (alias) => normalize(alias) === normalize(idea)
    );
    let score = hits.length * 10 + overlap.length * 5;
    if (exactName) score += 60;
    if (exactAlias) score += 50;
    results.push({ useCase, score });
  }
  results.sort(
    (left, right) =>
      right.score - left.score || left.useCase.name.localeCompare(right.useCase.name)
  );
  return results;
}

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

function renderResults(matches, level, data) {
  const section = qs("#results-section");
  const title = qs("#results-title");
  const results = qs("#results");
  section.hidden = false;

  if (!matches.length) {
    title.textContent = "No matching path yet";
    showEmpty(
      results,
      "Nothing matched those filters",
      "Try a broader idea, remove an area, or clear the filters and start again."
    );
    results.insertAdjacentHTML(
      "beforeend",
      `<p class="cta-row"><button type="button" class="button secondary" data-action="clear">Clear filters</button></p>`
    );
  } else {
    const [{ useCase }, ...alternatives] = matches;
    title.textContent = `A path for ${useCase.name.toLowerCase()}`;
    results.innerHTML = renderPath(useCase, level, data);
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

  section.scrollIntoView({ behavior: "smooth", block: "start" });
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
  title.textContent = "";
  renderIdeaSuggestions(data, ideaInput);
  qs("#featured-use-cases").innerHTML = data.useCases
    .map((useCase) => renderUseCaseCard(useCase, data))
    .join("");

  const params = readParams(["q", "areas", "level"]);
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
      section.scrollIntoView({ behavior: "smooth", block: "start" });
      ideaInput.focus({ preventScroll: true });
      return;
    }

    updateParams({ q: idea, areas: categories.join(","), level: levelValue });
    renderResults(scoreUseCases(idea, categories, data), levelValue, data);
  });

  form.addEventListener("reset", () => {
    window.setTimeout(() => {
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
    renderResults(scoreUseCases(params.q, selected, data), level, data);
  }
}

init();


