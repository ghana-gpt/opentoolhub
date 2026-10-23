# Open research data example

## Product idea

A research explorer that searches datasets, preprints, and published records, then keeps the DOI, license, and citation trail attached to every result.

## Problem it solves

Research outputs live in many repositories and indexes. A normal search result loses the provenance that makes a dataset reusable or a claim checkable. Researchers need discovery and traceability in the same workflow.

## Suggested stack

- Zenodo for datasets, software, and DOI records
- arXiv for preprint metadata
- OpenAlex for works, authors, and citation context
- Crossref for DOI and publisher metadata
- OpenAI or Hugging Face Inference for summaries after retrieval

## Feature ideas

- one search across datasets, preprints, and publications
- result cards with DOI, authors, license, and source
- citation trails and related-record links
- saved searches and exportable bibliographies
- generated summaries with inline citations

## Example user flow

1. A researcher enters a question about local heat and health.
2. The tool queries repositories and scholarly indexes.
3. Results are grouped by dataset, preprint, and publication.
4. The researcher opens a record and checks its DOI and license.
5. A summary is generated from the selected records with links back to each source.

## Why this matters

Open research is valuable only if people can verify and reuse it. This workflow treats provenance as a first-class feature and keeps generated text anchored to retrieved records.
