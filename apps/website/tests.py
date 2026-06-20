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

    The page is open to everyone — including anonymous visitors. The
    registry's per-view access gate determines what each visitor can
    find. Help docs are visible to everyone; CRUDViews default to
    staff-only and must opt in to broader access (see
    apps/smallstack/docs/search.md).
    """

    def test_anonymous_can_load_the_page(self, client):
        """Anonymous visitors can load /search/ — the page is public."""
        response = client.get("/search/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Find" in content
        assert "anything" in content

    def test_anonymous_sees_no_staff_or_authenticated_sources(self, client):
        """Anonymous visitors only see ANONYMOUS-level CRUDViews (none by
        default) plus the help docs. No User / APIToken / etc. leakage."""
        response = client.get("/search/")
        sources = response.context["indexed_sources"]
        # No model-kind sources (User + APIToken default to STAFF).
        model_sources = [s for s in sources if s["kind"] == "model"]
        assert model_sources == []

    def test_authenticated_empty_query_renders_editorial_layout(self, client, django_user_model):
        """Authenticated GET with no query renders the editorial shell."""
        user = django_user_model.objects.create_user(username="searcher", password="testpass")
        client.force_login(user)
        response = client.get("/search/")
        assert response.status_code == 200
        content = response.content.decode()
        # Editorial design tells — "Find anything" serif moment renders.
        assert "Find" in content
        assert "anything" in content
        # No results section without a query.
        assert response.context["total_hits"] == 0
        assert response.context["grouped"] == []

    def test_non_staff_user_does_not_see_staff_only_sources(self, client, django_user_model):
        """Security: non-staff users see the page, but staff-only models
        (User, APIToken — the default) are hidden from the sources panel."""
        user = django_user_model.objects.create_user(username="non_staff_user", password="testpass")
        client.force_login(user)
        response = client.get("/search/")
        assert response.status_code == 200
        # No model-kind sources reach the page for a non-staff user.
        sources = response.context["indexed_sources"]
        model_sources = [s for s in sources if s["kind"] == "model"]
        assert model_sources == []

    def test_staff_user_sees_staff_only_sources(self, client, django_user_model):
        """Security: staff users see all registered sources, including the
        default staff-only ones (User, APIToken)."""
        staff = django_user_model.objects.create_user(
            username="staff_searcher", password="testpass", is_staff=True
        )
        client.force_login(staff)
        response = client.get("/search/")
        assert response.status_code == 200
        sources = response.context["indexed_sources"]
        # At least the User CRUDView is registered by default and visible to staff.
        assert any(s["kind"] == "model" for s in sources)

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

    def test_nav_link_is_visible_to_everyone(self, client, django_user_model):
        """The Search link is in the website topbar for every visitor — the
        page is open to anonymous users (who can search help docs) and to
        signed-in users (who additionally see whatever they're permitted)."""
        # Anonymous — link present.
        response = client.get("/")
        assert 'href="/search/"' in response.content.decode()

        # Authenticated — link still present.
        user = django_user_model.objects.create_user(username="navtest", password="testpass")
        client.force_login(user)
        response = client.get("/")
        assert 'href="/search/"' in response.content.decode()
