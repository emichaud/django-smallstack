"""The task-reliability system checks (``apps/tasks/checks.py``).

Each check guards an invariant whose violation is an *absence* — no heartbeat,
no reaper — and therefore produces no symptom until a worker dies. The most
important assertion in this module is the first one: none of them may fire on
shipped defaults, because the harness smoke battery runs ``check --deploy`` and
a warning there is a failed deploy gate.
"""

from __future__ import annotations

import pytest
from django.core.checks.registry import run_checks

from apps.tasks import checks


def _ids(results) -> list[str]:
    return [r.id for r in results]


def test_no_check_fires_on_shipped_defaults():
    assert _ids(checks.check_db_worker_is_not_shadowed(None)) == []
    assert _ids(checks.check_lost_after_is_several_beats(None)) == []
    assert _ids(checks.check_use_tz_is_enabled(None)) == []
    assert _ids(checks.check_retryable_failures_are_not_logged_as_errors(None)) == []


@pytest.mark.django_db  # some of Django's own deploy checks touch the connection
def test_no_tasks_check_fires_under_check_deploy():
    """The smoke battery's gate: `check --deploy` must gain nothing from us.

    Asserted against the registry rather than the command's output, because the
    development settings legitimately raise unrelated `security.W*` warnings
    (and `call_command` turns any issue into SystemCheckError). What matters here
    is only that this app contributes none of them on shipped defaults.
    """
    results = run_checks(include_deployment_checks=True)
    assert [r.id for r in results if str(r.id).startswith("tasks.")] == []


class TestShadowingCheck:
    def test_warns_when_another_app_owns_db_worker(self, monkeypatch):
        monkeypatch.setattr(
            "django.core.management.get_commands",
            lambda: {"db_worker": "someone_elses_app"},
        )
        results = checks.check_db_worker_is_not_shadowed(None)
        assert _ids(results) == ["tasks.W001"]
        assert "someone_elses_app" in results[0].msg
        assert "subclass" in results[0].hint

    def test_silent_when_we_own_it(self, monkeypatch):
        monkeypatch.setattr("django.core.management.get_commands", lambda: {"db_worker": "apps.tasks"})
        assert checks.check_db_worker_is_not_shadowed(None) == []

    def test_silent_when_the_command_is_absent_entirely(self, monkeypatch):
        monkeypatch.setattr("django.core.management.get_commands", lambda: {})
        assert checks.check_db_worker_is_not_shadowed(None) == []

    def test_silent_when_heartbeats_are_deliberately_disabled(self, settings, monkeypatch):
        """A documented opt-out must not produce a warning.

        With SMALLSTACK_TASKS_HEARTBEAT_ENABLED=False our db_worker is a pure
        pass-through, so which command resolves changes nothing — and the
        warning's text ("background workers run without a heartbeat") describes
        exactly what the operator configured on purpose.
        """
        settings.SMALLSTACK_TASKS_HEARTBEAT_ENABLED = False
        monkeypatch.setattr(
            "django.core.management.get_commands", lambda: {"db_worker": "someone_elses_app"}
        )
        assert checks.check_db_worker_is_not_shadowed(None) == []

    def test_still_warns_when_heartbeats_are_enabled(self, settings, monkeypatch):
        """The guard must not swallow the real case."""
        settings.SMALLSTACK_TASKS_HEARTBEAT_ENABLED = True
        monkeypatch.setattr(
            "django.core.management.get_commands", lambda: {"db_worker": "someone_elses_app"}
        )
        assert _ids(checks.check_db_worker_is_not_shadowed(None)) == ["tasks.W001"]


class TestRatioCheck:
    @pytest.mark.parametrize(
        ("beat", "lost_after", "expected"),
        [
            (15, 90, []),  # shipped: 6 beats
            (15, 45, []),  # exactly 3 beats: the boundary is inclusive
            (15, 44, ["tasks.W002"]),  # just under
            (15, 15, ["tasks.W002"]),  # one beat: a single skip reaps live tasks
            (30, 90, []),  # scaled up, still 3 beats
            (60, 90, ["tasks.W002"]),  # raising the beat alone breaks the ratio
        ],
    )
    def test_ratio_boundary(self, settings, beat, lost_after, expected):
        settings.SMALLSTACK_TASKS_HEARTBEAT_SECONDS = beat
        settings.SMALLSTACK_TASKS_LOST_AFTER_SECONDS = lost_after
        assert _ids(checks.check_lost_after_is_several_beats(None)) == expected

    def test_a_nonsense_beat_interval_is_reported_not_divided_by(self, settings):
        settings.SMALLSTACK_TASKS_HEARTBEAT_SECONDS = 0
        assert _ids(checks.check_lost_after_is_several_beats(None)) == ["tasks.W003"]


class TestLogTakeoverCheck:
    """tasks.W005 — the Finding B fail-safe must not degrade silently.

    `signals.py` disconnects Django's blanket ERROR logger for finished tasks.
    If that ever fails it deliberately leaves Django's in place rather than
    double-logging, which means it falls back into the exact defect it was built
    to fix. A startup warning can be missed; a check is asked for by name on
    every manage.py command.
    """

    def test_silent_when_the_takeover_succeeded(self):
        from apps.tasks import signals

        assert signals.TOOK_OVER_TASK_LOGGING is True, "the takeover itself regressed"
        assert checks.check_retryable_failures_are_not_logged_as_errors(None) == []

    def test_warns_when_the_takeover_failed(self, monkeypatch):
        from apps.tasks import signals

        monkeypatch.setattr(signals, "TOOK_OVER_TASK_LOGGING", False)
        results = checks.check_retryable_failures_are_not_logged_as_errors(None)
        assert _ids(results) == ["tasks.W005"]
        assert "being retried" in results[0].msg
        assert "chain_outcome" in results[0].hint


class TestUseTzCheck:
    def test_warns_when_use_tz_is_off(self, settings):
        settings.USE_TZ = False
        results = checks.check_use_tz_is_enabled(None)
        assert _ids(results) == ["tasks.W004"]
        assert "reaper" in results[0].msg

    def test_silent_when_use_tz_is_on(self, settings):
        settings.USE_TZ = True
        assert checks.check_use_tz_is_enabled(None) == []
