"""G3-1: one-time credential tokens never reach a staff-readable log.

A password-reset link GET'd once sat in ``RequestLog.path`` and the Activity
pages showed it to every staff account; a staff account with no permissions
replayed it and took over a superuser. These tests drive the real middleware
with real reset/invite tokens and read back the row, the pages, the log
capture and the upgrade migrations.
"""

from __future__ import annotations

import importlib
import json
import logging

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.smallstack.logging import JSONFormatter, extract_extra
from apps.smallstack.redaction import redact_path, redact_text
from apps.telemetry.handlers import DatabaseLogHandler

from ..models import RequestLog

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def victim():
    return User.objects.create_superuser("g31_victim", "victim@example.com", "Victim-pass-123")


@pytest.fixture
def snoop():
    # Staff with zero permissions: the G3-1 attacker.
    return User.objects.create_user("g31_snoop", "snoop@example.com", "Snoop-pass-123", is_staff=True)


def _uid(user) -> str:
    return urlsafe_base64_encode(force_bytes(user.pk))


def _reset_path(user) -> tuple[str, str]:
    token = default_token_generator.make_token(user)
    return reverse("password_reset_confirm", kwargs={"uidb64": _uid(user), "token": token}), token


def _invite_path(user) -> tuple[str, str]:
    token = default_token_generator.make_token(user)
    return reverse("accounts:invite_accept", kwargs={"uidb64": _uid(user), "token": token}), token


def _all_paths() -> list[str]:
    return list(RequestLog.objects.values_list("path", flat=True))


class TestRecordTime:
    def test_reset_link_token_is_not_stored(self, victim):
        path, token = _reset_path(victim)
        response = Client().get(path)
        assert response.status_code == 302  # Django moves the token into the session
        stored = [p for p in _all_paths() if "/accounts/reset/" in p]
        assert stored, "the reset GET should still be logged"
        assert all(token not in p for p in _all_paths())
        assert f"/accounts/reset/{_uid(victim)}/***/" in stored[-1] or any(
            p.endswith(f"/accounts/reset/{_uid(victim)}/***/") for p in stored
        )

    def test_set_password_step_keeps_its_placeholder(self, victim):
        path, _ = _reset_path(victim)
        client = Client()
        location = client.get(path)["Location"]
        client.get(location)
        assert any(p.endswith(f"/accounts/reset/{_uid(victim)}/set-password/") for p in _all_paths())

    def test_invite_link_token_is_not_stored(self, victim):
        path, token = _invite_path(victim)
        Client().get(path)
        assert all(token not in p for p in _all_paths())
        assert any(p.endswith(f"/accounts/invite/{_uid(victim)}/***/") for p in _all_paths())

    def test_route_is_kept(self, victim):
        path, _ = _reset_path(victim)
        Client().get(path)
        row = RequestLog.objects.filter(path__contains="/accounts/reset/").latest("timestamp")
        assert row.route.endswith("/accounts/reset/<uidb64>/<token>/")


class TestStaffSurfaces:
    def test_activity_pages_do_not_show_the_token(self, victim, snoop):
        path, token = _reset_path(victim)
        Client().get(path)
        client = Client()
        client.force_login(snoop)
        for name in ("activity:requests", "activity:dashboard", "activity:resources"):
            response = client.get(reverse(name))
            assert response.status_code == 200, name  # staff with no permissions reads these
            assert token not in response.content.decode(), name
        body = client.get(reverse("activity:requests") + "?q=reset").content.decode()
        assert token not in body

    def test_snoop_cannot_replay_what_the_log_shows(self, victim, snoop):
        path, token = _reset_path(victim)
        Client().get(path)
        shown = RequestLog.objects.filter(path__contains="/accounts/reset/").latest("timestamp").path
        attacker = Client()
        response = attacker.get(shown)
        # The redacted link is not a valid token: no redirect into set-password.
        assert response.status_code == 200
        assert response.context["validlink"] is False


class TestPatterns:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/smallstack/accounts/reset/MQ/cx3-abc123/", "/smallstack/accounts/reset/MQ/***/"),
            ("/tools/accounts/invite/Mg/cx3-abc123/", "/tools/accounts/invite/Mg/***/"),
            ("/blog/subscribe/confirm/eyJ:1x:sig/", "/blog/subscribe/confirm/***/"),
            ("/blog/unsubscribe/eyJ:1x:sig/", "/blog/unsubscribe/***/"),
            ("/smallstack/accounts/reset/MQ/set-password/", "/smallstack/accounts/reset/MQ/set-password/"),
            ("/smallstack/dashboards/defaults/reset/metric/4/", "/smallstack/dashboards/defaults/reset/metric/4/"),
        ],
    )
    def test_shapes(self, path, expected):
        assert redact_path(path) == expected

    def test_route_driven_redaction_covers_a_new_token_route(self):
        assert redact_path("/x/magic/abc123/", "/x/magic/<str:token>/") == "/x/magic/***/"

    def test_query_credentials(self):
        assert redact_text("/feeds/a.rss?token=sk_123&fmt=atom") == "/feeds/a.rss?token=***&fmt=atom"
        assert redact_text("cb?code=abc&state=s1") == "cb?code=***&state=s1"


