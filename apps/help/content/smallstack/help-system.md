---
title: Using the Help System
description: How to add and edit documentation pages
---

# Using the Help System

The help system is a simple, file-based documentation viewer built into {{ project_name }}. It renders Markdown files as HTML pages with automatic navigation, search, and table of contents.

## How It Works

Documentation is stored as Markdown files in `apps/help/content/`. When you visit `/help/`, the system:

1. Reads the `_config.yaml` file for page ordering and metadata
2. Loads the requested `.md` file
3. Substitutes template variables (like `{{ version }}`)
4. Converts Markdown to HTML
5. Renders it using the admin theme

## Adding a New Page

### Step 1: Create the Markdown File

Create a new `.md` file in `apps/help/content/`:

```markdown
---
title: My New Page
description: A brief description for the index
---

# My New Page

Your content here...
```

The filename becomes the URL slug. For example:
- `my-new-page.md` → `/help/my-new-page/`

### Step 2: Add to Configuration

Edit `apps/help/content/_config.yaml`:

```yaml
pages:
  # ... existing pages ...

  - slug: my-new-page
    title: "My New Page"
    description: "A brief description"
    icon: "document"  # Optional icon name
```

### Step 3: Restart the Server

Changes are picked up automatically in development. For production, rebuild the Docker image.

## Template Variables

You can use template variables in your Markdown files:

| Variable | Value | Usage |
|----------|-------|-------|
| `version` | {{ version }} | `{{ "{{" }} version {{ "}}" }}` |
| `project_name` | {{ project_name }} | `{{ "{{" }} project_name {{ "}}" }}` |
| `python_version` | {{ python_version }} | `{{ "{{" }} python_version {{ "}}" }}` |
| `django_version` | {{ django_version }} | `{{ "{{" }} django_version {{ "}}" }}` |

### Adding Custom Variables

Edit `_config.yaml`:

```yaml
variables:
  version: "1.0.0"
  my_custom_var: "Custom Value"
```

Then use in Markdown: `{{ "{{" }} my_custom_var {{ "}}" }}`

## Markdown Features

### Basic Formatting

```markdown
**Bold text** and *italic text*

- Bullet list item
- Another item

1. Numbered list
2. Second item

> Blockquote for notes or tips
```

### Code Blocks

Use fenced code blocks with language hints:

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
[External link](https://example.com)
[Internal link](/help/theming/)
```

## Creating FAQ Pages

For FAQ-style pages with collapsible sections:

1. Set `is_faq: true` in `_config.yaml`:
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

Each H2 becomes a collapsible question with the following content as the answer.

## Available Icons

Use these icon names in your page configuration:

- `rocket` - Getting started, launch
- `help` - Help, documentation
- `palette` - Theming, design
- `docker` - Docker, containers
- `folder` - Files, structure
- `chat` - FAQ, questions
- `document` - Generic document

## File Structure

```
apps/help/
├── content/
│   ├── _config.yaml      # Navigation & variables
│   ├── getting-started.md
│   ├── help-system.md    # This page
│   ├── theming.md
│   └── ...
├── utils.py              # Markdown processing
├── views.py              # Page views
└── urls.py               # URL routing
```

## Tips

- Keep page slugs lowercase with hyphens (e.g., `my-page-name`)
- Use frontmatter for page-specific titles and descriptions
- Test your Markdown locally before deploying
- The search index is built from page titles and content
