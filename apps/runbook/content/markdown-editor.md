---
title: Markdown Editor
order: 5
---

# Markdown Editor

Runbook includes a built-in markdown editor for creating and editing documents directly in the browser.

## Opening the Editor

From any markdown document's detail page, click **Edit Content** in the page header. This opens a full-width textarea with the raw markdown content.

## Features

- **Monospace textarea** with syntax-friendly font and line height
- **Tab key** inserts 4 spaces (instead of moving focus)
- **Live preview** toggle renders the markdown server-side, so the preview matches the actual document display exactly
- **Auto-save to search index** — edits are immediately searchable

## Preview Mode

Click **Preview** in the toolbar to toggle between editing and preview. The preview is rendered on the server using the same markdown pipeline as the document detail page — what you see in preview is exactly what readers will see.

## Creating Documents from Scratch

From a runbook's detail page, click **New from Scratch** to create an empty markdown document. This generates a starter file with a `# Title` heading and opens the editor immediately.

## Markdown Syntax

Runbook supports standard markdown with these extensions:

| Feature | Syntax |
|---------|--------|
| Headings | `# H1`, `## H2`, `### H3` |
| Bold / Italic | `**bold**`, `*italic*` |
| Links | `[text](url)` |
| Images | `![alt](url)` |
| Code blocks | Triple backticks with optional language |
| Tables | Pipe-delimited (`\| A \| B \|`) |
| Blockquotes | `> quoted text` |
| Lists | `- item` or `1. item` |

## YAML Frontmatter

Documents may include optional YAML frontmatter at the top of the file. Frontmatter is stripped before rendering and does not appear in the document output or search index.

```markdown
---
title: My Document
author: Jane
---

# Actual Content Starts Here
```
