/** API catalog with search plus category and pricing filters. */

import { loadData, matchesQuery, apiSearchText } from "./data.js";
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
import { renderApiCard } from "./render.js";

const PRICING = ["free", "free-tier", "paid"];

function filterApis(data, query, categoryId, pricing) {
  return data.apis.filter((api) => {
    const categoryMatch =
      !categoryId || api.category_ids.includes(categoryId);
    const pricingMatch = !pricing || api.pricing === pricing;
    return (
      categoryMatch &&
      pricingMatch &&
      matchesQuery(apiSearchText(api, data), query)
    );
  });
}

async function init() {
  const grid = qs("#api-grid");
  const search = qs("#api-search");
  const categorySelect = qs("#api-category-filter");
  const pricingSelect = qs("#pricing-filter");
  const count = qs("#api-count");
  const clear = qs("#clear-apis");
  if (!grid || !search || !categorySelect || !pricingSelect || !count) {
    return;
  }

  setBusy(grid, "Loading APIs…");

  let data;
  try {
    data = await loadData();
  } catch (error) {
    showError(grid, error);
    return;
  }

  const usedCategories = new Set(data.apis.flatMap((api) => api.category_ids));
  categorySelect.innerHTML =
    `<option value="">All categories</option>` +
    data.categories
      .filter((category) => usedCategories.has(category.id))
      .map(
        (category) =>
          `<option value="${escapeHtml(category.id)}">${escapeHtml(
            category.name
          )}</option>`
      )
      .join("");

  const params = readParams(["q", "category", "pricing"]);
  search.value = params.q;
  categorySelect.value = data.categoryById.has(params.category)
    ? params.category
    : "";
  pricingSelect.value = PRICING.includes(params.pricing) ? params.pricing : "";

  function render() {
    const query = search.value.trim();
    const categoryId = categorySelect.value;
    const pricing = pricingSelect.value;
    const matches = filterApis(data, query, categoryId, pricing);
    updateParams({ q: query, category: categoryId, pricing });
    count.textContent = `${countLabel(matches.length, "API")} of ${
      data.apis.length
    }`;
    if (!matches.length) {
      showEmpty(
        grid,
        "No API matches",
        "Try another word or remove a filter. Every listing links to official documentation."
      );
      return;
    }
    grid.innerHTML = matches.map((api) => renderApiCard(api, data)).join("");
  }

  search.addEventListener("input", debounce(render, 180));
  categorySelect.addEventListener("change", render);
  pricingSelect.addEventListener("change", render);
  if (clear) {
    clear.addEventListener("click", () => {
      search.value = "";
      categorySelect.value = "";
      pricingSelect.value = "";
      render();
      search.focus();
    });
  }

  render();
}

init();
