# Skill: Help Documentation System

This skill describes how to create, edit, and manage help documentation in the SmallStack project.

## Overview

The help system is a file-based documentation viewer that renders Markdown files as HTML pages. It lives in `apps/help/` and uses:

- **Markdown files** for content (`apps/help/content/*.md`)
- **YAML config** for navigation, variables, and categories (`apps/help/content/_config.yaml`)
- **App-contributed docs** — Apps can register their own docs section via AppConfig
- **Django templates** for rendering (`templates/help/`)
- **CSS/JS** for styling (`static/smallstack/help/`)

## File Locations

```
apps/help/
├── content/                      # YOUR project's documentation
│   ├── _config.yaml              # Sections, navigation, variables
│   ├── index.md                  # Root section pages
│   └── [section-folder]/         # Optional sub-sections
│       ├── _config.yaml
│       └── page.md
├── utils.py                      # Markdown processing, grouping, two-tier loading
├── views.py                      # Views: Index, SectionIndex, Detail, SectionDetail
└── urls.py                       # URL routing

apps/smallstack/docs/             # Bundled SmallStack reference docs (app-contributed)
├── _config.yaml                  # SmallStack section config with categories
├── getting-started.md
├── kamal-deployment.md
└── ...

templates/help/
├── help_index.html           # Main help index (all sections)
├── help_section_index.html   # Section index with categorized card grids
├── help_detail.html          # Single doc page layout
└── includes/
    ├── help_sidebar.html     # Navigation sidebar (category-aware)
    └── help_card_icon.html   # SVG icon partial for help cards

static/smallstack/help/
├── css/help.css              # Help-specific styles
└── js/help.js                # Search, collapsibles, TOC
```

## Architecture: URL → View → Template

| URL | View | Template | Purpose |
|-----|------|----------|---------|
| `/help/` | `HelpIndexView` | `help_index.html` | Main index — shows all sections as card groups |
| `/help/<section>/` | `HelpSectionIndexView` | `help_section_index.html` | Section index — shows pages as categorized card grids |
| `/help/<slug>/` | `HelpDetailView` | `help_detail.html` | Root-level page detail |
| `/help/<section>/<slug>/` | `HelpSectionDetailView` | `help_detail.html` | Section page detail with sidebar |
| `/help/search-index.json` | `search_index_view` | — | JSON for client-side search |
| `/help/slides/<deck>/` | `SlideView` | `slides.html` | Slide deck presentation |

### View Context Variables

**`HelpSectionIndexView`** passes:
- `section` — dict with `slug`, `title`, `description`, `pages`
- `grouped_pages` — list of `{"category": str, "pages": list}` dicts (category-grouped pages)
- `sections` — all sections for navigation

**`HelpSectionDetailView`** passes:
- `page` — the rendered page dict
- `section_pages` — flat page list (for prev/next navigation)
- `section_pages_grouped` — grouped page list (for sidebar category headings)
- `prev_page`, `next_page` — adjacent pages in flat order

### Key Utility Functions (`utils.py`)

| Function | Returns | Purpose |
|----------|---------|---------|
| `get_section_pages(section)` | `list[dict]` | Flat page list — used for prev/next nav, search index |
| `get_section_pages_grouped(section)` | `list[dict]` | Grouped page list — used for section index and sidebar |
| `get_section_config(section)` | `dict` | Raw YAML config for a section |
| `get_help_page(slug, section)` | `dict \| None` | Load and render a single page |
| `get_all_sections()` | `list[dict]` | All sections with metadata |
| `build_search_index()` | `list[dict]` | Full-text search index |

### App-Contributed Docs

Apps can register their own help section by setting attributes on their AppConfig:

```python
class SmallStackConfig(AppConfig):
    help_content_dir = "docs"           # Relative to app directory
    help_section_slug = "smallstack"    # URL slug for the section
    help_section_title = "SmallStack Reference"
```

The app's `docs/` directory must contain a `_config.yaml` and `.md` files.

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

The help system uses a **section-based hierarchy**. Edit `apps/help/content/_config.yaml` and add the page to the appropriate section's `pages` list:

```yaml
sections:
  - slug: ""                           # Root section
    title: "Project Documentation"
    pages:
      # ... existing pages ...
      - slug: my-new-page             # Must match filename without .md
        title: "Your Page Title"      # Display title
        description: "Brief description for index card"
        icon: "document"              # Icon name (see available icons below)
        category: "Getting Started"   # Optional: group under this category heading

  # Optional: create sub-sections with their own folder
  - slug: guides
    title: "User Guides"
    pages:
      - slug: tutorial
        title: "Tutorial"
        description: "Step-by-step tutorial"
        icon: "rocket"
    # Files go in: apps/help/content/guides/tutorial.md
```

