"""Publish-side tests — curated feeds, rendering, access gating, enclosures,
and the removal of the one-flag model feed."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, RequestFactory

from apps.feeds.base import Feed, FeedItem
from apps.feeds.models import CollectedItem
from apps.feeds.registry import register_feed, unregister
from apps.feeds.render import render_feed
from apps.search.access import SearchAccess

pytestmark = pytest.mark.django_db


def _mk(title: str, when: datetime) -> CollectedItem:
    return CollectedItem.objects.create(
        source="t", guid=f"g-{title}", title=title, summary=f"about {title}", published=when
    )


class _CollectedFeed(Feed):
    """A curated feed over the bundled CollectedItem model — the shape every
    published feed takes now that the model-feed shortcut is gone."""

    slug = "collected-items"
    title = "Collected"
    access = SearchAccess.STAFF

    def items(self, request):
        for obj in CollectedItem.objects.order_by("-published", "-pk")[:50]:
            yield FeedItem(
                title=obj.title,
                link=f"/collected/{obj.pk}/",
                unique_id=f"feeds.CollectedItem:{obj.pk}",
                description=obj.summary,
                pubdate=obj.published,
                extra_kwargs={"categories": ("news",)},
            )


def test_curated_feed_items_and_ordering():
    _mk("older", datetime(2021, 1, 1, tzinfo=timezone.utc))
    _mk("newer", datetime(2022, 1, 1, tzinfo=timezone.utc))
    items = list(_CollectedFeed().items(RequestFactory().get("/")))
    assert [i.title for i in items] == ["newer", "older"]
    assert items[0].description == "about newer"
    assert items[0].unique_id == f"feeds.CollectedItem:{CollectedItem.objects.get(title='newer').pk}"
    assert items[0].extra_kwargs == {"categories": ("news",)}


def test_render_produces_rss_and_atom():
    _mk("hello", datetime(2022, 1, 1, tzinfo=timezone.utc))
    req = RequestFactory(HTTP_HOST="testserver").get("/feed/collected-items.rss")
    rss, ct_rss = render_feed(_CollectedFeed(), req, "rss")
    atom, ct_atom = render_feed(_CollectedFeed(), req, "atom")
    assert "rss+xml" in ct_rss and "<rss" in rss and "hello" in rss
    assert "atom+xml" in ct_atom and "<feed" in atom


# --- the one-flag model feed is gone --------------------------------------------


def test_the_model_feed_module_is_gone():
    with pytest.raises(ImportError):
        import apps.feeds.model_feed  # noqa: F401


def test_crudview_has_no_rss_attributes():
    from apps.smallstack.crud import CRUDView

    for name in ("enable_rss", "rss_slug", "rss_access", "rss_item_extra"):
        assert not hasattr(CRUDView, name), name


@pytest.mark.parametrize(
    "attrs",
    [
        {"enable_rss": True},
        {"enable_rss": False},  # even "off" — the attribute itself is the stale copy
        {"rss_slug": "things"},
        {"rss_item_extra": lambda self, obj: {}},
    ],
)
def test_declaring_a_removed_rss_attribute_fails_at_import(attrs):
    """A downstream that still carries the old flag must fail loudly at startup,
    not silently lose its feed (or worse, keep serving an unscoped one)."""
    from apps.smallstack.crud import CRUDView

    with pytest.raises(ImproperlyConfigured, match="removed in SmallStack 0.25.1"):
        type("StaleRssView", (CRUDView,), {"model": CollectedItem, **attrs})


def test_a_plain_crudview_still_registers():
    from apps.smallstack.crud import CRUDView

    cls = type("PlainView", (CRUDView,), {"model": CollectedItem, "url_base": "plain-feed-test"})
    assert cls.model is CollectedItem


# --- access gating through the HTTP view -------------------------------------


class _PublicFeed(Feed):
    slug = "t-public"
    title = "Public"
    access = SearchAccess.ANONYMOUS

    def items(self, request):
        return [FeedItem(title="hi", link="/x", unique_id="1")]


class _StaffFeed(Feed):
    slug = "t-staff"
    title = "Staff"
    access = SearchAccess.STAFF

    def items(self, request):
        return [FeedItem(title="secret", link="/y", unique_id="2")]


@pytest.fixture
def _feeds():
    register_feed(_PublicFeed())
    register_feed(_StaffFeed())
    yield
    unregister("t-public")
    unregister("t-staff")


def test_anonymous_feed_is_public(_feeds):
    resp = Client().get("/feed/t-public.rss")
    assert resp.status_code == 200
    assert "rss+xml" in resp["Content-Type"]


def test_staff_feed_401s_for_anonymous(_feeds):
    resp = Client().get("/feed/t-staff.rss")
    assert resp.status_code == 401
    assert resp["WWW-Authenticate"].startswith("Bearer")


def test_staff_feed_served_to_staff_session(_feeds, django_user_model):
    django_user_model.objects.create_user(username="boss", password="pw", is_staff=True)
    client = Client()
    client.login(username="boss", password="pw")
    assert client.get("/feed/t-staff.rss").status_code == 200


def test_unknown_feed_404s():
    assert Client().get("/feed/does-not-exist.rss").status_code == 404


def test_public_feed_404s_when_feeds_disabled(_feeds, settings):
    """Master switch off ⇒ the whole request surface 404s, even a public feed."""
    settings.SMALLSTACK_FEEDS_ENABLED = False
    assert Client().get("/feed/t-public.rss").status_code == 404


# --- enclosure / podcast seam (Django 6 dropped the singular `enclosure=`) ----


class _EnclosureFeed(Feed):
    """Emits one item carrying an enclosure via extra_kwargs (either key form)."""

    slug = "t-enclosure"
    title = "Enclosure"
    access = SearchAccess.ANONYMOUS

    def __init__(self, extra):
        self._extra = extra

    def items(self, request):
        return [FeedItem(title="ep", link="/e", unique_id="e1", extra_kwargs=self._extra)]


@pytest.mark.parametrize("key", ["enclosure", "enclosures"])
def test_enclosure_renders_for_singular_and_plural(key):
    from django.utils.feedgenerator import Enclosure

    enc = Enclosure("https://example.com/e.mp3", "1024", "audio/mpeg")
    extra = {"enclosure": enc} if key == "enclosure" else {"enclosures": [enc]}
    feed = _EnclosureFeed(extra)
    req = RequestFactory(HTTP_HOST="testserver").get("/feed/t-enclosure.rss")
    rss, _ = render_feed(feed, req, "rss")
    assert "<enclosure" in rss
    assert 'url="https://example.com/e.mp3"' in rss
