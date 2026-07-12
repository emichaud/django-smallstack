"""
Template tags for theme functionality including breadcrumbs, navigation helpers,
and timezone conversion.
"""

import datetime
import logging
import zoneinfo
from typing import Any

from django import template
from django.conf import settings
from django.urls import NoReverseMatch, reverse
from django.utils import dateformat

register = template.Library()
logger = logging.getLogger("smallstack")


class BreadcrumbNode(template.Node):
    """Node for rendering a breadcrumb item.

    All arguments are compiled FilterExpression objects so that filters
    work in breadcrumb arguments::

        {% load crud_tags %}
        {% breadcrumb "Clients" "construction/client-list"|ns:url_namespace %}
    """

    def __init__(self, label, url_name=None, url_args=None) -> None:
        self.label = label
        self.url_name = url_name
        self.url_args = url_args or []

    def render(self, context) -> str:
        label = self.label.resolve(context)

        # Get or create breadcrumbs list in context
        if "breadcrumbs" not in context:
            context["breadcrumbs"] = []

        breadcrumb = {"label": label, "url": None}

        # Resolve URL if provided
        if self.url_name:
            url_name = self.url_name.resolve(context)

            # Resolve URL args
            resolved_args = [arg.resolve(context) for arg in self.url_args]

            try:
                breadcrumb["url"] = reverse(url_name, args=resolved_args) if resolved_args else reverse(url_name)
            except Exception:
                breadcrumb["url"] = None

        context["breadcrumbs"].append(breadcrumb)
        return ""


@register.tag
def breadcrumb(parser, token) -> BreadcrumbNode:
    """
    Add a breadcrumb item to the breadcrumb trail.

    Usage:
        {% breadcrumb "Home" "home" %}
        {% breadcrumb "Profile" "profile" %}
        {% breadcrumb "Edit" %}  {# No URL for current page #}
        {% breadcrumb "User" "profile_detail" username %}  {# With URL args #}
        {% breadcrumb "Clients" "construction/client-list"|ns:url_namespace %}
    """
    bits = token.split_contents()
    tag_name = bits[0]

    if len(bits) < 2:
        raise template.TemplateSyntaxError(f"'{tag_name}' tag requires at least a label argument")

    label = parser.compile_filter(bits[1])
    url_name = parser.compile_filter(bits[2]) if len(bits) > 2 else None
    url_args = [parser.compile_filter(b) for b in bits[3:]]

    return BreadcrumbNode(label, url_name, url_args)


@register.simple_tag
def clear_breadcrumbs(context):
    """Clear the breadcrumbs list."""
    context["breadcrumbs"] = []
    return ""


@register.simple_tag(takes_context=True)
def nav_active(context, *url_names) -> str:
    """
    Return 'active' class if current URL matches any of the given URL names.

    Usage:
        <a href="{% url 'home' %}" class="{% nav_active 'home' %}">Home</a>
        <a href="{% url 'profile' %}" class="{% nav_active 'profile' %}">Profile</a>
        <a href="{% url 'help:index' %}" class="{% nav_active 'help:index' 'help:detail' %}">Help</a>
    """
    request = context.get("request")
    if not request:
        return ""

    for url_name in url_names:
        try:
            # For URL names that require arguments (like help:detail with slug),
            # we can't reverse them without args, so we check the namespace prefix
            if ":" in url_name:
                namespace = url_name.split(":")[0]
                # Check if current path is under this namespace
                try:
                    base_url = reverse(f"{namespace}:index")
                    if request.path.startswith(base_url):
                        return "active"
                except NoReverseMatch:
                    # Namespace has no ``:index`` route — not resolvable, so not active.
                    pass

            url = reverse(url_name)
            if request.path == url:
                return "active"
            # For nested URLs, check if current path starts with the URL
            if request.path.startswith(url) and url != "/":
                return "active"
        except NoReverseMatch:
            # This url_name doesn't reverse (needs args, or isn't registered) — skip it.
            continue

    return ""


