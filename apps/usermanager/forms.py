"""Forms for the User Manager — bespoke forms that span User + UserProfile."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from apps.accounts.forms import SignInFieldsLockMixin
from apps.profile.models import UserProfile

User = get_user_model()


class UserCreateForm(forms.ModelForm):
    """Create a user with a password set directly. (The Invite flow is the
    email-based alternative — this form is for setting a password up front so
    the new account is immediately usable, never passwordless.)"""

    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "class": "vTextField"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "class": "vTextField"}),
    )

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "is_staff", "is_active"]

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("The two password fields didn't match.")
        return p2

    def _post_clean(self):
        super()._post_clean()
        password = self.cleaned_data.get("password2")
        if password:
            try:
                validate_password(password, self.instance)
            except forms.ValidationError as error:
                self.add_error("password2", error)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserAccountForm(SignInFieldsLockMixin, forms.ModelForm):
    """Account tab: core User model fields. The username and email are locked
    for an editor the subset rule refuses (see ``SignInFieldsLockMixin``)."""

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "is_staff", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if field.disabled:
                continue  # its help text says why; an empty field shouldn't repeat it as a placeholder
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
