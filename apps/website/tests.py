"""Tests for the website app views."""

import pytest


@pytest.mark.starter_content
@pytest.mark.django_db
class TestWebsiteViews:
    """Smoke tests for all website views."""

    def test_home_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"SmallStack" in response.content

    def test_home_page_hero(self, client):
        """Hero tagline + four-shapes framing should render."""
        response = client.get("/")
        content = response.content.decode()
        assert "batteries-included" in content
        assert "scheduler systems" in content
        assert "MCP servers" in content

    def test_home_page_pipeline_section(self, client):
        """The model-to-three-surfaces pipeline is the page's centerpiece."""
        response = client.get("/")
        content = response.content.decode()
        assert "One model" in content
        assert "Three surfaces" in content
        assert "TicketCRUDView" in content
        assert "enable_mcp" in content

    def test_home_page_batteries_grid(self, client):
        """Batteries-included grid should name the built-in apps."""
        response = client.get("/")
        content = response.content.decode()
        assert "Explorer" in content
        assert "MCP admin" in content
        assert "Activity" in content
        assert "API Tokens" in content
        assert "Backups" in content

    def test_home_page_doc_links_for_anon(self, client):
        """Anonymous visitors get doc-page links into the smallstack help section."""
        response = client.get("/")
        content = response.content.decode()
        # Anon users see help-page deep links rather than live admin URLs.
        assert "/smallstack/help/smallstack/mcp-first-app/" in content
        assert "/smallstack/help/smallstack/building-crud-pages/" in content
        assert "/smallstack/help/smallstack/api-documentation/" in content

    def test_about_page(self, client):
        response = client.get("/about/")
        assert response.status_code == 200

    def test_getting_started_page(self, client):
        response = client.get("/getting-started/")
        assert response.status_code == 200

    def test_starter_page(self, client):
        response = client.get("/starter/")
        assert response.status_code == 200

    def test_starter_basic_page(self, client):
        response = client.get("/starter/basic/")
        assert response.status_code == 200

    def test_starter_forms_page(self, client):
        response = client.get("/starter/forms/")
        assert response.status_code == 200

    def test_components_redirects(self, client):
        response = client.get("/components/")
        assert response.status_code == 302
        assert "/help/" in response.url


@pytest.mark.starter_content
@pytest.mark.django_db
class TestHomePageAuthenticated:
    """Home page adapts to auth + staff state."""

    @pytest.fixture
    def staff_user(self, django_user_model):
        return django_user_model.objects.create_user(username="staff", password="testpass", is_staff=True)

    def test_staff_sees_live_app_links(self, client, staff_user):
        """Staff users get live links into the built-in admin apps."""
        client.force_login(staff_user)
        response = client.get("/")
        content = response.content.decode()
        # Live admin URLs (vs the doc deep-links shown to anonymous visitors).
        assert "/smallstack/explorer/" in content
        assert "/smallstack/mcp/" in content
        assert "/smallstack/activity/" in content
        assert "/smallstack/tokens/" in content
        assert "/smallstack/backups/" in content
        # Staff get the Dashboard CTA.
        assert "Open Dashboard" in content

    def test_anonymous_sees_signup_cta(self, client):
        """Anonymous users get the Sign Up CTA, not Dashboard."""
        response = client.get("/")
        content = response.content.decode()
        assert "Get Started" in content
        assert "Open Dashboard" not in content

    def test_regular_user_sees_anon_style_links(self, client, django_user_model):
        """Non-staff authed users get the same doc-page links as anonymous."""
        user = django_user_model.objects.create_user(username="regular", password="testpass")
        client.force_login(user)
        response = client.get("/")
        content = response.content.decode()
        # No live admin links for non-staff (the example URL in the code
        # block is a span, not an anchor — match the href shape).
        assert 'href="/smallstack/explorer/"' not in content
        assert 'href="/smallstack/tokens/"' not in content
        # But doc deep-links are present.
        assert "/smallstack/help/smallstack/explorer/" in content


@pytest.mark.django_db
class TestPublicSearchView:
    """Public-site /search/ (editorial "Find anything" design).

    Auth-gated by @login_required. Reuses apps.search registry for data.
    """

    def test_anonymous_redirects_to_login(self, client):
        """Anonymous visitors are bounced to /accounts/login/?next=/search/."""
        response = client.get("/search/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url
        assert "next=/search/" in response.url

    def test_authenticated_empty_query_renders_editorial_layout(self, client, django_user_model):
        """Authenticated GET with no query renders the editorial shell."""
        user = django_user_model.objects.create_user(username="searcher", password="testpass")
        client.force_login(user)
        response = client.get("/search/")
        assert response.status_code == 200
        content = response.content.decode()
        # Editorial design tells — "Find anything" serif moment + indexed sources panel.
        assert "Find" in content
        assert "anything" in content
        assert "Indexed" in content  # the "Indexed sources" label
        # No results section without a query.
        assert response.context["total_hits"] == 0
        assert response.context["grouped"] == []

    def test_authenticated_with_query_renders_results_shape(self, client, django_user_model):
        """A query renders the results-with-shape context.

        We assert the view's contract (status + context keys + grouped
        shape), not the search backend's recall — the latter depends on
        FTS index state that is exercised in apps/search/tests/.
        """
        user = django_user_model.objects.create_user(username="searcher2", password="testpass")
        client.force_login(user)
        response = client.get("/search/?q=admin")
        assert response.status_code == 200
        ctx = response.context
        assert ctx["query"] == "admin"
        assert "total_hits" in ctx
        assert "grouped" in ctx
        assert isinstance(ctx["grouped"], list)
        # Each grouped entry (if any) carries the documented shape.
        for group in ctx["grouped"]:
            assert "model_label" in group
            assert "model_verbose" in group
            assert "count" in group
            assert "hits" in group

    def test_authenticated_with_no_match_renders_empty_state(self, client, django_user_model):
        """A query with no matches renders the no-results state without crashing."""
        user = django_user_model.objects.create_user(username="searcher3", password="testpass")
        client.force_login(user)
        response = client.get("/search/?q=zzzzzznotfounditem")
        assert response.status_code == 200
        assert response.context["total_hits"] == 0
        assert response.context["grouped"] == []
        # No-results display copy.
        assert "Nothing matched" in response.content.decode()

    def test_nav_link_visible_only_when_authenticated(self, client, django_user_model):
        """The Search link in the website topbar is gated by user.is_authenticated."""
        # Anonymous — no link.
        response = client.get("/")
        assert 'href="/search/"' not in response.content.decode()

        # Authenticated — link present.
        user = django_user_model.objects.create_user(username="navtest", password="testpass")
        client.force_login(user)
        response = client.get("/")
        assert 'href="/search/"' in response.content.decode()
