"""
Admin configuration for the custom User model.
"""

from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.http import HttpRequest

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for the custom User model.

    Only a superuser may set ``is_superuser``, groups or direct permissions
    here: for anyone else (a *User manager* holding ``change_user``) they are
    read-only, so holding ``change_user`` can't be turned into a superuser
    account, or into permissions the editor doesn't hold. Group membership
    goes through the Access pages, which check what the group grants."""

    # Explorer checks Django model permissions on accounts whatever
    # SMALLSTACK_EXPLORER_MODEL_PERMISSIONS says (an account is access).
    explorer_model_permissions = True

    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
    )

    readonly_fields = ("last_login", "date_joined")

    #: Read-only for everyone but a superuser.
    superuser_only_fields = ("is_superuser", "groups", "user_permissions")

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Any:
        fields = tuple(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            fields += tuple(f for f in self.superuser_only_fields if f not in fields)
        return fields
