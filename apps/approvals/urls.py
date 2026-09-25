"""Approvals URLs.

No ``app_name`` — this app hosts a CRUDView, and CRUDView's internal reverses
use bare names (scheduler/webhooks precedent; see building-crud-pages.md).
Action + custom API routes are registered BEFORE the CRUD splat.
"""

from __future__ import annotations

from django.urls import path

from . import api, views

urlpatterns = [
    path("approvals/requests/<int:pk>/decide/", views.decide_request, name="approvals_decide"),
    path("approvals/requests/<int:pk>/cancel/", views.cancel_request, name="approvals_cancel"),
    # Custom REST (create + decide) — before the CRUD splat, runbook-style.
    path("api/approvals/requests/create/", api.api_create_request, name="approvals-requests-api-create"),
    path("api/approvals/requests/<int:pk>/decide/", api.api_decide_request, name="approvals-requests-api-decide"),
    *views.ApprovalRequestCRUDView.get_urls(),
]
