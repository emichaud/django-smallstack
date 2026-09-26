"""Scenario B URLs. No ``app_name`` — CRUDView uses bare URL names."""

from __future__ import annotations

from .views import AgentActionCRUDView

urlpatterns = [
    *AgentActionCRUDView.get_urls(),
]
