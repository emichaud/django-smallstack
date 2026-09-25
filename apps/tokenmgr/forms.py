"""Forms for the Token Manager."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

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

        # Lock the user picker for non-staff: they only mint for themselves.
        if not request_user.is_staff:
            self.fields["user"].queryset = self.fields["user"].queryset.filter(pk=request_user.pk)
            self.fields["user"].initial = request_user.pk
            self.fields["user"].widget = forms.HiddenInput()
            self.fields["access_level"].choices = NON_STAFF_ACCESS_LEVELS
            self.fields["access_level"].initial = "readonly"
        elif request_user.is_superuser:
            self.fields["access_level"].choices = SUPERUSER_ACCESS_LEVELS
            self.fields["user"].initial = request_user.pk
        else:
            # Staff but not superuser → no auth-level minting.
            self.fields["access_level"].choices = STAFF_ACCESS_LEVELS
            self.fields["user"].initial = request_user.pk

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
        u = self.request_user
        if u is None or not u.is_authenticated:
            raise forms.ValidationError("Authentication required.")
        if not u.is_staff and target.pk != u.pk:
            raise forms.ValidationError("Non-staff users may only mint tokens for themselves.")
        return target

    def clean(self):
        cleaned = super().clean()
        target = cleaned.get("user")
        level = cleaned.get("access_level")
        # A token's level never exceeds its owner's real role: a staff-level
        # token for a non-staff user would be refused by REST (which checks the
        # user) and only mislead whoever holds it. (Audit 2026-09-13, C1.)
        if target is not None and level in ("staff", "auth") and not target.is_staff:
            self.add_error("access_level", f"{target} is not staff; only read-only tokens can be minted for them.")
        return cleaned
