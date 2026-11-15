"""
Forms for the accounts app.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm

User = get_user_model()


class StyledSetPasswordForm(SetPasswordForm):
    """Django's SetPasswordForm with the SmallStack input class applied."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "vTextField"


class InviteUserForm(forms.Form):
    """Invite a new user by email. They set their own password via the link."""

    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"class": "vTextField", "autofocus": True}),
    )
    first_name = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "vTextField"})
    )
    last_name = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "vTextField"})
    )
    is_staff = forms.BooleanField(
        required=False,
        label="Grant staff access",
        help_text="Staff can reach the admin tools area.",
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email


#: Ticking the staff flag on a new account asks what setting it on an existing
#: one asks; the invite page uses the same permission.
CREATE_STAFF_PERMISSION = "accounts.change_user"


class AccountFormRulesMixin:
    """The account rules every ModelForm over the user model shares, given the
    ``user`` filling it in (fail closed without one):

    - **Creating:** the *Staff* box is dropped unless ``user`` holds
      :data:`CREATE_STAFF_PERMISSION` (superusers do), so a posted
      ``is_staff`` is ignored; the invite page's rule.
    - **Editing:** the username and email
      (``apps.access.services.SIGN_IN_FIELDS``) decide who can sign in as the
      account, so they're disabled, with the reason as help text, unless
      ``user`` passes the subset rule
      (:func:`apps.access.services.sign_in_refusal`). A disabled field keeps
      its stored value whatever is posted."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)  # type: ignore[call-arg]
        instance = getattr(self, "instance", None)
        if instance is None or instance.pk is None:
            if user is None or not user.has_perm(CREATE_STAFF_PERMISSION):
                self.fields.pop("is_staff", None)  # type: ignore[attr-defined]
            return
        from apps.access.services import SIGN_IN_FIELDS, sign_in_refusal

        if user is None:
            refusal = "Changing the username or email needs to know who is asking."
        else:
            refusal = sign_in_refusal(user, instance)
        if not refusal:
            return
        for name in SIGN_IN_FIELDS:
            field = self.fields.get(name)  # type: ignore[attr-defined]
            if field is not None:
                field.disabled = True
                field.help_text = refusal


class UserExplorerForm(AccountFormRulesMixin, forms.ModelForm):
    """Explorer's account form: the fields Explorer edits, with the username
    and email locked for an editor the subset rule refuses, and the staff box
    on create only for an editor holding ``accounts.change_user``."""

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "is_staff", "is_active"]


class SignupForm(UserCreationForm):
    """
    Form for user registration.
    Uses username and password only - no email required to activate.
    """

    class Meta:
        model = User
        fields = ("username",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add CSS classes for styling
        for field_name, field in self.fields.items():
            field.widget.attrs["class"] = "vTextField"
