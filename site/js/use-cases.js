/** Use case index with text and category filters kept in the URL. */

import { loadData, matchesQuery, useCaseSearchText } from "./data.js";
import {
  qs,
  debounce,
  readParams,
  updateParams,
  showError,
  setBusy,
  showEmpty,
  escapeHtml,
  countLabel,
} from "./ui.js";
import { renderUseCaseCard } from "./render.js";

function filterUseCases(data, query, categoryId) {
  return data.useCases.filter((useCase) => {
    const categoryMatch =
      !categoryId || useCase.categories.includes(categoryId);
    return categoryMatch && matchesQuery(useCaseSearchText(useCase, data), query);
  });
}

async function init() {
  const grid = qs("#use-cases-grid");
  const search = qs("#use-case-search");
  const categorySelect = qs("#category-filter");
  const count = qs("#use-cases-count");
  const clear = qs("#clear-use-cases");
  if (!grid || !search || !categorySelect || !count) {
    return;
  }

  setBusy(grid, "Loading use cases…");

  let data;
  try {
    data = await loadData();
  } catch (error) {
    showError(grid, error);
    return;
  }

  const params = readParams(["q", "category"]);
  search.value = params.q;
  categorySelect.innerHTML =
    `<option value="">All areas</option>` +
    data.categories
      .map(
        (category) =>
          `<option value="${escapeHtml(category.id)}">${escapeHtml(
            category.name
          )}</option>`
      )
      .join("");

  const validCategory = data.categoryById.has(params.category)
    ? params.category
    : "";
  categorySelect.value = validCategory;

  function render() {
    const query = search.value.trim();
    const categoryId = categorySelect.value;
    const matches = filterUseCases(data, query, categoryId);
    updateParams({ q: query, category: categoryId });
    count.textContent = `${countLabel(matches.length, "use case")} of ${
      data.useCases.length
    }`;
    if (!matches.length) {
      showEmpty(
        grid,
        "No use case matches",
        "Try fewer words, a different spelling, or another area."
      );
      return;
    }
    grid.innerHTML = matches
      .map((useCase) => renderUseCaseCard(useCase, data))
      .join("");
  }

  search.addEventListener("input", debounce(render, 180));
  categorySelect.addEventListener("change", render);
  if (clear) {
    clear.addEventListener("click", () => {
      search.value = "";
      categorySelect.value = "";
      render();
      search.focus();
    });
  }

  render();
}

init();
