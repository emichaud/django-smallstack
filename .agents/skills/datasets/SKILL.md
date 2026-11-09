---
name: datasets
description: "Build a dashboard/report/chart UI — the @dataset primitive: a named queryset surfaced as typed rows/columns (schema() → dimension/measure + filter widgets), rows()/series(), opt-in REST + MCP. Read before building anything that inspects a dataset to render pickers/charts"
license: MIT
metadata:
  source: "docs/skills/datasets.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/datasets.md` by `make skills-index` — edit the source, not this file.

# Datasets — filtered querysets as typed rows & columns (`@dataset`)

**Read this** before building anything that needs "a table of rows the user can slice and chart" — a dashboard builder, a report picker, an export screen, or an MCP/agent that queries structured data. A **dataset** is a named function returning a `QuerySet`; the framework turns it into typed rows + columns you can inspect, filter, and roll up **without knowing the underlying model**. That introspection is the whole point: you build the UI against the *schema*, not against a specific table.

> **Prerequisites**: [`modern-dark-theme.md`](modern-dark-theme.md) for the page/component patterns, [`building-a-user-facing-site.md`](building-a-user-facing-site.md) if the surface is non-staff.

## The one-paragraph model

Declare a dataset with `@dataset` over a queryset. The base derives everything a UI needs from `qs.model`: **column names, datatypes, a dimension/measure role, and ready-made filter widgets**. A visual builder then: lists datasets → reads one dataset's schema → offers field/filter pickers → asks for filtered `rows` or a grouped `series`. The builder is generic — it never hard-codes a model. Base ships one read-only `smallstack_<thing>` dataset per framework module (see [Bundled framework datasets](#bundled-framework-datasets)); you declare your own domain datasets alongside them.

This skill is long; the full text is in [references/datasets.md](references/datasets.md) — read it before acting.
