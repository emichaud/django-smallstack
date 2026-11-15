"""
Admin configuration for the custom User model.
"""

from typing import Any

from django.contrib import admin
from django.contrib.admin.utils import unquote
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from .forms import UserExplorerForm
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for the custom User model.

    Only a superuser may set ``is_superuser``, groups or direct permissions
    here: for anyone else (a *User manager* holding ``change_user``) they are
    read-only, so holding ``change_user`` can't be turned into a superuser
    account, or into permissions the editor doesn't hold. Group membership
    goes through the Access pages, which check what the group grants.

    Another account's password, username and email decide who can sign in as
    it, so they follow the subset rule
    (:func:`apps.access.services.sign_in_refusal`): the password form refuses
    with the reason, and the two fields are read-only, for an editor who
    lacks any permission the account holds."""

    # Explorer checks Django model permissions on accounts whatever
    # SMALLSTACK_EXPLORER_MODEL_PERMISSIONS says (an account is access).
    explorer_model_permissions = True
    # Explorer's edit form locks the username and email the same way.
    explorer_form_class = UserExplorerForm

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
        if obj is not None and obj.pk is not None:
            from apps.access.services import SIGN_IN_FIELDS, sign_in_refusal

            if sign_in_refusal(request.user, obj):
                fields += tuple(f for f in SIGN_IN_FIELDS if f not in fields)
        return fields

    def user_change_password(self, request: HttpRequest, id: str, form_url: str = "") -> HttpResponse:
        """Django's set-password form, refused (with the reason) when the
        editor lacks a permission the account holds."""
        from apps.access.services import sign_in_refusal

        target = self.get_object(request, unquote(id))
        if target is not None:
            refusal = sign_in_refusal(request.user, target)
            if refusal:
                raise PermissionDenied(refusal)
        return super().user_change_password(request, id, form_url)
