"""Sign-in events, logged.

Django's auth signals fire for every way in (password, sign-in code, invite,
sign-up), so one receiver each covers them all. Records name the account by
username and pk, never a password or code; a failed sign-in names only the
username that was tried, which django-axes also counts for lockouts.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_logged_in, dispatch_uid="accounts_log_signed_in")
def log_signed_in(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    logger.info("accounts: %s (pk=%s) signed in", user.get_username(), user.pk)


@receiver(user_logged_out, dispatch_uid="accounts_log_signed_out")
def log_signed_out(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    if user is not None:
        logger.info("accounts: %s (pk=%s) signed out", user.get_username(), user.pk)


@receiver(user_login_failed, dispatch_uid="accounts_log_sign_in_failed")
def log_sign_in_failed(sender: Any, credentials: dict[str, Any], request: Any = None, **kwargs: Any) -> None:
    # Django has already masked secrets in credentials; take only the username.
    logger.warning("accounts: sign-in failed for %r", credentials.get("username", ""))
