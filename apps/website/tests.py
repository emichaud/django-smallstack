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
        """Hero frames SmallStack as a platform to build on, not a starter."""
        response = client.get("/")
        content = response.content.decode()
        assert "platform" in content
        assert "to build apps on" in content
        assert "already built" in content
        # The "what you can build" shapes name the platform roles.
        assert "MCP servers" in content
        assert "Integration hubs" in content
        assert "Workflow apps" in content
        assert "Publishing" in content

    def test_home_page_pipeline_section(self, client):
        """The model-to-every-surface pipeline is the page's centerpiece."""
        response = client.get("/")
        content = response.content.decode()
        assert "One model" in content
        assert "Every surface" in content
        assert "TicketCRUDView" in content
        assert "enable_mcp" in content
        assert "enable_search" in content
        assert "enable_webhooks" in content
        # Feeds are a publishing surface (curated Feed), not a CRUDView flag.
        assert "enable_rss" not in content

    def test_home_page_batteries_grid(self, client):
        """Batteries-included grid should name the built-in apps — including
        the platform apps added since 0.13 (scheduler, webhooks, approvals,
        notifications, runbook, blog)."""
        response = client.get("/")
        content = response.content.decode()
        for name in [
            "Explorer",
            "Runbook",
            "Blog &amp; newsletter",
            "Approvals",
            "Notifications",
            "Scheduler",
            "Webhooks",
            "Logs",
            "MCP admin",
            "Activity",
            "API tokens",
            "Backups",
        ]:
            assert name in content, name

    def test_home_page_platform_seams(self, client):
        """The 'build on it' section lists the hooks the shipped apps use."""
        response = client.get("/")
        content = response.content.decode()
        for seam in [
            "nav.register()",
            "dashboard.register()",
            "@scheduled",
            "@approval_kind",
            "notify()",
            "@webhook_handler",
            "@dataset",
        ]:
            assert seam in content, seam

    def test_home_page_doc_links_for_anon(self, client):
        """Anonymous visitors get doc-page links into the smallstack help section."""
        response = client.get("/")
        content = response.content.decode()
        # Anon users see help-page deep links rather than live admin URLs.
        assert "/smallstack/help/smallstack/mcp-first-app/" in content
        assert "/smallstack/help/smallstack/building-crud-pages/" in content
        assert "/smallstack/help/smallstack/api-documentation/" in content
        # The newer platform apps deep-link into their help pages too.
        assert "/smallstack/help/smallstack/approvals/" in content
        assert "/smallstack/help/smallstack/scheduler/" in content
        assert "/smallstack/help/smallstack/webhooks/" in content
        assert "/smallstack/help/blog/" in content
        assert "/smallstack/help/runbook/getting-started/" in content
        # ...and never the live admin URLs.
        assert 'href="/smallstack/approvals/requests/"' not in content
        assert 'href="/smallstack/blog/posts/"' not in content

    def test_about_page(self, client):
        response = client.get("/about/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "platform to build applications on" in content
        # The features deck covers the platform apps, not just the 0.9-era ones.
        for title in [
            "One model, every surface",
            "Webhooks",
            "Approvals &amp; notifications",
            "Runbook, blog, newsletter &amp; feeds",
        ]:
            assert title in content, title

    def test_getting_started_page(self, client):
        response = client.get("/getting-started/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Six palettes" in content
        assert "Every surface" in content
        # Step 06 — the platform apps and their feature flags.
        assert "SMALLSTACK_APPROVALS_ENABLED" in content
        assert "SMALLSTACK_BLOG_ENABLED" in content
        assert "/smallstack/help/smallstack/approvals/" in content
        assert "/smallstack/help/blog/" in content

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
        # The platform apps added since 0.13 get live links too.
        assert 'href="/smallstack/runbook/"' in content
        assert 'href="/smallstack/blog/posts/"' in content
        assert 'href="/smallstack/approvals/requests/"' in content
        assert 'href="/smallstack/notifications/"' in content
        assert 'href="/smallstack/scheduler/"' in content
        assert 'href="/smallstack/webhooks/"' in content
        assert 'href="/smallstack/logs/"' in content
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
        assert 'href="/smallstack/approvals/requests/"' not in content
        # But doc deep-links are present.
        assert "/smallstack/help/smallstack/explorer/" in content
        assert "/smallstack/help/smallstack/approvals/" in content


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
        default) plus the help docs. No User / APIToken / etc. leakage.

        Assertion is "the specific STAFF/AUTH-tier bundled sources are
        hidden" rather than "no model sources visible at all" — round-4
        audit A1 — so the test survives downstream projects that register
        their own ANON-tier CRUDViews per ``building-a-user-facing-site.md``.
        """
        response = client.get("/search/")
        sources = response.context["indexed_sources"]
        model_labels = {s["model_label"] for s in sources if s["kind"] == "model"}
        # Bundled STAFF-tier opt-ins must not leak to anonymous visitors.
        assert "accounts.User" not in model_labels
        assert "smallstack.APIToken" not in model_labels

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
        (User, APIToken — the default) are hidden from the sources panel.

        Assertion is "the specific bundled STAFF-tier sources are hidden"
        rather than "no model sources visible at all" — round-4 audit A1
        — so the test survives downstream projects that register their own
        AUTH-tier CRUDViews per ``building-a-user-facing-site.md``.
        """
        user = django_user_model.objects.create_user(username="non_staff_user", password="testpass")
        client.force_login(user)
        response = client.get("/search/")
        assert response.status_code == 200
        sources = response.context["indexed_sources"]
        model_labels = {s["model_label"] for s in sources if s["kind"] == "model"}
        # Bundled STAFF-tier opt-ins must not leak to non-staff users.
        assert "accounts.User" not in model_labels
        assert "smallstack.APIToken" not in model_labels

    def test_staff_user_sees_staff_only_sources(self, client, django_user_model):
        """Security: staff users see all registered sources, including the
        default staff-only ones (User, APIToken)."""
        staff = django_user_model.objects.create_user(username="staff_searcher", password="testpass", is_staff=True)
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

    def test_empty_page_teaches_the_search_builder_shape(self, client):
        """The empty-query page shows the "Shape a result" panel: the
        transform_hit recipe plus a rendered example of the article card, so
        the custom shape is visible even on an install with no posts."""
        response = client.get("/search/")
        content = response.content.decode()
        assert "Shape" in content
        assert "transform_hit" in content
        assert "get_search_variants" in content
        assert 'class="result-card"' in content
        assert "search_blog_posts_compact" in content

    def test_search_builder_hit_renders_as_an_article_card(self, client, django_user_model):
        """A published post in a public blog is a SearchBuilder-shaped hit:
        the page renders the article card (blog byline, reading time, tags)
        instead of the default title/snippet row."""
        from apps.blog import service
        from apps.blog.models import Blog
        from apps.search.backends import get_backend
        from apps.search.registry import all_views

        owner = django_user_model.objects.create_user(username="writer", password="testpass")
        blog = Blog.objects.create(
            owner=owner, name="Field Notes", slug="field-notes", visibility=Blog.Visibility.PUBLIC
        )
        post = service.create_post(
            blog,
            title="Zanzibar quartets and quartz",
            body_markdown="A zanzibar essay.",
            excerpt="On timekeeping.",
            tags=["horology"],
            author=owner,
        )
        service.publish_post(post)
        for view in all_views():
            if view.model_label == "smallstack_blog.Post":
                get_backend().rebuild(view)

        response = client.get("/search/?q=zanzibar")
        assert response.status_code == 200
        content = response.content.decode()
        # The card, not the row, for this hit…
        assert 'class="result-card"' in content
        assert "Zanzibar quartets and quartz" in content
        assert "Field Notes" in content
        assert "min read" in content
        assert "horology" in content
        # …and the hit itself carries the shape for REST / MCP consumers.
        hits = [h for g in response.context["grouped"] for h in g["hits"] if g["model_label"] == "smallstack_blog.Post"]
        assert hits and hits[0].extra["card"] == "article"

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
