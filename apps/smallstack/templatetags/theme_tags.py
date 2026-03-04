"""
Template tags for theme functionality including breadcrumbs and navigation helpers.
"""

from django import template
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
