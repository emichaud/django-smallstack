"""Authentication backends.

EmailOrUsernameBackend lets users sign in with either their username or their
email address. Enable it by adding it to AUTHENTICATION_BACKENDS *after* the
axes backend (so brute-force protection still wraps it) and before the default
ModelBackend — see config/settings/base.py.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """Authenticate against username OR email (case-insensitive)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        ident = username.strip()
        try:
            if "@" in ident:
                user = User.objects.get(email__iexact=ident)
            else:
                user = User.objects.get(username__iexact=ident)
        except User.DoesNotExist:
            # Run the hasher once anyway to keep timing uniform (don't leak
            # whether the identifier exists).
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
