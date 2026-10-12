"""Post bodies are untrusted markdown, and ``body_html`` is emitted with
``|safe``.

The shared renderer's hardening has its own unit tests. These assert the
property at the layer that actually ships: whatever a post body contains, the
HTML **persisted on the row** and served to an anonymous reader must carry no
script, no event handler and no dangerous URL scheme. Testing the renderer
alone would not catch a service path that bypassed it.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from apps.blog import service
from apps.blog.models import Post

pytestmark = pytest.mark.django_db

# Schemes the renderer's URL sanitizer allows through.
SAFE_SCHEMES = {"http", "https", "mailto", "ftp", "tel"}
# Tags that execute, load, or restyle the page.
FORBIDDEN_TAGS = {
    "script", "iframe", "object", "embed", "svg", "style", "link",
    "meta", "base", "form", "body", "html",
}


class _Collector(HTMLParser):
    """Collects the *live* tags and attributes of a rendered body.

    Substring assertions cannot do this job: the hardened renderer escapes raw
    HTML, so `<img src=x onerror=alert(1)>` is stored as
    `&lt;img src=x onerror=alert(1)&gt;` — harmless display text that still
    contains the substring "onerror". Only parsing distinguishes escaped text
    from markup the browser would act on.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str, str]] = []  # (tag, name, value)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for name, value in attrs:
            self.attrs.append((tag, name.lower(), value or ""))

    handle_startendtag = handle_starttag


def assert_html_is_inert(html: str) -> None:
    """The invariant every stored ``body_html`` must satisfy."""
    c = _Collector()
    c.feed(html)

    bad_tags = sorted(set(c.tags) & FORBIDDEN_TAGS)
    assert not bad_tags, f"live executable/structural tags rendered: {bad_tags}"

    handlers = [(t, n) for t, n, _ in c.attrs if n.startswith("on")]
    assert not handlers, f"live event-handler attributes rendered: {handlers}"

    for tag, name, value in c.attrs:
        if name not in {"href", "src", "srcset", "action", "formaction", "poster"}:
            continue
        cleaned = "".join(value.split()).replace("\x00", "")
        if ":" not in cleaned.split("/")[0]:
            continue  # relative URL or fragment — fine
        scheme = cleaned.split(":", 1)[0].lower()
        assert scheme in SAFE_SCHEMES, f"<{tag} {name}> kept a {scheme}: URL"


XSS_PAYLOADS = [
    pytest.param("<script>alert(1)</script>", id="script-tag"),
    pytest.param("<img src=x onerror=alert(1)>", id="img-onerror"),
    pytest.param("<svg/onload=alert(1)>", id="svg-onload"),
    pytest.param("<iframe src='javascript:alert(1)'></iframe>", id="iframe"),
    pytest.param("[click](javascript:alert(1))", id="javascript-href"),
    pytest.param("[click](java\tscript:alert(1))", id="tab-hidden-scheme"),
    pytest.param("[click](JaVaScRiPt:alert(1))", id="mixed-case-scheme"),
    pytest.param("![x](data:text/html;base64,PHN2Zz4=)", id="data-uri-image"),
    pytest.param('# Heading {: onclick="alert(1)"}', id="attr-list-injection"),
    pytest.param("<a href='vbscript:msgbox(1)'>x</a>", id="vbscript"),
    pytest.param("<body onload=alert(1)>", id="body-onload"),
]


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_stored_html_is_neutralized_on_create(blog, owner, payload):
    post = service.create_post(blog, title="Attack", body_markdown=payload, actor=owner)
    post.refresh_from_db()
    assert_html_is_inert(post.body_html)


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_stored_html_is_neutralized_on_update(draft, owner, payload):
    """The update path renders through the same helper — a separate code path
    is exactly where a sanitizer gets forgotten."""
    service.update_post(draft, body_markdown=payload, actor=owner)
    draft.refresh_from_db()
    assert_html_is_inert(draft.body_html)


def test_raw_html_renders_as_visible_escaped_text(blog, owner):
    """Not stripped silently — escaped, so the author can see what happened
    instead of wondering where their paragraph went."""
    post = service.create_post(
        blog, title="T", body_markdown="<script>alert(1)</script>", actor=owner
    )
    assert "&lt;script&gt;" in post.body_html


def test_fenced_code_is_single_escaped(blog, owner):
    """A double-escape bug shows up as `&amp;lt;` in a code block — the kind of
    thing only a test notices, because it still *looks* like markup."""
    post = service.create_post(
        blog, title="T", body_markdown="```\n<div>a & b</div>\n```", actor=owner
    )
    assert "&lt;div&gt;a &amp; b&lt;/div&gt;" in post.body_html
    assert "&amp;lt;" not in post.body_html


def test_legitimate_links_and_images_survive(blog, owner):
    """Hardening must not be so blunt that ordinary content breaks."""
    post = service.create_post(
        blog,
        title="T",
        body_markdown=(
            "[abs](https://example.com)\n\n[rel](/about/)\n\n"
            "[mail](mailto:a@b.test)\n\n![pic](/media/blog/covers/x.png)"
        ),
        actor=owner,
    )
    html = post.body_html
    assert 'href="https://example.com"' in html
    assert 'href="/about/"' in html
    assert 'href="mailto:a@b.test"' in html
    assert 'src="/media/blog/covers/x.png"' in html


def test_structural_markdown_renders(blog, owner):
    post = service.create_post(
        blog,
        title="T",
        body_markdown=(
            "# H1\n\n## H2\n\n- a\n- b\n\n| x | y |\n|---|---|\n| 1 | 2 |\n\n"
            "> quote\n\n**bold** and `code`"
        ),
        actor=owner,
    )
    html = post.body_html
    for fragment in ("<h1", "<h2", "<ul", "<table", "<blockquote", "<strong", "<code"):
        assert fragment in html, f"{fragment} missing"
    assert post.body_toc, "headings should produce a TOC"


def test_excerpt_derived_from_a_hostile_body_carries_no_markup(blog, owner):
    """The excerpt reaches feeds, search results and the OG description —
    places that often render it without escaping."""
    post = service.create_post(
        blog,
        title="T",
        body_markdown="<script>alert(1)</script>\n\nActual prose here.",
        actor=owner,
    )
    assert "<script" not in post.excerpt


def test_rerender_does_not_reintroduce_markup(blog, owner):
    """A re-render must pass the body through the hardened renderer again, not
    trust whatever HTML is already on the row."""
    post = service.create_post(
        blog, title="T", body_markdown="<img src=x onerror=alert(1)>", actor=owner
    )
    Post.objects.filter(pk=post.pk).update(
        body_html='<img src=x onerror="alert(1)">', html_renderer_version=0
    )
    service.rerender_posts(stale_only=True)
    post.refresh_from_db()
    assert_html_is_inert(post.body_html)


def test_an_empty_body_is_safe(blog, owner):
    post = service.create_post(blog, title="Empty", body_markdown="", actor=owner)
    assert post.body_html == ""
    assert post.excerpt == ""
