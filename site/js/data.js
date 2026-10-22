/**
 * Load the JSON catalog and expose lookup and filtering helpers.
 *
 * Every page reads from data/*.json via scripts/build_site.py. Nothing is
 * hardcoded here: use cases, stacks, APIs, templates, and examples all come
 * from the validated data layer.
 */

const DATA_FILES = [
  "categories",
  "use-cases",
  "stacks",
  "apis",
  "templates",
  "examples",
];

async function fetchJson(name) {
  const response = await fetch(`data/${name}.json`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Could not load data/${name}.json (HTTP ${response.status}).`);
  }
  const payload = await response.json();
  if (!Array.isArray(payload)) {
    throw new Error(`data/${name}.json must contain a JSON array.`);
  }
  return payload;
}

let cache = null;

/** Load every data file once and index it for the page. */
export function loadData() {
  if (cache) {
    return cache;
  }
  const pending = Promise.all(DATA_FILES.map(fetchJson)).then(
    ([categories, useCases, stacks, apis, templates, examples]) => ({
      categories,
      useCases,
      stacks,
      apis,
      templates,
      examples,
      categoryById: new Map(categories.map((item) => [item.id, item])),
      useCaseById: new Map(useCases.map((item) => [item.id, item])),
      stackById: new Map(stacks.map((item) => [item.id, item])),
      apiById: new Map(apis.map((item) => [item.id, item])),
      templateById: new Map(templates.map((item) => [item.id, item])),
    })
  );
  cache = pending;
  pending.catch(() => {
    if (cache === pending) {
      cache = null;
    }
  });
  return pending;
}

/** Lowercase, strip accents, and reduce punctuation to single spaces. */
export function normalize(value) {
  return String(value ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function tokenize(value) {
  const text = normalize(value);
  return text ? text.split(" ") : [];
}

const STOPWORDS = new Set(
  "a an and app application build building create for from i in into my of on or the to tool tools using want with".split(
    " "
  )
);

/** Tokens that carry meaning for search, dropping common filler words. */
export function searchTokens(value) {
  return tokenize(value).filter((token) => !STOPWORDS.has(token));
}

/** True when every query token starts a word in the text (empty query = match). */
export function matchesQuery(text, query) {
  const tokens = searchTokens(query);
  if (!tokens.length) {
    return true;
  }
  const words = normalize(text).split(" ");
  return tokens.every((token) => words.some((word) => word.startsWith(token)));
}

export function useCaseSearchText(useCase, data) {
  const categoryNames = useCase.categories.map((id) => {
    const category = data.categoryById.get(id);
    return category ? category.name : id;
  });
  return [
    useCase.name,
    useCase.summary,
    useCase.goal,
    ...useCase.aliases,
    ...useCase.keywords,
    ...useCase.personas,
    ...categoryNames,
  ].join(" ");
}

export function stackSearchText(stack, data) {
  const apiNames = stack.tools.flatMap((tool) =>
    tool.api_ids.map((id) => data.apiById.get(id)?.name ?? id)
  );
  return [
    stack.name,
    stack.notes,
    stack.difficulty,
    ...stack.best_for,
    ...stack.tools.map((tool) => tool.slot),
    ...apiNames,
  ].join(" ");
}

export function apiSearchText(api, data) {
  const categoryNames = api.category_ids.map(
    (id) => data.categoryById.get(id)?.name ?? id
  );
  return [
    api.name,
    api.description,
    api.auth,
    api.pricing,
    ...api.best_for,
    ...api.related_tags,
    ...categoryNames,
  ].join(" ");
}

export function stacksForUseCase(useCase, data) {
  return useCase.stack_ids
    .map((id) => data.stackById.get(id))
    .filter(Boolean);
}

export function templatesForUseCase(useCase, data) {
  return useCase.template_ids
    .map((id) => data.templateById.get(id))
    .filter(Boolean);
}

export function examplesForUseCase(useCase, data) {
  return data.examples.filter((example) => example.use_case === useCase.id);
}

export function apisForStack(stack, data) {
  const seen = new Set();
  const apis = [];
  for (const tool of stack.tools) {
    for (const id of tool.api_ids) {
      if (seen.has(id)) {
        continue;
      }
      const api = data.apiById.get(id);
      if (api) {
        seen.add(id);
        apis.push(api);
      }
    }
  }
  return apis;
}
