"""
Data-driven navigation registry for SmallStack.

Apps register nav items in their AppConfig.ready() method:

    from apps.smallstack.navigation import nav
    nav.register(
        section="admin", label="Activity",
        url_name="activity:dashboard", icon_svg="<svg>...</svg>",
        staff_required=True, order=10,
    )

The context processor exposes ``nav_items`` to templates, grouped by section.
A theme app overrides the sidebar template to change HTML structure but iterates
the same nav data — adding/removing an app in INSTALLED_APPS automatically
updates navigation.
"""

from django.urls import NoReverseMatch, reverse

# Sections render in this order; unlisted sections appear last.
SECTION_ORDER = ["main", "resources", "admin"]


class _NavItem:
    __slots__ = (
        "section", "label", "url_name", "url_args", "url_kwargs",
        "icon_svg", "auth_required", "staff_required", "order",
    )

    def __init__(
        self, *, section, label, url_name, url_args=None, url_kwargs=None,
        icon_svg="", auth_required=False, staff_required=False, order=0,
    ):
        self.section = section
        self.label = label
        self.url_name = url_name
        self.url_args = url_args or []
        self.url_kwargs = url_kwargs or {}
        self.icon_svg = icon_svg
        self.auth_required = auth_required
        self.staff_required = staff_required
        self.order = order


class NavRegistry:
    def __init__(self):
        self._items: list[_NavItem] = []

    def register(
        self, *, section, label, url_name, url_args=None, url_kwargs=None,
        icon_svg="", auth_required=False, staff_required=False, order=0,
    ):
        self._items.append(_NavItem(
            section=section,
            label=label,
            url_name=url_name,
            url_args=url_args,
            url_kwargs=url_kwargs,
            icon_svg=icon_svg,
            auth_required=auth_required,
            staff_required=staff_required,
            order=order,
        ))

    def get_nav_items(self, request):
        """Return nav items resolved and filtered for the current request.

        Returns a list of dicts grouped by section (ordered per SECTION_ORDER):
        [
            {"section": "main", "items": [{"label": ..., "url": ..., "icon_svg": ..., "active": bool}, ...]},
            {"section": "resources", "items": [...]},
            {"section": "admin", "items": [...]},
        ]

        Only the single longest (most-specific) URL match is marked active,
        so ``/help/smallstack/`` won't also highlight ``/help/``.
        """
        user = getattr(request, "user", None)
        is_authenticated = getattr(user, "is_authenticated", False)
        is_staff = getattr(user, "is_staff", False)

        # First pass: resolve URLs and collect candidates
        resolved: list[tuple[dict, str]] = []  # (item_dict, url)
        for item in sorted(self._items, key=lambda i: i.order):
            if item.auth_required and not is_authenticated:
                continue
            if item.staff_required and not is_staff:
                continue
            try:
                url = reverse(item.url_name, args=item.url_args, kwargs=item.url_kwargs)
            except NoReverseMatch:
                continue
            resolved.append(({
                "label": item.label,
                "url": url,
                "icon_svg": item.icon_svg,
                "active": False,
                "url_name": item.url_name,
                "section": item.section,
            }, url))

        # Second pass: mark only the longest matching URL as active
        best_match = ""
        best_item = None
        for item_dict, url in resolved:
            if request.path == url:
                best_match = url
                best_item = item_dict
                break
            if url != "/" and request.path.startswith(url) and len(url) > len(best_match):
                best_match = url
                best_item = item_dict
        if best_item is not None:
            best_item["active"] = True

        # Group into sections
        sections: dict[str, list] = {}
        for item_dict, _url in resolved:
            sec = item_dict.pop("section")
            sections.setdefault(sec, []).append(item_dict)

        # Return in defined order
        def _section_key(name):
            try:
                return SECTION_ORDER.index(name)
            except ValueError:
                return len(SECTION_ORDER)

        return [
            {"section": name, "items": items}
            for name, items in sorted(sections.items(), key=lambda kv: _section_key(kv[0]))
        ]


# Module-level singleton
nav = NavRegistry()
