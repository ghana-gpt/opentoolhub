/** Small DOM, escaping, URL-state, and badge helpers shared by every page. */

export const REPO_URL = "https://github.com/ghana-gpt/opentoolhub";

const ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

export function qs(selector, root = document) {
  return root.querySelector(selector);
}

export function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

export function setBusy(node, message) {
  node.setAttribute("aria-busy", "true");
  node.innerHTML = `<p class="state" role="status">${escapeHtml(message)}</p>`;
}

export function setReady(node) {
  node.setAttribute("aria-busy", "false");
}

export function setClearState(button, active) {
  if (button) {
    button.disabled = !active;
  }
}

export function showError(node, error) {
  setReady(node);
  const message = error instanceof Error ? error.message : String(error);
  node.innerHTML = `
    <div class="state state-error" role="alert">
      <h3>Something went wrong</h3>
      <p>${escapeHtml(message)}</p>
      <p>If you opened this file directly from disk, serve the site instead:</p>
      <pre><code>python3 scripts/build_site.py --serve</code></pre>
    </div>`;
}

export function showEmpty(node, title, message, actionHtml = "") {
  setReady(node);
  node.innerHTML = `
    <div class="state">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(message)}</p>
      ${actionHtml}
    </div>`;
}

export function pill(text, modifier = "") {
  const className = modifier ? `pill pill-${modifier}` : "pill";
  return `<span class="${className}">${escapeHtml(text)}</span>`;
}

export function difficultyBadge(level) {
  return pill(`${level} difficulty`, level);
}

export function statusBadge(status) {
  return pill(status, status);
}

export function categoryLinks(categoryIds, data) {
  return categoryIds
    .map((id) => {
      const category = data.categoryById.get(id);
      const label = category ? category.name : id;
      return `<a class="tag" href="use-cases.html?category=${encodeURIComponent(
        id
      )}">${escapeHtml(label)}</a>`;
    })
    .join("");
}

export function repoUrl(path) {
  const encoded = String(path)
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `${REPO_URL}/blob/main/${encoded}`;
}

export function repoLink(path, label, className = "text-link") {
  return `<a class="${className}" href="${repoUrl(path)}" rel="noopener">${escapeHtml(
    label
  )}</a>`;
}

export function useCaseLink(
  useCase,
  label = useCase.name,
  className = "text-link",
  ariaLabel = ""
) {
  const accessible = ariaLabel ? ` aria-label="${escapeHtml(ariaLabel)}"` : "";
  return `<a class="${className}" href="use-case.html?id=${encodeURIComponent(
    useCase.id
  )}"${accessible}>${escapeHtml(label)}</a>`;
}

export function readParams(names) {
  const params = new URLSearchParams(window.location.search);
  return Object.fromEntries(names.map((name) => [name, params.get(name) ?? ""]));
}

export function updateParams(values) {
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(values)) {
    if (value) {
      url.searchParams.set(key, String(value));
    } else {
      url.searchParams.delete(key);
    }
  }
  window.history.replaceState(null, "", url);
}

export function debounce(callback, wait = 200) {
  let timer = 0;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => callback(...args), wait);
  };
}

export function countLabel(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

export function titleCase(value) {
  return String(value)
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
