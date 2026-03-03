# Skill: Help Documentation System

This skill describes how to create, edit, and manage help documentation in the Admin Starter project.

## Overview

The help system is a file-based documentation viewer that renders Markdown files as HTML pages. It lives in `apps/help/` and uses:

- **Markdown files** for content (`apps/help/content/*.md`)
- **YAML config** for navigation and variables (`apps/help/content/_config.yaml`)
- **Django templates** for rendering (`templates/help/`)
- **CSS/JS** for styling (`static/help/`)

## File Locations

```
apps/help/
├── content/
│   ├── _config.yaml          # Navigation order, variables, page metadata
│   ├── getting-started.md    # Documentation pages
│   ├── about.md
│   ├── theming.md
│   └── [other-pages].md
├── utils.py                  # Markdown processing functions
├── views.py                  # HelpIndexView, HelpDetailView
└── urls.py                   # URL routing

templates/help/
├── help_index.html           # Documentation index with cards
├── help_detail.html          # Single doc page layout
└── includes/
    └── help_sidebar.html     # Navigation sidebar

static/help/
├── css/help.css              # Help-specific styles
└── js/help.js                # Search, collapsibles, TOC
```

## Creating a New Help Page

### Step 1: Create the Markdown File

Create a new `.md` file in `apps/help/content/`:

```markdown
---
title: Your Page Title
description: Brief description for the index card
---

# Your Page Title

Your content here using standard Markdown...

## Section Heading

- Bullet points
- More items

### Subsection

Code blocks, tables, etc.
```

**File naming:**
- Use lowercase with hyphens: `my-new-page.md`
- The filename (without `.md`) becomes the URL slug: `/help/my-new-page/`

### Step 2: Add to _config.yaml

Edit `apps/help/content/_config.yaml` and add the page to the `pages` list:

```yaml
pages:
  # ... existing pages ...

  - slug: my-new-page          # Must match filename without .md
    title: "Your Page Title"   # Display title
    description: "Brief description for index card"
    icon: "document"           # Icon name (see available icons below)
```

**Page order:** Pages appear in the order listed in `_config.yaml`. This order is used for:
- The index page card grid
- The sidebar navigation
- Previous/Next navigation links

### Step 3: Add Icon (if using a new icon name)

If you use a new icon name, add it to `templates/help/help_index.html`:

```html
{% elif page.icon == "your-icon-name" %}
<svg viewBox="0 0 24 24" width="32" height="32" fill="currentColor">
    <path d="...svg path data..."/>
</svg>
```

**Available icons:** `rocket`, `help`, `palette`, `docker`, `folder`, `chat`, `info`, `email`, `package`, `settings`, `document` (default)

## Editing Existing Pages

1. Edit the `.md` file directly in `apps/help/content/`
2. Changes are reflected immediately (no server restart needed in development)
3. To change title/description/order, edit `_config.yaml`

## Removing a Help Page

1. Delete the `.md` file from `apps/help/content/`
2. Remove the corresponding entry from `_config.yaml` under `pages:`

## Template Variables

Variables can be used in Markdown files with `{{ variable_name }}` syntax.

**Defined in `_config.yaml`:**

```yaml
variables:
  version: "1.0.0"
  project_name: "Admin Starter"
  python_version: "3.12"
  django_version: "5.0"
```

**Usage in Markdown:**

```markdown
Welcome to {{ project_name }} version {{ version }}!
```

**Adding new variables:**

```yaml
variables:
  version: "1.0.0"
  project_name: "Admin Starter"
  my_custom_var: "Custom Value"    # Add here
```

## Special Page Types

### FAQ Pages

Add `is_faq: true` to make a page use collapsible Q&A styling:

```yaml
- slug: faq
  title: "FAQ"
  description: "Frequently asked questions"
  icon: "chat"
  is_faq: true    # Enables collapsible sections
```

In FAQ pages, each `## Heading` becomes a collapsible question, and the content until the next `##` is the answer.

## Markdown Features Supported

- **Headings:** `#`, `##`, `###`, `####`
- **Emphasis:** `**bold**`, `*italic*`
- **Lists:** Ordered and unordered
- **Code:** Inline `` `code` `` and fenced blocks with syntax highlighting
- **Tables:** GitHub-flavored markdown tables
- **Links:** `[text](url)` - internal links use `/help/slug/`
- **Blockquotes:** `> quoted text`
- **Images:** `![alt](url)`

**Internal links example:**

```markdown
See the [Docker Deployment](/help/docker-deployment/) guide.
Check the [FAQ](/help/faq/) for common questions.
```

## Navigation Structure

### Sidebar (left)
- Shows all pages from `_config.yaml` in order
- Current page is highlighted
- "All Documentation" link at bottom

### On This Page (right)
- Auto-generated from `##` and `###` headings
- Sticky positioned, scrolls with content
- Hidden on FAQ pages and narrow screens

### Prev/Next (bottom)
- Based on page order in `_config.yaml`
- First page has no "Previous"
- Last page has no "Next"

## URLs

| URL | View | Purpose |
|-----|------|---------|
| `/help/` | HelpIndexView | Documentation index |
| `/help/<slug>/` | HelpDetailView | Single doc page |
| `/help/search-index.json` | search_index_view | JSON for client-side search |

## Styling Notes

Help pages use CSS from `static/help/css/help.css`:

- Body text: 18px
- H2: 28px, H3: 24px, H4: 20px
- Tables: 18px with 14px padding
- Code blocks: 16px monospace
- Dark mode overrides included

## Search Functionality

- Client-side search using JavaScript
- Searches page titles and content
- Index built from `search-index.json` endpoint
- Debounced input (300ms delay)

## Complete _config.yaml Example

```yaml
# Help System Configuration

title: "Help & Documentation"

variables:
  version: "1.0.0"
  project_name: "Admin Starter"
  python_version: "3.12"
  django_version: "5.0"

pages:
  - slug: getting-started
    title: "Getting Started"
    description: "Quick start guide and project overview"
    icon: "rocket"

  - slug: about
    title: "About & Inspiration"
    description: "The philosophy behind Admin Starter"
    icon: "info"

  - slug: theming
    title: "Theming & Customization"
    description: "Customize colors, dark mode, and components"
    icon: "palette"

  - slug: faq
    title: "FAQ"
    description: "Frequently asked questions"
    icon: "chat"
    is_faq: true
```

## Troubleshooting

**Page not appearing:**
- Check filename matches slug in `_config.yaml`
- Ensure `.md` extension
- Verify YAML syntax (no tabs, proper indentation)

**Variables not substituting:**
- Use exact syntax: `{{ variable_name }}`
- Check variable exists in `_config.yaml` under `variables:`

**Styling issues:**
- Clear browser cache
- Check `help.css` for the relevant class
- Dark mode uses `[data-theme="dark"]` selectors

**Navigation order wrong:**
- Order in `_config.yaml` `pages:` list determines order
- Move entries up/down in the list
