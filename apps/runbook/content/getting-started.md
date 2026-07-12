---
title: Getting Started with Runbook
order: 1
---

# Getting Started with Runbook

Runbook is your team's knowledge base for operational documentation. Write and edit markdown documents directly in the browser, organize them into runbooks and sections, and search across all content.

## Version 1.0 — Markdown-First

Runbook v1.0 focuses on markdown as the single document format. This keeps things simple and ensures full-featured editing, rendering, and search from day one.

| Feature | Status |
|---------|--------|
| Markdown documents (.md) | Supported |
| In-browser editor with live preview | Supported |
| Full-text search (title + content) | Supported |
| Version history and restore | Supported |
| Bulk ZIP export with index | Supported |
| Slide view (presentations) | Coming soon |
| Step view (process timelines) | Coming soon |
| Word (.docx) and PDF support | Planned for v2 |

## Key Concepts

- **Runbook**: A top-level collection (e.g., "Operations", "Onboarding")
- **Section**: An organizational group within a runbook (e.g., "Incident Response", "Deploy Procedures")
- **Document**: A markdown file with title, description, and version history

## Quick Start

1. From the **Dashboard**, click **New Runbook** and give it a name
2. Open the runbook and click **New Section** to create a section
3. Click **New Document** to upload a `.md` file, or **New from Scratch** to start writing in the browser
4. The document renders as formatted HTML with a table of contents sidebar
5. Click **Edit Content** to open the in-browser markdown editor
6. Use **Search** to find documents by title, description, or content

## Editing Documents

There are two ways to modify a document's content:

- **Edit Content** — Opens a full-screen textarea editor. Toggle between editing and a live server-rendered preview. Saves directly to the file without creating a new version.
- **New Version** — Upload a replacement file. The old version is preserved in the version history and can be restored at any time.

## Search

Search looks across document titles, descriptions, and the full text content of every markdown file. Results link directly to the document detail page.

## Bulk Export

Download an entire runbook (or all runbooks) as a ZIP archive. Each runbook folder includes an `index.html` table of contents for offline browsing.
