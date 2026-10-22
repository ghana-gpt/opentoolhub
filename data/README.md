# OpenToolHub data

This folder is the single source of truth for the catalog. The Python
recommender, the validator, and the static site all read these files; the site
gets a staged copy at `site/data/` because browsers cannot read outside the
served directory.

Every file is a JSON array of objects with a unique kebab-case `id`. The full
field list, enums, and cross-file rules are in
[docs/data-model.md](../docs/data-model.md).

## Files

- `apis.json` — public APIs, official links, auth, pricing, and freshness
- `categories.json` — tool categories used by APIs, stacks, and the builder
- `examples.json` — worked walkthroughs, one per use case
- `stacks.json` — tool combinations with alternatives in every slot
- `templates.json` — starter and variant projects under `templates/`
- `use-cases.json` — the entry point: goals, keywords, aliases, and references

`README.md` (this file) is documentation, not catalog data.

## How the data is used

- `scripts/validate.py --strict` checks required fields, enums, unique ids,
  reciprocal references, and file paths.
- `scripts/recommend.py` resolves a plain-language goal to one use case, then
  prints its stack, APIs, templates, and example.
- `site/js/data.js` loads the staged copy and applies keyword matching and
  category filters in the browser.

## Changing data

1. Read [docs/data-model.md](../docs/data-model.md) first.
2. Keep both sides of every relationship: use case ↔ stack and use case ↔
   template.
3. Run the checks before opening a pull request:

```bash
python3 scripts/validate.py --strict
python3 -m unittest discover -s tests -v
python3 scripts/build_site.py --check
```
