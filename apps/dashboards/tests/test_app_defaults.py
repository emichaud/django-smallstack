"""Defaults an app ships (defaults.py): declared as data, created and kept in step
by the sync, edited in place by people, and never overwritten once they have."""

from __future__ import annotations

from io import StringIO

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.urls import reverse

from apps.dashboards import defaults as d
from apps.dashboards.defaults import Defaults, default_state, register_defaults, reset_default, sync_defaults
from apps.dashboards.models import Component, Dashboard, GoalList, Metric, RemovedDefault

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"
APP = "website"


def bundle(**overrides) -> Defaults:
    """A small app bundle: two metrics (one a rate), a saved card, a dashboard
    placing both, and a goal list."""
    spec = {
        "app": APP,
        "metrics": [
            {"key": "website_requests", "name": "Requests", "dataset": DS, "period_field": "timestamp"},
            {
                "key": "website_errors",
                "name": "Errors",
                "dataset": DS,
                "period_field": "timestamp",
                "filter_tree": {"field": "status_code", "op": ">=", "value": 500},
            },
            {
                "key": "website_error_rate",
                "name": "Error rate",
                "source": "rate",
                "numerator": "website_errors",
                "denominator": "website_requests",
                "format": "percent",
            },
        ],
        "components": [
            {"key": "website_errors_card", "name": "Errors card", "type": "metric", "metric": "website_errors"}
        ],
        "dashboards": [
            {
                "slug": "website-overview",
                "name": "Website",
                "layout": [
                    {"id": "a", "type": "metric", "metric": "website_requests", "x": 0, "y": 0, "w": 3, "h": 2},
                    {"id": "b", "component": "website_errors_card", "x": 3, "y": 0, "w": 3, "h": 2},
                ],
            }
        ],
        "goal_lists": [
            {
                "slug": "website-goals",
                "name": "Website goals",
                "sections": [{"title": "", "goals": [{"metric": "website_errors", "target": {"op": "=", "value": 0}}]}],
            }
        ],
    }
    spec.update(overrides)
    return Defaults(**spec)


@pytest.fixture(autouse=True)
def registry():
    """Each test registers what it needs, and sees nothing else: a project's own
    apps register bundles too. The real registry comes back after."""
    saved = dict(d._REGISTRY)
    d._REGISTRY.clear()
    yield
    d._REGISTRY.clear()
    d._REGISTRY.update(saved)


