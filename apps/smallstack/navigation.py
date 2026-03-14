"""
Data-driven navigation registry for SmallStack.

Apps register nav items in their AppConfig.ready() method:

    from apps.smallstack.navigation import nav
    nav.register(
        section="admin", label="Activity",
        url_name="activity:dashboard", icon_svg="<svg>...</svg>",
        staff_required=True, order=10,
    )

Sub-items use the ``parent`` kwarg (label string of the parent item):

    nav.register(section="main", label="Schedule", url_name="website:schedule", order=10)
    nav.register(section="main", label="Calendar", url_name="website:calendar", parent="Schedule", order=0)
    nav.register(section="main", label="Results", url_name="website:results", parent="Schedule", order=1)

The ``topbar`` section provides alternate items for the topbar horizontal nav.
When present, topbar renders these instead of ``main``. The sidebar ignores them.

    nav.register(section="topbar", label="Features", url_name="website:features", order=0)
    nav.register(section="topbar", label="Pricing", url_name="website:pricing", order=1)

The context processor exposes ``nav_items`` to templates, grouped by section.
A theme app overrides the sidebar template to change HTML structure but iterates
the same nav data — adding/removing an app in INSTALLED_APPS automatically
updates navigation.
"""

from django.urls import NoReverseMatch, reverse

# Sections render in this order; unlisted sections appear last.
# "topbar" is not rendered in the sidebar — it overrides "main" in the topbar only.
SECTION_ORDER = ["main", "topbar", "app", "page", "resources", "admin"]


class _NavItem:
    __slots__ = (
        "section", "label", "url_name", "url_args", "url_kwargs",
        "icon_svg", "auth_required", "staff_required", "order",
        "parent",
    )

    def __init__(
        self, *, section, label, url_name, url_args=None, url_kwargs=None,
        icon_svg="", auth_required=False, staff_required=False, order=0,
        parent=None,
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
        self.parent = parent


class NavRegistry:
    def __init__(self):
        self._items: list[_NavItem] = []

    def register(
        self, *, section, label, url_name, url_args=None, url_kwargs=None,
        icon_svg="", auth_required=False, staff_required=False, order=0,
        parent=None,
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
            parent=parent,
        ))

    def get_nav_items(self, request):
        """Return nav items resolved and filtered for the current request.

        Returns a list of dicts grouped by section (ordered per SECTION_ORDER):
        [
            {"section": "main", "items": [
                {"label": ..., "url": ..., "icon_svg": ..., "active": bool,
                 "children": [...], "has_active_child": bool},
            ]},
            ...
        ]

        Items with a ``parent`` are nested under the matching parent item.
        If the parent doesn't exist, the child is promoted to top-level.

        Only the single longest (most-specific) URL match is marked active,
        so ``/help/smallstack/`` won't also highlight ``/help/``.
        """
        user = getattr(request, "user", None)
        is_authenticated = getattr(user, "is_authenticated", False)
        is_staff = getattr(user, "is_staff", False)

        # First pass: resolve URLs and collect candidates
        resolved: list[tuple[dict, str, str | None]] = []  # (item_dict, url, parent)
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
                "children": [],
                "has_active_child": False,
            }, url, item.parent))

        # Second pass: mark only the longest matching URL as active
        best_match = ""
        best_item = None
        for item_dict, url, _parent in resolved:
            if request.path == url:
                best_match = url
                best_item = item_dict
                break
            if url != "/" and request.path.startswith(url) and len(url) > len(best_match):
                best_match = url
                best_item = item_dict
        if best_item is not None:
            best_item["active"] = True

        # Third pass: build parent→children tree
        # Index top-level items by (section, label)
        parent_index: dict[tuple[str, str], dict] = {}
        top_level: list[tuple[dict, str]] = []
        children: list[tuple[dict, str, str]] = []

        for item_dict, url, parent in resolved:
            if parent is None:
                top_level.append((item_dict, url))
                parent_index[(item_dict["section"], item_dict["label"])] = item_dict
            else:
                children.append((item_dict, url, parent))

        # Attach children to parents
        for item_dict, url, parent_label in children:
            key = (item_dict["section"], parent_label)
            parent_item = parent_index.get(key)
            if parent_item is not None:
                parent_item["children"].append(item_dict)
                if item_dict["active"]:
                    parent_item["has_active_child"] = True
            else:
                # Parent not found — promote to top-level (defensive)
                top_level.append((item_dict, url))

        # Group into sections
        sections: dict[str, list] = {}
        for item_dict, _url in top_level:
            sec = item_dict.pop("section")
            item_dict.pop("url_name", None)
            # Also clean url_name from children
            for child in item_dict["children"]:
                child.pop("section", None)
                child.pop("url_name", None)
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
