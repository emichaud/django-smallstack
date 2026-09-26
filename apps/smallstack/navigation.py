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

import logging
from typing import Any

from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger("smallstack.navigation")

# Sections render in this order; unlisted sections appear last.
# "topbar" is not rendered in the sidebar — it overrides "main" in the topbar only.
SECTION_ORDER = ["main", "topbar", "app", "page", "resources", "admin"]

# Sections whose items are listed A–Z by label instead of by ``order``.
#
# The admin section is a tool drawer: a dozen unrelated utilities contributed by
# whichever apps happen to be installed, with no workflow sequence to preserve.
# Hand-numbering it meant every new app picked a number, the numbers collided
# (Status and Explorer both sat at 20, so their relative order came down to
# INSTALLED_APPS ordering), and the list drifted out of alphabetical as soon as
# anything was added or relabelled. Sorting here keeps it A–Z permanently,
# including for apps a downstream project adds.
#
# ``order`` is ignored for these sections — see ``register``.
ALPHABETICAL_SECTIONS = {"admin"}


def _sort_key(item: "_NavItem") -> tuple:
    """Alphabetical for tool-drawer sections, explicit ``order`` everywhere else.

    Case-insensitive so "API Health" files under A next to "Activity" rather
    than ahead of every lowercase label, which is what a reader scanning the
    menu expects. Falls back to the raw label so the sort stays stable when two
    labels differ only in case.
    """
    if item.section in ALPHABETICAL_SECTIONS:
        return (0, item.label.casefold(), item.label)
    return (item.order, "", "")


class _NavItem:
    __slots__ = (
        "section",
        "label",
        "url_name",
        "url_args",
        "url_kwargs",
        "icon_svg",
        "auth_required",
        "staff_required",
        "order",
        "parent",
        "zone",
        "active_prefix",
        "active_exact",
        "visible",
    )

    def __init__(
        self,
        *,
        section: str,
        label: str,
        url_name: str,
        url_args: list | None = None,
        url_kwargs: dict | None = None,
        icon_svg: str = "",
        auth_required: bool = False,
        staff_required: bool = False,
        order: int = 0,
        parent: str | None = None,
        zone: str = "smallstack",
        active_prefix: str | None = None,
        active_exact: bool = False,
        visible: Any = None,
    ) -> None:
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
        self.zone = zone
        # Optional path prefix that marks this item active for ANY URL beneath it
        # (e.g. "/smallstack/status/" so all status sub-pages highlight one item).
        # Include the trailing slash to avoid bleeding into siblings like
        # "/status-report/". Falls back to the item's own resolved URL when unset.
        self.active_prefix = active_prefix
        # Only an exact path match marks this item active — never a prefix.
        # For a section root this is the difference between "you are here" and
        # "you are somewhere below here": the dashboard lives at /smallstack/,
        # which prefixes every admin route, so any page with no nav entry of its
        # own (the notifications inbox, reached from the topbar bell) lit up
        # Dashboard and told the user they were somewhere they weren't.
        # (Test round 2026-09-26, T3.)
        self.active_exact = active_exact
        # Optional ``(request) -> bool`` predicate, applied AFTER auth_required /
        # staff_required. For rules the two flags cannot express — most often
        # "show this entry only to users the staff-only ADMIN section hides",
        # which is how a non-staff approver gets a link to a console they are
        # already allowed to use (F-46). A predicate that raises hides the item
        # rather than breaking the page.
        self.visible = visible


class NavRegistry:
    def __init__(self) -> None:
        self._items: list[_NavItem] = []

    def register(
        self,
        *,
        section: str,
        label: str,
        url_name: str,
        url_args: list | None = None,
        url_kwargs: dict | None = None,
        icon_svg: str = "",
        auth_required: bool = False,
        staff_required: bool = False,
        order: int = 0,
        parent: str | None = None,
        zone: str = "smallstack",
        active_prefix: str | None = None,
        active_exact: bool = False,
        visible: Any = None,
    ) -> None:
        """Register a nav item.

        ``order`` sorts items within a section — EXCEPT for the sections in
        ``ALPHABETICAL_SECTIONS`` (currently ``admin``), which are always listed
        A–Z by label. Passing ``order`` for one of those is harmless but has no
        effect; drop it rather than tuning a number that does nothing.
        """
        self._items.append(
            _NavItem(
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
                zone=zone,
                active_prefix=active_prefix,
                active_exact=active_exact,
                visible=visible,
            )
        )

    def get_nav_items(self, request: HttpRequest, zone: str | None = None) -> list[dict[str, Any]]:
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
        for item in sorted(self._items, key=_sort_key):
            if zone is not None and item.zone != zone:
                continue
            if item.auth_required and not is_authenticated:
                continue
            if item.staff_required and not is_staff:
                continue
            if item.visible is not None:
                try:
                    if not item.visible(request):
                        continue
                except Exception:  # noqa: BLE001 — a bad predicate hides, never 500s
                    logger.warning(
                        "nav: visible() raised for %r — hiding the item", item.label,
                        exc_info=True,
                    )
                    continue
            try:
                url = reverse(item.url_name, args=item.url_args, kwargs=item.url_kwargs)
            except NoReverseMatch:
                continue
            resolved.append(
                (
                    {
                        "label": item.label,
                        "url": url,
                        "icon_svg": item.icon_svg,
                        "active": False,
                        "url_name": item.url_name,
                        "section": item.section,
                        "children": [],
                        "has_active_child": False,
                        # Match against the explicit prefix when given, else the URL.
                        "active_match": item.active_prefix or url,
                        "active_exact": item.active_exact,
                    },
                    url,
                    item.parent,
                )
            )

        # Second pass: mark only the longest matching URL/prefix as active
        best_match = ""
        best_item = None
        for item_dict, url, _parent in resolved:
            match = item_dict["active_match"]
            if request.path == match:
                best_match = match
                best_item = item_dict
                break
            if item_dict["active_exact"]:
                continue
            if match != "/" and request.path.startswith(match) and len(match) > len(best_match):
                best_match = match
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
            item_dict.pop("active_match", None)
            item_dict.pop("active_exact", None)
            # Also clean internal keys from children
            for child in item_dict["children"]:
                child.pop("section", None)
                child.pop("url_name", None)
                child.pop("active_match", None)
                child.pop("active_exact", None)
            sections.setdefault(sec, []).append(item_dict)

        # Return in defined order
        def _section_key(name: str) -> int:
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
