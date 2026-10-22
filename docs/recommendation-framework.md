# Recommendation system and product differentiation

OpenToolHub is designed to be more than a registry of tools. It is a practical recommendation system for builders.

## Core difference from a simple API list

A basic directory lets users browse names and categories. OpenToolHub is designed to help users answer:

- What should I build?
- What tools fit my idea?
- What stack makes sense?
- Which tools are best together?
- Where should I begin prototyping?

## The value model

OpenToolHub adds value through a few layers:

1. Use-case discovery
2. Stack recommendations
3. Starter templates
4. Integration guidance
5. Builder context and product fit
6. Community contributions

## Recommendation dimensions

A useful recommendation system should rate tools by several factors:

- ease of integration
- data freshness
- regional or local coverage
- cost and operational effort
- AI-readiness
- civic/public-interest suitability
- overall reliability
- open-data friendliness
- project type fit
- maintenance and community support

## Why this matters

A public tool directory helps with lookup. A recommendation engine helps with decision-making.

The project aims to move users from raw discovery to better product judgment.

## Implemented today

The current recommender (`scripts/recommend.py`) is deterministic and data
driven. It scores ids, names, aliases, and keyword coverage from `data/`, then
resolves the winning use case to its stack, APIs, templates, examples, and
rationale. Ambiguous matches return alternatives. It does not call a model and
does not rank providers by quality.

## Not implemented yet

These are design goals, not current behavior:

- per-tool quality or reliability scores
- regional coverage comparison
- comparison pages between overlapping APIs
- persona-based filtering beyond catalog text
- community scoring or submitted rankings

The data model already records integration complexity, pricing, auth, and data
freshness so these comparisons can be added without inventing values later.
