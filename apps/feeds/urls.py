"""Feed URLs — mounted at ``/feed/`` in config/urls.py.

``/feed/<slug>.rss``  → RSS 2.0
``/feed/<slug>.atom`` → Atom 1.0
"""

from __future__ import annotations

from django.urls import path, register_converter

from . import views


class FeedFormatConverter:
    """Matches the ``rss`` / ``atom`` suffix so ``<slug>`` can contain dashes."""

    regex = "rss|atom"

    def to_python(self, value: str) -> str:
        return value

    def to_url(self, value: str) -> str:
        return value


register_converter(FeedFormatConverter, "feedfmt")

app_name = "feeds"

urlpatterns = [
    path("<slug:slug>.<feedfmt:fmt>", views.feed_view, name="feed"),
]
