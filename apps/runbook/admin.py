"""Admin registration for Runbook models."""

from django.contrib import admin

from .models import Document, DocumentImage, DocumentVersion, Runbook, Section, Subscription


@admin.register(Runbook)
class RunbookAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "owner", "is_public", "is_template", "updated_at"]
    list_filter = ["is_public", "is_template", "owner"]
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ["name"]
    raw_id_fields = ["owner"]


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ["name", "runbook", "slug", "order", "created_at"]
    list_filter = ["runbook"]
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ["name"]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = [
        "title", "runbook", "section", "key", "version",
        "is_template", "is_generated", "is_archived", "updated_at",
    ]
    list_filter = ["file_type", "is_template", "is_generated", "is_archived", "section__runbook", "section"]
    search_fields = ["title", "key", "description"]
    raw_id_fields = ["runbook", "section", "current_version", "created_by"]


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ["__str__", "document", "version", "file_type", "created_by", "created_at"]
    list_filter = ["file_type", "created_at"]
    search_fields = ["title", "description"]
    raw_id_fields = ["document", "created_by"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["document", "subscriber", "created_at"]
    raw_id_fields = ["document", "subscriber"]


@admin.register(DocumentImage)
class DocumentImageAdmin(admin.ModelAdmin):
    list_display = ["__str__", "document", "alt", "uploaded_by", "created_at"]
    list_filter = ["created_at"]
    raw_id_fields = ["document", "uploaded_by"]
