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
