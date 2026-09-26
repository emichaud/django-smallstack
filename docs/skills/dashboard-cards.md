# Dashboard Cards & Drill-down Modals

The single standard for the metric tiles at the top of admin dashboards — and
the click-to-open drill-down modal behind them. Read this before adding stat
cards to any page; it replaces hand-written `.stat-card` markup and the
copy-pasted htmx wiring that used to drift between apps.

One tag renders the card. One global modal shows the drill-down. One helper
builds the drill-down body. You never author the markup, the `hx-*` attributes,
or the modal include by hand.

## TL;DR

```django
{% load theme_tags %}
<div class="stat-cards">
  {% stat_card value=total label="Users" title="All Users" detail_url="manage/users-stat-detail" detail_arg="total" %}
  {% stat_card value=active label="Active" state="success" %}
  {% stat_card value=avg_ms label="Avg Response" unit="ms" %}
</div>
```

The drill-down modal is already in `base.html` — there is **nothing to include**.
A clickable card's endpoint returns a stat list (see below).

## The `{% stat_card %}` tag

`apps/smallstack/templatetags/theme_tags.py`. Three modes, picked by argument:

| Mode | Trigger | Renders |
|------|---------|---------|
| **Static** | neither `detail_url` nor `link_url` | a plain metric tile |
| **Drill-down** | `detail_url` (+ optional `detail_arg`) | clickable tile → opens the modal via htmx |
| **Navigation** | `link_url` (+ optional `link_arg`) | clickable tile → navigates to a full page |

Arguments:

| Arg | Purpose |
|-----|---------|
| `value` | The big number / metric (required). |
| `label` | Small mono caption under the value (required). |
| `title` | Modal heading in drill-down mode. Defaults to `label`. |
| `detail_url` / `detail_arg` | URL name (+ one positional arg) of the htmx drill-down endpoint. |
| `link_url` / `link_arg` | URL name (+ one positional arg) to navigate to. Use when the content is too large for a modal (a full table page). `detail_url` wins if both are set. |
| `state` | `success` \| `warning` \| `danger` \| `muted` — drives the accent stripe **and** the value color. Anything else is ignored. |
| `unit` | Small trailing unit after the value (e.g. `ms`). |

Drive `state` from data instead of `{% if %}` chains — the `yesno` filter is the
idiom for "color only when non-zero":

```django
{% stat_card value=fail_count label="Failures" state=fail_count|yesno:"danger,muted" detail_url="api_admin:stat_detail" detail_arg="fail" %}
```

## The drill-down body

A clickable card's endpoint returns an **HTML fragment** (no base template) that
htmx swaps into the modal. There are two shapes:

### Stat list (default — a list of entities)

Build rows with `stat_list_row()` and wrap with `render_stat_list()` from
`apps/smallstack/stat_lists.py`. This is the shared renderer — do **not**
hand-roll `format_html` row markup in your view.

```python
from apps.smallstack.stat_lists import render_stat_list, stat_list_row

@staff_member_required
def user_stat_detail(request, stat_type):
    users = User.objects.filter(is_active=True).order_by("username")
    rows = [
        stat_list_row(
            u.username,
            href=reverse("manage/users-update", args=[u.pk]),
            avatar=True,                       # True → initials from the name
            meta=u.email or "No email on file",
        )
        for u in users
    ]
    return render_stat_list(rows, empty="No active users.")
```

`stat_list_row(name, *, href=None, avatar=None, meta=None, count=None)`:

| Arg | Effect |
|-----|--------|
| `name` | Primary label (required). |
| `href` | Makes the row a link with a chevron. Omit → a non-navigable row. |
| `avatar` | Monogram circle. `True` derives initials from `name`; or pass an explicit string. |
| `meta` | Muted secondary text (email, access level, …). |
| `count` | Right-aligned numeric pill (tabular figures). |

`render_stat_list(rows, *, empty="Nothing to show.")` → the `HttpResponse` to
return. Empty input renders the `empty` message.

### Table (when the content is genuinely tabular)

For a log or grid, return a plain `<table>` instead — the modal styles tables
automatically (sticky header, zebra rows, hover) from `--primary`, no classes
needed. Reach for a table only when the data is columnar; prefer a stat list for
"a list of things you click through to."

```python
return render(request, "app/partials/stat_table.html", {"items": qs})
```

## Wiring it up (end to end)

```python
# urls.py
path("stats/<str:stat_type>/", user_stat_detail, name="manage/users-stat-detail"),
```

```django
{# template — the modal is global, so this is all you write #}
{% load theme_tags %}
<div class="stat-cards" style="margin-bottom: 24px;">
  {% stat_card value=dashboard_stats.total label="Total Users" title="All Active Users" detail_url="manage/users-stat-detail" detail_arg="total" %}
</div>
```

That's the whole pattern. See `apps/usermanager/views.py` (`user_stat_detail`),
`apps/tokenmgr/views.py` (`token_stat_detail`), and `apps/mcp/admin_views.py`
(`MCPAdminStatDetailView`) for live examples.

## Anti-patterns

❌ **Hand-writing the card markup + htmx wiring.** It drifts: someone forgets
`hx-target`, or `cursor: pointer`, or the modal include.

```django
<!-- ❌ don't -->
<div class="stat-card stat-card-clickable" style="cursor: pointer;"
     hx-get="{% url 'app:stat_detail' 'x' %}" hx-target="#stat-modal-body"
     onclick="openStatModal('X')">
  <div class="stat-card-value">{{ n }}</div><div class="stat-card-label">X</div>
</div>
```

```django
<!-- ✓ do -->
{% stat_card value=n label="X" detail_url="app:stat_detail" detail_arg="x" %}
```

❌ **Including the modal on the page.** `{% include "smallstack/includes/stat_modal.html" %}`
is in `base.html` now — including it again duplicates the markup and the JS. Just
use the tag.

❌ **Hand-rolling `format_html('<a class="stat-list-row">…')` in the view.** Use
`stat_list_row()` — it's XSS-safe and keeps every drill-down list identical.

❌ **A second modal implementation for a dashboard drill-down.** There is one:
the global stat modal. (The `.crud-modal` delete/bulk confirm and `.field-preview`
modals are separate on purpose — POST actions and field previews, not drill-downs.)

❌ **Hard-coded value colors** (`style="color: #e5534b"`). Use `state` — it stays
correct across all six palettes. See `modern-dark-theme.md`.

## Related skills

- `modern-dark-theme.md` — the palette-correct variable system these cards obey
- `admin-page-styling.md` — the broader component reference (buttons, tables, badges)
- `dashboard-widgets.md` — a different thing: the `DashboardWidget` **data
  protocol** that feeds the `/smallstack/` dashboard. These stat cards are the UI
  pattern for an app's own dashboard page; a `DashboardWidget` is a registrable
  data source for the central dashboard. They compose but are not the same.
- `htmx-patterns.md` — the htmx + partial-response conventions the drill-down uses
