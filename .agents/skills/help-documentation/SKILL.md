---
name: help-documentation
description: "Help system, sections, bundled SmallStack docs"
license: MIT
metadata:
  source: "docs/skills/help-documentation.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/help-documentation.md` by `make skills-index` — edit the source, not this file.

# Skill: Help Documentation System

This skill describes how to create, edit, and manage help documentation in the SmallStack project.

## Overview

The help system is a file-based documentation viewer that renders Markdown files as HTML pages. It lives in `apps/help/` and uses:

- **Markdown files** for content (`apps/help/content/*.md` for project docs, app `docs/` dirs for app-contributed docs)
- **YAML config** for navigation, variables, and categories (`apps/help/content/_config.yaml`)
- **App-contributed docs** — Apps can register their own docs section via AppConfig
- **App-contributed slides** — Apps can register slides via `help_slides_dir` on AppConfig
- **Django templates** for rendering (`templates/help/`)
- **CSS/JS** for styling (`static/smallstack/help/`)

This skill is long; the full text is in [references/help-documentation.md](references/help-documentation.md) — read it before acting.
