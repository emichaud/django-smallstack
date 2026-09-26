"""Scenario A URLs.

No ``app_name``: this module hosts a CRUDView and CRUDView's internal reverses
use bare names (docs/skills/crud-views.md "URL namespaces"). Action + custom
routes are registered BEFORE the CRUD splat.
"""

from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path(
        "demo/purchasing/requests/<int:pk>/review/",
        views.PurchaseRequestReviewView.as_view(),
        name="demo_purchasing_review",
    ),
    path(
        "demo/purchasing/requests/<int:pk>/submit/",
        views.submit_purchase_request,
        name="demo_purchasing_submit",
    ),
    *views.PurchaseRequestCRUDView.get_urls(),
]
