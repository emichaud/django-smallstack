"""Ownership + visibility authorization matrix (permissions.py)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from apps.runbook import permissions

from ._factory import make_document, make_runbook

User = get_user_model()


@pytest.fixture
def staff(db):
    return User.objects.create_user("staff", password="p", is_staff=True)


@pytest.fixture
def owner(db):
    return User.objects.create_user("owner", password="p")


@pytest.fixture
def other(db):
    return User.objects.create_user("other", password="p")


@pytest.fixture
def rbs(db, owner):
    """One runbook of each shape: owner-private, owner-public, and system (owner-null)."""
    return {
        "private": make_runbook(name="Priv", slug="priv", owner=owner, is_public=False),
        "public": make_runbook(name="Pub", slug="pub", owner=owner, is_public=True),
        "system": make_runbook(name="Sys", slug="sys", owner=None, is_public=False),
    }


@pytest.mark.django_db
class TestCanView:
    def test_owner_sees_own_private(self, owner, rbs):
        assert permissions.can_view(owner, rbs["private"])

    def test_other_cannot_see_private(self, other, rbs):
        assert not permissions.can_view(other, rbs["private"])

    def test_signed_in_users_see_public_anon_does_not(self, other, rbs):
        assert permissions.can_view(other, rbs["public"])  # any signed-in user
        assert not permissions.can_view(AnonymousUser(), rbs["public"])  # anon: nothing (signed-in only)

    def test_staff_sees_everything(self, staff, rbs):
        assert all(permissions.can_view(staff, rb) for rb in rbs.values())

    def test_system_is_staff_only_view(self, other, rbs):
        assert not permissions.can_view(other, rbs["system"])

    def test_none_runbook_is_staff_only(self, staff, other):
        assert permissions.can_view(staff, None)
        assert not permissions.can_view(other, None)


@pytest.mark.django_db
class TestCanEdit:
    def test_owner_edits_own(self, owner, rbs):
        assert permissions.can_edit(owner, rbs["private"])
        assert permissions.can_edit(owner, rbs["public"])

    def test_other_cannot_edit_public(self, other, rbs):
        # public = readable by all, but only the owner/staff may edit
        assert permissions.can_view(other, rbs["public"])
        assert not permissions.can_edit(other, rbs["public"])

    def test_staff_edits_everything(self, staff, rbs):
        assert all(permissions.can_edit(staff, rb) for rb in rbs.values())

    def test_system_is_staff_only_edit(self, owner, other, rbs):
        assert not permissions.can_edit(owner, rbs["system"])
        assert not permissions.can_edit(other, rbs["system"])


@pytest.mark.django_db
class TestScopers:
    def test_viewable_runbooks(self, owner, other, staff, rbs):
        assert set(permissions.viewable_runbooks(owner).values_list("slug", flat=True)) == {"priv", "pub"}
        assert set(permissions.viewable_runbooks(other).values_list("slug", flat=True)) == {"pub"}
        assert permissions.viewable_runbooks(staff).count() == 3
        assert permissions.viewable_runbooks(AnonymousUser()).count() == 0  # anon: nothing (signed-in only)

    def test_viewable_documents_scopes_and_hides_detached(self, owner, other, staff, rbs):
        make_document(title="p", slug="p", runbook=rbs["private"])
        make_document(title="u", slug="u", runbook=rbs["public"])
        make_document(title="detached", slug="det", runbook=None)  # no runbook → staff-only

        assert set(permissions.viewable_documents(owner).values_list("slug", flat=True)) == {"p", "u"}
        assert set(permissions.viewable_documents(other).values_list("slug", flat=True)) == {"u"}
        # staff sees the detached doc too
        assert "det" in set(permissions.viewable_documents(staff).values_list("slug", flat=True))
        # anonymous sees nothing (public is signed-in-only)
        assert permissions.viewable_documents(AnonymousUser()).count() == 0
