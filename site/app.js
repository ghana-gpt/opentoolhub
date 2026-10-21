const useCaseData = '../data/use-cases.json';
const stackData = '../data/stacks.json';
const templateData = '../data/templates.json';

async function loadJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load ${url}`);
  }
  return response.json();
}

function renderCards(targetId, items, type) {
  const target = document.getElementById(targetId);
  if (!target) return;

  target.innerHTML = items.map((item) => {
    if (type === 'use-case') {
      return `
        <article class="card">
          <span class="pill">${item.name}</span>
          <h3>${item.name}</h3>
          <p>${item.summary}</p>
          <div class="meta-row">
            <strong>Goal</strong>
            <span>${item.goal}</span>
          </div>
          <div class="tag-list">
            ${item.categories.map((cat) => `<span class="tag">${cat}</span>`).join('')}
          </div>
        </article>
      `;
    }

    if (type === 'stack') {
      return `
        <article class="card">
          <span class="pill">${item.use_case}</span>
          <h3>${item.name}</h3>
          <p>${item.notes}</p>
          <div class="meta-row">
            <strong>Difficulty</strong>
            <span>${item.difficulty}</span>
          </div>
          <div class="tag-list">
            ${item.categories.map((cat) => `<span class="tag">${cat}</span>`).join('')}
          </div>
          <ul class="mini-list">
            ${item.recommended_tools.map((tool) => `<li>${tool}</li>`).join('')}
          </ul>
        </article>
      `;
    }

    if (type === 'template') {
      return `
        <article class="card">
          <span class="pill">${item.category}</span>
          <h3>${item.name}</h3>
          <p>${item.description}</p>
          <div class="tag-list">
            ${item.tags.map((tag) => `<span class="tag">${tag}</span>`).join('')}
          </div>
        </article>
      `;
    }

    return '';
  }).join('');
}

async function initHome() {
  const [useCases, stacks, templates] = await Promise.all([
    loadJson(useCaseData),
    loadJson(stackData),
    loadJson(templateData)
  ]);

  renderCards('featured-use-cases', useCases.slice(0, 3), 'use-case');
  renderCards('featured-stacks', stacks.slice(0, 3), 'stack');
  renderCards('featured-templates', templates.slice(0, 3), 'template');
}

async function initUseCases() {
  const useCases = await loadJson(useCaseData);
  renderCards('use-cases-grid', useCases, 'use-case');
}

async function initStacks() {
  const stacks = await loadJson(stackData);
  renderCards('stacks-grid', stacks, 'stack');
}

async function initTemplates() {
  const templates = await loadJson(templateData);
  renderCards('templates-grid', templates, 'template');
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('featured-use-cases')) {
    initHome();
  }

  if (document.getElementById('use-cases-grid')) {
    initUseCases();
  }

  if (document.getElementById('stacks-grid')) {
    initStacks();
  }

  if (document.getElementById('templates-grid')) {
    initTemplates();
  }
});
