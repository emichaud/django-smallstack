"""Console URLs, mounted under ``/smallstack/`` by apps/smallstack/site_urls.py.

No ``app_name``: this module hosts CRUDViews, whose internal reverses use bare
route names (the scheduler / webhooks / approvals precedent). The public
reading surface is a separate module with its own namespace, so the two sets of
names cannot collide.

Action routes are registered **before** the CRUD splat, or ``posts/preview/``
would be swallowed by ``posts/<pk>/``.
"""

from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    # Markdown preview for the editor (htmx). Before the splat.
    path("blog/posts/preview/", views.post_preview, name="blog_post_preview"),
    # Lifecycle actions — POST only, ownership-checked, service-backed.
    path("blog/posts/<int:pk>/publish/", views.post_publish, name="blog_post_publish"),
    path("blog/posts/<int:pk>/unpublish/", views.post_unpublish, name="blog_post_unpublish"),
    path("blog/posts/<int:pk>/schedule/", views.post_schedule, name="blog_post_schedule"),
    path("blog/posts/<int:pk>/archive/", views.post_archive, name="blog_post_archive"),
    path("blog/posts/<int:pk>/resync/", views.post_resync, name="blog_post_resync"),
    # Publish a runbook document into a blog. On the blog side by design —
    # runbook stays unaware the blog exists.
    path("blog/import-runbook/", views.runbook_import, name="blog_runbook_import"),
    # Newsletter issue actions — POST only, ownership-checked, service-backed.
    path("blog/posts/<int:pk>/newsletter/", views.post_send_newsletter, name="blog_post_newsletter"),
    path("blog/issues/<int:pk>/queue/", views.issue_queue, name="blog_issue_queue"),
    path("blog/issues/<int:pk>/cancel/", views.issue_cancel, name="blog_issue_cancel"),
    path("blog/issues/<int:pk>/test/", views.issue_test, name="blog_issue_test"),
    path("blog/issues/<int:pk>/retry/", views.issue_retry, name="blog_issue_retry"),
    *views.BlogCRUDView.get_urls(),
    *views.PostCRUDView.get_urls(),
    *views.TagCRUDView.get_urls(),
    *views.SubscriptionCRUDView.get_urls(),
    *views.SubscriberCRUDView.get_urls(),
    *views.IssueCRUDView.get_urls(),
    *views.DeliveryCRUDView.get_urls(),
]
