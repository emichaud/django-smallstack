"""
Template tags for theme functionality including breadcrumbs, navigation helpers,
and timezone conversion.
"""

import zoneinfo

from django import template
from django.conf import settings
from django.urls import reverse

register = template.Library()


class BreadcrumbNode(template.Node):
    """Node for rendering a breadcrumb item."""

    def __init__(self, label, url_name=None, url_args=None):
        self.label = label
        self.url_name = url_name
        self.url_args = url_args or []

    def render(self, context):
        # Resolve label if it's a variable
        try:
            label = template.Variable(self.label).resolve(context)
        except template.VariableDoesNotExist:
            label = self.label.strip("\"'")

        # Get or create breadcrumbs list in context
        if "breadcrumbs" not in context:
            context["breadcrumbs"] = []

        breadcrumb = {"label": label, "url": None}

        # Resolve URL if provided
        if self.url_name:
            try:
                url_name = template.Variable(self.url_name).resolve(context)
            except template.VariableDoesNotExist:
                url_name = self.url_name.strip("\"'")

            # Resolve URL args
            resolved_args = []
            for arg in self.url_args:
                try:
                    resolved_args.append(template.Variable(arg).resolve(context))
                except template.VariableDoesNotExist:
                    resolved_args.append(arg.strip("\"'"))

            try:
                breadcrumb["url"] = reverse(url_name, args=resolved_args) if resolved_args else reverse(url_name)
            except Exception:
                breadcrumb["url"] = None

        context["breadcrumbs"].append(breadcrumb)
        return ""


@register.tag
def breadcrumb(parser, token):
    """
    Add a breadcrumb item to the breadcrumb trail.

    Usage:
        {% breadcrumb "Home" "home" %}
        {% breadcrumb "Profile" "profile" %}
        {% breadcrumb "Edit" %}  {# No URL for current page #}
        {% breadcrumb "User" "profile_detail" username %}  {# With URL args #}
    """
    bits = token.split_contents()
    tag_name = bits[0]

    if len(bits) < 2:
        raise template.TemplateSyntaxError(f"'{tag_name}' tag requires at least a label argument")

    label = bits[1]
    url_name = bits[2] if len(bits) > 2 else None
    url_args = bits[3:] if len(bits) > 3 else []

    return BreadcrumbNode(label, url_name, url_args)


@register.simple_tag
def clear_breadcrumbs(context):
    """Clear the breadcrumbs list."""
    context["breadcrumbs"] = []
    return ""


@register.simple_tag(takes_context=True)
def nav_active(context, *url_names):
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
                except Exception:
                    pass

            url = reverse(url_name)
            if request.path == url:
                return "active"
            # For nested URLs, check if current path starts with the URL
            if request.path.startswith(url) and url != "/":
                return "active"
        except Exception:
            pass

    return ""


@register.inclusion_tag("smallstack/includes/breadcrumbs.html", takes_context=True)
def render_breadcrumbs(context):
    """Render the breadcrumbs trail."""
    return {
        "breadcrumbs": context.get("breadcrumbs", []),
        "request": context.get("request"),
    }


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
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
def render_paginator(context, page_obj, hx_target="#tab-content", hx_swap="innerHTML"):
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
def user_localtime(dt, request):
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
        pass
    # Fall back to system timezone
    return dt.astimezone(zoneinfo.ZoneInfo(settings.TIME_ZONE))
