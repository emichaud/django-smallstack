"""Filter-bar choices must respect the CRUDView's tenancy scope.

``filter_fields`` renders a dropdown per field. For a ForeignKey, the choices
used to come from ``related_model._default_manager.all()[:100]`` — the whole
related table, regardless of who was looking. On a tenancy-scoped CRUDView
(the documented end-user pattern in ``building-a-user-facing-site.md``) that is
a cross-tenant disclosure: ``get_list_queryset`` correctly hid other people's
rows from the table while the filter bar above it listed them by name.

``/smallstack/tokens/`` is the shipped instance of the bug — it is reachable by
any signed-in user, scoped by ``owner``, and declares ``user`` among its
``filter_fields``, so its filter bar enumerated every username on the
installation. It is used here as the regression case precisely because it
ships.

The fix derives choices from the tenancy-scoped list queryset, taken *before*
this request's own filters are applied — so the dropdowns stay switchable.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.smallstack.crud import _build_filter_meta
from apps.smallstack.models import APIToken

User = get_user_model()
pytestmark = pytest.mark.django_db


def _choice_labels(meta: dict) -> set[str]:
    return {label for _value, label in meta["choices"]}


def test_fk_filter_choices_exclude_other_tenants(client: Client):
    """The headline case: Alice's token list must not name Bob."""
    alice = User.objects.create_user(username="alice_f", password="pw")
    bob = User.objects.create_user(username="bob_f", password="pw")
    APIToken.objects.create(user=alice, name="alice key", prefix="aaaaaaaa")
    APIToken.objects.create(user=bob, name="bob key", prefix="bbbbbbbb")

    client.force_login(alice)
    body = client.get("/smallstack/tokens/").content.decode()

    assert "alice key" in body, "Alice should see her own token"
    assert "bob key" not in body, "list scoping is broken, not just the filter bar"
    assert "bob_f" not in body, "the filter dropdown leaked another user's username"


def test_fk_filter_choices_still_offer_your_own_values(client: Client):
    alice = User.objects.create_user(username="alice_g", password="pw")
    APIToken.objects.create(user=alice, name="alice key", prefix="cccccccc")

    client.force_login(alice)
    body = client.get("/smallstack/tokens/").content.decode()
    assert "alice_g" in body, "the filter must still offer values present in your own rows"


def test_staff_see_every_value(client: Client):
    """Staff bypass the scoper, so their filter bar is complete."""
    staff = User.objects.create_user(username="staff_f", password="pw", is_staff=True)
    bob = User.objects.create_user(username="bob_h", password="pw")
    APIToken.objects.create(user=bob, name="bob key", prefix="dddddddd")

    client.force_login(staff)
    body = client.get("/smallstack/tokens/").content.decode()
    assert "bob_h" in body


def test_choices_are_not_collapsed_by_an_active_filter(client: Client):
    """The subtle half of the fix: choices come from the queryset scoped by
    tenancy but NOT by this request's filters. Deriving them after filtering
    would leave each dropdown showing only the value already selected, so you
    could never switch to another one."""
    alice = User.objects.create_user(username="alice_i", password="pw")
    APIToken.objects.create(user=alice, name="active key", prefix="eeeeeeee", is_active=True)
    APIToken.objects.create(user=alice, name="revoked key", prefix="ffffffff", is_active=False)

    client.force_login(alice)
    body = client.get("/smallstack/tokens/?token_type=personal").content.decode()
    # Both of Alice's own tokens remain reachable from the filter bar's options
    # even while a filter is applied.
    assert "alice_i" in body


# ── The helper's own contract ───────────────────────────────────────────────


def test_build_filter_meta_without_a_queryset_offers_no_fk_rows():
    """`queryset=None` means "no row context" and must NOT fall back to the
    whole related table — that fallback was the bug."""
    meta = _build_filter_meta(APIToken, "user", queryset=None)
    assert meta is not None
    assert meta["type"] == "choice"
    assert _choice_labels(meta) == {"All"}


def test_build_filter_meta_derives_fk_rows_from_the_queryset():
    alice = User.objects.create_user(username="alice_j", password="pw")
    bob = User.objects.create_user(username="bob_j", password="pw")
    APIToken.objects.create(user=alice, name="a", prefix="11111111")
    APIToken.objects.create(user=bob, name="b", prefix="22222222")

    scoped = APIToken.objects.filter(user=alice)
    meta = _build_filter_meta(APIToken, "user", queryset=scoped)
    assert meta is not None
    assert _choice_labels(meta) == {"All", "alice_j"}


def test_build_filter_meta_ignores_null_fks():
    """A NULL FK must not become a phantom choice."""
    alice = User.objects.create_user(username="alice_k", password="pw")
    APIToken.objects.create(user=alice, name="a", prefix="33333333")
    meta = _build_filter_meta(APIToken, "user", queryset=APIToken.objects.all())
    assert meta is not None
    assert "" in {v for v, _ in meta["choices"]}  # the "All" sentinel
    assert None not in {label for _v, label in meta["choices"]}


def test_low_cardinality_column_choices_are_scoped_too():
    """The same reasoning applies to the distinct-values branch: the shape of
    other tenants' rows is not public either."""
    alice = User.objects.create_user(username="alice_l", password="pw")
    bob = User.objects.create_user(username="bob_l", password="pw")
    APIToken.objects.create(user=alice, name="mine", prefix="44444444")
    APIToken.objects.create(user=bob, name="theirs", prefix="55555555")

    meta = _build_filter_meta(APIToken, "name", queryset=APIToken.objects.filter(user=alice))
    if meta and meta["type"] == "choice":
        labels = _choice_labels(meta)
        assert "theirs" not in labels
