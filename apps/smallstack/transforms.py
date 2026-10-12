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
from collections.abc import Sequence
from typing import Any, TypedDict

import markdown
import yaml
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe
from markdown.treeprocessors import Treeprocessor

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

    def inline(self, value: Any, obj: Any, field_name: str, context: Any, **options: Any) -> Any:
        """Render the table-cell representation.

        Receives the *cooked* value (after choice display, boolean, null handling).
        Returns str or SafeString.
        """
        return value

    def expanded(self, raw_value: Any, obj: Any, field_name: str, context: Any, **options: Any) -> dict[str, Any]:
        """Render the modal/panel content.

        Receives the *raw* attribute value (for proper JSON/markdown rendering).
        Returns a dict of template context vars.
        """
        raise NotImplementedError

    def get_expanded_template(self) -> str:
        """Template for expanded view. Override for custom layouts."""
        return "smallstack/crud/object_field_preview.html"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry: dict[str, FieldTransform] = {}


def register(transform: FieldTransform) -> None:
    """Register a transform instance by its name."""
    _registry[transform.name] = transform


def get(name: str) -> FieldTransform | None:
    """Look up a registered transform. Returns None if not found."""
    return _registry.get(name)


# ---------------------------------------------------------------------------
# Format detection and rendering helpers (moved from crud.py)
# ---------------------------------------------------------------------------


def _detect_format(text: str) -> str:
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


def _render_json_preview(text: str) -> SafeString | str:
    """Render JSON with syntax-highlighted spans, or empty string if not valid JSON."""
    t = text.strip()
    try:
        obj = json.loads(t)
        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        return ""
    escaped = escape(pretty)
    # Apply syntax spans (same CSS classes as the old JS version)
    html = re.sub(r"(&quot;(?:\\.|[^&])*?&quot;)\s*:", r'<span class="json-key">\1</span>:', escaped)
    html = re.sub(r":\s*(&quot;(?:\\.|[^&])*?&quot;)", r': <span class="json-str">\1</span>', html)
    html = re.sub(r":\s*(true|false)", r': <span class="json-bool">\1</span>', html)
    html = re.sub(r":\s*(-?\d+\.?\d*)", r': <span class="json-num">\1</span>', html)
    html = re.sub(r":\s*(null)", r': <span class="json-null">\1</span>', html)
    return mark_safe(html)


# URL schemes allowed in rendered-markdown links/images. Anything else
# (``javascript:``, ``data:``, ``vbscript:`` …) is a stored-XSS vector.
_ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "ftp", "tel"}
_URL_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.\-]*):", re.IGNORECASE)


def _is_safe_url(url: str) -> bool:
    """Whether ``url`` is safe to keep as an ``href``/``src``.

    False only when it carries a scheme outside the allowlist. Whitespace and NULs
    are stripped before the scheme check because browsers ignore them inside a URL
    (``java\\tscript:`` still fires). Relative URLs and fragments (no scheme) are safe.
    """
    if not url:
        return True
    cleaned = re.sub(r"[\s\x00]+", "", url)
    match = _URL_SCHEME_RE.match(cleaned)
    return True if not match else match.group(1).lower() in _ALLOWED_URL_SCHEMES


class _SafeUrlTreeprocessor(Treeprocessor):
    """Blank ``href``/``src`` values that use a disallowed URL scheme."""

    def run(self, root):
        for el in root.iter():
            if el.tag == "a" and "href" in el.attrib and not _is_safe_url(el.attrib["href"]):
                el.set("href", "#")
            elif el.tag == "img" and "src" in el.attrib and not _is_safe_url(el.attrib["src"]):
                el.set("src", "")
        return root


def harden_markdown_renderer(renderer: "markdown.Markdown") -> "markdown.Markdown":
    """Neutralize the two stored-XSS vectors on a ``markdown.Markdown`` instance,
    in place, before ``.convert()``. Use on **any** renderer that processes
    untrusted (user- or AI-authored) content:

    1. **Raw HTML** — deregister the ``html_block`` preprocessor + ``html`` inline
       pattern, so raw ``<script>`` / ``<img onerror>`` render as escaped *text*.
       (Python-Markdown removed ``safe_mode``; this is the version-independent
       equivalent, and unlike pre-escaping it keeps fenced code single-escaped.)
    2. **Dangerous URL schemes** — a tree processor blanks ``href``/``src`` values
       using ``javascript:`` / ``data:`` / ``vbscript:`` etc.

    Extensions are the caller's responsibility: do NOT enable ``md_in_html`` (raw
    HTML) or ``attr_list`` (attribute/event-handler injection) for untrusted input.
    """
    renderer.preprocessors.deregister("html_block", strict=False)
    renderer.inlinePatterns.deregister("html", strict=False)
    renderer.treeprocessors.register(_SafeUrlTreeprocessor(renderer), "safe_urls", 5)
    return renderer


class RenderedMarkdown(TypedDict):
    """Output of :func:`render_markdown`."""

    html: str
    toc: str
    toc_tokens: list[dict]


# Structural, output-only extensions — safe for untrusted input.
_DEFAULT_MD_EXTENSIONS: tuple[str, ...] = ("fenced_code", "tables")

# Extensions that reopen a stored-XSS vector `harden_markdown_renderer` closes,
# and which it cannot defend against: `attr_list` / `legacy_attrs` let authored
# markdown set arbitrary attributes (including `onclick=`), and `md_in_html`
# restores raw-HTML passthrough. Rejected outright rather than documented,
# because the `extensions` override is otherwise an invitation to enable one.
_UNSAFE_MD_EXTENSIONS: frozenset[str] = frozenset({"attr_list", "legacy_attrs", "md_in_html"})


