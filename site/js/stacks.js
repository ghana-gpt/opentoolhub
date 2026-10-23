/** Stack index with search and difficulty filters kept in the URL. */

import { loadData, matchesQuery, stackSearchText } from "./data.js";
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
import { renderStackCard } from "./render.js";

const LEVELS = ["low", "medium", "high"];

function filterStacks(data, query, difficulty, categoryId) {
  return data.stacks.filter((stack) => {
    const levelMatch = !difficulty || stack.difficulty === difficulty;
    const categoryMatch =
      !categoryId || stack.categories.includes(categoryId);
    return (
      levelMatch &&
      categoryMatch &&
      matchesQuery(stackSearchText(stack, data), query)
    );
  });
}

async function init() {
  const grid = qs("#stack-grid");
  const search = qs("#stack-search");
  const levelSelect = qs("#difficulty-filter");
  const categorySelect = qs("#stack-category-filter");
  const count = qs("#stack-count");
  const clear = qs("#clear-stacks");
  if (!grid || !search || !levelSelect || !categorySelect || !count) {
    return;
  }

  setBusy(grid, "Loading stacks…");

  let data;
  try {
    data = await loadData();
  } catch (error) {
    showError(grid, error);
    return;
  }

  levelSelect.innerHTML =
    `<option value="">Any difficulty</option>` +
    LEVELS.map(
      (level) =>
        `<option value="${level}">${level.charAt(0).toUpperCase()}${level.slice(
          1
        )}</option>`
    ).join("");

  const usedCategories = new Set(
    data.stacks.flatMap((stack) => stack.categories)
  );
  categorySelect.innerHTML =
    `<option value="">All areas</option>` +
    data.categories
      .filter((category) => usedCategories.has(category.id))
      .map((category) => {
        const total = data.stacks.filter((stack) =>
          stack.categories.includes(category.id)
        ).length;
        return `<option value="${escapeHtml(category.id)}">${escapeHtml(
          category.name
        )} (${total})</option>`;
      })
      .join("");

  const params = readParams(["q", "level", "category"]);
  search.value = params.q;
  levelSelect.value = LEVELS.includes(params.level) ? params.level : "";
  categorySelect.value = data.categoryById.has(params.category)
    ? params.category
    : "";

  function render() {
    const query = search.value.trim();
    const difficulty = levelSelect.value;
    const categoryId = categorySelect.value;
    const matches = filterStacks(data, query, difficulty, categoryId);
    updateParams({ q: query, level: difficulty, category: categoryId });
    setClearState(clear, Boolean(query || difficulty || categoryId));
    count.textContent = `${countLabel(matches.length, "stack")} of ${
      data.stacks.length
    }`;
    if (!matches.length) {
      showEmpty(
        grid,
        "No stack matches",
        "Try another word, remove the difficulty or area filter, or browse every use case."
      );
      return;
    }
    grid.innerHTML = matches
      .map((stack) => renderStackCard(stack, data, { detailed: true }))
      .join("");
    setReady(grid);
  }

  search.addEventListener("input", debounce(render, 180));
  levelSelect.addEventListener("change", render);
  categorySelect.addEventListener("change", render);
  if (clear) {
    clear.addEventListener("click", () => {
      search.value = "";
      levelSelect.value = "";
      categorySelect.value = "";
      render();
      search.focus();
    });
  }

  render();
  const rawHash = window.location.hash.slice(1);
  let targetId = rawHash;
  try {
    targetId = decodeURIComponent(rawHash);
  } catch {
    targetId = rawHash;
  }
  const target = targetId ? document.getElementById(targetId) : null;
  if (target) {
    target.scrollIntoView({ block: "start" });
    target.focus({ preventScroll: true });
  }
}

init();
