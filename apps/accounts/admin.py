"""
Admin configuration for the custom User model.
"""

from typing import Any

from django import forms
from django.contrib import admin
from django.contrib.admin.utils import unquote
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from .forms import UserExplorerForm
from .models import User


def _is_superuser(user: Any) -> bool:
    return bool(getattr(user, "is_superuser", False) and getattr(user, "is_active", False))


def _delete_refusal(actor: Any, target: Any, queryset: Any = None) -> str:
    """The User Manager's delete guards, or "" when ``actor`` may delete ``target``."""
    if getattr(actor, "pk", None) == target.pk:
        return "You cannot delete your own account."
    if target.is_superuser and not _is_superuser(actor):
        return "Only a superuser can delete a superuser account."
    if target.is_superuser and target.is_active:
        others = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target.pk)
        if queryset is not None:
            others = others.exclude(pk__in=queryset.values("pk"))
        if not others.exists():
            return "You can't delete the last active superuser."
    return ""


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
    lacks any permission the account holds.

    The active, staff and superuser flags follow the User Manager's rules
    (:func:`apps.access.services.account_flags_refusal`): only a superuser
    changes a superuser's account (for anyone else it opens read-only, and a
    POST is refused), nobody deactivates their own account or removes their
    own staff access, and nobody deactivates or demotes the last active
    superuser. The same rules hold for deleting, single or bulk."""

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

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """``change_user``, and only a superuser changes a superuser's account
        (the User Manager's ``can_edit_account``)."""
        if obj is not None and obj.is_superuser and not _is_superuser(request.user):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """``delete_user``, and the User Manager's delete guards: not your own
        account, a superuser's only by a superuser, never the last active one."""
        if obj is not None and _delete_refusal(request.user, obj):
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset: Any) -> None:
        """The bulk *Delete selected* action asks the same guards per account."""
        for target in queryset:
            refusal = _delete_refusal(request.user, target, queryset=queryset)
            if refusal:
                raise PermissionDenied(refusal)
        super().delete_queryset(request, queryset)

    def get_form(self, request: HttpRequest, obj: Any = None, change: bool = False, **kwargs: Any) -> Any:
        form = super().get_form(request, obj, change=change, **kwargs)
        if obj is None or obj.pk is None:
            return form
        actor = request.user

        class FlagRulesForm(form):  # type: ignore[valid-type,misc]
            def clean(self) -> Any:
                from apps.access.services import account_flags_refusal

                cleaned = super().clean()
                # clean() runs before the instance takes the posted values, so
                # self.instance still holds the stored flags. A read-only
                # field isn't in the form: it keeps its stored value.
                refusal = account_flags_refusal(
                    actor,
                    self.instance,
                    is_active=cleaned.get("is_active", self.instance.is_active),
                    is_staff=cleaned.get("is_staff", self.instance.is_staff),
                    is_superuser=cleaned.get("is_superuser", self.instance.is_superuser),
                )
                if refusal:
                    raise forms.ValidationError(refusal)
                return cleaned

        FlagRulesForm.__name__ = form.__name__
        return FlagRulesForm

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
