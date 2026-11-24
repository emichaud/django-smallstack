"""Access events in Django admin: readable, never editable (evidence)."""

from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group
from django.http import HttpRequest

from .models import AccessEvent, AccessReview, AccessReviewItem, DirectoryIdentity, EvidenceBundle, ManagedGroup


@admin.register(AccessEvent)
class AccessEventAdmin(admin.ModelAdmin):
    list_display = ("at", "kind", "actor_label", "subject_label", "group_label", "permission", "source")
    list_filter = ("kind",)
    search_fields = ("actor_label", "subject_label", "group_label", "permission", "request_id")
    date_hierarchy = "at"
    readonly_fields = [f.name for f in AccessEvent._meta.fields]
    # Evidence: Explorer checks model permissions here whatever the site setting.
    explorer_model_permissions = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(ManagedGroup)
class ManagedGroupAdmin(admin.ModelAdmin):
    list_display = ("group", "app_label", "directory_role", "grants_staff", "description", "synced_at")
    readonly_fields = (
        "group",
        "app_label",
        "description",
        "declared_permissions",
        "directory_role",
        "grants_staff",
        "synced_at",
    )
    explorer_model_permissions = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """The row is the group's declaration as code keeps it: deleting it
        would make a directory-managed group local without a trace (G4-5).
        ``sync_groups`` maintains it; remove the declaration in code instead."""
        return False


@admin.register(DirectoryIdentity)
class DirectoryIdentityAdmin(admin.ModelAdmin):
    """Written by the sign-in sync only; readable here as evidence."""

    list_display = ("provider", "subject", "user", "email", "last_seen_at")
    list_filter = ("provider",)
    search_fields = ("subject", "email", "display_name", "user__username")
    readonly_fields = [f.name for f in DirectoryIdentity._meta.fields]
    explorer_model_permissions = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class _ReviewItemInline(admin.TabularInline):
    model = AccessReviewItem
    extra = 0
    can_delete = False
    readonly_fields = ("user_label", "decision", "decided_by_label", "decided_at", "note", "follow_up")
    fields = readonly_fields

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(AccessReview)
class AccessReviewAdmin(admin.ModelAdmin):
    """Evidence: opened, decided and signed on the Access pages; read here."""

    list_display = ("__str__", "status", "opened_via", "opened_by_label", "signed_by_label", "signed_at")
    list_filter = ("status", "scope", "opened_via")
    readonly_fields = [f.name for f in AccessReview._meta.fields]
    inlines = [_ReviewItemInline]
    explorer_model_permissions = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(EvidenceBundle)
class EvidenceBundleAdmin(admin.ModelAdmin):
    """Stored evidence packs: built by the schedule or on request, downloaded
    from the Evidence page; read here, removed only by retention."""

    list_display = ("__str__", "reason", "built_by_label", "size", "sha256")
    list_filter = ("scope", "reason")
    readonly_fields = [f.name for f in EvidenceBundle._meta.fields]
    explorer_model_permissions = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class GroupAdmin(BaseGroupAdmin):
    """Django's group admin, except a directory-managed group opens read-only
    and can't be deleted (G2-3): renaming it, clearing its permissions or
    deleting it (which strips its members) would undo the directory's
    membership as a local edit to it would. ``SMALLSTACK_DIRECTORY_LOCAL_OVERRIDE``
    lifts it, as it does on every other surface."""

    def _directory_managed(self, obj: Any) -> bool:
        from .services import directory_refusal

        return obj is not None and bool(directory_refusal(obj))

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if self._directory_managed(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if self._directory_managed(obj):
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset: Any) -> None:
        """*Delete selected* skips directory-managed groups."""
        from django.contrib import messages

        keep = [g.pk for g in queryset if self._directory_managed(g)]
        super().delete_queryset(request, queryset.exclude(pk__in=keep))
        if keep:
            self.message_user(
                request, f"Kept {len(keep)} directory-managed group(s): change them in the directory.", messages.WARNING
            )


if admin.site.is_registered(Group):
    admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)
