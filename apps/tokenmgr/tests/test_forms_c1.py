"""Minting a staff-level token for a non-staff user is refused (audit 2026-09-13, C1)."""

import pytest

from apps.tokenmgr.forms import TokenCreateForm

pytestmark = pytest.mark.django_db


def test_staff_cannot_mint_staff_level_token_for_non_staff_user(django_user_model):
    from django.contrib.auth.models import Permission

    staffer = django_user_model.objects.create_user(username="s", password="x", is_staff=True)
    # Minting for someone else needs add_apitoken (G1-1).
    staffer.user_permissions.add(Permission.objects.get(codename="add_apitoken"))
    staffer = django_user_model.objects.get(pk=staffer.pk)
    bob = django_user_model.objects.create_user(username="bob", password="x")
    form = TokenCreateForm(data={"name": "t", "user": bob.pk, "access_level": "staff"}, request_user=staffer)
    assert not form.is_valid()
    assert "access_level" in form.errors

    ok = TokenCreateForm(data={"name": "t", "user": bob.pk, "access_level": "readonly"}, request_user=staffer)
    assert ok.is_valid(), ok.errors