@register.inclusion_tag("smallstack/includes/breadcrumbs.html", takes_context=True)
def render_breadcrumbs(context) -> dict[str, Any]:
    """Render the breadcrumbs trail."""
    return {
        "breadcrumbs": context.get("breadcrumbs", []),
        "request": context.get("request"),
    }


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs) -> str:
    """Build a query string merging kwargs into the current request.GET.

    Usage:
        {% querystring page=3 %}        → "?tab=recent&page=3"
        {% querystring page=page_num %} → resolves page_num from context
    """
    request = context.get("request")
    if request:
        params = request.GET.copy()
    else:
        from django.http import QueryDict

        params = QueryDict(mutable=True)
    for key, value in kwargs.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = str(value)
    qs = params.urlencode()
    return f"?{qs}" if qs else ""


@register.inclusion_tag("smallstack/includes/paginator.html", takes_context=True)
def render_paginator(context, page_obj, hx_target="#tab-content", hx_swap="innerHTML swap:150ms"):
    """Render paginator controls for a Page object.

    Usage:
        {% render_paginator page_obj %}
        {% render_paginator page_obj hx_target="#my-div" %}
    """
    request = context.get("request")
    return {
        "page_obj": page_obj,
        "request": request,
        "hx_target": hx_target,
        "hx_swap": hx_swap,
    }


@register.filter
def user_localtime(dt, request) -> datetime.datetime | None:
    """Convert a datetime to the current user's local timezone.

    Falls back to the system TIME_ZONE setting for anonymous users or
    users without a timezone preference.

    Usage:
        {% load theme_tags %}
        {{ record.created_at|user_localtime:request|date:"M d, Y H:i" }}
    """
    if dt is None:
        return None
    try:
        if request and hasattr(request, "user") and request.user.is_authenticated:
            return request.user.profile.to_local_time(dt)
    except Exception:
        # Broad by design: a template filter must never raise. Log for debugging
        # a missing profile / bad timezone, then fall back to the system tz below.
        logger.debug("user_localtime: falling back to system tz", exc_info=True)
    # Fall back to system timezone
    return dt.astimezone(zoneinfo.ZoneInfo(settings.TIME_ZONE))


@register.simple_tag(takes_context=True)
def localtime_tooltip(context, dt, fmt="M d, Y g:i A T", force_tooltip=False) -> str:
    """Render a datetime with a CSS hover tooltip showing server time and UTC.

    Uses timezone info cached on the request by TimezoneMiddleware to avoid
    per-call database queries. When the user's timezone differs from the
    server timezone, the output is wrapped in a <span class="tz-tip"> with
    a popup showing the server time and UTC.

    When timezones match, outputs plain text with no tooltip — unless
    force_tooltip=True, which always renders the tooltip (useful in data
    tables where UTC context is helpful regardless of TZ match).

    Usage:
        {% load theme_tags %}
        {% localtime_tooltip record.created_at %}
        {% localtime_tooltip record.created_at "M d, Y g:i:s A T" %}
    """
    if dt is None:
        return ""

    request = context.get("request")

    # Read cached TZ info from middleware (no DB queries)
    server_tz = getattr(request, "_tz_server", None) or zoneinfo.ZoneInfo(settings.TIME_ZONE)
    user_tz = getattr(request, "_tz_user", None) or server_tz
    tz_differs = getattr(request, "_tz_differs", False)

    user_dt = dt.astimezone(user_tz)
    user_str = dateformat.format(user_dt, fmt)

    if not tz_differs and not force_tooltip:
        return user_str

    # Build tooltip lines: server time + UTC
    utc_tz = zoneinfo.ZoneInfo("UTC")
    server_dt = dt.astimezone(server_tz)
    utc_dt = dt.astimezone(utc_tz)
    # Use a compact format for tooltip lines
    tip_fmt = "M d, Y g:i A T"
    server_str = dateformat.format(server_dt, tip_fmt)
    utc_str = dateformat.format(utc_dt, tip_fmt)
    from django.utils.html import format_html

    return format_html(
        '<span class="tz-tip" data-tz-server="{}" data-tz-utc="{}">{}</span>',
        f"Server: {server_str}",
        f"UTC: {utc_str}",
        user_str,
    )


