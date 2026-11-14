"""Audit logging — the failure/no-op discipline of log_write + AuditMixin.

log_write must NEVER raise (audit must not break the write it records) and must
no-op without a real acting user. These are the security-relevant paths that
were previously uncovered (F4).
"""

from __future__ import annotations

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from apps.smallstack import audit
from apps.smallstack.audit import AuditMixin, log_write

pytestmark = pytest.mark.django_db


def _user():
    return get_user_model().objects.create_user(username="auditor", password="pw")


def test_log_write_creates_entry_with_source_label():
    user = _user()
    entry = log_write(user, user, CHANGE, source="REST API")
    assert entry is not None
    assert LogEntry.objects.filter(pk=entry.pk).exists()
    assert entry.change_message == "via REST API"


def test_log_write_noops_without_a_real_user():
    user = _user()
    before = LogEntry.objects.count()
    # AnonymousUser (pk is None) → no audit row, no error.
    assert log_write(AnonymousUser(), user, CHANGE, source="MCP") is None
    assert LogEntry.objects.count() == before


def test_log_write_never_raises_when_logging_fails(monkeypatch):
    user = _user()

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(audit, "log_action", _boom)
    # Must swallow the error and return None — the write it records must survive.
    assert log_write(user, user, CHANGE, source="REST API") is None


def test_audit_message_reflects_changed_fields():
    class _Form:
        changed_data = ["status", "priority"]

    class _EmptyForm:
        changed_data = []

    mixin = AuditMixin()
    assert mixin.get_audit_message(_Form()) == "Changed status, priority."
    assert mixin.get_audit_message(_EmptyForm()) == ""
