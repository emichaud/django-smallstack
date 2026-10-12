"""AppConfig for the blog + newsletter app."""

from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger("smallstack.blog")


class BlogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.blog"
    # Common-noun label, namespaced per house style (smallstack_runbook,
    # smallstack_approvals, smallstack_notifications). Final before 0001 —
    # the label is baked into migration state AND into CRUD template paths
    # (templates live under templates/smallstack_blog/crud/, not blog/crud/).
    label = "smallstack_blog"
    verbose_name = "Blog"

    # Surfaces apps/blog/content/*.md in the help app at /help/blog/.
    help_content_dir = "content"
    help_section_slug = "blog"
    help_section_title = "Blog"

    def ready(self) -> None:
        if not getattr(settings, "SMALLSTACK_BLOG_ENABLED", True):
            return
        try:
            from . import receivers

            receivers.connect()
        except ImportError:
            pass  # runbook not installed — the bridge is optional
        except Exception:  # noqa: BLE001
            logger.warning("blog: receiver wiring failed", exc_info=True)

        self._register_surfaces()

    def _register_surfaces(self) -> None:
        """Nav registrations — each isolated so one failure can't block
        startup (approvals/scheduler exemplar)."""
        try:
            from apps.smallstack.navigation import nav

            icon = (
                '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                '<path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2z'
                'm-2 4H7V5h10v2zm0 4H7V9h10v2zm-3 4H7v-2h7v2z"/></svg>'
            )
            # The author's studio, beside Runbook in the main section. Any
            # signed-in user can own a blog, so no staff gate.
            nav.register(
                section="main",
                label="My blogs",
                url_name="myblogs:dashboard",
                icon_svg=icon,
                auth_required=True,
                order=6,
                active_prefix="/my/blogs/",
            )
            # Staff entry in the alphabetised `admin` section. NB: `order` is
            # ignored there (ALPHABETICAL_SECTIONS) — don't bother tuning it.
            nav.register(
                section="admin",
                label="Blog",
                url_name="blog/posts-list",
                icon_svg=icon,
                staff_required=True,
                active_prefix="/smallstack/blog/",
            )
            # The console is LoginRequired + ownership-scoped, so a non-staff
            # author can use it — but the ADMIN section is staff-only in the
            # sidebar template, which would leave her with no nav entry and no
            # way back to her drafts. Registered separately and hidden from
            # staff so they don't see "Blog" twice. (Mirrors approvals F-46.)
            nav.register(
                section="app",
                label="Blog",
                url_name="blog/posts-list",
                icon_svg=icon,
                auth_required=True,
                visible=lambda request: not getattr(
                    getattr(request, "user", None), "is_staff", False
                ),
                active_prefix="/smallstack/blog/",
                order=6,
            )
        except Exception:  # noqa: BLE001
            logger.warning("blog: nav registration failed", exc_info=True)

        try:
            from apps.smallstack import dashboard

            from .dashboard_widgets import BlogDashboardWidget

            dashboard.register(BlogDashboardWidget())
        except ImportError:
            pass  # dashboard surface not installed — optional
        except Exception:  # noqa: BLE001
            logger.warning("blog: dashboard widget registration failed", exc_info=True)

        try:
            from apps.smallstack import monitors

            from .monitors import BlogService, NewsletterSendMonitor, ScheduledPostsMonitor

            monitors.register_service(BlogService())
            monitors.register_monitor(ScheduledPostsMonitor())
            monitors.register_monitor(NewsletterSendMonitor())
        except ImportError:
            pass  # status surface not installed — optional
        except Exception:  # noqa: BLE001
            logger.warning("blog: status monitor registration failed", exc_info=True)

        try:
            from apps.feeds import register_feed

            from .feeds import LatestPostsFeed

            # The site-wide river at /feed/blog.rss. Per-blog feeds are built
            # per request instead — blogs are created at runtime and the
            # registry is a static slug map populated here, at startup.
            register_feed(LatestPostsFeed())
        except ImportError:
            pass  # feeds app not installed — optional
        except Exception:  # noqa: BLE001
            logger.warning("blog: feed registration failed", exc_info=True)