# Map common status keywords -> semantic badge variant. Used when a call site
# passes the raw status as the label and lets the tag infer the colour.
_BADGE_VARIANTS = {"success", "warning", "error", "info", "neutral"}
_STATUS_VARIANT_MAP = {
    # success / healthy
    "pass": "success", "ok": "success", "active": "success", "success": "success",
    "up": "success", "operational": "success", "healthy": "success", "met": "success",
    "commit": "success", "enabled": "success", "yes": "success",
    # warning / degraded
    "warn": "warning", "warning": "warning", "degraded": "warning", "below": "warning",
    "pending": "warning", "partial": "warning",
    # error / failed
    "fail": "error", "failed": "error", "failure": "error", "error": "error",
    "down": "error", "revoked": "error", "breach": "error", "missing": "error",
    "disabled": "error", "no": "error",
    # neutral / informational
    "pruned": "neutral", "neutral": "neutral", "staff": "neutral", "unknown": "neutral",
    "info": "info",
}


@register.inclusion_tag("smallstack/includes/stat_card.html")
def stat_card(
    value,
    label,
    title=None,
    detail_url=None,
    detail_arg=None,
    link_url=None,
    link_arg=None,
    state=None,
    unit=None,
):
    """Render a dashboard stat card.

    Three modes, picked by which argument you pass:

    Static metric (no interaction)::

        {% stat_card value=count label="Avg Response" unit="ms" %}

    Drill-down (opens the always-present modal via htmx)::

        {% stat_card value=count label="Users" title="All Users"
                     detail_url="manage/users-stat-detail" detail_arg="total" %}

    Navigation (plain link to a full page — for content too large for a modal)::

        {% stat_card value=count label="Endpoints →" link_url="api_admin:endpoints" %}

    Args:
        value: The big number / metric.
        label: The small mono caption below the value.
        title: Modal heading (drill-down mode). Defaults to ``label``.
        detail_url: URL name of the ``hx-get`` drill-down endpoint. The endpoint
            should return a stat list (see ``render_stat_list``) or a ``<table>``.
        detail_arg: Single positional URL argument for ``detail_url``.
        link_url: URL name to navigate to (navigation mode). Mutually exclusive
            with ``detail_url`` — ``detail_url`` wins if both are given.
        link_arg: Single positional URL argument for ``link_url``.
        state: ``success`` | ``warning`` | ``danger`` | ``muted`` — drives the
            accent stripe and value color. Anything else is ignored.
        unit: Small trailing unit rendered after the value (e.g. ``ms``).

    The clickable wiring (``hx-get`` / ``hx-target`` / ``onclick``) and the modal
    include are handled for you — never hand-write them. See
    ``docs/skills/dashboard-cards.md``.
    """
    href = None
    mode = None
    if detail_url:
        href = reverse(detail_url, args=[detail_arg]) if detail_arg is not None else reverse(detail_url)
        mode = "modal"
    elif link_url:
        href = reverse(link_url, args=[link_arg]) if link_arg is not None else reverse(link_url)
        mode = "link"
    return {
        "value": value,
        "label": label,
        "title": title or label,
        "href": href,
        "mode": mode,
        "state": state if state in {"success", "warning", "danger", "muted"} else None,
        "unit": unit,
    }


@register.simple_tag
def status_badge(label, variant=None):
    """Render a consistent status pill.

    ``{% status_badge "active" %}`` -> ``<span class="badge badge-success">active</span>``
    (variant inferred from the label via ``_STATUS_VARIANT_MAP``).

    Pass ``variant`` explicitly when the label is not a known keyword — e.g.
    HTTP codes: ``{% status_badge code "warning" %}`` for a 4xx.
    """
    from django.utils.html import format_html

    label = "" if label is None else str(label)
    if variant is None:
        variant = _STATUS_VARIANT_MAP.get(label.strip().lower(), "neutral")
    variant = str(variant).lower()
    if variant not in _BADGE_VARIANTS:
        variant = "neutral"
    return format_html('<span class="badge badge-{}">{}</span>', variant, label)
