---
title: Using the Help System
description: How to add and edit documentation pages
---

# Using the Help System

The help system is a file-based documentation viewer built into {{ project_name }}. It renders Markdown files as HTML pages with automatic navigation, search, and table of contents.

## How It Works

Documentation is stored as Markdown files in `apps/help/content/`. The system supports:

- **Sections** - Organize docs into folders (e.g., `/help/smallstack/getting-started/`)
- **Root pages** - Top-level docs (e.g., `/help/index/`)
- **Variables** - Template substitution (e.g., `{{ version }}`)
- **Search** - Client-side full-text search
- **FAQ mode** - Collapsible question/answer sections

## Documentation Structure

SmallStack uses sections to separate your project docs from the framework reference:

```
apps/help/content/
├── _config.yaml           # Main config with sections
├── index.md               # Your project welcome page
├── user-guide.md          # Your project docs
└── smallstack/            # SmallStack reference docs
    ├── _config.yaml       # Section config
    ├── getting-started.md
    └── ...
```

**URLs:**
- `/help/` - Documentation index
- `/help/index/` - Your welcome page
- `/help/smallstack/getting-started/` - SmallStack docs

## Configuration

### Root _config.yaml

The main config defines sections and variables:

```yaml
title: "Documentation"

variables:
  version: "1.0.0"
  project_name: "My Project"

sections:
  # Root section (your project docs)
  - slug: ""
    title: "Project Documentation"
    pages:
      - slug: index
        title: "Welcome"
        icon: "home"
      - slug: user-guide
        title: "User Guide"
        icon: "book"

  # SmallStack reference (subfolder)
  - slug: smallstack
    title: "SmallStack Reference"
    folder: smallstack/
    config: smallstack/_config.yaml
```

### Section _config.yaml

Each section folder can have its own config:

```yaml
title: "SmallStack Reference"

variables:
  project_name: "Django SmallStack"

pages:
  - slug: getting-started
    title: "Getting Started"
    icon: "rocket"
```

Section variables override root variables.

## Adding Pages

### To Your Project Docs (Root Level)

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
        description: "Brief description"
        icon: "document"
```

URL: `/help/my-page/`

### To a Section (Subfolder)

1. Create `apps/help/content/dev/api.md`

2. Add section to root config:

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

## Creating Your Own Sections

### Example: User Guide + Developer Docs

```yaml
# apps/help/content/_config.yaml
sections:
  # User documentation
  - slug: ""
    title: "User Guide"
    pages:
      - slug: index
        title: "Getting Started"
        icon: "rocket"
      - slug: features
        title: "Features"
        icon: "star"

  # Developer documentation
  - slug: dev
    title: "Developer Docs"
    pages:
      - slug: api
        title: "API Reference"
        icon: "code"
      - slug: webhooks
        title: "Webhooks"
        icon: "link"

  # Keep SmallStack reference (optional)
  - slug: smallstack
    title: "Framework Reference"
    folder: smallstack/
    config: smallstack/_config.yaml
```

Create the files:
```
apps/help/content/
├── _config.yaml
├── index.md           # User: Getting Started
├── features.md        # User: Features
├── dev/
│   ├── api.md         # Dev: API Reference
│   └── webhooks.md    # Dev: Webhooks
└── smallstack/        # SmallStack docs
```

## Removing SmallStack Docs

If you don't want SmallStack reference docs:

1. Delete the `smallstack/` folder
2. Remove the smallstack section from `_config.yaml`:

```yaml
sections:
  - slug: ""
    title: "Documentation"
    pages:
      - slug: index
        title: "Welcome"
        icon: "home"
  # smallstack section removed
```

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
| 🏠 | `home` | Welcome, index |
| 🚀 | `rocket` | Getting started |
| 📖 | `book` | Guides, manuals |
| ❓ | `help` | Help, support |
| 🎨 | `palette` | Theming, design |
| ⚙️ | `settings` | Configuration |
| 📧 | `email` | Email, notifications |
| 📦 | `package` | Installation |
| 🗄️ | `database` | Database |
| ☁️ | `cloud` | Deployment |
| 🐳 | `docker` | Docker |
| 📁 | `folder` | Structure |
| 💬 | `chat` | FAQ |
| ℹ️ | `info` | About |
| 🤖 | `ai` | AI features |

## File Organization

```
apps/help/
├── content/
│   ├── _config.yaml      # Root config with sections
│   ├── index.md          # Your welcome page
│   └── smallstack/       # SmallStack section
│       ├── _config.yaml  # Section config
│       └── *.md          # Section pages
├── utils.py              # Markdown processing
├── views.py              # Page views
└── urls.py               # URL routing
```

## Tips

- Keep slugs lowercase with hyphens (`my-page-name`)
- Use frontmatter for page-specific titles
- Section variables override root variables
- The search index includes all sections
