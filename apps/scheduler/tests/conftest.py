"""Isolate the scheduler's tick tests from code-declared schedules.

``services.run_due_jobs()`` is a **global** tick: it runs every job that is
due, not just the one a test created. But the DB is also populated with a
``ScheduledJob`` row for every ``@scheduled`` declaration in the project,
synced lazily on the first tick in a process (``_ensure_code_jobs_synced``).

So a test asserting ``result.enqueued == 0`` is implicitly asserting "no app
anywhere in this project has a code job that happens to be due right now" —
which is not a property of the scheduler, and not one any test can keep true.
It held only while every bundled cadence was long enough (5m, 15m, daily) to
stay in the future for the length of a suite run. Adding a one-minute job
broke eight tests that have nothing to do with it, intermittently, depending
on how long the run had been going. A downstream project with a frequent job
would hit the same thing, with no clue where to look.

This fixture makes each tick test see only the rows it created:

* ``_code_jobs_synced`` is forced ``True`` so the lazy sync does not fire
  mid-test (the one test that *wants* the sync overrides this itself);
* any ``source=CODE`` row is removed before the test body runs.

Tests that assert *on* the sync keep working — they reset the flag through
``monkeypatch``, which still wins because this runs first.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_code_jobs(request):
    """Remove code-declared schedules so a global tick only sees test data."""
    # Only meaningful for DB tests; skip the rest so no DB is opened needlessly.
    if "django_db" not in request.keywords and "db" not in request.fixturenames:
        yield
        return

    from apps.scheduler import services
    from apps.scheduler.models import ScheduledJob

    previous = services._code_jobs_synced
    services._code_jobs_synced = True
    ScheduledJob.objects.filter(source=ScheduledJob.Source.CODE).delete()
    try:
        yield
    finally:
        services._code_jobs_synced = previous
