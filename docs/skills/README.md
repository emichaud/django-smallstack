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
| [help-documentation.md](help-documentation.md) | Creating, editing, and managing help documentation |
| [theming-system.md](theming-system.md) | CSS variables, dark mode, UI components |
| [django-apps.md](django-apps.md) | Creating new Django apps following project conventions |
| [authentication.md](authentication.md) | Custom user model, auth views, protecting views |
| [templates.md](templates.md) | Template inheritance, blocks, includes, common patterns |

## Usage

AI agents should read relevant skill files before making changes to the corresponding parts of the codebase. For example:

- Before adding a help page → read `help-documentation.md`
- Before modifying CSS/theming → read `theming-system.md`
- Before creating a new app → read `django-apps.md`
- Before working with auth → read `authentication.md`
- Before creating templates → read `templates.md`

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
