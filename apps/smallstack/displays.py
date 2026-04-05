"""Display protocol for SmallStack CRUD views.

Display classes render a dataset into a visual format. CRUDView provides
the data; the display class renders it.

Built-in displays:
    List:   TableDisplay, CardDisplay, AvatarCardDisplay, CalendarDisplay
    Detail: DetailTableDisplay, DetailFormDisplay, DetailGridDisplay, DetailCardDisplay
    Form:   DefaultFormDisplay, SectionedFormDisplay

List accessories (rendered above the toolbar):
    ListAccessory (base), StatsAccessory

Dashboard widgets (rendered on /smallstack/):
    DashboardWidget (base)
"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def paginate_queryset(queryset, paginate_by, request):
    """Paginate a queryset and return context dict for templates.

    Returns a dict with object_list, page_obj, paginator, is_paginated,
    and paginate_by — ready to context.update() in any display.

    If paginate_by is falsy, returns {"object_list": queryset} unchanged.
    """
    if not paginate_by:
        return {"object_list": queryset}

    from django.core.paginator import Paginator

    paginator = Paginator(queryset, paginate_by)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # SmallStack pagination display helpers
    page_obj.showing_start = page_obj.start_index()
    page_obj.showing_end = page_obj.end_index()
    page_obj.total_count = paginator.count

    return {
        "object_list": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "is_paginated": page_obj.has_other_pages(),
        "paginate_by": paginate_by,
    }


def build_palette_context(displays, active_display, request):
    """Build structured palette context used by all action types.

    Returns a dict with:
        displays: list of {name, icon, active, url}
        active: name of the active display
        show_palette: whether the palette should be shown
    """
    items = []
    for d in displays:
        items.append(
            {
                "name": d.name,
                "icon": d.icon,
                "active": d.name == active_display.name,
                "url": f"?display={d.name}",
            }
        )
    show = getattr(active_display, "show_palette", True) and len(displays) > 1
    return {
        "displays": items,
        "active": active_display.name,
        "show_palette": show,
    }


# ---------------------------------------------------------------------------
# List displays
# ---------------------------------------------------------------------------


class ListDisplay:
    """Base class for list view displays.

    Subclass this to create custom list displays (maps, charts, etc.).
    CRUDView picks the active display and calls get_context() to build
    template context, then renders template_name inside the list view.

    Class attributes:
        supports_bulk: If False, the list page hides bulk-select UI when
            this display is active (e.g. map views, charts, custom layouts
            where per-row checkboxes don't fit).
    """

    name = ""
    icon = ""
    template_name = ""
    supports_bulk: bool = True

    def get_context(self, queryset, crud_config, request):
        """Return additional template context for rendering this display."""
        return {}


class DetailDisplay:
    """Base class for detail view displays.

    Subclass this to create alternative detail renderings (maps, etc.).
    """

    name = ""
    icon = ""
    template_name = ""

    def get_context(self, obj, crud_config, request):
        """Return additional template context for rendering this display."""
        return {}


class DetailTableDisplay(DetailDisplay):
    """Default detail view — vertical key/value table ({% crud_detail %} tag)."""

    name = "table"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M3 3v18h18V3H3zm8 16H5v-6h6v6zm0-8H5V5h6v6zm8 8h-6v-6h6v6zm0-8h-6V5h6v6z"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/detail_table.html"


class DetailFormDisplay(DetailDisplay):
    """Form-style detail view — renders fields as readonly form inputs."""

    name = "form"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 '
        '0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/detail_form.html"

    def get_context(self, obj, crud_config, request):
        from apps.smallstack.templatetags.crud_tags import _get_field_label, _get_field_value

        detail_fields = crud_config._get_detail_fields() or []
        field_transforms = crud_config._get_effective_transforms()

        field_rows = []
        for field_name in detail_fields:
            label = _get_field_label(obj.__class__, field_name)
            value = _get_field_value(obj, field_name, field_transforms)
            is_bool = isinstance(getattr(obj, field_name, None), bool)
            field_rows.append({"label": label, "value": value, "is_bool": is_bool})

        return {"field_rows": field_rows}


class DetailGridDisplay(DetailDisplay):
    """Two-column grid detail view — label in left column, boxed value in right."""

    name = "grid"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M3 3v18h18V3H3zm7 16H5v-3h5v3zm0-5H5v-3h5v3zm0-5H5V6h5v3z'
        'm9 10h-7v-3h7v3zm0-5h-7v-3h7v3zm0-5h-7V6h7v3z"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/detail_grid.html"

    def get_context(self, obj, crud_config, request):
        from apps.smallstack.templatetags.crud_tags import _get_field_label, _get_field_value

        detail_fields = crud_config._get_detail_fields() or []
        field_transforms = crud_config._get_effective_transforms()

        field_rows = []
        for field_name in detail_fields:
            label = _get_field_label(obj.__class__, field_name)
            value = _get_field_value(obj, field_name, field_transforms)
            is_bool = isinstance(getattr(obj, field_name, None), bool)
            field_rows.append({"label": label, "value": value, "is_bool": is_bool})

        return {"field_rows": field_rows}


class DetailCardDisplay(DetailDisplay):
    """Two-column profile-style detail: image on left, fields on right.

    Usage:
        detail_displays = [
            DetailTableDisplay,
            DetailCardDisplay(image_field="profile_photo"),
        ]

    If no image_field is set or the field is empty, falls back to an
    icon placeholder on the left.
    """

    name = "card"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4z'
        'm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/detail_card.html"

    def __init__(self, image_field=None):
        self.image_field = image_field

    def get_context(self, obj, crud_config, request):
        """Build field rows and resolve image URL."""
        from apps.smallstack.templatetags.crud_tags import _get_field_label, _get_field_value

        detail_fields = crud_config._get_detail_fields() or []
        field_transforms = crud_config._get_effective_transforms()

        # Resolve image
        image_url = None
        if self.image_field:
            image_file = getattr(obj, self.image_field, None)
            if image_file:
                try:
                    image_url = image_file.url
                except ValueError:
                    pass

        # Build field rows, excluding the image field
        field_rows = []
        for field_name in detail_fields:
            if field_name == self.image_field:
                continue
            label = _get_field_label(obj.__class__, field_name)
            value = _get_field_value(obj, field_name, field_transforms)
            field_rows.append({"label": label, "value": value})

        return {
            "image_url": image_url,
            "field_rows": field_rows,
        }


class TableDisplay(ListDisplay):
    """Basic HTML table display using the {% crud_table %} template tag."""

    name = "table"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M3 3v18h18V3H3zm8 16H5v-6h6v6zm0-8H5V5h6v6zm8 8h-6v-6h6v6zm0-8h-6V5h6v6z"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/table.html"

    def get_context(self, queryset, crud_config, request):
        """Paginate the queryset for the basic table display."""
        return paginate_queryset(queryset, crud_config._resolve_paginate_by(), request)


def _resolve_field(obj, path):
    """Resolve a field reference: callable, dotted path ('user.username'), or attr name.

    Returns None if any segment is missing.
    """
    if path is None:
        return None
    if callable(path):
        return path(obj)
    value = obj
    for part in str(path).split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _resolve_image_url(obj, path):
    """Resolve an ImageField-style reference to its .url (or None)."""
    image = _resolve_field(obj, path)
    if not image:
        return None
    try:
        return image.url
    except (ValueError, AttributeError):
        return None


def _derive_initials(text, n=2):
    """Derive up-to-N-letter initials from a string (e.g. 'Jane Doe' -> 'JD')."""
    if not text:
        return "?"
    parts = [p for p in str(text).strip().split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return str(text)[:n].upper()


class CardDisplay(ListDisplay):
    """Grid-of-cards base display — peer to TableDisplay.

    Handles the grid wrapper, pagination, bulk-select checkbox, pk, and
    detail URL for each card. Subclasses define `item_template` (the
    per-card partial) and override `build_card()` to shape each card's
    dict for their template.

    Default behavior (no subclass needed): renders a key-value card for
    each object using the model's list_columns/list_fields — the first
    field becomes the card title, remaining fields render as
    label: value rows. Works on any model with zero config.

    Variants:
        CardDisplay()               — key-value layout (zero config)
        AvatarCardDisplay(...)      — avatar + title + subtitle + pill
        (custom)                    — subclass with your own item_template

    Usage:
        explorer_displays = [TableDisplay, CardDisplay]  # zero config
        explorer_displays = [TableDisplay, AvatarCardDisplay(
            title_field="name", image_field="photo")]

    Authoring new variants:
        class StatCardDisplay(CardDisplay):
            item_template = "myapp/cards/stat.html"
            def __init__(self, value_field, label_field):
                self.value_field = value_field
                self.label_field = label_field
            def build_card(self, obj, cfg, req):
                return {
                    "value": _resolve_field(obj, self.value_field),
                    "label": _resolve_field(obj, self.label_field),
                }
    """

    name = "cards"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M4 5h5v4H4V5zm7 0h5v4h-5V5zm7 0h2v4h-2V5zM4 11h5v4H4v-4z'
        'm7 0h5v4h-5v-4zm7 0h2v4h-2v-4zM4 17h5v4H4v-4zm7 0h5v4h-5v-4zm7 0h2v4h-2v-4z"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/cards.html"
    item_template = "smallstack/crud/displays/cards/keyvalue.html"

    def get_context(self, queryset, crud_config, request):
        """Orchestrate pagination, per-card URLs, and item-template dispatch."""
        from apps.smallstack.crud import Action

        paginate_by = crud_config._resolve_paginate_by()
        page_context = paginate_queryset(queryset, paginate_by, request)
        items = page_context.pop("object_list", queryset)

        has_detail = Action.DETAIL in crud_config.actions

        cards = []
        for obj in items:
            card = self.build_card(obj, crud_config, request)
            card["pk"] = obj.pk
            card["obj"] = obj
            card["detail_url"] = self._resolve_detail_url(obj, crud_config) if has_detail else None
            cards.append(card)

        return {
            "cards": cards,
            "item_template": self.item_template,
            "object_list": items,
            "paginate_by": paginate_by or 0,
            **page_context,
        }

    def build_card(self, obj, crud_config, request):
        """Build the per-card dict. Default: key-value layout using list_fields.

        Returns a dict with {"title": ..., "rows": [{"label", "value"}, ...]}.
        Subclasses typically replace this with their own shape.
        """
        from apps.smallstack.templatetags.crud_tags import _get_field_label, _get_field_value

        field_transforms = crud_config._get_effective_transforms()
        list_fields = crud_config._get_list_columns() or crud_config._get_list_fields() or []

        title = str(obj)
        rows = []
        for i, field_name in enumerate(list_fields):
            value = _get_field_value(obj, field_name, field_transforms)
            if i == 0:
                title = value or str(obj)
                continue
            label = _get_field_label(obj.__class__, field_name)
            rows.append({"label": label, "value": value})
        return {"title": title, "rows": rows}

    @staticmethod
    def _resolve_detail_url(obj, crud_config):
        from django.urls import reverse

        url_base = crud_config._get_url_base()
        namespace = getattr(crud_config, "namespace", None)
        url_name = f"{url_base}-detail"
        if namespace:
            url_name = f"{namespace}:{url_name}"
        return reverse(url_name, kwargs={"pk": obj.pk})


class AvatarCardDisplay(CardDisplay):
    """Card variant with avatar, title, subtitle, and optional pill.

    Fields can be referenced as attribute names, dotted paths
    ('user.username'), or callables (obj -> value).

    Subclass + override build_card (or get_context) to inject computed
    fields (e.g. pills whose values aren't plain model fields). Subclasses
    that only need to annotate cards can call super().get_context() and
    mutate the returned 'cards' list.

    Usage:
        displays = [
            AvatarCardDisplay(
                title_field="name",
                subtitle_field="email",
                image_field="avatar",
                pill_field="status",
            ),
        ]
    """

    item_template = "smallstack/crud/displays/cards/avatar.html"

    def __init__(
        self,
        title_field=None,
        subtitle_field=None,
        image_field=None,
        pill_field=None,
        pill_label=None,
        show_avatar=None,
    ):
        self.title_field = title_field
        self.subtitle_field = subtitle_field
        self.image_field = image_field
        self.pill_field = pill_field
        self.pill_label = pill_label
        # Default: show avatar when an image_field is provided. Pass
        # show_avatar=True to force an initials-only avatar for models
        # without a photo (e.g. User).
        self.show_avatar = show_avatar if show_avatar is not None else (image_field is not None)

    def build_card(self, obj, crud_config, request):
        title_field = self.title_field or (crud_config._get_list_fields() or ["__str__"])[0]
        title = _resolve_field(obj, title_field) or str(obj)
        subtitle = _resolve_field(obj, self.subtitle_field) if self.subtitle_field else None
        pill_value = _resolve_field(obj, self.pill_field) if self.pill_field else None

        if self.show_avatar:
            image_url = _resolve_image_url(obj, self.image_field) if self.image_field else None
            initials = _derive_initials(title) if not image_url else None
        else:
            image_url = None
            initials = None

        return {
            "title": title,
            "subtitle": subtitle,
            "image_url": image_url,
            "initials": initials,
            "show_avatar": self.show_avatar,
            "pill_value": pill_value,
            "pill_label": self.pill_label,
        }


class CalendarDisplay(ListDisplay):
    """Month-grid calendar view of records with a date or datetime field.

    Each record renders as a clickable chip on its date cell. For records
    with a range (start + end), pass `end_field` to stretch the event
    across every day in the range.

    Usage:
        # Single-date events
        CalendarDisplay(date_field="due_date", title_field="title")

        # Ranged events (e.g. maintenance windows, reservations)
        CalendarDisplay(
            date_field="start",
            end_field="end",
            title_field="title",
        )

    URL navigation:
        ?display=calendar&month=YYYY-MM

    The display filters the queryset to the visible month, so very large
    datasets don't blow up. Bulk-select is disabled (doesn't fit the
    calendar cell layout).
    """

    name = "calendar"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19'
        "c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11z"
        'M9 10H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2z"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/calendar.html"
    supports_bulk = False

    def __init__(
        self,
        date_field,
        end_field=None,
        title_field=None,
        status_field=None,
        variant="chip",
        month_param="month",
    ):
        self.date_field = date_field
        self.end_field = end_field
        self.title_field = title_field
        self.status_field = status_field
        self.variant = variant
        self.month_param = month_param

    def get_context(self, queryset, crud_config, request):
        import calendar as pycal
        from datetime import date as date_cls
        from datetime import timedelta

        from django.utils import timezone

        from apps.smallstack.crud import Action

        today = timezone.localdate()

        # Parse month from URL (?month=YYYY-MM), default to current month
        month_str = request.GET.get(self.month_param, "")
        try:
            year, month = (int(x) for x in month_str.split("-"))
            cursor = date_cls(year, month, 1)
        except (ValueError, TypeError):
            cursor = today.replace(day=1)

        _, last_day = pycal.monthrange(cursor.year, cursor.month)
        month_start = cursor
        month_end = cursor.replace(day=last_day)
        next_day_after = month_end + timedelta(days=1)

        # Filter queryset to events overlapping the visible month
        if self.end_field:
            filtered = queryset.filter(
                **{f"{self.date_field}__lt": next_day_after},
                **{f"{self.end_field}__gte": month_start},
            )
        else:
            filtered = queryset.filter(
                **{f"{self.date_field}__gte": month_start},
                **{f"{self.date_field}__lt": next_day_after},
            )

        # Bucket events onto each day they touch
        has_detail = Action.DETAIL in crud_config.actions
        events_by_day = {}
        for obj in filtered:
            start = _to_local_date(_resolve_field(obj, self.date_field))
            end = (
                _to_local_date(_resolve_field(obj, self.end_field))
                if self.end_field
                else start
            )
            if start is None:
                continue
            if end is None:
                end = start

            title = (
                _resolve_field(obj, self.title_field) if self.title_field else str(obj)
            )
            detail_url = (
                CardDisplay._resolve_detail_url(obj, crud_config) if has_detail else None
            )
            # Raw values for the hover tooltip
            raw_start = _resolve_field(obj, self.date_field)
            raw_end = _resolve_field(obj, self.end_field) if self.end_field else None
            status = (
                _resolve_field(obj, self.status_field) if self.status_field else None
            )
            event = {
                "title": title,
                "detail_url": detail_url,
                "pk": obj.pk,
                "start": raw_start,
                "end": raw_end,
                "status": status,
            }

            day = max(start, month_start)
            last = min(end, month_end)
            while day <= last:
                events_by_day.setdefault(day, []).append(event)
                day += timedelta(days=1)

        # Build Monday-start 7-column week grid
        first_weekday = month_start.weekday()  # 0 = Monday
        weeks = []
        current_week = [None] * first_weekday
        for day_num in range(1, last_day + 1):
            d = month_start.replace(day=day_num)
            current_week.append(
                {
                    "day": day_num,
                    "date": d,
                    "is_today": d == today,
                    "events": events_by_day.get(d, []),
                }
            )
            if len(current_week) == 7:
                weeks.append(current_week)
                current_week = []
        if current_week:
            current_week.extend([None] * (7 - len(current_week)))
            weeks.append(current_week)

        prev_month = (month_start - timedelta(days=1)).replace(day=1)
        next_month_any_day = next_day_after

        return {
            "weeks": weeks,
            "weekday_headers": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "month_label": month_start.strftime("%B %Y"),
            "month_start": month_start,
            "month_end": month_end,
            "prev_month": f"{prev_month.year}-{prev_month.month:02d}",
            "next_month": f"{next_month_any_day.year}-{next_month_any_day.month:02d}",
            "today_month": f"{today.year}-{today.month:02d}",
            "is_current_month": month_start.year == today.year and month_start.month == today.month,
            "month_param": self.month_param,
            "event_count": sum(len(v) for v in events_by_day.values()),
            "variant": self.variant,
        }


def _to_local_date(value):
    """Coerce a date/datetime/None into a local date."""
    if value is None:
        return None
    if hasattr(value, "hour"):  # datetime
        from django.utils import timezone

        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date()
    return value  # already a date


# ---------------------------------------------------------------------------
# Form displays
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# List accessories
# ---------------------------------------------------------------------------


class ListAccessory:
    """Renders supplementary content above the list display (stats, charts, etc.).

    Subclass this to create custom accessories. CRUDView calls render()
    with the unfiltered queryset so stats reflect totals regardless of filters.
    """

    template_name = ""

    def get_context(self, queryset, crud_config, request):
        """Return template context. queryset is the UNFILTERED full set."""
        return {}

    def render(self, queryset, crud_config, request):
        """Render this accessory to an HTML string."""
        from django.template.loader import render_to_string

        ctx = self.get_context(queryset, crud_config, request)
        return render_to_string(self.template_name, ctx, request=request)


class StatsAccessory(ListAccessory):
    """Row of stat cards above the list. Declarative config, no custom template.

    Usage:
        list_accessories = [
            StatsAccessory(stats=[
                {"label": "Total", "value": lambda qs: qs.count()},
                {"label": "Staff", "value": lambda qs: qs.filter(is_staff=True).count()},
                {"label": "Admins", "value": 0},
            ])
        ]

    Each stat dict has:
        label: Display label
        value: callable(queryset) → value, or a static string/int
        color: Optional CSS color for the value (e.g. "var(--primary)")
    """

    template_name = "smallstack/crud/accessories/stats.html"

    def __init__(self, stats):
        self.stats = stats

    def get_context(self, queryset, crud_config, request):
        items = []
        for spec in self.stats:
            value = spec["value"]
            if callable(value):
                value = value(queryset)
            items.append(
                {
                    "label": spec["label"],
                    "value": value,
                    "color": spec.get("color", ""),
                }
            )
        return {"accessory_items": items}


# ---------------------------------------------------------------------------
# Form displays
# ---------------------------------------------------------------------------


class FormDisplay:
    """Base class for form view displays.

    Subclass this to create custom form layouts (sectioned, wizard,
    multi-column, etc.). CRUDView picks the active display and calls
    get_context() to build template context, then renders template_name.
    """

    name = ""
    icon = ""
    template_name = ""
    show_palette = True

    def get_context(self, form, obj, crud_config, request):
        """Return additional template context for rendering this form display.

        Args:
            form: The Django Form instance (bound on POST, unbound on GET)
            obj: The model instance (None for create, instance for update)
            crud_config: The CRUDView config class
            request: The HTTP request
        """
        return {}


class DefaultFormDisplay(FormDisplay):
    """Auto-generated vertical form — the current default layout."""

    name = "form"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 '
        '0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/form_default.html"
    show_palette = False


class SectionedFormDisplay(FormDisplay):
    """Group form fields into labeled section cards.

    Usage:
        SectionedFormDisplay(sections=[
            ("Contact Info", None, ["first_name", "last_name", "phone"]),
            ("Project", None, ["title", "description", "status"]),
        ])

    Each section is a tuple of (title, icon_html_or_None, [field_names]).
    Fields not present in the form are silently skipped.
    """

    name = "sectioned"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/form_sectioned.html"

    def __init__(self, sections, columns=2):
        """
        Args:
            sections: list of (title, icon_html_or_None, [field_names])
            columns: grid columns for the section layout (1 or 2)
        """
        self.sections = sections
        self.columns = columns

    def get_context(self, form, obj, crud_config, request):
        sections = []
        for title, icon, field_names in self.sections:
            fields = [form[name] for name in field_names if name in form.fields]
            if fields:
                sections.append({"title": title, "icon": icon, "fields": fields})
        return {"form_sections": sections, "form_columns": self.columns}


# ---------------------------------------------------------------------------
# Dashboard widgets
# ---------------------------------------------------------------------------


class DashboardWidget:
    """At-a-glance widget rendered on the SmallStack dashboard.

    Subclass this and override get_data() to produce the widget's content.
    For Explorer-registered models, attach widgets via:
        AdminClass.explorer_dashboard_widgets = [MyWidget()]

    For standalone widgets (no Explorer model), register via:
        from apps.smallstack import dashboard
        dashboard.register(MyWidget())

    Class attributes:
        title: Label shown above the headline.
        icon: SVG icon markup (trusted HTML).
        order: Sort order among widgets (lower = earlier).
        widget_type: Template partial selector. Today only "card" is shipped.
        span: CSS grid column span (1 = normal, 2 = wide).
        url_name: Overrides auto-resolved Explorer list URL.
        url_kwargs: kwargs for URL reversal.
        group: Optional group name for filtered views (standalone widgets only;
               Explorer widgets inherit group from ModelInfo).
        on_dashboard: Whether this widget surfaces on the main /smallstack/
               dashboard. Set False to scope a widget to its group/app/model
               page only (useful for granular widgets that would clutter the
               top-level view). Default True.
    """

    title: str = ""
    icon: str = ""
    order: int = 50
    widget_type: str = "card"
    span: int = 1
    url_name: str | None = None
    url_kwargs: dict | None = None
    group: str | None = None
    on_dashboard: bool = True

    def get_data(self, model_class=None) -> dict:
        """Return widget data. Shape depends on widget_type.

        For widget_type="card", the template reads:
            {"headline": str, "detail": str, "status"?: str}

        Any additional keys are passed through to the API (GET
        /api/dashboard/widgets/) but ignored by the HTML template.
        This lets you surface richer, machine-readable data to API
        consumers (raw counts, timestamps, trends, thresholds, etc.)
        without affecting the card UI.

        Example:
            return {
                "headline": "42 requests",
                "detail": "in last 24h",
                # Extras — API only:
                "extra": {
                    "total": 42,
                    "window_hours": 24,
                    "by_status": {"2xx": 38, "4xx": 3, "5xx": 1},
                },
            }

        If the extras are expensive to compute, override
        get_api_extras() instead — it's only called for API responses.

        Args:
            model_class: For Explorer widgets, the Django model class the
                         widget is attached to. None for standalone widgets.
        """
        raise NotImplementedError

    def get_api_extras(self, model_class=None) -> dict | None:
        """Return additional API-only data, merged into the serialized
        widget's "data" field. Called only when serializing for the API,
        not when rendering HTML.

        Override this when the extra data is expensive to compute and
        you don't want it slowing down page renders.
        """
        return None
