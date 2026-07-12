---
title: Search
order: 6
---

# Search

Runbook provides full-text search across all current documents.

## What Gets Searched

Search queries match against three fields:

- **Title** — the document's display name
- **Description** — the optional summary field set when uploading
- **Content** — the full text of the markdown file (with YAML frontmatter stripped)

All matching is case-insensitive substring search. A query for "deploy" will match "Deployment Checklist", "How to deploy", and any document containing the word "deploy" in its body.

## Where to Search

- **Dashboard** — click **Search** in the page header
- **Document list** — use the search field at the top to filter the list
- **Live search** — the search results page supports htmx-powered instant results as you type

## Search Indexing

Document content is extracted and stored in a `content_text` field whenever a document is created, uploaded, or edited. This means:

- Edits made via the in-browser editor are searchable immediately
- New versions are indexed on upload
- To re-index all documents (e.g., after a bulk import), run:

```bash
uv run python manage.py reindex_documents
```
