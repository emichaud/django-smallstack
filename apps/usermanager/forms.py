"""Forms for the User Manager — bespoke forms that span User + UserProfile."""

from django import forms
from django.contrib.auth import get_user_model

from apps.profile.models import UserProfile

User = get_user_model()


class UserAccountForm(forms.ModelForm):
    """Account tab: core User model fields."""

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "is_staff", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if field.help_text and not isinstance(field.widget, (forms.CheckboxInput, forms.Select)):
                field.widget.attrs.setdefault("placeholder", str(field.help_text))


class UserProfileForm(forms.ModelForm):
    """Profile tab: UserProfile fields including photos."""

    class Meta:
        model = UserProfile
        fields = [
            "display_name",
            "bio",
            "profile_photo",
            "background_photo",
            "location",
            "website",
            "date_of_birth",
            "timezone",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
            "bio": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # All profile fields are optional
        for field in self.fields.values():
            field.required = False
            if field.help_text and not isinstance(field.widget, (forms.CheckboxInput, forms.FileInput, forms.Select)):
                field.widget.attrs.setdefault("placeholder", str(field.help_text))