**Page order:** Pages appear in the order listed in `_config.yaml`. This order is used for:
- The index page card grid (within each category group)
- The sidebar navigation
- Previous/Next navigation links

### Step 3: Add Icon (if using a new icon name)

If you use a new icon name, add it to `templates/help/includes/help_card_icon.html`:

```html
{% elif page.icon == "your-icon-name" %}
<svg viewBox="0 0 24 24" width="32" height="32" fill="currentColor">
    <path d="...svg path data..."/>
</svg>
```

**Available icons:** `home`, `rocket`, `book`, `help`, `palette`, `docker`, `folder`, `chat`, `info`, `email`, `tasks`, `package`, `settings`, `ai`, `database`, `cloud`, `cube`, `code`, `lock`, `link`, `chart`, `clock`, `users`, `slides`, `terminal`, `document` (default fallback)

## Category Grouping

Categories let you organize a section's pages into visual groups on the section index page and in the sidebar navigation.

### How It Works

1. **Opt-in:** If a section's `_config.yaml` has a `categories:` list, grouping is enabled. No list = flat rendering (identical to the default behavior).
2. **Defined order:** Categories appear in the order listed in `categories:`. This controls both the card grid and sidebar.
3. **Page assignment:** Each page references a category by name via the `category:` field.

### Configuration

```yaml
# Section _config.yaml
title: "My Documentation"

# Define category display order (optional — omit for flat rendering)
categories:
  - "Getting Started"
  - "Configuration"
  - "Advanced"

pages:
  - slug: readme
    title: "README"
    icon: "book"
    category: "Getting Started"

  - slug: settings
    title: "Settings"
    icon: "settings"
    category: "Configuration"

  - slug: faq
    title: "FAQ"
    icon: "chat"
    # No category → appears in ungrouped bucket at the end
```

### Rendering Rules

| Scenario | Behavior |
|----------|----------|
| Section has `categories:` list | Pages grouped by category with headings |
| Section has NO `categories:` list | Flat card grid, identical to default |
| Page has `category:` matching list entry | Appears under that category heading |
| Page has `category:` NOT in list | Appended alphabetically after listed categories; dev warning logged |
| Page has no `category:` field | Goes into ungrouped bucket rendered last (no heading) |

### Template Rendering

**Section index (`help_section_index.html`):**
```html
{% for group in grouped_pages %}
<div class="help-section">
    {% if group.category %}
    <h2 class="help-category-title">{{ group.category }}</h2>
    {% endif %}
    <div class="help-cards-grid">
        {% for page in group.pages %}
        ...card markup...
        {% endfor %}
    </div>
</div>
{% endfor %}
```

When no categories are defined, `grouped_pages` contains a single group with `category=""`, so no heading is rendered — identical to the old flat layout.

**Sidebar (`help_sidebar.html`):**
For the current section, if multiple groups exist, category sub-headings appear between nav link lists. Other sections render flat.

### CSS Classes

| Class | Element | Description |
|-------|---------|-------------|
| `.help-category-title` | `<h2>` | Category heading on section index (muted, uppercase, small) |
| `.help-nav-category-title` | `<h4>` | Category sub-heading in sidebar nav |
| `.help-section + .help-section` | spacing | Gap between category groups |

## Editing Existing Pages

1. Edit the `.md` file directly in `apps/help/content/`
2. Changes are reflected immediately (no server restart needed in development)
3. To change title/description/category/order, edit `_config.yaml`

## Removing a Help Page

1. Delete the `.md` file from `apps/help/content/`
2. Remove the corresponding entry from `_config.yaml` under `pages:`

## Template Variables

Variables can be used in Markdown files with `{{ variable_name }}` syntax.

**Defined in `_config.yaml`:**

```yaml
variables:
  version: "1.0.0"
  project_name: "Django SmallStack"
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
  project_name: "Django SmallStack"
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
  category: "Reference"
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
See the [Docker Deployment](/help/smallstack/docker-deployment/) guide.
Check the [FAQ](/help/smallstack/faq/) for common questions.
```

## Navigation Structure

### Sidebar (left)
- Shows all sections with their pages
- For the current section: if categories are defined, pages are grouped under category sub-headings
- Other sections show flat page lists
- Current page is highlighted
- "All Documentation" link at bottom

