"""Explorer registration for Runbook models (optional SmallStack integration)."""

try:
    from django.contrib import admin

    from apps.explorer.registry import explorer

    from .models import Document, DocumentVersion, Runbook, Section

    class RunbookExplorerAdmin(admin.ModelAdmin):
        list_display = ["name", "slug", "is_template", "created_at", "updated_at"]
        explorer_fields = ["name", "slug", "description", "icon", "is_template"]
        explorer_group = "Runbook"

    class SectionExplorerAdmin(admin.ModelAdmin):
        list_display = ["name", "runbook", "slug", "order", "created_at"]
        explorer_fields = ["name", "runbook", "slug", "description", "icon", "order"]
        explorer_group = "Runbook"

    class DocumentExplorerAdmin(admin.ModelAdmin):
        list_display = ["title", "runbook", "section", "key", "version", "is_generated", "updated_at"]
        explorer_fields = [
            "title", "slug", "runbook", "section", "key", "file_type",
            "description", "version", "is_generated", "is_archived",
        ]
        explorer_group = "Runbook"
        explorer_readonly = True

    class DocumentVersionExplorerAdmin(admin.ModelAdmin):
        list_display = ["document", "version", "file_type", "created_by", "created_at"]
        explorer_fields = ["document", "version", "file_type", "description", "source", "via"]
        explorer_group = "Runbook"
        explorer_readonly = True

    explorer.register(Runbook, RunbookExplorerAdmin)
    explorer.register(Section, SectionExplorerAdmin)
    explorer.register(Document, DocumentExplorerAdmin)
    explorer.register(DocumentVersion, DocumentVersionExplorerAdmin)

except ImportError:
    pass  # Explorer app not available — skip registration
