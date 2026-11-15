---
name: crud-views
description: "The CRUDView reference — the declarative class behind list/create/detail/update/delete: actions, config attributes, display protocol, related tabs, get_list_queryset"
license: MIT
metadata:
  source: "docs/skills/crud-views.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/crud-views.md` by `make skills-index` — edit the source, not this file.

# Skill: CRUDView

CRUDView is SmallStack's declarative class for generating Django CRUD views from a single configuration. It produces list, create, detail, update, and delete views with URLs, templates, and wiring.

## Overview

The pattern: define a model and a CRUDView config. CRUDView generates the views, URL patterns, forms, breadcrumbs and a sortable, resizable list table, and, when you switch them on, the REST API and MCP tools for the same model.

This skill is long; the full text is in [references/crud-views.md](references/crud-views.md) — read it before acting.