### On This Page (right)
- Auto-generated from `##` and `###` headings
- Sticky positioned, scrolls with content
- Hidden on FAQ pages and narrow screens

### Prev/Next (bottom)
- Based on page order in `_config.yaml` (flat order, not grouped)
- First page has no "Previous"
- Last page has no "Next"

## Styling Notes

Help pages use CSS from `static/smallstack/help/css/help.css`:

- Body text: 18px
- H2: 28px, H3: 24px, H4: 20px
- Tables: 18px with 14px padding
- Code blocks: 16px monospace
- Category headings: 13px, uppercase, muted color, bottom border
- Dark mode overrides included

## Search Functionality

- Client-side search using JavaScript
- Searches page titles and content
- Index built from `search-index.json` endpoint
- Debounced input (300ms delay)

## Bundled SmallStack Docs

SmallStack ships 35+ reference pages in `apps/smallstack/docs/`. These are **automatically contributed** as a "SmallStack Reference" section via AppConfig when `SMALLSTACK_DOCS_ENABLED=True` (the default).

The SmallStack docs use category grouping with 12 categories: Getting Started, Development, Customization, Theming, UI Components, Configuration, Database, Auth & Users, Built-in Tools, Packages, Deployment, and Reference.

### Controlling Bundled Docs

```python
# config/settings/base.py (or .env)
SMALLSTACK_DOCS_ENABLED = True   # Show bundled docs (default)
SMALLSTACK_DOCS_ENABLED = False  # Hide bundled docs
```

### Two-Tier Loading

The help system loads from two sources:
1. **`content/`** — Your project docs (conflict-free, fully customizable)
2. **App-contributed docs** — Apps with `help_content_dir` on their AppConfig (e.g., SmallStack's bundled docs)

User sections are shown first, app-contributed sections are appended at the end.

## Complete _config.yaml Example

```yaml
# Section _config.yaml (e.g., apps/help/content/guides/_config.yaml)

title: "User Guides"
description: "How to use this application"

# Variables available in markdown files
variables:
  version: "2.0.0"
  support_email: "help@example.com"

# Optional: define categories for grouped display
# Omit this entirely for flat (ungrouped) rendering
categories:
  - "Basics"
  - "Advanced"
  - "Troubleshooting"

pages:
  - slug: welcome
    title: "Welcome"
    description: "Introduction to the guides"
    icon: "home"
    category: "Basics"

  - slug: getting-started
    title: "Getting Started"
    description: "Quick start guide"
    icon: "rocket"
    category: "Basics"

  - slug: advanced-config
    title: "Advanced Configuration"
    description: "Power user settings"
    icon: "settings"
    category: "Advanced"

  - slug: faq
    title: "FAQ"
    description: "Frequently asked questions"
    icon: "chat"
    is_faq: true
    category: "Troubleshooting"
```

**Root help config** (different structure — defines sections, not pages directly):

```yaml
# apps/help/content/_config.yaml

title: "Help & Documentation"

variables:
  version: "1.0.0"
  project_name: "Your Project"

sections:
  - slug: ""
    title: "Project Documentation"
    pages:
      - slug: index
        title: "Welcome"
        icon: "home"

  - slug: guides
    title: "User Guides"

# App-contributed sections (like SmallStack) are appended automatically
```

## Page Config Fields Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `slug` | string | yes | — | Filename without `.md`, used in URL |
| `title` | string | no | slug (titlecased) | Display title |
| `description` | string | no | `""` | Subtitle shown on index cards |
| `icon` | string | no | `""` | Icon name for index cards (see list above) |
| `category` | string | no | `""` | Category group name (must match `categories:` list entry) |
| `is_faq` | boolean | no | `false` | Enable collapsible Q&A rendering |

## Troubleshooting

**Page not appearing:**
- Check filename matches slug in `_config.yaml`
- Ensure `.md` extension
- Verify YAML syntax (no tabs, proper indentation)

**Variables not substituting:**
- Use exact syntax: `{{ variable_name }}`
- Check variable exists in `_config.yaml` under `variables:`

**Categories not grouping:**
- Ensure `categories:` list exists at the top level of the section's `_config.yaml`
- Page `category:` values must match list entries exactly (case-sensitive)
- Check dev console/server logs for warnings about undefined categories

**Styling issues:**
- Clear browser cache
- Check `help.css` for the relevant class
- Dark mode uses `[data-theme="dark"]` selectors

**Navigation order wrong:**
- Order in `_config.yaml` `pages:` list determines order
- Move entries up/down in the list
- Category grouping does not change prev/next order — that always follows the flat page list