class TestLogCapture:
    def _record(self, msg: str, *args, **extra) -> logging.LogRecord:
        record = logging.LogRecord("django.security.csrf", logging.WARNING, __file__, 1, msg, args, None)
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def test_telemetry_row_is_redacted(self, victim):
        path, token = _invite_path(victim)
        request = RequestFactory().post(path + "?token=sk_live")
        record = self._record("Forbidden (CSRF token missing.): %s", path, request=request, link=path)
        row = DatabaseLogHandler(start_worker=False)._to_row(record)
        assert token not in row["message"]
        assert token not in json.dumps(row["extra"])
        assert "sk_live" not in json.dumps(row["extra"])

    def test_json_formatter_is_redacted(self, victim):
        path, token = _reset_path(victim)
        line = JSONFormatter().format(self._record("Not Found: %s", path))
        assert token not in line
        assert "/accounts/reset/" in line

    def test_extract_extra_redacts_a_request(self, victim):
        path, token = _reset_path(victim)
        request = RequestFactory().get(path)
        assert token not in str(extract_extra(self._record("x", request=request)))


class TestAccessSource:
    def test_actor_middleware_source_is_redacted(self, victim):
        from apps.access.context import ActorMiddleware, current_source

        path, token = _invite_path(victim)
        seen = {}

        def get_response(request):
            seen["source"] = current_source()
            from django.http import HttpResponse

            return HttpResponse()

        ActorMiddleware(get_response)(RequestFactory().get(path))
        assert token not in seen["source"]
        assert seen["source"].endswith("/***/")


class TestUpgradeMigrations:
    def test_activity_migration_redacts_old_rows(self, victim):
        path, token = _reset_path(victim)
        invite, invite_token = _invite_path(victim)
        RequestLog.objects.create(path=path, route="", method="GET", status_code=302, response_time_ms=1)
        RequestLog.objects.create(
            path=invite,
            route="/smallstack/accounts/invite/<uidb64>/<token>/",
            method="GET",
            status_code=200,
            response_time_ms=1,
        )
        RequestLog.objects.create(path="/plain/", method="GET", status_code=200, response_time_ms=1)
        module = importlib.import_module("apps.activity.migrations.0005_redact_token_paths")
        module.redact_paths(django_apps, None)
        paths = _all_paths()
        assert all(token not in p and invite_token not in p for p in paths)
        assert "/plain/" in paths
        assert sum(p.endswith("/***/") for p in paths) == 2

    def test_telemetry_migration_redacts_old_rows(self, victim):
        from apps.telemetry.models import LogRecord

        path, token = _invite_path(victim)
        from django.utils import timezone

        LogRecord.objects.create(
            ts=timezone.now(),
            level="WARNING",
            level_no=30,
            logger="django.security.csrf",
            message=f"Forbidden (CSRF token missing.): {path}",
            extra={"request": f"<WSGIRequest: POST '{path}'>"},
        )
        module = importlib.import_module("apps.telemetry.migrations.0002_redact_token_text")
        module.redact_rows(django_apps, None)
        row = LogRecord.objects.get()
        assert token not in row.message
        assert token not in json.dumps(row.extra)


class TestEverySinkOfThePath:
    """Every page that reads RequestLog.path, read as a superuser (the widest reader)."""

    def test_no_surface_shows_the_token(self, victim, snoop):
        path, token = _reset_path(victim)
        Client(SERVER_NAME="localhost").get(path)
        row = RequestLog.objects.filter(path__contains="/accounts/reset/").latest("timestamp")
        reader = Client(SERVER_NAME="localhost")
        reader.force_login(victim)
        urls = [
            reverse("activity:dashboard"),
            reverse("activity:requests"),
            reverse("activity:requests") + "?q=reset",
            reverse("activity:resources"),
            reverse("activity:resource_detail") + "?r=" + row.resource_key,
            "/smallstack/activity/stat/top_paths/",
            "/smallstack/api/activity/",
            "/smallstack/mcp/activity/",
            "/smallstack/explorer/monitoring/requestlog/",
            f"/smallstack/explorer/monitoring/requestlog/{row.pk}/",
            f"/smallstack/explorer/monitoring/requestlog/{row.pk}/field-preview/path/",
            "/admin/activity/requestlog/",
            f"/admin/activity/requestlog/{row.pk}/change/",
            "/smallstack/datasets/browse/",
            "/smallstack/datasets/browse/smallstack_requests/",
            "/smallstack/datasets/smallstack_requests/",
            "/smallstack/datasets/smallstack_requests/series/?dimension=path",
            "/smallstack/logs/",
        ]
        checked = 0
        for url in urls:
            response = reader.get(url)
            if response.status_code == 200:
                checked += 1
            assert token not in response.content.decode(errors="replace"), url
        assert checked >= 10
