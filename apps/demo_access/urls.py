"""Scenario C URLs. No ``app_name`` — CRUDView uses bare URL names.

The custom REST route is registered BEFORE the CRUD splat (runbook/approvals
precedent), so ``api/demo/access/requests/file/`` isn't shadowed by the
generated ``api/demo/access/requests/<pk>/`` detail route.
"""

from __future__ import annotations

from django.urls import path

from . import api, views

urlpatterns = [
    path(
        "api/demo/access/requests/file/",
        api.api_file_access_request,
        name="demo-access-requests-api-file",
    ),
    *views.AccessRequestCRUDView.get_urls(),
    *views.WebhookEchoCRUDView.get_urls(),
]
