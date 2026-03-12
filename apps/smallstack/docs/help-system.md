---
title: Using the Help System
description: How to add and edit documentation pages
---

# Using the Help System

The help system is a file-based documentation viewer built into {{ project_name }}. It renders Markdown files as HTML pages with automatic navigation, search, category grouping, and table of contents.

## How It Works

Documentation is loaded from two sources:

- **`apps/help/content/`** - Your project's documentation (conflict-free zone)
- **App-contributed docs** - Apps can register their own doc sections (e.g., SmallStack reference docs)

The system supports:

- **Sections** - Organize docs into folders with their own config
- **Categories** - Group pages within a section under visual headings
- **Variables** - Template substitution (e.g., `{{ version }}`)
- **Search** - Client-side full-text search
- **FAQ mode** - Collapsible question/answer sections

## Documentation Structure

```
apps/help/
├── content/                 # YOUR docs (edit freely)
│   ├── _config.yaml         # Your sections and pages
│   ├── index.md             # Your welcome page
│   └── guides/              # Your custom sections
│       ├── _config.yaml
│       └── user-guide.md
└── utils.py                 # Processing logic

apps/smallstack/docs/        # SmallStack docs (app-contributed)
├── _config.yaml             # SmallStack config with categories
├── getting-started.md
└── ...
```

**URLs:**
- `/help/` - Documentation index (all sections)
- `/help/index/` - Your welcome page
- `/help/guides/user-guide/` - Your section pages
- `/help/smallstack/getting-started/` - SmallStack docs

## Controlling SmallStack Docs

SmallStack reference docs are shown by default. To hide them:

```python
# config/settings/base.py (or .env)
SMALLSTACK_DOCS_ENABLED = False
```

When disabled:
- SmallStack section disappears from navigation
- `/help/smallstack/*` URLs return 404
- Search excludes SmallStack content

## Configuration

### Your _config.yaml

Define your project's documentation:

```yaml
# apps/help/content/_config.yaml
title: "Documentation"

variables:
  version: "1.0.0"
  project_name: "My Project"

sections:
  # Root section (your main docs)
  - slug: ""
    title: "Project Documentation"
    pages:
      - slug: index
        title: "Welcome"
        icon: "home"
      - slug: user-guide
        title: "User Guide"
        icon: "book"

  # Additional sections
  - slug: dev
    title: "Developer Docs"
    pages:
      - slug: api
        title: "API Reference"
        icon: "code"
```

### Section with Subfolder

For sections with many pages, create a subfolder with its own config:

```yaml
# apps/help/content/guides/_config.yaml
title: "User Guides"

pages:
  - slug: getting-started
    title: "Getting Started"
    icon: "rocket"
  - slug: advanced
    title: "Advanced Usage"
    icon: "settings"
```

Section variables override root variables.

## Category Grouping

Categories let you organize a section's pages into visual groups. When a section has categories, the index page shows pages under category headings instead of a single flat grid, and the sidebar shows category sub-headings.

### Adding Categories

Add a `categories:` list to a section's `_config.yaml` and a `category:` field to each page:

```yaml
# apps/help/content/guides/_config.yaml
title: "User Guides"

# Define category display order
categories:
  - "Getting Started"
  - "Configuration"
  - "Advanced Topics"

pages:
  - slug: welcome
    title: "Welcome"
    icon: "home"
    category: "Getting Started"

  - slug: first-steps
    title: "First Steps"
    icon: "rocket"
    category: "Getting Started"

  - slug: settings
    title: "Settings"
    icon: "settings"
    category: "Configuration"

  - slug: power-user
    title: "Power User Guide"
    icon: "code"
    category: "Advanced Topics"

  - slug: changelog
    title: "Changelog"
    icon: "info"
    # No category → appears at the end without a heading
```

### How Categories Behave

- **Opt-in:** If `categories:` is omitted, the section renders as a flat card grid — identical to the default.
- **Display order:** Categories appear in the order defined in the `categories:` list, top to bottom.
- **Page order within a category:** Pages keep their order from the `pages:` list.
- **Missing category:** If a page's `category:` doesn't match any entry in the list, it's appended alphabetically after the listed categories (with a warning in the server log).
- **No category:** Pages without a `category:` field go into an ungrouped bucket at the end.
- **Previous/Next links:** Always follow the flat page order from the `pages:` list, regardless of category grouping.

### Page Config Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `slug` | yes | — | Filename without `.md`, used in URL |
| `title` | no | slug (titlecased) | Display title |
| `description` | no | `""` | Subtitle on index cards |
| `icon` | no | `""` | Icon name for cards |
| `category` | no | `""` | Category group name |
| `is_faq` | no | `false` | Collapsible Q&A mode |

