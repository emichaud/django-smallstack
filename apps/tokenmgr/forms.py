"""Forms for the Token Manager."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

#: Minting a token for an account other than your own (superusers excepted).
MINT_FOR_OTHERS = "smallstack.add_apitoken"

# Access level choices, narrowed per role.
NON_STAFF_ACCESS_LEVELS = [
    ("readonly", "Read-only"),
]

STAFF_ACCESS_LEVELS = [
    ("staff", "Staff"),
    ("readonly", "Read-only"),
]

SUPERUSER_ACCESS_LEVELS = [
    ("auth", "Auth (user management)"),
    ("staff", "Staff"),
    ("readonly", "Read-only"),
]


def may_mint_for_others(minter: Any) -> bool:
    """Whether ``minter`` may own-pick another account at all: a superuser, or
    an active staff account holding :data:`MINT_FOR_OTHERS`."""
    if not (minter and minter.is_authenticated and minter.is_active):
        return False
    return minter.is_superuser or (minter.is_staff and minter.has_perm(MINT_FOR_OTHERS))


def mint_refusal(minter: Any, target: Any) -> str | None:
    """Why ``minter`` may not mint a token owned by ``target``, or ``None``.

    Whoever holds a token acts as its owner, so minting one for someone hands
    the minter everything that account can do. The rule (every surface that
    mints applies it):

    - anyone may mint for themselves;
    - a superuser may mint for anyone;
    - otherwise the minter needs ``smallstack.add_apitoken`` and staff, and the
      owner must be an active non-superuser holding no permission the minter
      lacks (the same subset rule as adding someone to a group).
    """
    if minter is None or not minter.is_authenticated:
        return "Authentication required."
    if target.pk == minter.pk:
        return None
    if minter.is_superuser and minter.is_active:
        return None
    if not may_mint_for_others(minter):
        return f"You may only mint tokens for yourself; minting for another account needs {MINT_FOR_OTHERS}."
    if not target.is_active:
        return f"{target} is deactivated."
    if target.is_superuser:
        return f"{target} is a superuser; only a superuser may mint a token for them."
    from apps.access.services import permissions_actor_lacks_for_user

    missing = permissions_actor_lacks_for_user(minter, target)
    if missing:
        shown = ", ".join(missing[:5]) + (f" and {len(missing) - 5} more" if len(missing) > 5 else "")
        return (
            f"{target} holds {len(missing)} permission{'s' if len(missing) != 1 else ''} you don't "
            f"({shown}); a token for them would act with it."
        )
    return None


def mintable_users(minter: Any):
    """The accounts ``minter`` may pick as a token's owner (see :func:`mint_refusal`).

    A queryset for the picker; it reads Django's model permissions from the
    database, so ``clean()`` re-checks the choice with :func:`mint_refusal`
    (which also sees any custom auth backend)."""
    users = get_user_model().objects.all()
    if minter is None or not minter.is_authenticated:
        return users.none()
    if minter.is_superuser and minter.is_active:
        return users
    if not may_mint_for_others(minter):
        return users.filter(pk=minter.pk)
    held = minter.get_all_permissions()
    beyond = Permission.objects.exclude(
        pk__in=[
            p.pk
            for p in Permission.objects.select_related("content_type")
            if f"{p.content_type.app_label}.{p.codename}" in held
        ]
    )
    others = (
        users.filter(is_active=True, is_superuser=False)
        .exclude(user_permissions__in=beyond)
        .exclude(groups__permissions__in=beyond)
    )
    return users.filter(pk__in=others.values("pk")) | users.filter(pk=minter.pk)


def _apply_text_class(form):
    for field in form.fields.values():
        if isinstance(field.widget, (forms.TextInput, forms.Textarea)):
            field.widget.attrs.setdefault("class", "vTextField")


class TokenCreateForm(forms.Form):
    """Mint a new APIToken.

    Built with the requesting `user` so we can:
    - default `user` to themselves
    - hide the user picker when they're not staff
    - restrict `access_level` choices to what their role allows
    """

    user = forms.ModelChoiceField(
        queryset=get_user_model().objects.all(),
        required=True,
        label="User",
        help_text="Who owns this token. Auto-filled with you.",
    )
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(
            attrs={"placeholder": "e.g. CI/CD Pipeline, Claude Desktop", "autofocus": True}
        ),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Optional context — what this token is used for"}
        ),
    )
    access_level = forms.ChoiceField(
        choices=SUPERUSER_ACCESS_LEVELS,
        initial="readonly",
        help_text="readonly: GET only. staff: full API. auth: user management.",
    )
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        help_text="Leave blank for a never-expiring token.",
    )

    def __init__(self, *args, request_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_text_class(self)
        self.request_user = request_user

        if request_user is None or not request_user.is_authenticated:
            return

        # The picker offers only the accounts this minter may pick; with just
        # themselves to pick, it is hidden.
        self.fields["user"].queryset = mintable_users(request_user)
        self.fields["user"].initial = request_user.pk
        if not may_mint_for_others(request_user):
            self.fields["user"].widget = forms.HiddenInput()
        if not request_user.is_staff:
            self.fields["access_level"].choices = NON_STAFF_ACCESS_LEVELS
            self.fields["access_level"].initial = "readonly"
        elif request_user.is_superuser:
            self.fields["access_level"].choices = SUPERUSER_ACCESS_LEVELS
        else:
            # Staff but not superuser → no auth-level minting.
            self.fields["access_level"].choices = STAFF_ACCESS_LEVELS

    def clean_access_level(self):
        level = self.cleaned_data["access_level"]
        u = self.request_user
        if u is None or not u.is_authenticated:
            raise forms.ValidationError("Authentication required.")
        if not u.is_staff and level != "readonly":
            raise forms.ValidationError("Non-staff users may only mint read-only tokens.")
        if level == "auth" and not u.is_superuser:
            raise forms.ValidationError("Only superusers may mint auth-level tokens.")
        return level

    def clean_user(self):
        target = self.cleaned_data["user"]
        refusal = mint_refusal(self.request_user, target)
        if refusal:
            raise forms.ValidationError(refusal)
        return target

    def clean(self):
        cleaned = super().clean()
        target = cleaned.get("user")
        level = cleaned.get("access_level")
        # The owner rule again, on the cleaned pair: clean_user and the
        # picker's queryset are not the only gate a crafted POST meets.
        refusal = mint_refusal(self.request_user, target) if target is not None else None
        if refusal:
            self.add_error("user", refusal)
            return cleaned
        # A token's level never exceeds its owner's real role: a staff-level
        # token for a non-staff user would be refused by REST (which checks the
        # user) and only mislead whoever holds it.
        if target is not None and level in ("staff", "auth") and not target.is_staff:
            self.add_error("access_level", f"{target} is not staff; only read-only tokens can be minted for them.")
        return cleaned
