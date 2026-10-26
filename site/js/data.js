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
  "a an and any app application are around best build building can compare compared comparison create do does find finder for from get good great help how i in into is it like looking make me my near nearby need needs new of on or please show shows simple some that the their them there this to tool tools us use used using versus vs want we where which who why will with you your".split(
    " "
  )
);

// Scoring constants and stem rules mirrored from scripts/recommend.py. Keep the
// two implementations in step: tests/test_site.py checks the published contract.
const MAX_TOKEN_WEIGHT = 4;
const MIN_COVERAGE = 0.5;
const KEYWORD_SCORE_FLOOR = 50;
const KEYWORD_SCORE_SPAN = 38;
const MAX_KEYWORD_SCORE = 88;
const FUZZY_WEIGHT = 0.8;
const MIN_KEYWORD_SCORE = 55;
const FUZZY_MIN_WEIGHT = 3;

const STEM_RULES = [
  ["isations", "ize"],
  ["izations", "ize"],
  ["isation", "ize"],
  ["ization", "ize"],
  ["ising", "ize"],
  ["izing", "ize"],
  ["ised", "ize"],
  ["ized", "ize"],
  ["ises", "ize"],
  ["izes", "ize"],
  ["ise", "ize"],
  ["ize", "ize"],
];

/** Reduce a token to one form so plurals and -ise spellings still match. */
export function stem(token) {
  let word = token;
  if (word.length <= 3) {
    return word;
  }
  for (const [suffix, replacement] of STEM_RULES) {
    if (word.endsWith(suffix)) {
      word = word.slice(0, -suffix.length) + replacement;
      break;
    }
  }
  if (word.endsWith("ies") && word.length > 4) {
    word = `${word.slice(0, -3)}y`;
  } else if (word.endsWith("sses")) {
    word = word.slice(0, -2);
  } else if (word.endsWith("s") && !/(ss|us|is)$/.test(word) && word.length > 3) {
    word = word.slice(0, -1);
  }
  if (word.endsWith("ing") && word.length > 5) {
    word = word.slice(0, -3);
    if (word.length > 2 && word[word.length - 1] === word[word.length - 2]) {
      word = word.slice(0, -1);
    }
  } else if (word.endsWith("ed") && word.length > 4) {
    word = word.slice(0, -2);
  }
  return word;
}

/** Tokens that carry meaning for search, dropping common filler words. */
export function searchTokens(value) {
  return tokenize(value).filter((token) => !STOPWORDS.has(token));
}

