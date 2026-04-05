# Skill: Card Displays

Card displays render a queryset as a grid of cards — a peer to `TableDisplay`. SmallStack ships a family of card variants and a simple authoring pattern for adding new ones.

## Architecture

Three layers, each doing one job:

1. **Template** (`displays/cards.html`) — the grid wrapper. Iterates over cards and `{% include item_template %}` for each. Knows nothing about specific card shapes.
2. **Base class** (`CardDisplay` in `apps/smallstack/displays.py`) — owns pagination, bulk checkbox, pk, detail URL, and dispatch to `item_template`. Subclasses override `build_card()` + `item_template`.
3. **Variant classes + partials** — declare the card shape by pairing a `build_card()` implementation with its own `item_template` HTML partial.

## Built-in variants

| Class | Config | Use when |
|-------|--------|----------|
| `CardDisplay` | Zero args — reads `list_columns`/`list_fields` | Any model. Label:value rows under a title. Drop-in alternative to `TableDisplay`. |
| `AvatarCardDisplay` | `title_field`, `subtitle_field`, `image_field`, `pill_field`, `pill_label` | Records with a "hero" field (name/username) + a photo. People, orgs, projects. |

## Usage

### Zero-config (default key-value cards)

```python
explorer_displays = [TableDisplay, CardDisplay]
```

Uses whatever your model already declares via `list_columns` or `list_fields`. First field becomes the card title; remaining fields render as `label: value` rows.

### Avatar variant (one line)

```python
explorer_displays = [
    TableDisplay,
    AvatarCardDisplay(
        title_field="user.username",      # dotted path supported
        subtitle_field="display_name",
        image_field="profile_photo",
        pill_field="status",              # optional
        pill_label="rank",                # optional
    ),
]
```

Field values can be attribute names, dotted paths (`"user.username"`), or callables (`obj -> value`).

### Subclass for computed fields

When a card needs a value that isn't stored on the model:

```python
class ProfileCardDisplay(AvatarCardDisplay):
    def __init__(self):
        super().__init__(
            title_field="user.username",
            subtitle_field="display_name",
            image_field="profile_photo",
        )

    def get_context(self, queryset, crud_config, request):
        ctx = super().get_context(queryset, crud_config, request)
        now = timezone.now()
        for card in ctx["cards"]:
            created_at = getattr(card["obj"], "created_at", None)
            days = (now - created_at).days if created_at else 0
            card["pill_value"] = days
            card["pill_label"] = "day" if days == 1 else "days"
        return ctx
```

**Prefer pushing computed values down the stack:**

1. **Queryset annotation** (best — works for API, CSV, and every display):
   ```python
   class ProfileManager(models.Manager):
       def with_tenure(self):
           return self.annotate(days_since_signup=...)
   ```
2. **Model property** (still good — dotted paths resolve properties):
   ```python
   @property
   def days_since_signup(self):
       return (timezone.now() - self.created_at).days
   ```
3. **Display subclass override** — last resort, for values that are genuinely presentation-only.

## Authoring a new card variant

Three pieces:

**1. An item template partial** — `templates/myapp/cards/stat.html`:

```django
<{% if card.detail_url %}a href="{{ card.detail_url }}"{% else %}div{% endif %}
    class="card-grid-item card-grid-item--stat"
    {% if enable_bulk %}data-pk="{{ card.pk }}"{% endif %}
>
    {% if enable_bulk %}
    <div class="card-grid-check" onclick="event.stopPropagation();">
        <input type="checkbox" class="bulk-select-row" data-pk="{{ card.pk }}">
    </div>
    {% endif %}
    <div class="stat-card-value">{{ card.value }}</div>
    <div class="stat-card-label">{{ card.label }}</div>
</{% if card.detail_url %}a{% else %}div{% endif %}>
```

**2. A subclass** of `CardDisplay`:

```python
from apps.smallstack.displays import CardDisplay, _resolve_field

class StatCardDisplay(CardDisplay):
    item_template = "myapp/cards/stat.html"

    def __init__(self, value_field, label_field):
        self.value_field = value_field
        self.label_field = label_field

    def build_card(self, obj, crud_config, request):
        return {
            "value": _resolve_field(obj, self.value_field),
            "label": _resolve_field(obj, self.label_field),
        }
```

**3. Optional CSS** for the new variant class (`.card-grid-item--stat`) in your app's stylesheet.

The base `CardDisplay` handles the grid wrapper, pagination, bulk checkbox, `pk`, `obj`, and `detail_url` — your subclass only builds the dict its partial consumes.

## What the base provides to every card

Every card dict receives these keys automatically (you don't build them):

| Key | Value |
|-----|-------|
| `pk` | Object primary key (for bulk checkbox `data-pk`) |
| `obj` | The model instance itself (useful in template or subclass mutations) |
| `detail_url` | Resolved URL to the detail view, or `None` if detail action is disabled |

Your `build_card()` returns whatever other keys your template consumes.

## Beyond cards: generalizing the pattern

The same pattern works for *any* list display family — calendars, maps, kanban boards, gantt charts. Subclass `ListDisplay` (not `CardDisplay`), declare the field kwargs your layout needs, turn the queryset into whatever shape your template wants.

`CardDisplay` is just the `ListDisplay` variant that adds per-item template dispatch (because cards have sub-variants). Unique one-off displays can skip the `item_template` indirection entirely and use a single `template_name`.

**Example already in the codebase:** `CalendarDisplay` renders a month grid with events on their date cells, built as a sibling `ListDisplay` (not a card variant). See **`calendar-displays.md`** for the full reference.

```python
explorer_displays = [
    TableDisplay,
    CalendarDisplay(date_field="start", end_field="end", title_field="title"),
]
```

## Files

| Path | Role |
|------|------|
| `apps/smallstack/displays.py` | `CardDisplay`, `AvatarCardDisplay`, `_resolve_field`, `_resolve_image_url`, `_derive_initials` |
| `apps/smallstack/templates/smallstack/crud/displays/cards.html` | Grid wrapper — iterates cards, includes `item_template` |
| `apps/smallstack/templates/smallstack/crud/displays/cards/avatar.html` | Avatar variant partial |
| `apps/smallstack/templates/smallstack/crud/displays/cards/keyvalue.html` | Default key-value partial |
| `apps/smallstack/static/smallstack/css/components.css` | `.card-grid*` styles |

## Related skills

- `calendar-displays.md` — sibling list-display family for date-based models
- `crud-views.md` — display protocol overview, `list_fields` vs `list_columns`
- `explorer.md` — `explorer_displays` attribute on admin classes
- `dashboard-widgets.md` — `DashboardWidget` uses the same widget_type/partial dispatch idea
