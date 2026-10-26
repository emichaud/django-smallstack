"""Bundled dataset for feeds: items collected from external RSS/Atom sources."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.datasets.framework import framework_dataset

from .models import CollectedItem


@framework_dataset(
    "smallstack_collected_items",
    label="Collected feed items",
    description=(
        "Items pulled from registered external feeds: source, title, link, author, when it was published "
        "and when we fetched it."
    ),
    columns=["source", "title", "link", "author", "published", "fetched_at", "guid"],
    filterable=["source", "title", "author", "published", "fetched_at"],
)
def collected_items() -> QuerySet[CollectedItem]:
    return CollectedItem.objects.all()
