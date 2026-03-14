---
title: Explorer Overview
description: A staff-facing data browser that auto-generates CRUD views from your Django admin registrations
---

# Explorer

Explorer is SmallStack's built-in model browser. It reads your existing Django `ModelAdmin` registrations and generates a full CRUD interface — list, detail, create, update, delete — without writing views, templates, URLs, or table classes.

You opt models in with a single attribute (`explorer_enabled = True`), and Explorer does the rest. It's the fastest path from "I have a model" to "I can manage it in a browser."

## How It Works

Explorer runs on an **admin-first** discovery system:

1. On app startup, Explorer's registry walks `admin.site._registry`
2. Any `ModelAdmin` with `explorer_enabled = True` is picked up
3. Explorer reads `list_display`, permissions, and other supported admin attributes
4. It dynamically generates a `CRUDView` subclass for each registered model
5. URL patterns are built and injected at `/smallstack/explorer/`

The result is a staff-only data browser at `/smallstack/explorer/` with:

- **Index page** — a grid of all registered models grouped by custom groups or Django app
- **Sidebar filtering** — switch between group view and app view
- **Per-model CRUD** — list with sorting, detail view, create/edit forms, and delete confirmation
- **Readonly detection** — models with restricted permissions automatically get list + detail only

### The Explorer Index

The main Explorer page lives at `/smallstack/explorer/`. It shows every registered model as a card with the record count and a link to the CRUD list. The left sidebar lets you filter by group or by Django app.

**Direct link:** [Explorer Index](/smallstack/explorer/)

### Accessing Explorer

Explorer is registered in the **Admin** section of the sidebar nav and is restricted to staff users. You'll find it at:

- **Sidebar:** Admin → Explorer
- **Apps menu:** The grid icon in the topbar (staff only) also links to Explorer via the admin items
- **Direct URL:** `/smallstack/explorer/`

## Enabling Models

Add `explorer_enabled = True` to any `ModelAdmin`. That's the only required step.

```python
# apps/myapp/admin.py
from django.contrib import admin
from .models import Widget

@admin.register(Widget)
class WidgetAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_active", "created_at"]
    explorer_enabled = True
```

Explorer reads `list_display` for columns (real model fields only — callables are skipped). If no real fields remain, it auto-detects from the model's field definitions.

You can also override which fields Explorer shows, force readonly mode, and more. See the full API reference:

→ [Enabling Models for Explorer](/smallstack/help/explorer/admin-api/)

## Composability — The Real Power

Explorer isn't locked to a single page. Its views, mixins, context helpers, and template tags are designed to be embedded into your own pages. This is the key difference from Django admin.

### Three Ways to Compose

**View Mixins** — the recommended approach. Add a mixin to any `TemplateView` and it populates your template context automatically:

```python
from django.views.generic import TemplateView
from apps.explorer.mixins import ExplorerModelMixin

class HeartbeatPageView(ExplorerModelMixin, TemplateView):
    template_name = "myapp/heartbeat.html"
    explorer_app_label = "heartbeat"
    explorer_model_name = "heartbeat"
```

In the template, use `{% crud_table %}` anywhere to render the auto-generated CRUD table:

```html
{% load crud_tags %}

<div class="card">
    <h2>My Custom Header</h2>
    <!-- your own content here -->
</div>

<div class="card">
    {% crud_table %}
</div>
```

**Context Helpers** — for when you need more control:

```python
from apps.explorer.registry import explorer_registry

ctx = explorer_registry.get_model_context("heartbeat", "heartbeat")
if ctx:
    context.update(ctx.as_context())
    context["my_chart"] = build_chart()  # mix in your own data
```

**Dataclasses** — typed access to `GroupContext`, `AppContext`, `ModelContext`, and `ModelCardInfo` for full programmatic control.

The full composability guide covers all patterns in detail:

→ [Composability Guide](/smallstack/help/explorer/composability/)

## Example Pages

Explorer ships with working example pages that demonstrate each composition pattern. These are staff-only pages under `/smallstack/explorer/examples/`.

| Example | URL | What It Shows |
|---------|-----|---------------|
| **Classic Index** | [/smallstack/explorer/examples/classic/](/smallstack/explorer/examples/classic/) | Grid/list toggle with django-tables2, the original Explorer layout |
| **Group Page** | [/smallstack/explorer/examples/group/Monitoring/](/smallstack/explorer/examples/group/Monitoring/) | Sidebar of custom groups + model cards for the selected group |
| **App Page** | [/smallstack/explorer/examples/app/heartbeat/](/smallstack/explorer/examples/app/heartbeat/) | Sidebar of Django apps + model cards for the selected app |
| **Single Model** | [/smallstack/explorer/examples/model/heartbeat/heartbeat/](/smallstack/explorer/examples/model/heartbeat/heartbeat/) | Standalone CRUD list with pagination for one model |
| **Heartbeat Compose** | [/smallstack/explorer/examples/heartbeat/](/smallstack/explorer/examples/heartbeat/) | Custom uptime chart + CRUD table on the same page — the canonical "mix your content with Explorer" pattern |

Each example includes an **Overview** tab showing the live page and a **Code Examples** tab with copy-pasteable view and template code.

> **Note:** These example pages require at least one model to be registered with `explorer_enabled = True`. The heartbeat examples specifically reference the built-in Heartbeat model.

## Explorer vs CRUDView

Explorer and CRUDView serve different purposes:

| | Explorer | CRUDView |
|---|----------|----------|
| **Setup** | One attribute on ModelAdmin | View class + table class + URL wiring |
| **Customization** | Use the admin API attributes | Full control over views, forms, templates |
| **Layout** | Auto-generated from registry | You design the page |
| **Best for** | Quick data browsing, staff tools | Production-facing management pages |

**The recommended pattern:** Start with Explorer for rapid prototyping and internal tools. When you need custom layouts, branding, or user-facing workflows, graduate to CRUDView. Explorer's composability mixins bridge the gap — you can embed Explorer's auto-generated tables inside your own custom pages without rewriting anything.

For the full CRUDView guide:

→ [Building CRUD Pages](/smallstack/help/smallstack/building-crud-pages/)

## Related Documentation

- [Enabling Models for Explorer](/smallstack/help/explorer/admin-api/) — ModelAdmin API reference
- [Composability Guide](/smallstack/help/explorer/composability/) — Embed Explorer into your own pages
- [Building CRUD Pages](/smallstack/help/smallstack/building-crud-pages/) — Manual CRUD with CRUDView and django-tables2
- [Navigation](/smallstack/help/smallstack/navigation/) — How nav items are registered (Explorer registers to the admin section)