## Adding Pages

### To Root Level

1. Create `apps/help/content/my-page.md`:

```markdown
---
title: My Page
description: A brief description
---

# My Page

Content here. Use {{ project_name }} for variables.
```

2. Add to `apps/help/content/_config.yaml`:

```yaml
sections:
  - slug: ""
    title: "Documentation"
    pages:
      - slug: index
        title: "Welcome"
        icon: "home"
      - slug: my-page           # New page
        title: "My Page"
        icon: "document"
```

URL: `/help/my-page/`

### To a Section

1. Create folder and file: `apps/help/content/dev/api.md`

2. Add section to config:

```yaml
sections:
  - slug: dev
    title: "Developer Docs"
    pages:
      - slug: api
        title: "API Reference"
        icon: "code"
```

URL: `/help/dev/api/`

## Template Variables

Use variables in your Markdown files:

| Variable | Usage |
|----------|-------|
| `version` | `{{ "{{" }} version {{ "}}" }}` → {{ version }} |
| `project_name` | `{{ "{{" }} project_name {{ "}}" }}` → {{ project_name }} |
| `python_version` | `{{ "{{" }} python_version {{ "}}" }}` → {{ python_version }} |

### Custom Variables

Add to `_config.yaml`:

```yaml
variables:
  version: "1.0.0"
  support_email: "support@myapp.com"
```

Use: `Contact us at {{ "{{" }} support_email {{ "}}" }}`

## Markdown Features

### Frontmatter

Frontmatter is optional metadata at the very top of a markdown file, wrapped in triple dashes (`---`). It's not displayed as page content — it's used by the help system to set the page title and description.

```markdown
---
title: My Page Title
description: A short summary of this page
---

# The actual content starts here...
```

If you include a `title` in frontmatter, it overrides whatever title is set in `_config.yaml` for that page. If you skip frontmatter entirely, the help system uses the config values instead — so it's completely optional.

### Code Blocks

````markdown
```python
def hello():
    print("Hello, World!")
```
````

### Tables

```markdown
| Column 1 | Column 2 |
|----------|----------|
| Cell 1   | Cell 2   |
```

### Links

```markdown
[External](https://example.com)
[Internal](/help/smallstack/theming/)
```

### Blockquotes

```markdown
> **Note:** Important information here.
```

## FAQ Pages

For collapsible Q&A sections:

1. Set `is_faq: true` in config:
   ```yaml
   - slug: faq
     title: "FAQ"
     is_faq: true
     category: "Reference"
   ```

2. Use H2 headings for questions:
   ```markdown
   ## How do I reset my password?

   Go to the login page and click "Forgot password"...

   ## Can I change my username?

   Currently, usernames cannot be changed...
   ```

## Available Icons

| Icon | Name | Use for |
|------|------|---------|
| 🏠 | `home` | Welcome, index, navigation |
| 🚀 | `rocket` | Getting started, deployment |
| 📖 | `book` | Guides, manuals |
| ❓ | `help` | Help, support |
| 🎨 | `palette` | Theming, design, customization |
| ⚙️ | `settings` | Configuration, forms |
| 📧 | `email` | Email, notifications |
| 📦 | `package` | Installation, packages |
| 🗄️ | `database` | Database |
| ☁️ | `cloud` | Deployment |
| 🐳 | `docker` | Docker |
| 📁 | `folder` | Structure, cards |
| 💬 | `chat` | FAQ, messages |
| ℹ️ | `info` | About, logging |
| 🤖 | `ai` | AI features |
| 🔗 | `link` | Quick links |
| 📊 | `chart` | Charts, monitoring |
| 🕐 | `clock` | Timezones |
| 👥 | `users` | User management |
| 🎬 | `slides` | Presentations |
| 💻 | `terminal` | CLI, commands |
| 🔒 | `lock` | Authentication, security |
| 🧊 | `cube` | Dependencies, 3D |
| 💻 | `code` | Code, development |

## Slide Viewer

The help system also includes a slide presentation mode for focused walkthroughs. See [Using the Slide Viewer](/help/smallstack/slide-viewer/) for full documentation on creating and embedding slide decks.

## Tips

- Keep slugs lowercase with hyphens (`my-page-name`)
- Use frontmatter for page-specific titles
- Section variables override root variables
- The search index includes all enabled sections
- Your `content/` folder is conflict-free on upstream pulls
- Categories are optional — omit `categories:` for flat rendering
- Category names are case-sensitive — they must match exactly between the list and page entries
