/** Starter template index with search and status filters. */

import { loadData, matchesQuery } from "./data.js";
import {
  qs,
  debounce,
  readParams,
  updateParams,
  showError,
  setBusy,
  showEmpty,
  countLabel,
  escapeHtml,
  setReady,
  setClearState,
} from "./ui.js";
import { renderTemplateCard } from "./render.js";

const STATUSES = ["starter", "variant"];

function templateText(template, data) {
  const categoryNames = template.category_ids.map(
    (id) => data.categoryById.get(id)?.name ?? id
  );
  const useCaseNames = template.use_case_ids.map(
    (id) => data.useCaseById.get(id)?.name ?? id
  );
  return [
    template.name,
    template.description,
    ...template.tags,
    ...categoryNames,
    ...useCaseNames,
  ].join(" ");
}

function filterTemplates(data, query, status, categoryId) {
  return data.templates.filter((template) => {
    const statusMatch = !status || template.status === status;
    const categoryMatch =
      !categoryId || template.category_ids.includes(categoryId);
    return (
      statusMatch &&
      categoryMatch &&
      matchesQuery(templateText(template, data), query)
    );
  });
}

async function init() {
  const grid = qs("#template-grid");
  const search = qs("#template-search");
  const statusSelect = qs("#status-filter");
  const categorySelect = qs("#template-category-filter");
  const count = qs("#template-count");
  const clear = qs("#clear-templates");
  if (!grid || !search || !statusSelect || !categorySelect || !count) {
    return;
  }

  setBusy(grid, "Loading templates…");

  let data;
  try {
    data = await loadData();
  } catch (error) {
    showError(grid, error);
    return;
  }

  const usedCategories = new Set(
    data.templates.flatMap((template) => template.category_ids)
  );
  categorySelect.innerHTML =
    `<option value="">All areas</option>` +
    data.categories
      .filter((category) => usedCategories.has(category.id))
      .map((category) => {
        const total = data.templates.filter((template) =>
          template.category_ids.includes(category.id)
        ).length;
        return `<option value="${escapeHtml(category.id)}">${escapeHtml(
          category.name
        )} (${total})</option>`;
      })
      .join("");

  const params = readParams(["q", "status", "category"]);
  search.value = params.q;
  statusSelect.value = STATUSES.includes(params.status) ? params.status : "";
  categorySelect.value = data.categoryById.has(params.category)
    ? params.category
    : "";

  function render() {
    const query = search.value.trim();
    const status = statusSelect.value;
    const categoryId = categorySelect.value;
    const matches = filterTemplates(data, query, status, categoryId);
    updateParams({ q: query, status, category: categoryId });
    setClearState(clear, Boolean(query || status || categoryId));
    count.textContent = `${countLabel(matches.length, "template")} of ${
      data.templates.length
    }`;
    if (!matches.length) {
      showEmpty(
        grid,
        "No template matches",
        "Try another word, remove the status or area filter, or browse the use cases."
      );
      return;
    }
    grid.innerHTML = matches
      .map((template) => renderTemplateCard(template, data))
      .join("");
    setReady(grid);
  }

  search.addEventListener("input", debounce(render, 180));
  statusSelect.addEventListener("change", render);
  categorySelect.addEventListener("change", render);
  if (clear) {
    clear.addEventListener("click", () => {
      search.value = "";
      statusSelect.value = "";
      categorySelect.value = "";
      render();
      search.focus();
    });
  }

  render();
}

init();
