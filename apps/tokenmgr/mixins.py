"""View mixins for self-service token management."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin

#: Revoking a token you don't own changes someone else's access, so it asks
#: the model's change permission (the shipped *Token manager* group holds it).
REVOKE_PERMISSION = "smallstack.change_apitoken"
#: Reading other accounts' tokens (owners, levels, usage) asks the model's view
#: permission, as Django admin and Explorer do; your own are always yours.
VIEW_PERMISSION = "smallstack.view_apitoken"


def may_read_all_tokens(user: Any) -> bool:
    """Whether ``user`` sees every account's tokens: an active superuser, or
    active staff holding :data:`VIEW_PERMISSION` (the *Token manager* group)."""
    if not (user is not None and getattr(user, "is_authenticated", False) and user.is_active):
        return False
    return bool(user.is_superuser or (user.is_staff and user.has_perm(VIEW_PERMISSION)))


class LoginRequiredAuthMixin(LoginRequiredMixin):
    """Authenticated users only — no staff requirement.

    Used as the base auth gate for token management views. Combined with
    `_owner_or_staff(...)` helpers in views to enforce per-row ownership.
    """


def is_owner_or_staff(user, token) -> bool:
    """Return True if `user` may view `token`: its owner, or an account that
    reads every token (:func:`may_read_all_tokens`). The name predates the
    permission; plain staff no longer qualify.

    Reading only: revoking asks :func:`revoke_refusal`."""
    if not getattr(user, "is_authenticated", False):
        return False
    if token.user_id == user.pk:
        return True
    return may_read_all_tokens(user)


def revoke_refusal(actor: Any, token: Any) -> str | None:
    """Why ``actor`` may not revoke ``token``, or ``None`` when they may.

    Anyone may revoke their own token. Revoking another account's needs active
    staff holding ``smallstack.change_apitoken``, and only a superuser revokes
    a superuser's token. Superusers may revoke any token."""
    if not getattr(actor, "is_authenticated", False):
        return "Sign in to revoke a token."
    if token.user_id == actor.pk or actor.is_superuser:
        return None
    if not (actor.is_active and actor.is_staff and actor.has_perm(REVOKE_PERMISSION)):
        return f"Revoking another account's token needs the {REVOKE_PERMISSION} permission."
    if token.user.is_superuser:
        return "Only a superuser may revoke a superuser's token."
    return None


def may_revoke(actor: Any, token: Any) -> bool:
    """Whether ``actor`` may revoke ``token`` (see :func:`revoke_refusal`)."""
    return revoke_refusal(actor, token) is None
