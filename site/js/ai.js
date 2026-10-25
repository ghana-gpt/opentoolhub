/** Optional local AI panel. Talks only to the loopback proxy, never to a model. */

import { escapeHtml, qs, repoLink, setBusy, setReady } from "./ui.js";

const STATUS_URL = "api/ai/status";
const CHAT_URL = "api/ai/chat";
const DOCS = "docs/local-ai.md";

const QUICK_START = [
  "ollama pull phi3:mini",
  "export OPEN_TOOL_HUB_AI_PROVIDERS=local",
  "export OPEN_TOOL_HUB_AI_LOCAL_KIND=ollama",
  "export OPEN_TOOL_HUB_AI_LOCAL_MODEL=phi3:mini",
  "python3 scripts/ai_proxy.py",
].join("\n");

async function readJson(response) {
  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message =
      (payload && (payload.detail || payload.error)) ||
      `The AI endpoint answered ${response.status}.`;
    const error = new Error(message);
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload ?? {};
}

function setupCard(reason) {
  const detail = reason
    ? `<p class="small muted">${escapeHtml(reason)}</p>`
    : "";
  return `
    <h2>Start the local endpoint</h2>
    <p>
      This page needs <code>scripts/ai_proxy.py</code>, which serves this site
      and adds <code>/api/ai/status</code> and <code>/api/ai/chat</code> on
      <code>127.0.0.1</code>. There is no AI backend on GitHub Pages, and there
      never will be: your key stays on your machine.
    </p>
    ${detail}
    <pre><code>${escapeHtml(QUICK_START)}</code></pre>
    <p>
      Then reload this page. Any provider works: Ollama, OpenAI, Anthropic,
      DeepSeek, Qwen, or an OpenAI-compatible local server. The full list of
      variables is in ${repoLink(DOCS, DOCS)}.
    </p>`;
}

function providerList(payload) {
  const providers = Array.isArray(payload.providers) ? payload.providers : [];
  if (!providers.length) {
    return `<p class="hint">No provider is configured yet.</p>`;
  }
  const rows = providers
    .map((provider) => {
      const state = provider.ready
        ? `<span class="pill">ready</span>`
        : `<span class="pill">${escapeHtml(provider.reason || "not ready")}</span>`;
      const model = provider.model ? escapeHtml(provider.model) : "(no model)";
      return `
        <div class="ai-provider">
          <div>
            <strong>${escapeHtml(provider.label || provider.id)}</strong>
            <p class="small muted">${escapeHtml(provider.kind)} · ${model}</p>
          </div>
          ${state}
        </div>`;
    })
    .join("");
  const order = Array.isArray(payload.order) ? payload.order.join(" → ") : "";
  return `
    ${rows}
    ${order ? `<p class="small muted">Fallback order: ${escapeHtml(order)}</p>` : ""}`;
}

function fillProviders(select, payload) {
  const ready = (payload.providers || []).filter((provider) => provider.ready);
  select.innerHTML =
    `<option value="">Fallback order</option>` +
    ready
      .map(
        (provider) =>
          `<option value="${escapeHtml(provider.id)}">${escapeHtml(
            provider.label || provider.id
          )} · ${escapeHtml(provider.model || provider.kind)}</option>`
      )
      .join("");
}

function renderAnswer(node, payload) {
  const completion = payload.completion || {};
  const attempts = Array.isArray(payload.attempts) ? payload.attempts : [];
  const trail = attempts
    .map((attempt) => {
      const suffix = attempt.error
        ? ` — ${escapeHtml(attempt.error)}`
        : attempt.latency_ms
          ? ` — ${escapeHtml(attempt.latency_ms)} ms`
          : "";
      return `<li><strong>${escapeHtml(attempt.provider_id)}</strong>: ${escapeHtml(
        attempt.status
      )}${suffix}</li>`;
    })
    .join("");
  const latency =
    completion.latency_ms !== undefined ? `${completion.latency_ms} ms` : "";
  const meta = [completion.provider_id, completion.model, latency]
    .filter(Boolean)
    .map((part) => escapeHtml(part))
    .join(" · ");

  setReady(node);
  node.hidden = false;
  node.innerHTML = `
    <h2>Answer</h2>
    <pre class="ai-answer-text">${escapeHtml(completion.text || "")}</pre>
    <p class="small muted">${meta}</p>
    ${trail ? `<h3>Attempts</h3><ul class="ai-attempts">${trail}</ul>` : ""}
    <p class="hint">
      A model can be wrong. Check the API's official documentation and
      <a class="text-link" href="data/catalog.json">catalog.json</a> before you
      rely on a detail.
    </p>`;
}

function renderAnswerError(node, error) {
  setReady(node);
  node.hidden = false;
  const attempts =
    error.payload && Array.isArray(error.payload.attempts)
      ? error.payload.attempts
      : [];
  const trail = attempts
    .map(
      (attempt) =>
        `<li><strong>${escapeHtml(attempt.provider_id)}</strong>: ${escapeHtml(
          attempt.status
        )}${attempt.error ? ` — ${escapeHtml(attempt.error)}` : ""}</li>`
    )
    .join("");
  node.innerHTML = `
    <div class="state state-error" role="alert">
      <h3>No answer</h3>
      <p>${escapeHtml(error.message)}</p>
      ${trail ? `<ul class="ai-attempts">${trail}</ul>` : ""}
      <p>${repoLink(DOCS, "Troubleshooting in the setup guide")}</p>
    </div>`;
}

async function ask(node, body, provider) {
  setBusy(node, "Waiting for the model…");
  node.hidden = false;
  const response = await fetch(CHAT_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(provider ? { ...body, provider } : body),
  });
  return readJson(response);
}

async function init() {
  const statusText = qs("#ai-status-text");
  const statusNode = qs("#ai-status");
  const form = qs("#ai-form");
  const prompt = qs("#ai-prompt");
  const providerSelect = qs("#ai-provider");
  const askButton = qs("#ai-ask");
  const answer = qs("#ai-answer");
  if (
    !statusText ||
    !statusNode ||
    !form ||
    !prompt ||
    !providerSelect ||
    !askButton ||
    !answer
  ) {
    return;
  }

  let payload;
  try {
    const response = await fetch(STATUS_URL, {
      headers: { Accept: "application/json" },
    });
    payload = await readJson(response);
  } catch (error) {
    const missingEndpoint =
      error instanceof TypeError ||
      error.status === 404 ||
      error.status === 405 ||
      error.status === 501;
    statusText.textContent = "Local AI is not running";
    statusNode.innerHTML = setupCard(
      missingEndpoint
        ? "No local endpoint answered. Serve this page with scripts/ai_proxy.py."
        : error.message
    );
    return;
  }

  if (payload.mode !== "local-ai" || !payload.ready_count) {
    statusText.textContent = "Local AI needs a provider";
    statusNode.innerHTML = setupCard(payload.error || "");
    return;
  }

  const total = Array.isArray(payload.order) ? payload.order.length : 0;
  statusText.textContent = `${payload.ready_count} of ${total} providers ready`;
  statusNode.innerHTML = `<h2>Configured providers</h2>${providerList(payload)}`;
  fillProviders(providerSelect, payload);
  form.hidden = false;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = prompt.value.trim();
    if (!text) {
      prompt.focus();
      return;
    }
    askButton.disabled = true;
    try {
      const result = await ask(answer, { prompt: text }, providerSelect.value);
      renderAnswer(answer, result);
    } catch (error) {
      renderAnswerError(answer, error);
    } finally {
      askButton.disabled = false;
    }
  });
}

init();

