"""
Register Django's built-in LogEntry model in admin for browsing audit logs.

This gives you a read-only activity log at /admin/admin/logentry/ showing
all actions recorded by Django admin and by log_action().
"""

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry

from .models import APIToken

#: A token's owner and level are set when it is made and never change: whoever
#: holds the key would otherwise act as the new owner (a staff account
#: reassigning its own token to a superuser would become one), or with the new
#: level (a Token manager raising their own token to ``auth``, which only a
#: superuser may mint).
TOKEN_FIELDS_FIXED_ON_CHANGE = ("user", "access_level")


def may_change_token_state(actor, token) -> bool:
    """Only a superuser revokes (or re-activates) a superuser's token; the
    model's change permission covers every other token."""
    owner = getattr(token, "user", None) if token is not None and token.pk else None
    return not (owner is not None and owner.is_superuser and not getattr(actor, "is_superuser", False))


class APITokenExplorerForm(forms.ModelForm):
    """Explorer's token form: the owner is chosen on create and read-only after."""

    class Meta:
        model = APIToken
        fields = ["name", "user", "token_type", "access_level", "is_active"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            for name in TOKEN_FIELDS_FIXED_ON_CHANGE:
                # A disabled field ignores what is posted and keeps the stored value.
                self.fields[name].disabled = True
                self.fields[name].help_text = "Set when the token is made; it can't be changed afterwards."
            if user is None or not may_change_token_state(user, self.instance):
                self.fields["is_active"].disabled = True
                self.fields["is_active"].help_text = "Only a superuser may revoke a superuser's token."


@admin.register(APIToken)
class APITokenAdmin(admin.ModelAdmin):
    """Browse + revoke API tokens. Exposed via Explorer for non-admin staff."""

    list_display = [
        "name",
        "user",
        "token_type",
        "access_level",
        "created_at",
        "last_used_at",
        "is_active",
    ]
    list_filter = ["token_type", "access_level", "is_active"]
    search_fields = ["name", "user__username", "prefix"]
    readonly_fields = [
        "prefix",
        "hashed_key",
        "created_at",
        "last_used_at",
        "revoked_at",
        "request_count",
    ]
    actions = ["revoke_tokens"]

    # Explorer integration: surfaces APIToken under the "Auth" group so the
    # MCP consent page can deep-link users here for token management.
    explorer_enabled = True
    explorer_group = "Auth"
    explorer_list_fields = ("name", "user", "token_type", "access_level", "is_active")
    explorer_form_class = APITokenExplorerForm
    # Who holds a token decides what it can do: always ask Django's model
    # permissions, whatever SMALLSTACK_EXPLORER_MODEL_PERMISSIONS says.
    explorer_model_permissions = True

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields += [f for f in TOKEN_FIELDS_FIXED_ON_CHANGE if f not in fields]
            if not may_change_token_state(getattr(request, "user", None), obj) and "is_active" not in fields:
                fields.append("is_active")
        return fields

    @admin.action(description="Revoke selected tokens", permissions=["change"])
    def revoke_tokens(self, request, queryset):
        """Revoke the selected live tokens (needs ``change_apitoken``); a
        superuser's are skipped unless a superuser runs it. Each revoke is
        recorded as a ``token_revoked`` access event."""
        count = skipped = 0
        for token in queryset.filter(is_active=True).select_related("user"):
            if not may_change_token_state(request.user, token):
                skipped += 1
                continue
            token.revoke()
            count += 1
        self.message_user(request, f"Revoked {count} token(s).", level=messages.SUCCESS)
        if skipped:
            self.message_user(
                request, f"Skipped {skipped} superuser token(s): only a superuser may revoke those.", messages.WARNING
            )


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ["action_time", "user", "content_type", "object_repr", "action_flag", "change_message"]
    list_filter = ["action_flag", "content_type", "user"]
    search_fields = ["object_repr", "change_message"]
    date_hierarchy = "action_time"

    # The change history is evidence: Explorer always asks Django's model
    # permissions for it, and never edits or deletes it (has_*_permission below).
    explorer_model_permissions = True

    # Explorer overrides: drop change_message + object_repr, widen the timestamp.
    explorer_list_fields = ("action_time", "user", "content_type", "action_flag")
    explorer_column_widths = {
        "action_time": "240px",  # the local date and time in full
        "action_flag": "120px",
    }
    readonly_fields = [
        "action_time",
        "user",
        "content_type",
        "object_id",
        "object_repr",
        "action_flag",
        "change_message",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
