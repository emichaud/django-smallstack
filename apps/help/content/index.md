# Welcome to {{ project_name }}

This is your project's documentation home. Edit this file to introduce your project.

## Getting Started

Add your project-specific documentation here. Common pages to create:

- **User Guide** - How to use your application
- **API Reference** - Developer documentation
- **FAQ** - Common questions and answers

## Documentation Structure

Your docs live in `apps/help/content/`. The structure is:

```
apps/help/content/
├── _config.yaml      # Your doc configuration
├── index.md          # This welcome page
└── guides/           # Your custom sections
    └── user-guide.md
```

### Adding New Pages

1. Create a `.md` file in this folder
2. Add it to `_config.yaml` under your section's pages
3. It will appear at `/help/your-page-slug/`

## Quick Links

### Your Project
- Edit `templates/website/home.html` for your homepage
- Edit `.env` to set `SITE_NAME` and `SITE_DOMAIN`
- Add pages in `apps/website/` for landing pages, about, etc.
