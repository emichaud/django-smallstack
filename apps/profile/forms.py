"""
Forms for the profile app.
"""

from django import forms

from .models import UserProfile


class UserProfileForm(forms.ModelForm):
    """Form for editing user profile, including user email."""

    # Email field from the User model
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"class": "vTextField", "placeholder": "you@example.com"}),
        help_text="Your email address for notifications and password recovery.",
    )

    class Meta:
        model = UserProfile
        fields = [
            "profile_photo",
            "background_photo",
            "display_name",
            "bio",
            "location",
            "website",
            "date_of_birth",
            "timezone",
            "theme_preference",
            "color_palette",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(
                attrs={"type": "date", "class": "vTextField"},
                format="%Y-%m-%d",
            ),
            "bio": forms.Textarea(attrs={"rows": 4, "class": "vLargeTextField"}),
            "display_name": forms.TextInput(attrs={"class": "vTextField"}),
            "location": forms.TextInput(attrs={"class": "vTextField"}),
            "website": forms.URLInput(attrs={"class": "vTextField"}),
            "timezone": forms.Select(attrs={"class": "vTextField"}),
            "theme_preference": forms.Select(attrs={"class": "vTextField"}),
            "color_palette": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make all profile fields optional in the form
        for field in self.fields.values():
            field.required = False

        # Populate email from the related user
        if self.instance and self.instance.pk and self.instance.user:
            self.fields["email"].initial = self.instance.user.email

    def save(self, commit=True):
        """Save the profile and update the user's email."""
        profile = super().save(commit=commit)

        # Update the user's email
        if self.instance and self.instance.user:
            self.instance.user.email = self.cleaned_data.get("email") or None
            if commit:
                self.instance.user.save(update_fields=["email"])

        return profile
