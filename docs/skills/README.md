# AI Agent Skills

This directory contains reference documentation designed for AI agents (LLMs) working on this codebase. These "skill files" provide structured knowledge about the project's architecture, conventions, and patterns.

## Purpose

When an AI agent is asked to modify or extend this project, these files help it:

- Understand project conventions and patterns
- Follow existing code style and structure
- Make changes that integrate properly with the codebase
- Avoid common mistakes

## Available Skills

| File | Description |
|------|-------------|
| [django-apps.md](django-apps.md) | Creating new Django apps following project conventions |
| [templates.md](templates.md) | Template inheritance, blocks, includes, common patterns |
| [theming-system.md](theming-system.md) | CSS variables, palettes, dark mode, UI components |
| [authentication.md](authentication.md) | Custom user model, auth views, protecting views |
| [htmx-patterns.md](htmx-patterns.md) | htmx setup, CSRF, partials, dual-response views, OOB messages |
| [help-documentation.md](help-documentation.md) | Help system, sections, bundled SmallStack docs |
| [settings.md](settings.md) | Split settings, environment variables, feature flags |
| [background-tasks.md](background-tasks.md) | Django Tasks framework with django-tasks-db backend |
| [activity-tracking.md](activity-tracking.md) | HTTP request logging middleware and configuration |
| [logging-audit.md](logging-audit.md) | Logging configuration and audit trail |
| [screenshot-workflow.md](screenshot-workflow.md) | Visual verification with shot-scraper and screenshot_auth |
| [docker-deployment.md](docker-deployment.md) | Docker Compose setup, services, volumes |
| [kamal-deployment.md](kamal-deployment.md) | Kamal deployment configuration, VPS setup, SSL, commands |
| [development-workflow.md](development-workflow.md) | Branching, testing, coverage, documentation, commit style |
| [release-process.md](release-process.md) | Versioning, release checklist, GitHub releases |
| [integration-workflow.md](integration-workflow.md) | Pulling upstream into downstream projects, deploying |

## Usage

AI agents should read relevant skill files before making changes to the corresponding parts of the codebase. For example:

- Before creating a new app → read `django-apps.md`
- Before creating templates → read `templates.md`
- Before modifying CSS/theming → read `theming-system.md`
- Before working with auth → read `authentication.md`
- Before adding htmx interactions → read `htmx-patterns.md`
- Before adding a help page → read `help-documentation.md`
- Before changing settings → read `settings.md`
- Before adding background tasks → read `background-tasks.md`
- Before working with activity tracking → read `activity-tracking.md`
- Before taking screenshots → read `screenshot-workflow.md`
- Before deploying with Docker → read `docker-deployment.md`
- Before deploying with Kamal → read `kamal-deployment.md`
- Before developing features → read `development-workflow.md`
- Before releasing a version → read `release-process.md`
- Before pulling upstream into downstream → read `integration-workflow.md`

## For Humans

These files are also useful for developers new to the project. They provide quick references for:

- Understanding how different systems work
- Following established patterns
- Finding the right files to modify

## Contributing

When adding significant new features or systems to the project, consider creating a corresponding skill file to document:

- File locations and structure
- Key concepts and patterns
- Step-by-step procedures
- Configuration options
- Best practices
