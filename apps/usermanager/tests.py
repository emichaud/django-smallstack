"""Tests for the User Manager app."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )


class TestUserListView:
    """Tests for the user list page."""

    def test_requires_staff(self, client, user):
        client.login(username="testuser", password="testpass123")
        response = client.get(reverse("manage/users-list"))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-list"))
        assert response.status_code == 200

    def test_has_table_context(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-list"))
        # v0.12+ uses TableDisplay/{% crud_table %}, which renders straight
        # from object_list rather than a django-tables2 ``table`` object.
        assert "object_list" in response.context

    def test_search_filters_users(self, client, staff_user, user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-list") + "?q=testuser")
        assert response.status_code == 200
        content = response.content.decode()
        assert "testuser" in content

    def test_search_htmx_returns_partial(self, client, staff_user, user):
        client.force_login(staff_user)
        response = client.get(
            reverse("manage/users-list") + "?q=test",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "<html" not in content

    def test_uses_framework_toolbar_search(self, client, staff_user):
        """The list uses the framework's search_fields-driven toolbar (not a
        bespoke search bar), while keeping the custom dashboard stat cards."""
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-list"))
        content = response.content.decode()
        assert "list-toolbar-search-input" in content
        assert response.context["dashboard_stats"] is not None

    def test_breadcrumbs_in_title_bar(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-list"))
        content = response.content.decode()
        assert "Home" in content
        assert "Users" in content


class TestUserEditView:
    """Tests for the user edit page."""

    def test_requires_staff(self, client, user):
        client.login(username="testuser", password="testpass123")
        response = client.get(reverse("manage/users-update", kwargs={"pk": user.pk}))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user, user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-update", kwargs={"pk": user.pk}))
        assert response.status_code == 200

    def test_does_not_shadow_logged_in_user(self, client, staff_user, user):
        """Editing another user should not shadow the logged-in user context."""
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-update", kwargs={"pk": user.pk}))
        # The auth user in context should still be the staff user, not the edited user
        assert response.context["user"].username == "staffuser"


class TestUserStatDetail:
    """Tests for the stat detail drilldown endpoint."""

    def test_requires_staff(self, client, user):
        client.force_login(user)
        response = client.get(reverse("manage/users-stat-detail", kwargs={"stat_type": "total"}))
        # Uses @staff_member_required which redirects non-staff
        assert response.status_code == 302

    def test_total_returns_html(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-stat-detail", kwargs={"stat_type": "total"}))
        assert response.status_code == 200
        body = response.content.decode()
        # New list layout: each user is a row linking into their edit page.
        assert "stat-list" in body
        assert staff_user.username in body
        assert reverse("manage/users-update", kwargs={"pk": staff_user.pk}) in body


class TestTimezoneDashboardSorting:
    """Regression guard: the timezone table kept django-tables2-style column
    sorting after the tables2 removal (v0.12)."""

    def test_requires_staff(self, client, user):
        client.force_login(user)
        response = client.get(reverse("manage/users-timezones"))
        assert response.status_code == 403

    def test_default_orders_by_offset(self, client, staff_user):
        client.force_login(staff_user)
        resp = client.get(reverse("manage/users-timezones"))
        assert resp.status_code == 200
        offsets = [r["offset_hours"] for r in resp.context["sorted_rows"]]
        assert offsets == sorted(offsets)

    def test_ordering_by_user_desc(self, client, staff_user):
        client.force_login(staff_user)
        # add a second user so ordering is observable
        User.objects.create_user(username="aaa_first", email="a@example.com", password="x")
        resp = client.get(reverse("manage/users-timezones"), {"ordering": "-user"})
        usernames = [r["user"].username.lower() for r in resp.context["sorted_rows"]]
        assert usernames == sorted(usernames, reverse=True)
        user_header = next(h for h in resp.context["tz_headers"] if h["key"] == "user")
        assert user_header["direction"] == "desc"

    def test_sort_link_preserves_search_query(self, client, staff_user):
        client.force_login(staff_user)
        resp = client.get(reverse("manage/users-timezones"), {"q": "staff", "ordering": "user"})
        assert resp.status_code == 200
        # the rendered sort links must carry the active q so search survives a sort click
        assert "q=staff" in resp.content.decode()

    def test_search_form_carries_active_sort(self, client, staff_user):
        """The search form re-sends the active sort (hidden field) so an HTMX
        search keeps the current column ordering instead of resetting it."""
        client.force_login(staff_user)
        resp = client.get(reverse("manage/users-timezones"), {"ordering": "user"})
        assert '<input type="hidden" name="ordering" value="user">' in resp.content.decode()

    def test_default_sort_keeps_search_url_clean(self, client, staff_user):
        client.force_login(staff_user)
        resp = client.get(reverse("manage/users-timezones"))
        # default "offset" sort needs no hidden field — keeps search URLs clean
        assert 'name="ordering"' not in resp.content.decode()

    def test_search_request_keeps_sort_and_filters(self, client, staff_user):
        """An HTMX search that carries ?ordering= returns results both filtered
        and sorted (the round-trip the hidden field enables)."""
        client.force_login(staff_user)
        for i in range(3):
            User.objects.create_user(username=f"zsorttest_{i}", email=f"z{i}@e.com", password="x")
        resp = client.get(
            reverse("manage/users-timezones"),
            {"q": "zsorttest", "ordering": "-user"},
            HTTP_HX_REQUEST="true",
        )
        names = [r["user"].username for r in resp.context["sorted_rows"]]
        assert names == ["zsorttest_2", "zsorttest_1", "zsorttest_0"]


# ── Create with password (closes the passwordless-create blocker) ────────────
@pytest.fixture
def superuser(db):
    return User.objects.create_user(
        username="root", email="root@example.com", password="testpass123",
        is_staff=True, is_superuser=True,
    )


class TestCreateUser:
    def test_add_user_sets_a_usable_password(self, client, staff_user):
        client.force_login(staff_user)
        resp = client.post(
            reverse("manage/users-create"),
            {
                "username": "freshie", "email": "fresh@example.com", "is_active": "on",
                "password1": "Cr3ate!pass99", "password2": "Cr3ate!pass99",
            },
        )
        assert resp.status_code == 302
        u = User.objects.get(username="freshie")
        assert u.has_usable_password()
        assert u.check_password("Cr3ate!pass99")  # never passwordless

    def test_add_user_requires_a_password(self, client, staff_user):
        client.force_login(staff_user)
        resp = client.post(
            reverse("manage/users-create"), {"username": "nopw", "is_active": "on"}
        )
        assert resp.status_code == 200  # re-render with errors
        assert not User.objects.filter(username="nopw").exists()


# ── Privilege guardrails ─────────────────────────────────────────────────────
class TestGuardrails:
    def _edit(self, client, target, **extra):
        data = {"username": target.username, "email": target.email or ""}
        data.update(extra)
        return client.post(reverse("manage/users-update", kwargs={"pk": target.pk}), data)

    def test_cannot_remove_own_staff(self, client, superuser):
        client.force_login(superuser)
        resp = self._edit(client, superuser, is_active="on")  # is_staff omitted -> unchecked
        assert resp.status_code == 200  # blocked, re-render
        superuser.refresh_from_db()
        assert superuser.is_staff

    def test_cannot_deactivate_self(self, client, superuser):
        client.force_login(superuser)
        resp = self._edit(client, superuser, is_staff="on")  # is_active omitted
        assert resp.status_code == 200
        superuser.refresh_from_db()
        assert superuser.is_active

    def test_nonsuperuser_cannot_destaff_superuser(self, client, staff_user, superuser):
        client.force_login(staff_user)  # staff, not superuser
        resp = self._edit(client, superuser, is_active="on")  # try to drop is_staff
        assert resp.status_code == 200
        superuser.refresh_from_db()
        assert superuser.is_staff and superuser.is_superuser

    def test_nonsuperuser_cannot_delete_superuser(self, client, staff_user, superuser):
        client.force_login(staff_user)
        resp = client.post(reverse("manage/users-delete", kwargs={"pk": superuser.pk}))
        assert resp.status_code == 403
        assert User.objects.filter(pk=superuser.pk).exists()

    def test_superuser_can_delete_normal_user(self, client, superuser, user):
        client.force_login(superuser)
        resp = client.post(reverse("manage/users-delete", kwargs={"pk": user.pk}))
        assert resp.status_code == 302
        assert not User.objects.filter(pk=user.pk).exists()

    def test_cannot_delete_self(self, client, superuser):
        client.force_login(superuser)
        resp = client.post(reverse("manage/users-delete", kwargs={"pk": superuser.pk}))
        assert resp.status_code == 403
        assert User.objects.filter(pk=superuser.pk).exists()


# ── Edit account actions ─────────────────────────────────────────────────────
class TestAccountActions:
    def test_send_link_invites_user_without_password(self, client, staff_user):
        from django.core import mail

        invited = User.objects.create_user("pending", email="pending@example.com")
        invited.set_unusable_password()
        invited.save()
        client.force_login(staff_user)
        resp = client.post(reverse("manage/users-send-link", kwargs={"pk": invited.pk}))
        assert resp.status_code == 302
        assert len(mail.outbox) == 1
        assert "invited" in mail.outbox[0].subject.lower()

    def test_send_link_resets_user_with_password(self, client, staff_user, user):
        from django.core import mail

        client.force_login(staff_user)
        resp = client.post(reverse("manage/users-send-link", kwargs={"pk": user.pk}))
        assert resp.status_code == 302
        assert len(mail.outbox) == 1
        assert "reset" in mail.outbox[0].subject.lower()

    def test_unlock_account(self, client, staff_user, user):
        client.force_login(staff_user)
        resp = client.post(reverse("manage/users-unlock", kwargs={"pk": user.pk}))
        assert resp.status_code == 302  # clears axes lockouts, redirects back


# ── v0.11.19 template-suffix regression guard ────────────────────────────────
class TestTabbedFormRegression:
    def test_template_names_match_create_edit_form(self):
        from apps.usermanager.views import UserCRUDView

        for suffix in ("create", "edit", "form"):
            assert UserCRUDView._get_template_names(suffix) == ["accounts/user_form.html"]

    def test_edit_page_renders_the_tabbed_form(self, client, staff_user):
        client.force_login(staff_user)
        resp = client.get(reverse("manage/users-update", kwargs={"pk": staff_user.pk}))
        assert resp.status_code == 200
        # The custom tabbed form (not the generic CRUD form) must render.
        assert "user-tabs" in resp.content.decode()
