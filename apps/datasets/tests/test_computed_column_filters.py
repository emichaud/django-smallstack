"""Filters must apply to COMPUTED (annotated) dataset columns.

Downstream-reported: a plain filter on a computed column — `?hours_band=business`,
`?route=on_call`, `?answered=1` — was silently ignored and returned **every row**.
`_apply_list_filters` resolved every declared filter name with
`model._meta.get_field()` and `continue`d when that raised, so an annotation
(which is a real column on the queryset, just not on the model) was dropped.

That is the dangerous failure mode for an analytical surface: no error, no empty
result — a tile labelled "business hours" quietly showing *all* hours. It also
broke a documented promise: "Every operation works on a computed dataset"
(docs/skills/datasets.md) and the filter invariant that rows/series/scalar all
honour the same `{name: scalar}` contract.

The pipeline now consults `qs.query.annotations` before giving up, and types the
comparison from the annotation's `output_field`.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db.models import BooleanField, Case, CharField, Count, Value, When
from django.urls import reverse

from apps.datasets import core
from apps.datasets.registry import dataset

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def computed_ds(db):
    """A dataset whose columns are annotations, in the reported shapes:
    a boolean flag, a categorical band, and an aggregate count."""

    @dataset(
        "t_computed_filters",
        label="Computed filters probe",
        columns=[
            ("username", "str"),
            ("answered", "bool"),
            ("hours_band", "str"),
            ("login_count", "int"),
        ],
        filterable=["username", "answered", "hours_band", "login_count"],
        enable_api=True,
    )
    def _ds():
        return User.objects.annotate(
            answered=Case(
                When(is_staff=True, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
            hours_band=Case(
                When(is_staff=True, then=Value("business")),
                default=Value("after_hours"),
                output_field=CharField(),
            ),
            login_count=Count("logentry"),
        )

    return core.get_dataset("t_computed_filters")


@pytest.fixture
def people(db):
    return [
        User.objects.create_user("staff_a", password="p", is_staff=True),
        User.objects.create_user("staff_b", password="p", is_staff=True),
        User.objects.create_user("plain_c", password="p", is_staff=False),
    ]


# --- the reported bug --------------------------------------------------------


def test_boolean_computed_filter_narrows(computed_ds, people):
    """`?answered=1` — the reported VM-answered case."""
    assert computed_ds.count() == 3
    assert computed_ds.count(filters={"answered": "1"}) == 2      # was 3
    assert computed_ds.count(filters={"answered": "0"}) == 1      # was 3
    assert computed_ds.count(filters={"answered": "true"}) == 2
    assert computed_ds.count(filters={"answered": "false"}) == 1


def test_categorical_computed_filter_narrows(computed_ds, people):
    """`?hours_band=business` / `?route=on_call` — exact match, not substring."""
    assert computed_ds.count(filters={"hours_band": "business"}) == 2     # was 3
    assert computed_ds.count(filters={"hours_band": "after_hours"}) == 1  # was 3
    assert computed_ds.count(filters={"hours_band": "busi"}) == 0, (
        "computed columns are categorical — a partial value must not match"
    )


def test_aggregate_annotation_filters_via_having(computed_ds, people):
    """An aggregate annotation filters too (Django turns it into HAVING)."""
    assert computed_ds.count(filters={"login_count": "0"}) == 3


# --- the contracts the fix must not break ------------------------------------


def test_unknown_filter_key_is_still_tolerated(computed_ds, people):
    """Unknown keys stay ignored — the documented absent-not-error contract.
    Only *declared* filter fields that are real annotations now apply."""
    assert computed_ds.count(filters={"no_such_column": "whatever"}) == 3


def test_real_model_field_filters_unchanged(computed_ds, people):
    assert computed_ds.count(filters={"username": "staff_a"}) == 1


def test_unparseable_boolean_narrows_nothing_rather_than_raising(computed_ds, people):
    assert computed_ds.count(filters={"answered": "maybe"}) == 3


def test_filter_applies_across_rows_series_and_scalar(computed_ds, people):
    """The documented invariant: one filter contract for all three read paths —
    an active filter must reduce the table, the chart AND the KPI."""
    filters = {"hours_band": "business"}

    rows = computed_ds.rows(filters=filters)
    assert len(rows) == 2

    series = computed_ds.series(dimension="hours_band", filters=filters)
    assert sum(p["value"] for p in series) == 2, series

    assert computed_ds.scalar(agg="count", filters=filters) == 2


# --- end to end over REST (the surface it was reported on) -------------------


@pytest.fixture
def _api_token(db):
    from apps.smallstack.models import APIToken

    # A superuser: the dataset reads the user model, which needs accounts.view_user.
    admin = User.objects.create_user(username="ds_admin", password="x", is_staff=True, is_superuser=True)
    _token, raw = APIToken.create_token(admin, name="test")
    return raw


def test_rest_rows_honour_a_computed_filter(client, computed_ds, people, _api_token):
    resp = client.get(
        f"{reverse('datasets:rows', args=['t_computed_filters'])}?hours_band=business",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 200
    payload = resp.json()
    rows = payload.get("rows") or payload.get("results") or []
    assert rows, payload
    bands = {r["hours_band"] for r in rows}
    assert bands == {"business"}, "REST returned rows the filter should have excluded"


def test_rest_scalar_honours_a_computed_filter(client, computed_ds, people, _api_token):
    resp = client.get(
        f"{reverse('datasets:scalar', args=['t_computed_filters'])}?agg=count&answered=1",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 200
    payload = resp.json()
    value = payload["value"] if isinstance(payload, dict) else payload
    assert value == 3  # ds_admin + staff_a + staff_b are all staff ⇒ answered=1
