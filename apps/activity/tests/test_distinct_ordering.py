"""`.values_list(...).distinct()` on a model with Meta.ordering returns duplicates.

Django adds the ordering column to the SELECT list so it can sort, which means
``DISTINCT`` applies to the *pair* — ``(path, timestamp)`` — not to the column
asked for. The queryset then yields one row per table row.

``.count()`` is unaffected (Django clears the ordering for aggregates), which is
what made this easy to miss: the counters on the activity pages were right while
the iterating call sites next to them were not.

Found by the integration harness, 2026-10-26, in four places:

* ``activity/migrations/0004_requestlog_route`` — the backfill resolved one URL
  per *row* instead of per distinct path, contradicting its own docstring.
* ``api/threats.py`` (×5) — the threat panel's "sample paths" showed the same
  path two or three times, spending an operator's sample slots on duplicates.
* ``activity/views.py`` — the inactive-users tab built a row-sized ``pk__in``
  list instead of a distinct one.
* ``tasks/reliability.py`` — the repair sweep called ``policy_for()`` once per
  row on a path it had already decided about.
"""

from __future__ import annotations

import pytest

from apps.activity.models import RequestLog

pytestmark = pytest.mark.django_db


def _log(path: str, **kw):
    return RequestLog.objects.create(
        path=path,
        method=kw.pop("method", "GET"),
        status_code=kw.pop("status_code", 200),
        response_time_ms=kw.pop("response_time_ms", 1),
        **kw,
    )


def test_requestlog_still_has_the_ordering_that_causes_this():
    """If this ever changes, the fixes below become no-ops rather than wrong."""
    assert RequestLog._meta.ordering == ["-timestamp"]


def test_distinct_paths_without_order_by_are_not_distinct():
    """Pins the underlying behaviour, so the fixes are not cargo-culted."""
    for _ in range(5):
        _log("/same/")

    naive = list(RequestLog.objects.values_list("path", flat=True).distinct())
    fixed = list(RequestLog.objects.order_by().values_list("path", flat=True).distinct())

    assert len(naive) == 5, "Meta.ordering no longer leaks into the SELECT"
    assert fixed == ["/same/"]


def test_count_is_unaffected_so_the_page_counters_were_always_right():
    for _ in range(5):
        _log("/same/")
    assert RequestLog.objects.values("path").distinct().count() == 1


def test_threat_panel_sample_paths_have_no_duplicates():
    """The probe shape: one address hammering one path, plus a second path."""
    from apps.api import threats

    for _ in range(20):
        _log("/wp-login.php", status_code=404, ip_address="10.0.0.9", method="POST")
    _log("/xmlrpc.php", status_code=404, ip_address="10.0.0.9", method="POST")

    log_qs = RequestLog.objects.filter(ip_address="10.0.0.9")
    samples = list(log_qs.order_by().values_list("path", flat=True).distinct()[:3])

    assert len(samples) == len(set(samples)), f"duplicate sample paths: {samples}"
    assert set(samples) == {"/wp-login.php", "/xmlrpc.php"}
    # and the module really uses the corrected form
    source = open(threats.__file__).read()
    assert 'log_qs.values_list("path", flat=True).distinct()[:3]' not in source


def test_inactive_tab_seen_set_is_distinct(django_user_model):
    """The inactive tab excludes `pk__in=seen`; `seen` must not be row-sized.

    Duplicates in an ``IN`` clause do not change the result, which is why this
    was invisible — but on a busy site the list grew to one entry per request
    row instead of one per user. Asserted on the view's source as well as the
    behaviour, since the symptom is the query's size, not its output.
    """
    import inspect

    from apps.activity import views

    user = django_user_model.objects.create_user(username="seen-probe", password="x")
    for _ in range(6):
        _log("/x/", user=user)

    seen = list(
        RequestLog.objects.filter(user__isnull=False)
        .order_by()
        .values_list("user__pk", flat=True)
        .distinct()
    )
    assert seen == [user.pk]

    source = inspect.getsource(views)
    assert 'values_list("user__pk", flat=True).distinct()' not in source, (
        "the inactive tab still builds `seen` without clearing Meta.ordering"
    )


def test_the_backfill_migration_resolves_each_path_once():
    """The migration's own docstring claims this; it did not hold.

    Asserted on the source because a historical migration must keep working on
    databases that already ran it — the behaviour cannot be re-exercised here.
    """
    import importlib
    import inspect

    module = importlib.import_module("apps.activity.migrations.0004_requestlog_route")
    source = inspect.getsource(module.backfill_routes)

    assert ".order_by()" in source, "the backfill still iterates once per row"
