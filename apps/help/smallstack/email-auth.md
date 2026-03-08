---
title: Email & Password Reset
description: Configure SMTP email, password reset, and email login
---

# Email & Password Reset

This guide covers email configuration for password resets and optionally allowing users to log in with their email address. For an overview of SmallStack's authentication system and feature flags, see [Authentication](/help/smallstack/authentication/).

## Email Configuration

### Development (Console Backend)

For local development, Django can print emails to the console instead of sending them. This is already configured in `config/settings/development.py`:

```python
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
```

When a user requests a password reset, the email content appears in your terminal.

### Production (SMTP)

For production, configure SMTP in your `.env` file:

```bash
# Email settings
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=noreply@yourdomain.com
```

Then update `config/settings/production.py`:

```python
from decouple import config

EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@example.com")
```

### Common Email Providers

**Gmail:**
```bash
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password  # Use App Password, not account password
```

**SendGrid:**
```bash
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=your-sendgrid-api-key
```

**Mailgun:**
```bash
EMAIL_HOST=smtp.mailgun.org
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=postmaster@your-domain.mailgun.org
EMAIL_HOST_PASSWORD=your-mailgun-password
```

## Password Reset Flow

Django's password reset is already wired up in {{ project_name }}. The flow works like this:

1. User clicks "Forgot your password?" on login page
2. User enters their email address
3. Django sends a reset link (valid for a limited time)
4. User clicks link, enters new password
5. User is redirected to login

### URL Configuration

These URLs are included via `django.contrib.auth.urls` in `config/urls.py`:

| URL | View | Template |
|-----|------|----------|
| `/accounts/password_reset/` | PasswordResetView | `registration/password_reset_form.html` |
| `/accounts/password_reset/done/` | PasswordResetDoneView | `registration/password_reset_done.html` |
| `/accounts/reset/<uidb64>/<token>/` | PasswordResetConfirmView | `registration/password_reset_confirm.html` |
| `/accounts/reset/done/` | PasswordResetCompleteView | `registration/password_reset_complete.html` |

### Customizing Reset Emails

To customize the password reset email, create these templates:

**`templates/registration/password_reset_subject.txt`**
```
{{ project_name }} - Password Reset
```

**`templates/registration/password_reset_email.html`**
```html
{% autoescape off %}
Hello,

You requested a password reset for your account at {{ site_name }}.

Click the link below to set a new password:

{{ protocol }}://{{ domain }}{% url 'password_reset_confirm' uidb64=uid token=token %}

If you didn't request this, you can ignore this email.

Thanks,
The {{ site_name }} Team
{% endautoescape %}
```

## Login with Email (Optional)

By default, Django uses username for authentication. To allow email login:

### Step 1: Create a Custom Authentication Backend

Create `apps/smallstack/backends.py`:

```python
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """
    Authenticate with either username or email address.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        # Try to find user by email first, then username
        try:
            if "@" in username:
                user = User.objects.get(email__iexact=username)
            else:
                user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            # Run the default password hasher to mitigate timing attacks
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
```

### Step 2: Configure Authentication Backends

Add to `config/settings/base.py`:

```python
AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.EmailOrUsernameBackend",
    "django.contrib.auth.backends.ModelBackend",  # Fallback
]
```

### Step 3: Update Login Form Label (Optional)

To change the login form label from "Username" to "Username or Email", update the login template.

Edit `templates/registration/login.html` and change the label:

```html
<label for="id_username">Username or Email</label>
```

Or create a custom form in `apps/smallstack/forms.py`:

```python
from django.contrib.auth.forms import AuthenticationForm


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username or Email"
        self.fields["username"].widget.attrs["placeholder"] = "Username or email address"
```

Then use it in your login view by updating `config/urls.py`:

```python
from django.contrib.auth.views import LoginView
from apps.accounts.forms import EmailOrUsernameAuthenticationForm

urlpatterns = [
    # ... other urls
    path(
        "accounts/login/",
        LoginView.as_view(
            authentication_form=EmailOrUsernameAuthenticationForm
        ),
        name="login",
    ),
    path("accounts/", include("django.contrib.auth.urls")),
    # ... other urls
]
```

## Testing Email Configuration

The quickest way to verify your SMTP config is Django's built-in test command:

```bash
python manage.py sendtestemail you@example.com
```

This sends a test email using your current settings — no shell or code required. If it arrives, your email is working.

For more control, you can also test from the Django shell:

```python
# In Django shell: uv run python manage.py shell

from django.core.mail import send_mail

send_mail(
    subject="Test Email",
    message="If you receive this, email is working!",
    from_email="noreply@yourdomain.com",
    recipient_list=["your-email@example.com"],
)
```

## Requiring Email Verification (Advanced)

If you want users to verify their email before accessing the site, you'll need to:

1. Add an `email_verified` field to your User model
2. Create a verification token system
3. Send verification email on signup
4. Restrict access until verified

This is beyond the scope of the starter kit, but packages like `django-allauth` provide this functionality if needed.

## Troubleshooting

### Emails Not Sending

1. Check your SMTP credentials
2. Verify `EMAIL_BACKEND` is set correctly
3. Check spam/junk folders
4. Test with console backend first

### Gmail "Less Secure Apps" Error

Gmail no longer supports "less secure apps." You must:

1. Enable 2-Factor Authentication on your Google account
2. Generate an App Password at https://myaccount.google.com/apppasswords
3. Use the App Password (not your account password) as `EMAIL_HOST_PASSWORD`

### Reset Link Expired

The default token validity is 3 days. To change it, add to settings:

```python
PASSWORD_RESET_TIMEOUT = 86400  # 1 day in seconds
```

## Summary

| Feature | Status | Notes |
|---------|--------|-------|
| Console email (dev) | Built-in | Works out of the box |
| SMTP email (prod) | Configuration | Add settings to `.env` |
| Password reset | Built-in | Templates included |
| Email login | Optional | Add custom backend |
| Email verification | Not included | Use django-allauth if needed |