@pytest.fixture
def staff(client):
    user = User.objects.create_user("defaults-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


def outcomes(report) -> dict[str, str]:
    return {f"{kind}:{key}": outcome for _app, kind, key, outcome, _detail in report.lines}


# -- declaring -----------------------------------------------------------------


def test_a_declaration_is_checked_when_registered():
    with pytest.raises(ImproperlyConfigured, match="no installed app"):
        register_defaults(Defaults(app="nope"))
    with pytest.raises(ImproperlyConfigured, match="needs its key"):
        register_defaults(Defaults(app=APP, metrics=[{"name": "No key"}]))
    with pytest.raises(ImproperlyConfigured, match="unknown field"):
        register_defaults(Defaults(app=APP, metrics=[{"key": "website_x", "colour": "red"}]))
    with pytest.raises(ImproperlyConfigured, match="must start with 'website_'"):
        register_defaults(Defaults(app=APP, metrics=[{"key": "requests"}]))
    with pytest.raises(ImproperlyConfigured, match="must start with 'website-'"):
        register_defaults(Defaults(app=APP, dashboards=[{"slug": "overview"}]))
    register_defaults(Defaults(app=APP, prefix="", dashboards=[{"slug": "overview", "name": "Overview"}]))


# -- syncing -------------------------------------------------------------------


def test_the_sync_creates_everything_in_order_then_leaves_it_be():
    register_defaults(bundle())
    first = outcomes(sync_defaults())
    assert set(first.values()) == {"created"} and len(first) == 6
    m = Metric.objects.get(key="website_error_rate")
    assert (m.provided_by, m.provided_key, m.owner_id) == (APP, "website_error_rate", None) and m.is_rate
    board = Dashboard.objects.get(slug="website-overview")
    assert board.is_default and board.layout[1]["component"] == "website_errors_card"
    stamp = board.updated_at
    again = outcomes(sync_defaults())
    assert set(again.values()) == {"current"}
    board.refresh_from_db()
    assert board.updated_at == stamp  # nothing rewritten when nothing changed


def test_a_changed_declaration_updates_an_untouched_row_and_spares_an_edited_one():
    register_defaults(bundle())
    sync_defaults()
    edited = Metric.objects.get(key="website_requests")
    edited.name = "All requests"  # someone renames it
    edited.save()
    newer = bundle()
    newer.metrics[0]["description"] = "Every request."
    newer.metrics[1]["unit"] = "errors"
    register_defaults(newer)
    result = outcomes(sync_defaults())
    assert result["metric:website_requests"] == "customised" and result["metric:website_errors"] == "updated"
    assert Metric.objects.get(key="website_errors").unit == "errors"
    kept = Metric.objects.get(key="website_requests")
    assert (kept.name, kept.description) == ("All requests", "")
    state = default_state(kept)
    assert state["customised"] and state["newer"] and state["shipped"] and state["app"] == APP
    # Reset to default: the app's definition now, over the edit.
    reset_default(kept)
    kept.refresh_from_db()
    assert (kept.name, kept.description) == ("Requests", "Every request.")
    assert default_state(kept) == {**state, "customised": False, "newer": False}
    assert outcomes(sync_defaults())["metric:website_requests"] == "current"


def test_editing_a_placed_card_doesnt_make_its_dashboard_customised():
    register_defaults(bundle())
    sync_defaults()
    card = Component.objects.get(key="website_errors_card")
    card.options = {"style": {"size": "xl"}}
    card.save()  # re-saves the dashboard with the card's new design copied in
    assert not default_state(Dashboard.objects.get(slug="website-overview"))["customised"]
    assert default_state(Component.objects.get(key="website_errors_card"))["customised"]


def test_a_deleted_default_stays_deleted_until_restored():
    register_defaults(bundle())
    sync_defaults()
    GoalList.objects.get(slug="website-goals").delete()
    assert RemovedDefault.objects.filter(app=APP, kind="goals", key="website-goals").exists()
    assert outcomes(sync_defaults())["goals:website-goals"] == "removed"
    assert not GoalList.objects.filter(slug="website-goals").exists()
    assert outcomes(sync_defaults([APP], restore=True))["goals:website-goals"] == "created"
    assert GoalList.objects.get(slug="website-goals").is_default


def test_a_name_already_taken_is_a_conflict_unless_adopted():
    Metric(key="website_requests", name="Mine", dataset=DS).save()
    register_defaults(bundle())
    assert outcomes(sync_defaults())["metric:website_requests"] == "conflict"
    assert not Metric.objects.get(key="website_requests").is_default
    assert outcomes(sync_defaults([APP], adopt=True))["metric:website_requests"] == "adopted"
    adopted = Metric.objects.get(key="website_requests")
    assert adopted.is_default and adopted.name == "Requests"


def test_a_bundle_registered_without_auto_runs_only_when_named():
    register_defaults(bundle(auto=False))
    assert outcomes(sync_defaults()) == {}
    assert not Metric.objects.filter(key="website_requests").exists()
    sync_defaults([APP])
    assert Metric.objects.filter(key="website_requests").exists()


def test_a_dry_run_writes_nothing():
    register_defaults(bundle())
    assert set(outcomes(sync_defaults(dry_run=True)).values()) == {"created"}
    assert not Metric.objects.filter(provided_by=APP).exists()


def test_defaults_of_an_app_turned_off_are_parked_and_come_back(monkeypatch):
    register_defaults(bundle())
    sync_defaults()
    d._REGISTRY.pop(APP)
    monkeypatch.setattr(d, "_label_installed", lambda label: label != APP)
    parked = outcomes(sync_defaults())
    assert parked["metric:website_requests"] == "parked"
    m = Metric.objects.get(key="website_requests")
    assert m.is_archived and m.provided_parked
    monkeypatch.setattr(d, "_label_installed", lambda label: True)
    register_defaults(bundle())
    assert outcomes(sync_defaults())["metric:website_requests"] == "restored"
    m.refresh_from_db()
    assert not m.is_archived and not m.provided_parked


def test_the_sync_is_off_in_test_settings_so_shipped_defaults_dont_leak_into_tests():
    from django.conf import settings as live

    assert live.SMALLSTACK_DASHBOARD_DEFAULTS_SYNC is False


def test_the_sync_runs_after_migrate_and_by_command(settings):
    from apps.dashboards.apps import _sync_defaults_after_migrate

    settings.SMALLSTACK_DASHBOARD_DEFAULTS_SYNC = True  # off in test settings
    register_defaults(bundle())
    _sync_defaults_after_migrate(django_apps.get_app_config("auth"))  # another app's signal: nothing
    assert not Metric.objects.filter(provided_by=APP).exists()
    _sync_defaults_after_migrate(django_apps.get_app_config("smallstack_dashboards"))
    assert Metric.objects.filter(provided_by=APP).count() == 3
    out = StringIO()
    call_command("dashboard_defaults", "--dry-run", stdout=out)
    assert "Would be: 6 already current." in out.getvalue()


# -- on the page -----------------------------------------------------------------


def test_the_page_says_where_a_default_came_from_and_resets_it(client, staff):
    register_defaults(bundle())
    sync_defaults()
    m = Metric.objects.get(key="website_requests")
    page = client.get(m.get_absolute_url()).content.decode()
    assert "From Website" in page and "Reset to default" not in page  # untouched: nothing to reset
    m.name = "Renamed"
    m.save()
    page = client.get(m.get_absolute_url()).content.decode()
    reset = reverse("dashboards_default_reset", args=["metric", m.pk])
    assert "From Website · customised" in page and f'hx-get="{reset}?next=' in page
    modal = client.get(reset, HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in modal and "exactly as Website ships it now" in modal and "are replaced" in modal
    assert client.post(reset, {"next": m.get_absolute_url()}).status_code == 302
    m.refresh_from_db()
    assert m.name == "Requests"
    # A row made here has no reset; a viewer who can't edit gets nothing.
    mine = Metric(key="mine", name="Mine", dataset=DS)
    mine.save()
    assert client.get(reverse("dashboards_default_reset", args=["metric", mine.pk])).status_code == 404
    client.force_login(User.objects.create_user("viewer", password="x"))
    assert client.get(reset).status_code == 404