/** Stopword-filtered, stemmed tokens used for ranking. */
export function scoringTokens(value) {
  return searchTokens(value).map(stem);
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

/** Match _search_document() in scripts/recommend.py field for field. */
export function useCaseSearchText(useCase, data) {
  const categoryNames = useCase.categories.flatMap((id) => {
    const category = data.categoryById.get(id);
    return category ? [category.name, ...category.aliases] : [id];
  });
  const stackTerms = useCase.stack_ids.flatMap((id) => {
    const stack = data.stackById.get(id);
    return stack
      ? [stack.name, ...stack.best_for, ...stack.tools.map((tool) => tool.slot)]
      : [];
  });
  const templateNames = useCase.template_ids.flatMap((id) => {
    const template = data.templateById.get(id);
    return template ? [template.name] : [];
  });
  return [
    useCase.name,
    useCase.summary,
    useCase.goal,
    ...useCase.aliases,
    ...useCase.keywords,
    ...useCase.personas,
    ...categoryNames,
    ...stackTerms,
    ...templateNames,
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

/**
 * Weight every searchable term of every use case by the field containing it.
 * Mirrors _use_case_weights() and _build_index() in scripts/recommend.py.
 */
export function buildSearchIndex(data) {
  const weights = new Map();
  for (const useCase of data.useCases) {
    const terms = new Map();
    const add = (text, weight) => {
      for (const term of scoringTokens(text)) {
        if ((terms.get(term) ?? 0) < weight) {
          terms.set(term, weight);
        }
      }
    };
    add(useCase.name, 4);
    for (const alias of useCase.aliases) {
      add(alias, 4);
    }
    for (const keyword of useCase.keywords) {
      add(keyword, 3);
    }
    add(useCase.summary, 2);
    add(useCase.goal, 2);
    for (const persona of useCase.personas) {
      add(persona, 1);
    }
    for (const id of useCase.categories) {
      const category = data.categoryById.get(id);
      if (category) {
        add(category.name, 2);
        for (const alias of category.aliases) {
          add(alias, 2);
        }
      }
    }
    for (const id of useCase.stack_ids) {
      const stack = data.stackById.get(id);
      if (stack) {
        add(stack.name, 2);
        for (const text of stack.best_for) {
          add(text, 1);
        }
        for (const tool of stack.tools) {
          add(tool.slot, 1);
        }
      }
    }
    for (const id of useCase.template_ids) {
      const template = data.templateById.get(id);
      if (template) {
        add(template.name, 2);
      }
    }
    weights.set(useCase.id, terms);
  }
  const documentFrequency = new Map();
  for (const terms of weights.values()) {
    for (const term of terms.keys()) {
      documentFrequency.set(term, (documentFrequency.get(term) ?? 0) + 1);
    }
  }
  return { weights, documentFrequency, count: Math.max(weights.size, 1) };
}

function idf(term, index) {
  const frequency = index.documentFrequency.get(term) ?? 0;
  if (!frequency) {
    return 1;
  }
  return Math.log(1 + index.count / frequency);
}

/** True when the two strings differ by at most one edit or adjacent swap. */
function withinOneEdit(left, right) {
  if (left === right) {
    return true;
  }
  if (Math.abs(left.length - right.length) > 1) {
    return false;
  }
  let start = 0;
  const limit = Math.min(left.length, right.length);
  while (start < limit && left[start] === right[start]) {
    start += 1;
  }
  let endLeft = left.length;
  let endRight = right.length;
  while (
    endLeft > start &&
    endRight > start &&
    left[endLeft - 1] === right[endRight - 1]
  ) {
    endLeft -= 1;
    endRight -= 1;
  }
  const remainderLeft = left.slice(start, endLeft);
  const remainderRight = right.slice(start, endRight);
  if (remainderLeft.length <= 1 && remainderRight.length <= 1) {
    return true;
  }
  return (
    remainderLeft.length === 2 &&
    remainderRight.length === 2 &&
    remainderLeft === [...remainderRight].reverse().join("")
  );
}

function fuzzyTerm(term, terms) {
  if (term.length < 5) {
    return null;
  }
  const matches = [];
  for (const [candidate, weight] of terms) {
    if (weight >= FUZZY_MIN_WEIGHT && withinOneEdit(term, candidate)) {
      matches.push(candidate);
    }
  }
  return matches.length === 1 ? matches[0] : null;
}

function evidence(useCaseId, tokens, index) {
  const terms = index.weights.get(useCaseId);
  let total = 0;
  let matchedWeight = 0;
  let exactMatches = 0;
  const matched = [];
  for (const token of tokens) {
    const tokenIdf = idf(token, index);
    total += tokenIdf * MAX_TOKEN_WEIGHT;
    if (terms.has(token)) {
      exactMatches += 1;
      matched.push(token);
      matchedWeight += tokenIdf * terms.get(token);
      continue;
    }
    const candidate = fuzzyTerm(token, terms);
    if (candidate) {
      matched.push(candidate);
      matchedWeight += tokenIdf * terms.get(candidate) * FUZZY_WEIGHT;
    }
  }
  return {
    coverage: total ? matchedWeight / total : 0,
    matched,
    fuzzyOnly: matched.length > 0 && exactMatches === 0,
  };
}

/** Round half to even, matching Python's round() so both rankers agree. */
function roundScore(value) {
  const lower = Math.floor(value);
  const fraction = value - lower;
  if (fraction > 0.5) {
    return lower + 1;
  }
  if (fraction < 0.5) {
    return lower;
  }
  return lower % 2 === 0 ? lower : lower + 1;
}

function scoreOneUseCase(useCase, normalizedIdea, tokens, index) {
  if (normalizedIdea === normalize(useCase.id)) {
    return { score: 100, matchedBy: "id" };
  }
  if (normalizedIdea === normalize(useCase.name)) {
    return { score: 95, matchedBy: "name" };
  }
  if (useCase.aliases.some((alias) => normalizedIdea === normalize(alias))) {
    return { score: 90, matchedBy: "alias" };
  }
  if (!tokens.length) {
    return { score: 0, matchedBy: "none" };
  }

  const { coverage, matched, fuzzyOnly } = evidence(useCase.id, tokens, index);
  // One hit inside a multi-word phrase is weak evidence, unless the term is a
  // rare keyword or name match that almost no other use case shares.
  if (matched.length < 2 && tokens.length > 1) {
    const terms = index.weights.get(useCase.id);
    const distinctive = matched.some(
      (term) =>
        terms.get(term) >= 3 && (index.documentFrequency.get(term) ?? 0) <= 2
    );
    if (!distinctive) {
      return { score: 0, matchedBy: "none" };
    }
  } else if (coverage < MIN_COVERAGE) {
    return { score: 0, matchedBy: "none" };
  }
  const rarity = Math.max(
    ...matched.map(
      (term) => 1 - (index.documentFrequency.get(term) ?? 0) / index.count
    )
  );
  const strength = coverage * (0.6 + 0.4 * rarity);
  const score = Math.min(
    MAX_KEYWORD_SCORE,
    KEYWORD_SCORE_FLOOR + roundScore(KEYWORD_SCORE_SPAN * strength)
  );
  if (score < MIN_KEYWORD_SCORE) {
    return { score: 0, matchedBy: "none" };
  }
  return { score, matchedBy: fuzzyOnly ? "fuzzy" : "keywords" };
}

/** Rank use cases for an idea, optionally narrowed to selected category ids. */
export function scoreUseCases(
  idea,
  categoryIds,
  data,
  index = buildSearchIndex(data)
) {
  const hasIdea = String(idea).trim().length > 0;
  const normalizedIdea = normalize(idea);
  const tokens = scoringTokens(idea);
  const results = [];
  for (const useCase of data.useCases) {
    const overlap = categoryIds.filter((id) => useCase.categories.includes(id));
    if (categoryIds.length && !overlap.length) {
      continue;
    }
    const { score, matchedBy } = scoreOneUseCase(
      useCase,
      normalizedIdea,
      tokens,
      index
    );
    if (hasIdea && !score) {
      continue;
    }
    results.push({ useCase, score, matchedBy });
  }
  results.sort((left, right) => {
    const leftName = left.useCase.name.toLowerCase();
    const rightName = right.useCase.name.toLowerCase();
    return (
      right.score - left.score ||
      (leftName < rightName ? -1 : leftName > rightName ? 1 : 0)
    );
  });
  return results;
}

/** Closest partial matches, used when nothing clears the scoring threshold. */
export function suggestUseCases(
  idea,
  data,
  index = buildSearchIndex(data),
  limit = 3
) {
  const tokens = scoringTokens(idea);
  if (!tokens.length) {
    return [];
  }
  const closest = [];
  for (const useCase of data.useCases) {
    const { coverage, matched } = evidence(useCase.id, tokens, index);
    if (!matched.length) {
      continue;
    }
    closest.push({ useCase, matched: [...new Set(matched)], coverage });
  }
  closest.sort((left, right) => {
    const byTerms = right.matched.length - left.matched.length;
    if (byTerms) {
      return byTerms;
    }
    if (right.coverage !== left.coverage) {
      return right.coverage - left.coverage;
    }
    return left.useCase.name.toLowerCase() < right.useCase.name.toLowerCase()
      ? -1
      : 1;
  });
  return closest.slice(0, limit);
}