def render_markdown(
    content: str,
    *,
    extensions: Sequence[str] | None = None,
    toc: bool = True,
) -> RenderedMarkdown:
    """Render untrusted markdown to safe HTML, with TOC metadata.

    **The** renderer for user- and AI-authored markdown anywhere in SmallStack
    (runbook documents, blog posts, CRUD field previews). Its output is emitted
    with ``|safe``, so :func:`harden_markdown_renderer` is applied
    unconditionally: raw HTML renders as escaped *text* and dangerous URL
    schemes are blanked.

    ``extensions`` defaults to ``fenced_code`` + ``tables``. ``toc=True``
    additionally enables the ``toc`` extension with permalinks off and
    populates the ``toc`` / ``toc_tokens`` keys (ids are still emitted, so
    deep links work).

    The ``extensions`` override exists so a fork can opt into something richer
    (``codehilite``, say) and own that decision. It cannot be used to weaken
    the sanitizer: ``attr_list``, ``legacy_attrs`` and ``md_in_html`` raise
    :class:`ValueError`, because those three reopen stored-XSS vectors that
    :func:`harden_markdown_renderer` closes and *cannot* defend against —
    hardening strips raw HTML and bad URL schemes, not authored attributes.

    Raises eagerly rather than dropping them silently: a caller asking for
    ``attr_list`` should learn why it is refused, not wonder why the syntax
    does nothing. The extension list is a code constant, so this can only fire
    on a programming error, never on user input.

    Note ``apps/help/utils.py`` has its own *unhardened* renderer for bundled,
    developer-authored docs — it enables exactly these extensions on trusted
    content. Do not reach for that one on user content.
    """
    exts = list(_DEFAULT_MD_EXTENSIONS if extensions is None else extensions)
    unsafe = sorted(_UNSAFE_MD_EXTENSIONS.intersection(e for e in exts if isinstance(e, str)))
    if unsafe:
        raise ValueError(
            f"render_markdown() refuses the stored-XSS extension(s) {unsafe}: this renderer "
            "handles untrusted, user- and AI-authored markdown. If you need them for trusted "
            "developer-authored content, build your own markdown.Markdown instance."
        )
    configs: dict[str, dict[str, Any]] = {}
    if toc:
        if "toc" not in exts:
            exts.append("toc")
        configs["toc"] = {"permalink": False}

    renderer = markdown.Markdown(extensions=exts, extension_configs=configs)
    harden_markdown_renderer(renderer)
    html = renderer.convert(content)
    return {
        "html": html,
        "toc": getattr(renderer, "toc", ""),
        "toc_tokens": getattr(renderer, "toc_tokens", []),
    }


def _render_markdown_preview(text: str) -> SafeString:
    """Render untrusted markdown to safe HTML for the field-preview modal."""
    return mark_safe(render_markdown(text, toc=False)["html"])


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

_FM_KEYVAL = re.compile(r"[\w.\-]+\s*:\s*.*")
_FM_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split markdown into ``(raw_frontmatter, body)``.

    ``raw_frontmatter`` is the YAML *inside* the ``---`` fences (``""`` when
    there is none); ``body`` is everything else, stripped.

    Robust to:
      * CRLF / LF line endings and a leading BOM,
      * blank lines or a standalone image before the block — an image inserted
        at the top of a document is a common way frontmatter gets pushed below
        the first line (and then renders as body text). Anything skipped this
        way is kept in ``body``.

    Only a ``---`` fenced block whose every line is ``key: value`` counts as
    frontmatter, so genuine ``---`` thematic breaks with prose between them are
    left alone. That check is why this is not ``text.split("---", 2)``.
    """
    if text.startswith("\ufeff"):
        text = text[1:]

    lines = text.splitlines(keepends=True)
    i = 0
    # Skip leading blank lines and standalone images (kept in the body).
    while i < len(lines) and (not lines[i].strip() or _FM_IMAGE.fullmatch(lines[i].strip())):
        i += 1

    if i < len(lines) and lines[i].strip() == "---":
        j = i + 1
        while j < len(lines) and lines[j].strip() != "---":
            j += 1
        if j < len(lines):  # found the closing fence
            block = [ln.strip() for ln in lines[i + 1:j] if ln.strip()]
            if block and all(_FM_KEYVAL.fullmatch(ln) for ln in block):
                body = "".join(lines[:i] + lines[j + 1:]).strip()
                return "".join(lines[i + 1:j]), body

    return "", text.strip()


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse leading YAML frontmatter, returning ``(metadata, body)``.

    ``metadata`` is ``{}`` when there is no frontmatter or the block does not
    parse as a YAML mapping — malformed frontmatter must never cost us the
    document body, so parse errors degrade to "no metadata" rather than raising.
    """
    raw, body = split_frontmatter(text)
    if not raw:
        return {}, body
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}, body
    return (loaded, body) if isinstance(loaded, dict) else ({}, body)


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

    def inline(
        self, value: Any, obj: Any, field_name: str, context: Any, threshold: int | None = None, **options: Any,
    ) -> Any:
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

    def expanded(self, raw_value: Any, obj: Any, field_name: str, context: Any, **options: Any) -> dict[str, Any]:
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

    def inline(
        self, value: Any, obj: Any, field_name: str, context: Any, fmt: str = "M d, Y g:i A T", **options: Any,
    ) -> Any:
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
