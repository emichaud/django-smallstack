"""An ICS ``UID`` must identify the event, not the URL it was fetched from.

RFC 5545 §3.8.4.7 wants a UID that is globally unique *and* persistent — it is
how a subscribed client recognises an event it already has. It used to be built
from ``request.get_host()``, so the same row answered ``…@localhost:8055`` to
one caller and ``…@localhost`` to another, differing only by the port.

A feed is subscribed once and polled for months. The day the host changes
(dev → prod, a new domain, a proxy forwarding a different ``Host``) every event
re-appears as new: duplicates accumulate in the subscriber's client and the
originals stop updating, because nothing matches them any more. It surfaces
later, on someone else's screen, and reads as the calendar being broken.

Found by the integration harness, 2026-10-28.
"""

from __future__ import annotations

import re

import pytest
from django.test import Client, override_settings
from django.utils import timezone

pytestmark = pytest.mark.django_db

UID_RE = re.compile(r"^UID:(.+)$", re.MULTILINE)


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_user(
        username="ics-staff", password="x", is_staff=True, is_superuser=True
    )


@pytest.fixture
def an_event(staff):
    """One row on a bundled staff calendar, so the feed is never empty."""
    from apps.heartbeat.models import MaintenanceWindow

    now = timezone.now()
    return MaintenanceWindow.objects.create(
        title="ICS-UID-PROBE", start=now, end=now + timezone.timedelta(hours=2)
    )


def _uids(client: Client, host: str) -> list[str]:
    response = client.get(
        "/smallstack/calendar/api/events.ics",
        {"ds": "smallstack_maintenance_windows"},
        HTTP_HOST=host,
    )
    assert response.status_code == 200, response.status_code
    return [u.strip() for u in UID_RE.findall(response.content.decode())]


@override_settings(
    SITE_DOMAIN="cal.example.com", ALLOWED_HOSTS=["*"], SMALLSTACK_CALENDAR_ENABLED=True
)
def test_uid_is_identical_across_hosts_and_ports(client, staff, an_event):
    """The regression: same row, same database, different Host → same UID."""
    client.force_login(staff)

    from_a = _uids(client, "localhost")
    from_b = _uids(client, "localhost:8055")
    from_c = _uids(client, "some-proxy.internal")

    assert from_a, "no events in the feed — the probe proves nothing"
    assert from_a == from_b == from_c, (
        f"UID changed with the request host: {from_a} / {from_b} / {from_c}"
    )
    assert from_a[0].endswith("@cal.example.com"), from_a[0]


@override_settings(SITE_DOMAIN="cal.example.com", ALLOWED_HOSTS=["*"])
def test_uid_keeps_the_stable_identifier_on_the_left(client, staff, an_event):
    """`{calendar}-{pk}` was always stable; only the domain was not."""
    client.force_login(staff)
    uid = _uids(client, "localhost")[0]

    local, _, domain = uid.partition("@")
    assert local == f"smallstack_maintenance_windows-{an_event.pk}"
    assert domain == "cal.example.com"


class TestUidDomainResolution:
    """`SITE_DOMAIN` first, then a URL-shaped setting, then the request.

    ``_uid_domain`` is imported per-test rather than at module scope so the
    behavioural tests above still COLLECT against a tree without it — otherwise
    the file errors at import and proves nothing about the regression.
    """

    @override_settings(SITE_DOMAIN="cal.example.com")
    def test_site_domain_wins(self):
        from apps.calendar.api import _uid_domain

        assert _uid_domain(None) == "cal.example.com"

    @override_settings(SITE_DOMAIN="cal.example.com:8443")
    def test_port_is_stripped(self):
        """:8000 and :8055 are the same deployment."""
        from apps.calendar.api import _uid_domain

        assert _uid_domain(None) == "cal.example.com"

    @override_settings(SITE_DOMAIN="", SITE_URL="https://from-url.example.com")
    def test_falls_back_to_a_url_shaped_setting(self):
        from apps.calendar.api import _uid_domain

        assert _uid_domain(None) == "from-url.example.com"

    @override_settings(SITE_DOMAIN="", SITE_URL="", SMALLSTACK_SITE_URL="", BASE_URL="")
    def test_falls_back_to_a_constant_rather_than_an_empty_domain(self):
        """An empty right-hand side would make the UID malformed."""
        from apps.calendar.api import _uid_domain

        assert _uid_domain(None) == "smallstack"

    @override_settings(SITE_DOMAIN="", SITE_URL="", ALLOWED_HOSTS=["*"])
    def test_request_host_is_the_last_resort_not_the_first(self, rf):
        """An unconfigured deployment still emits something usable."""
        from apps.calendar.api import _uid_domain

        assert _uid_domain(rf.get("/", HTTP_HOST="fallback.example.org:9000")) == (
            "fallback.example.org"
        )
