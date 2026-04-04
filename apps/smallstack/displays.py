"""Display protocol for SmallStack CRUD views.

Display classes render a dataset into a visual format. CRUDView provides
the data; the display class renders it.

Built-in displays:
    List:   TableDisplay, CardDisplay
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
    """

    name = ""
    icon = ""
    template_name = ""

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


class CardDisplay(ListDisplay):
    """3-column card grid display.

    Each card shows a title and subtitle, and links to the detail view.

    Usage:
        displays = [CardDisplay(title_field="name", subtitle_field="created_at")]
    """

    name = "cards"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M4 5h5v4H4V5zm7 0h5v4h-5V5zm7 0h2v4h-2V5zM4 11h5v4H4v-4z'
        'm7 0h5v4h-5v-4zm7 0h2v4h-2v-4zM4 17h5v4H4v-4zm7 0h5v4h-5v-4zm7 0h2v4h-2v-4z"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/cards.html"

    def __init__(self, title_field=None, subtitle_field=None):
        self.title_field = title_field
        self.subtitle_field = subtitle_field

    def get_context(self, queryset, crud_config, request):
        """Build card data with pagination."""
        from django.urls import reverse

        paginate_by = crud_config._resolve_paginate_by()
        url_base = crud_config._get_url_base()
        title_field = self.title_field or crud_config._get_list_fields()[0]
        subtitle_field = self.subtitle_field

        # Paginate
        page_context = paginate_queryset(queryset, paginate_by, request)
        items = page_context.pop("object_list", queryset)

        # Build cards
        from apps.smallstack.crud import Action

        has_detail = Action.DETAIL in crud_config.actions
        namespace = getattr(crud_config, "namespace", None)
        cards = []
        for obj in items:
            title = getattr(obj, title_field, str(obj))
            subtitle = getattr(obj, subtitle_field, "") if subtitle_field else ""
            if has_detail:
                url_name = f"{url_base}-detail"
                if namespace:
                    url_name = f"{namespace}:{url_name}"
                detail_url = reverse(url_name, kwargs={"pk": obj.pk})
            else:
                detail_url = None
            cards.append(
                {
                    "pk": obj.pk,
                    "obj": obj,
                    "title": title,
                    "subtitle": subtitle,
                    "detail_url": detail_url,
                }
            )

        return {
            "cards": cards,
            "object_list": items,
            "paginate_by": paginate_by or 0,
            **page_context,
        }


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
