"""Display protocol for SmallStack CRUD views.

Display classes render a dataset into a visual format. CRUDView provides
the data; the display class renders it.

Built-in displays:
    List:   TableDisplay, Table2Display, CardDisplay
    Detail: DetailTableDisplay, DetailCardDisplay
    Form:   DefaultFormDisplay, SectionedFormDisplay
"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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
        paginate_by = crud_config._resolve_paginate_by()
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
        page_obj.page_range_display = paginator.get_elided_page_range(
            page_obj.number, on_each_side=2, on_ends=1
        )

        return {
            "object_list": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "is_paginated": page_obj.has_other_pages(),
        }


class Table2Display(ListDisplay):
    """django-tables2 sortable table display."""

    name = "table2"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M3 3v18h18V3H3zm8 16H5v-6h6v6zm0-8H5V5h6v6zm8 8h-6v-6h6v6zm0-8h-6V5h6v6z"/>'
        '<path d="M16 1l-3 3h2v4h2V4h2l-3-3z" opacity="0.6"/>'
        "</svg>"
    )
    template_name = "smallstack/crud/displays/table2.html"

    def get_context(self, queryset, crud_config, request):
        """Configure a django-tables2 table with pagination."""
        table_class = crud_config.table_class
        if not table_class:
            # Fall back to basic table if no table_class configured
            return TableDisplay().get_context(queryset, crud_config, request)

        from django_tables2 import RequestConfig

        table = table_class(queryset)
        paginate_by = crud_config._resolve_paginate_by()
        paginate = {"per_page": paginate_by} if paginate_by else False
        RequestConfig(request, paginate=paginate).configure(table)
        return {"table": table}


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
        page_context = {}
        if paginate_by:
            from django.core.paginator import Paginator

            paginator = Paginator(queryset, paginate_by)
            page_number = request.GET.get("page", 1)
            page_obj = paginator.get_page(page_number)
            items = page_obj.object_list
            page_obj.showing_start = page_obj.start_index()
            page_obj.showing_end = page_obj.end_index()
            page_obj.total_count = paginator.count
            page_obj.page_range_display = paginator.get_elided_page_range(
                page_obj.number, on_each_side=2, on_ends=1
            )
            page_context = {
                "page_obj": page_obj,
                "paginator": paginator,
                "is_paginated": page_obj.has_other_pages(),
            }
        else:
            items = queryset

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
            cards.append({
                "obj": obj,
                "title": title,
                "subtitle": subtitle,
                "detail_url": detail_url,
            })

        return {
            "cards": cards,
            "object_list": items,
            **page_context,
        }


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
