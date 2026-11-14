"""Tests for the website app: the home page and the public-site chrome."""

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
