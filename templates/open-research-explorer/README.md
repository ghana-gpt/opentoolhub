# Open research explorer starter

This starter is for tools that help people find research outputs, understand their metadata, and follow the evidence back to the source.

## Typical goal

A researcher, librarian, or AI builder wants one search flow across datasets, preprints, and published records without losing the DOI, license, or provenance of each result.

## Suggested stack

- Zenodo for datasets, software, and DOI records
- arXiv for preprint metadata and full-text links
- OpenAlex for works, authors, institutions, and citation context
- Crossref for DOI and publisher metadata
- OpenAI or Hugging Face Inference for summarization after retrieval

## Example flow

1. The user enters a research question or topic
2. Repositories and scholarly indexes return candidate records
3. Results are grouped by output type: dataset, preprint, or publication
4. The user opens a record and sees its DOI, authors, license, and source
5. A summary is generated only from the retrieved records and cited back to them

## Recommended features

- faceted search by output type, year, and institution
- DOI and license shown next to every result
- citation trails that preserve the original metadata
- saved searches and exportable bibliographies
- generated summaries with inline source links

## Best use cases

- literature reviews
- dataset discovery
- reproducible research workflows
- research monitoring and alerts

## Why this matters

Open research is only reusable when its provenance survives the search experience. This template treats citations and licenses as product features, not footnotes.
