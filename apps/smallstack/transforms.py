"""Field transform system for SmallStack CRUD views.

Transforms control how field values are rendered in table cells (inline)
and optionally provide an expanded view (modal/panel loaded via HTMX).

Built-in transforms:
    "preview"   — Truncate long text with click-to-expand modal (JSON/MD/text tabs)
    "localtime" — Timezone-aware datetime with tooltip

Usage on CRUDView:
    class TicketCRUD(CRUDView):
        field_transforms = {
            "description": "preview",
            "created_at": "localtime",
            "status": ("badge", {"colors": STATUS_COLORS}),
        }

Custom transforms register via AppConfig.ready():
    from apps.smallstack.transforms import register

    class CurrencyTransform(FieldTransform):
        name = "currency"
        def inline(self, value, obj, field_name, context, symbol="$", decimals=2):
            return f"{symbol}{float(value):,.{decimals}f}"

    register(CurrencyTransform())
"""

import json
import re

from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe

# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class FieldTransform:
    """Base class for field transforms.

    Subclasses must set ``name`` and implement ``inline()``.
    Transforms with ``has_expanded = True`` also implement ``expanded()``
    and are accessible via the HTMX field-preview endpoint.
    """

    name: str = ""
    has_expanded: bool = False

    def inline(self, value, obj, field_name, context, **options):
        """Render the table-cell representation.

        Receives the *cooked* value (after choice display, boolean, null handling).
        Returns str or SafeString.
        """
        return value

    def expanded(self, raw_value, obj, field_name, context, **options):
        """Render the modal/panel content.

        Receives the *raw* attribute value (for proper JSON/markdown rendering).
        Returns a dict of template context vars.
        """
        raise NotImplementedError

    def get_expanded_template(self):
        """Template for expanded view. Override for custom layouts."""
        return "smallstack/crud/object_field_preview.html"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry: dict[str, FieldTransform] = {}


def register(transform):
    """Register a transform instance by its name."""
    _registry[transform.name] = transform


def get(name):
    """Look up a registered transform. Returns None if not found."""
    return _registry.get(name)


# ---------------------------------------------------------------------------
# Format detection and rendering helpers (moved from crud.py)
# ---------------------------------------------------------------------------


def _detect_format(text):
    """Detect whether text is JSON, Markdown, or plain text."""
    t = text.strip()
    if t and ((t[0] == "{" and t[-1] == "}") or (t[0] == "[" and t[-1] == "]")):
        try:
            json.loads(t)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass
    md_patterns = [
        r"^#{1,6}\s",
        r"^\s*[-*+]\s",
        r"\[.+\]\(.+\)",
        r"```[\s\S]*```",
        r"^\|.*\|$",
        r"\*\*.+\*\*",
        r"^>\s",
    ]
    for pattern in md_patterns:
        if re.search(pattern, t, re.MULTILINE):
            return "markdown"
    return "text"


def _render_json_preview(text):
    """Render JSON with syntax-highlighted spans, or empty string if not valid JSON."""
    t = text.strip()
    try:
        obj = json.loads(t)
        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        return ""
    escaped = escape(pretty)
    # Apply syntax spans (same CSS classes as the old JS version)
    html = re.sub(r'(&quot;(?:\\.|[^&])*?&quot;)\s*:', r'<span class="json-key">\1</span>:', escaped)
    html = re.sub(r':\s*(&quot;(?:\\.|[^&])*?&quot;)', r': <span class="json-str">\1</span>', html)
    html = re.sub(r':\s*(true|false)', r': <span class="json-bool">\1</span>', html)
    html = re.sub(r':\s*(-?\d+\.?\d*)', r': <span class="json-num">\1</span>', html)
    html = re.sub(r':\s*(null)', r': <span class="json-null">\1</span>', html)
    return mark_safe(html)


def _render_markdown_preview(text):
    """Render markdown to HTML, without TOC permalinks."""
    import markdown as md_lib

    renderer = md_lib.Markdown(
        extensions=["fenced_code", "tables", "attr_list", "md_in_html"],
    )
    return mark_safe(renderer.convert(text))


# ---------------------------------------------------------------------------
# Built-in: PreviewTransform
# ---------------------------------------------------------------------------

TRUNCATE_THRESHOLD = 50


class PreviewTransform(FieldTransform):
    """Truncate long text in list view, with click-to-expand HTMX modal.

    Options:
        threshold (int): Character threshold for truncation (default 50).
    """

    name = "preview"
    has_expanded = True

    def inline(self, value, obj, field_name, context, threshold=None, **options):
        from django.utils.safestring import SafeString

        # Link fields should not be truncated — they render as clickable links
        if options.get("is_link_field"):
            return value

        threshold = threshold or TRUNCATE_THRESHOLD

        # Only truncate plain strings, not already-safe HTML
        if not isinstance(value, str) or isinstance(value, SafeString):
            return value
        if len(value) <= threshold:
            return value

        truncated = value[:threshold].rstrip()

        # Read url_base from template context (works with real Context or dict)
        url_base = ""
        if context:
            try:
                url_base = context["url_base"]
            except (KeyError, TypeError):
                url_base = context.get("url_base", "") if isinstance(context, dict) else ""

        if url_base and hasattr(obj, "pk"):
            preview_url = reverse(
                f"{url_base}-field-preview",
                kwargs={"pk": obj.pk, "field_name": field_name},
            )
            return mark_safe(
                f'<span class="field-preview-trigger" '
                f'hx-get="{preview_url}" '
                f'hx-target="#field-preview-content" '
                f'hx-swap="innerHTML">'
                f"{escape(truncated)}"
                f'<span class="field-preview-more" title="Click to preview full content">&hellip;</span>'
                f"</span>"
            )
        return mark_safe(
            f'<span class="field-preview-trigger">'
            f"{escape(truncated)}"
            f'<span class="field-preview-more" title="Click to preview full content">&hellip;</span>'
            f"</span>"
        )

    def expanded(self, raw_value, obj, field_name, context, **options):
        if isinstance(raw_value, (dict, list)):
            raw_text = json.dumps(raw_value, ensure_ascii=False)
        else:
            raw_text = str(raw_value) if raw_value is not None else ""

        fmt = _detect_format(raw_text)
        return {
            "raw_text": raw_text,
            "detected_format": fmt,
            "json_html": _render_json_preview(raw_text),
            "markdown_html": _render_markdown_preview(raw_text),
        }


# ---------------------------------------------------------------------------
# Built-in: LocaltimeTransform
# ---------------------------------------------------------------------------


class LocaltimeTransform(FieldTransform):
    """Wrap datetime values with localtime_tooltip for timezone-aware display.

    Options:
        fmt (str): Date format string (default "M d, Y g:i A T").
    """

    name = "localtime"
    has_expanded = False

    def inline(self, value, obj, field_name, context, fmt="M d, Y g:i A T", **options):
        import datetime

        if not isinstance(value, datetime.datetime):
            return value
        if context is None:
            return value

        from .templatetags.theme_tags import localtime_tooltip

        return mark_safe(localtime_tooltip(context, value, fmt=fmt, force_tooltip=True))


# ---------------------------------------------------------------------------
# Auto-register built-ins
# ---------------------------------------------------------------------------

register(PreviewTransform())
register(LocaltimeTransform())
