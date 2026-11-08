"""``seed_dashboards`` — the demo, including a rate made from two of its metrics."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.dashboards.models import Metric, Report

pytestmark = pytest.mark.django_db


def seed() -> None:
    call_command("seed_dashboards", stdout=StringIO())


def test_the_demo_seeds_a_valid_server_error_rate():
    seed()
    rate = Metric.objects.get(key="demo_server_error_rate")
    assert rate.is_rate and rate.owner_id is None
    assert (rate.numerator, rate.denominator, rate.format) == ("demo_server_errors", "demo_requests", "percent")
    # Period-aware because its parts are, so a goal or a period bar applies to it.
    assert rate.period_field == "timestamp"
    rate.full_clean()
    assert {"metric": "demo_server_error_rate"} in Report.objects.get(slug="monthly-kpis").items


def test_re_seeding_does_not_duplicate_the_rate():
    seed()
    seed()
    assert Metric.objects.filter(key="demo_server_error_rate").count() == 1
