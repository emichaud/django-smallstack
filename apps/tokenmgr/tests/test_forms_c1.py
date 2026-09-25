"""Minting a staff-level token for a non-staff user is refused (audit 2026-09-13, C1)."""

import pytest

from apps.tokenmgr.forms import TokenCreateForm

pytestmark = pytest.mark.django_db


def test_staff_cannot_mint_staff_level_token_for_non_staff_user(django_user_model):
    staffer = django_user_model.objects.create_user(username="s", password="x", is_staff=True)
    bob = django_user_model.objects.create_user(username="bob", password="x")
    form = TokenCreateForm(data={"name": "t", "user": bob.pk, "access_level": "staff"}, request_user=staffer)
    assert not form.is_valid()
    assert "access_level" in form.errors

    ok = TokenCreateForm(data={"name": "t", "user": bob.pk, "access_level": "readonly"}, request_user=staffer)
    assert ok.is_valid(), ok.errors
