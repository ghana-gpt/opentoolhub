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

function filterTemplates(data, query, status) {
  return data.templates.filter((template) => {
    const statusMatch = !status || template.status === status;
    return statusMatch && matchesQuery(templateText(template, data), query);
  });
}

async function init() {
  const grid = qs("#template-grid");
  const search = qs("#template-search");
  const statusSelect = qs("#status-filter");
  const count = qs("#template-count");
  const clear = qs("#clear-templates");
  if (!grid || !search || !statusSelect || !count) {
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

  const params = readParams(["q", "status"]);
  search.value = params.q;
  statusSelect.value = STATUSES.includes(params.status) ? params.status : "";

  function render() {
    const query = search.value.trim();
    const status = statusSelect.value;
    const matches = filterTemplates(data, query, status);
    updateParams({ q: query, status });
    count.textContent = `${countLabel(matches.length, "template")} of ${
      data.templates.length
    }`;
    if (!matches.length) {
      showEmpty(
        grid,
        "No template matches",
        "Try another word, remove the status filter, or browse the use cases."
      );
      return;
    }
    grid.innerHTML = matches
      .map((template) => renderTemplateCard(template, data))
      .join("");
  }

  search.addEventListener("input", debounce(render, 180));
  statusSelect.addEventListener("change", render);
  if (clear) {
    clear.addEventListener("click", () => {
      search.value = "";
      statusSelect.value = "";
      render();
      search.focus();
    });
  }

  render();
}

init();
