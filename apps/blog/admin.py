"""Django-admin registrations.

Thin on purpose: the authoring surface is the themed console at
/smallstack/blog/, and these exist so the Model Explorer can discover the
models and so staff have a raw escape hatch. Business rules live in
``apps.blog.service`` — editing here bypasses them.
"""

from __future__ import annotations

from django.contrib import admin

from .models import Blog, Delivery, Issue, Post, Subscriber, Subscription, Tag


@admin.register(Blog)
class BlogAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "visibility", "owner", "newsletter_enabled", "updated_at")
    list_filter = ("visibility", "newsletter_enabled")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("owner",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "blog", "slug")
    list_filter = ("blog",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "blog", "status", "author", "published_at", "updated_at")
    list_filter = ("status", "blog", "is_featured")
    search_fields = ("title", "slug", "excerpt", "body_markdown")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("blog", "author", "tags", "source_document")
    readonly_fields = ("uid", "body_html", "body_toc", "html_renderer_version", "source_synced_at")
    date_hierarchy = "published_at"


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "is_suppressed", "bounce_count", "consecutive_failures")
    list_filter = ("is_suppressed",)
    search_fields = ("email", "name")
    readonly_fields = ("bounce_count", "consecutive_failures", "last_failure_at")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("subscriber", "blog", "status", "source", "confirmed_at")
    list_filter = ("status", "blog", "source")
    search_fields = ("subscriber__email",)
    autocomplete_fields = ("subscriber", "blog")


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ("subject", "blog", "status", "recipient_count", "sent_count", "finished_at")
    list_filter = ("status", "blog")
    search_fields = ("subject",)
    autocomplete_fields = ("blog", "post")
    readonly_fields = ("uid", "body_html", "queued_at", "started_at", "finished_at")


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ("email", "issue", "status", "attempts", "sent_at")
    list_filter = ("status",)
    search_fields = ("email",)
    readonly_fields = ("issue", "subscriber", "email", "attempts", "claimed_at", "sent_at")
