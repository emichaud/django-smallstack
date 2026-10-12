"""The MINOR/NOTE findings from the integration harness's blog programme.

Each fails against the code before its fix.

* **A-enum** — the login redirect was an existence oracle: a members blog
  answered 302 while an unused slug answered 404, so internal blog names were
  enumerable without an account.
* **N3** — an explicit ``https://`` in ``SITE_URL`` was silently downgraded to
  ``http://`` unless ``USE_HTTPS`` was also set, so newsletters carried
  ``http://`` unsubscribe links.
* **N6** — ``sync="auto"`` is honoured by *enqueuing* a resync, so with no
  worker the post silently serves stale text, and nothing reported it.
* **N7** — ``p`` is a fixed URL segment (the post shortlink) that was missing
  from ``RESERVED_BLOG_SLUGS``.
* **N8** — ``canonical_url`` reached an ``href`` unfiltered. Not reachable
  through a user-facing surface (``URLValidator`` blocks it there), but the
  service layer does not ``full_clean()``.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, override_settings

from apps.accounts.emails import site_base_url
from apps.blog import service
from apps.blog.models import Blog, Post, validate_unreserved_slug

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def owner():
    return User.objects.create_user(username="minor-owner", password="x")


@pytest.fixture
def members_blog(owner):
    return service.create_blog(
        name="Members", slug="members-blog", owner=owner, visibility=Blog.Visibility.MEMBERS
    )


# ---------------------------------------------------------------------------
# A-enum — the login redirect must not be an existence oracle
# ---------------------------------------------------------------------------
def test_anonymous_gets_one_answer_for_everything_it_cannot_read(owner, members_blog):
    """All three tiers must be indistinguishable, not just two.

    The first attempt at this fix made the *absent* case redirect like a
    members blog and left private blogs on 404 — which moved the oracle onto
    the more sensitive tier instead of removing it. Hence all three here.
    """
    service.create_blog(
        name="Priv", slug="priv-blog", owner=owner, visibility=Blog.Visibility.PRIVATE
    )
    anon = Client()
    answers = {
        "members": anon.get(f"/blog/{members_blog.slug}/"),
        "private": anon.get("/blog/priv-blog/"),
        "absent": anon.get("/blog/no-such-blog-at-all/"),
    }

    codes = {name: r.status_code for name, r in answers.items()}
    assert len(set(codes.values())) == 1, f"anonymous responses differ by tier: {codes}"
    assert codes["members"] == 302
    for name, response in answers.items():
        assert "/login" in response["Location"], name


def test_a_public_blog_is_unaffected(owner):
    """Guards against over-correcting: public reading must still work."""
    service.create_blog(
        name="Pub", slug="pub-blog", owner=owner, visibility=Blog.Visibility.PUBLIC
    )
    assert Client().get("/blog/pub-blog/").status_code == 200


def test_a_signed_in_visitor_still_gets_an_honest_404(members_blog):
    """The ambiguity is confined to the audience it protects against."""
    reader = User.objects.create_user(username="reader", password="x")
    c = Client()
    c.force_login(reader)

    assert c.get(f"/blog/{members_blog.slug}/").status_code == 200
    assert c.get("/blog/definitely-not-here/").status_code == 404


# ---------------------------------------------------------------------------
# N3 — an explicit scheme wins over the USE_HTTPS default
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            dict(SITE_DOMAIN="n.example.com", SITE_URL="https://n.example.com", USE_HTTPS=False),
            "https://n.example.com",
        ),
        (
            dict(SITE_DOMAIN="n.example.com", SITE_URL="https://n.example.com", USE_HTTPS=True),
            "https://n.example.com",
        ),
        (dict(SITE_DOMAIN="n.example.com", SITE_URL="", USE_HTTPS=False), "http://n.example.com"),
        (
            dict(SITE_DOMAIN="n.example.com", SITE_URL="http://n.example.com", USE_HTTPS=False),
            "http://n.example.com",
        ),
        # A stale SITE_URL naming a DIFFERENT host must not upgrade the scheme.
        (
            dict(
                SITE_DOMAIN="n.example.com", SITE_URL="https://other.example.com", USE_HTTPS=False
            ),
            "http://n.example.com",
        ),
        (
            dict(SITE_DOMAIN="localhost:8000", SITE_URL="https://n.example.com", USE_HTTPS=False),
            "https://n.example.com",
        ),
    ],
)
def test_site_base_url_scheme_resolution(kwargs, expected):
    with override_settings(**kwargs):
        assert site_base_url() == expected


# ---------------------------------------------------------------------------
# N7 — "p" is reserved
# ---------------------------------------------------------------------------
def test_the_shortlink_prefix_is_a_reserved_blog_slug():
    with pytest.raises(ValidationError):
        validate_unreserved_slug("p")


def test_reserved_set_covers_every_fixed_segment_that_can_be_a_slug():
    """Guards the set against drifting behind the URLConf it defends."""
    import re

    from django.core.validators import validate_slug

    from apps.blog.models import RESERVED_BLOG_SLUGS

    source = open("apps/blog/public_urls.py").read()
    fixed = set(re.findall(r'path\(\s*["\']([a-z0-9][a-z0-9\-_.]*)', source))
    fixed = {f.split("/")[0] for f in fixed if "<" not in f}

    for segment in fixed:
        try:
            validate_slug(segment)
        except ValidationError:
            continue  # cannot be a slug (dots), so cannot collide
        assert segment in RESERVED_BLOG_SLUGS, (
            f"{segment!r} is a fixed URL segment and a valid slug, but is not reserved"
        )


# ---------------------------------------------------------------------------
# N8 — canonical_url is scheme-filtered where it is rendered
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("https://example.com/x", "https://example.com/x"),
        ("http://example.com/x", "http://example.com/x"),
        ("/relative/path/", "/relative/path/"),
        ("", ""),
        ("javascript:alert(1)", ""),
        ("JavaScript:alert(1)", ""),
        ("data:text/html,<script>alert(1)</script>", ""),
        ("vbscript:msgbox(1)", ""),
    ],
)
def test_safe_canonical_url_filters_dangerous_schemes(owner, stored, expected):
    blog = service.create_blog(
        name="Canon", slug="canon-blog", owner=owner, visibility=Blog.Visibility.PUBLIC
    )
    post = service.create_post(blog, title="C", body_markdown="b", actor=owner)
    # Written the way only a trusted internal caller can: the service does not
    # full_clean(), which is the gap this property covers.
    Post.objects.filter(pk=post.pk).update(canonical_url=stored)
    post.refresh_from_db()

    assert post.safe_canonical_url == expected


def test_a_dangerous_canonical_url_never_reaches_the_rendered_page(owner):
    blog = service.create_blog(
        name="Canon2", slug="canon2-blog", owner=owner, visibility=Blog.Visibility.PUBLIC
    )
    post = service.create_post(blog, title="C2", body_markdown="b", actor=owner)
    service.publish_post(post, actor=owner)
    Post.objects.filter(pk=post.pk).update(canonical_url="javascript:alert(1)")

    html = Client().get(post.get_absolute_url()).content.decode()

    assert "javascript:alert(1)" not in html


# ---------------------------------------------------------------------------
# N6 — a stalled auto-sync is visible on /smallstack/status/
# ---------------------------------------------------------------------------
def test_auto_sync_monitor_reports_posts_behind_their_document(owner):
    """With no worker, an auto-synced post serves stale text and said nothing."""
    from apps.blog.monitors import AutoSyncMonitor
    from apps.runbook import service as rb

    blog = service.create_blog(
        name="Sync", slug="sync-blog", owner=owner, visibility=Blog.Visibility.PUBLIC
    )
    book = rb.create_runbook("sync-book", name="Sync Book", owner=owner)
    doc = rb.create_document(book, body="v1 body\n", title="Doc", key="sd", actor=owner)
    post = service.publish_document(doc, blog, status=Post.Status.DRAFT, sync="auto", actor=owner)

    assert AutoSyncMonitor().check().ok is True
    assert service.stale_autosync_count() == 0

    # The document moves on; the queued resync never runs (no worker here).
    rb.write_version(doc, body="v2 body\n", actor=owner)
    Post.objects.filter(pk=post.pk).update(source_version=0)

    assert service.stale_autosync_count() == 1
    result = AutoSyncMonitor().check()
    assert result.ok is False
    assert "db_worker" in result.note


def test_auto_sync_monitor_ignores_manual_posts(owner):
    """`sync="manual"` is *supposed* to drift — it must not raise an alarm."""
    from apps.blog.monitors import AutoSyncMonitor
    from apps.runbook import service as rb

    blog = service.create_blog(
        name="Sync2", slug="sync2-blog", owner=owner, visibility=Blog.Visibility.PUBLIC
    )
    book = rb.create_runbook("sync2-book", name="Sync2 Book", owner=owner)
    doc = rb.create_document(book, body="v1\n", title="Doc2", key="sd2", actor=owner)
    post = service.publish_document(
        doc, blog, status=Post.Status.DRAFT, sync="manual", actor=owner
    )
    rb.write_version(doc, body="v2\n", actor=owner)
    Post.objects.filter(pk=post.pk).update(source_version=0)

    assert service.stale_autosync_count() == 0
    assert AutoSyncMonitor().check().ok is True
