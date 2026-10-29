---
name: api
description: "The REST API reference — token auth, CRUD endpoints, FK expansion, date filtering, aggregation, serialization"
license: MIT
metadata:
  source: "docs/skills/api.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/api.md` by `make skills-index` — edit the source, not this file.

# Skill: REST API

SmallStack includes a lightweight REST API layer built on stock Django views. It provides JSON endpoints for CRUDView models with Bearer token authentication, FK expansion, date range filtering, and aggregation. Designed to be replaced by DRF if the project graduates.

## Overview

The API is opt-in per CRUDView. When enabled, `get_urls()` generates JSON list and detail endpoints alongside the existing HTML views. Authentication uses API tokens (Bearer scheme) or falls back to session auth. The URL prefix is configurable via `SMALLSTACK_API_PREFIX` (default: `"api/"`).

This skill is long; the full text is in [references/api.md](references/api.md) — read it before acting.
