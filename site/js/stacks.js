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
} from "./ui.js";
import { renderStackCard } from "./render.js";

const LEVELS = ["low", "medium", "high"];

function filterStacks(data, query, difficulty) {
  return data.stacks.filter((stack) => {
    const levelMatch = !difficulty || stack.difficulty === difficulty;
    return levelMatch && matchesQuery(stackSearchText(stack, data), query);
  });
}

async function init() {
  const grid = qs("#stack-grid");
  const search = qs("#stack-search");
  const levelSelect = qs("#difficulty-filter");
  const count = qs("#stack-count");
  const clear = qs("#clear-stacks");
  if (!grid || !search || !levelSelect || !count) {
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

  const params = readParams(["q", "level"]);
  search.value = params.q;
  levelSelect.value = LEVELS.includes(params.level) ? params.level : "";

  function render() {
    const query = search.value.trim();
    const difficulty = levelSelect.value;
    const matches = filterStacks(data, query, difficulty);
    updateParams({ q: query, level: difficulty });
    count.textContent = `${countLabel(matches.length, "stack")} of ${
      data.stacks.length
    }`;
    if (!matches.length) {
      showEmpty(
        grid,
        "No stack matches",
        "Try another word, remove the difficulty filter, or browse every use case."
      );
      return;
    }
    grid.innerHTML = matches
      .map((stack) => renderStackCard(stack, data, { detailed: true }))
      .join("");
  }

  search.addEventListener("input", debounce(render, 180));
  levelSelect.addEventListener("change", render);
  if (clear) {
    clear.addEventListener("click", () => {
      search.value = "";
      levelSelect.value = "";
      render();
      search.focus();
    });
  }

  render();
}

init();
