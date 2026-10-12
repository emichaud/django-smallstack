"""Signed tokens for the subscriber lifecycle.

Every confirm and unsubscribe link is a ``django.core.signing`` token — a
signed, URL-safe, structured payload keyed on ``SECRET_KEY``. Chosen over a
bare ``TimestampSigner`` because the payload is a dict and ``loads(max_age=…)``
gives expiry for free. ``SECRET_KEY_FALLBACKS`` is honoured by ``signing``, so
rotating the key does not invalidate unsubscribe links already sitting in
people's inboxes.

**Four checks on read**, each closing a specific failure mode seen in prior art:

1. ``s`` — the subscription must still exist.
2. ``b`` — it must be the blog the token was minted for. A single opaque
   subscriber id reused across every list meant one unsubscribe link silently
   governed all of them.
3. ``e`` — the address must still match. A merge or a correction kills old links.
4. ``v`` — ``token_version`` must match. Re-subscribing bumps it, so an
   unsubscribe link from two years ago cannot quietly kill a fresh signup —
   a failure nobody notices until the reader complains a second time.

**Distinct salt per purpose**, so a confirm token can never be replayed as an
unsubscribe token even though the payloads are identical in shape.

The payload is **signed, not encrypted**: it is readable base64. Nothing goes
in it beyond the address the link was mailed to.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core import signing

from .models import Subscription, normalize_email

CONFIRM_SALT = "smallstack.blog.subscription.confirm.v1"
UNSUBSCRIBE_SALT = "smallstack.blog.subscription.unsubscribe.v1"


class InvalidToken(Exception):
    """The token is malformed, expired, tampered with, or no longer current.

    One exception for every failure, deliberately: distinguishing "expired"
    from "wrong blog" from "no such subscription" in a response would turn the
    endpoint into an oracle about who is subscribed to what.
    """


def confirm_max_age() -> int:
    """Seconds a confirmation link stays valid."""
    return int(getattr(settings, "SMALLSTACK_BLOG_CONFIRM_MAX_AGE_DAYS", 7)) * 24 * 3600


def _payload(subscription: Subscription) -> dict[str, Any]:
    return {
        "s": subscription.pk,
        "b": subscription.blog_id,
        "e": normalize_email(subscription.subscriber.email),
        "v": subscription.token_version,
    }


def make_confirm_token(subscription: Subscription) -> str:
    return signing.dumps(_payload(subscription), salt=CONFIRM_SALT, compress=True)


def make_unsubscribe_token(subscription: Subscription) -> str:
    return signing.dumps(_payload(subscription), salt=UNSUBSCRIBE_SALT, compress=True)


def _read(raw: str, *, salt: str, max_age: int | None) -> Subscription:
    try:
        data = signing.loads(raw, salt=salt, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise InvalidToken("This link has expired.") from exc
    except signing.BadSignature as exc:
        raise InvalidToken("This link is not valid.") from exc
    except Exception as exc:  # noqa: BLE001 — a malformed payload is just invalid
        raise InvalidToken("This link is not valid.") from exc

    if not isinstance(data, dict):
        raise InvalidToken("This link is not valid.")

    subscription_pk = data.get("s")
    if not isinstance(subscription_pk, int):
        raise InvalidToken("This link is not valid.")
    subscription = (
        Subscription.objects.select_related("subscriber", "blog")
        .filter(pk=subscription_pk)
        .first()
    )
    if subscription is None:
        raise InvalidToken("This link is not valid.")
    if subscription.blog_id != data.get("b"):
        raise InvalidToken("This link is not valid.")
    if normalize_email(subscription.subscriber.email) != normalize_email(
        str(data.get("e") or "")
    ):
        raise InvalidToken("This link is not valid.")
    if subscription.token_version != data.get("v"):
        raise InvalidToken("This link is no longer valid.")
    return subscription


def read_confirm_token(raw: str) -> Subscription:
    """Resolve a confirmation token. Expires — an unconfirmed signup is stale
    after a week and re-subscribing is trivial."""
    return _read(raw, salt=CONFIRM_SALT, max_age=confirm_max_age())


def read_unsubscribe_token(raw: str) -> Subscription:
    """Resolve an unsubscribe token.

    **No expiry, on purpose.** An RFC 8058 ``List-Unsubscribe`` header in a
    two-year-old email must still work; an expired opt-out link is a
    compliance problem, not a security feature.
    """
    return _read(raw, salt=UNSUBSCRIBE_SALT, max_age=None)
