"""Linked cards: a click on one card narrows another. The bus is in the page
(cards.js); the server's part is that a listening card redraws narrowed to the
slice it's sent, mapped to its columns, checked against its data, and only
ever narrowed — never widened, never pointed at a column it doesn't have."""

from __future__ import annotations

import json
from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.dashboards.models import Dashboard
from apps.dashboards.tests.test_dashboards import DS_STAFF, _seed

pytestmark = pytest.mark.django_db

SRC = {"dataset": DS_STAFF, "filter_tree": {}, "agg": "count", "measure": "", "period_field": "timestamp"}
GET = json.dumps({"field": "method", "op": "=", "value": "GET"})


@pytest.fixture
def staff(client):
    user = get_user_model().objects.create_user("lk-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


def _board(*cells):
    d = Dashboard(name="Linked", slug="linked", layout=list(cells))
    d.save()
    return d


def _cell(client, cell_id, narrow=""):
    url = f"/smallstack/dashboards/d/linked/cells/{cell_id}/"
    return client.get(url + (f"?narrow={quote(narrow)}" if narrow else "")).content.decode()


def test_a_listening_card_redraws_narrowed_to_what_it_was_sent(client, staff):
    _seed()  # GET ×3, POST, DELETE
    _board(
        {"id": "by", "type": "pie", **SRC, "x": 0, "y": 0, "w": 4, "h": 3,
         "options": {"dimension": "method", "publish": "verb"}},
        {"id": "n", "type": "metric", **SRC, "x": 4, "y": 0, "w": 3, "h": 2,
         "options": {"listen": {"channel": "verb"}}},
        {"id": "t", "type": "table", **SRC, "x": 0, "y": 3, "w": 6, "h": 4,
         "options": {"rows": 10, "listen": {"channel": "verb"}, "drilldown": {"columns": ["method", "path"]}}},
    )
    assert ">5<" in _cell(client, "n")
    narrowed = _cell(client, "n", GET)
    assert ">3<" in narrowed
    # Its rows open narrowed too: the slice rides on every rows link it draws.
    assert "rows/?narrow=" in narrowed and "%22GET%22" in narrowed
    table = _cell(client, "t", GET)
    assert "3 rows" in table and ">POST<" not in table
    # The page marks who sends and who listens, for cards.js.
    page = client.get("/smallstack/dashboards/d/linked/").content.decode()
    assert 'data-cell-id="by" data-publish="verb"' in page and 'data-cell-id="n" data-listen="verb"' in page


def test_a_slice_only_narrows_and_is_refused_rather_than_dropped(client, staff):
    _seed()
    _board(
        {"id": "n", "type": "metric", **{**SRC, "filter_tree": {"field": "method", "op": "=", "value": "POST"}},
         "options": {"listen": {"channel": "verb"}}},
        {"id": "plain", "type": "metric", **SRC, "x": 3, "options": {}},
    )
    assert ">0<" in _cell(client, "n", GET)  # POST AND GET: nothing — the card's own filter still holds
    bad = json.dumps({"field": "nope", "op": "=", "value": "x"})
    assert "filters a column this card" in _cell(client, "n", bad)  # never the whole set under a narrowed heading
    assert "listen to other cards" in _cell(client, "plain", GET)
    assert "sent to this card isn" in _cell(client, "n", "{not json")


def test_a_map_points_their_column_at_mine(client, staff):
    _seed()
    _board({"id": "n", "type": "metric", **SRC, "options": {"listen": {"channel": "s", "map": {"verb": "method"}}}})
    assert ">3<" in _cell(client, "n", json.dumps({"field": "verb", "op": "=", "value": "GET"}))


def test_a_listener_that_publishes_sends_its_slice_on(client, staff):
    """Chaining: the second card's clicks carry the first card's slice too."""
    _seed()
    options = {"dimension": "status_code", "publish": "b", "listen": {"channel": "a"}}
    _board({"id": "by", "type": "ranked", **SRC, "options": options})
    html = _cell(client, "by", GET)
    links = [part.split('"')[0] for part in html.split("rows/?narrow=")[1:]]
    assert links and all("%22GET%22" in link and "status_code" in link for link in links)  # the slice AND its own group


@pytest.mark.parametrize(
    "cell, reason",
    [
        ({"type": "text", "options": {"markdown": "x", "publish": "a"}}, "draws no data"),
        ({"type": "metric", **SRC, "options": {"publish": "Has Spaces"}}, "channel name"),
        ({"type": "table", **SRC, "options": {"listen": {"channel": "a"}, "publish": "a"}}, "listen.channel"),
        ({"type": "metric", **SRC, "options": {"listen": {"channel": "a", "map": {"x": "ghost"}}}}, "column 'ghost'"),
        ({"type": "metric", **SRC, "options": {"listen": "a"}}, "listen:"),
    ],
)
def test_links_are_checked_on_save(cell, reason):
    with pytest.raises(ValidationError, match=reason):
        Dashboard(name="B", slug="b", layout=[cell]).full_clean()


# -- a calendar's days -----------------------------------------------------------------

DAY = json.dumps(
    {"and": [{"field": "date", "op": ">=", "value": "2026-01-02"}, {"field": "date", "op": "<", "value": "2026-01-03"}]}
)


def _calendar_key(user):
    from apps.calendar.dashboard_cards import calendar_choices

    return calendar_choices(user)[0][0]


def test_a_calendar_card_sends_its_days_and_can_be_checked(client, staff):
    key = _calendar_key(staff)
    _board(
        {"id": "cal", "type": "calendar", "x": 0, "y": 0, "w": 4, "h": 4,
         "options": {"calendars": key, "mode": "month", "publish": "day"}},
        {"id": "t", "type": "table", **SRC, "x": 4, "y": 0, "w": 8, "h": 4, "options": {"listen": {"channel": "day"}}},
    )
    cell = _cell(client, "cal")
    assert 'data-day="' in cell and "data-day-label=" in cell  # each day carries what a click sends
    page = client.get("/smallstack/dashboards/d/linked/").content.decode()
    assert 'data-cell-id="cal" data-publish="day"' in page
    with pytest.raises(ValidationError, match="nothing to narrow"):
        Dashboard(name="B", slug="b", layout=[
            {"type": "calendar", "options": {"calendars": key, "listen": {"channel": "x"}}}
        ]).full_clean()


def test_a_day_lands_on_the_listeners_own_date_column(client, staff):
    """A calendar sends a day on "date"; a listener reads it on its period
    column, or on the column its map names, or says why it can't."""
    from datetime import datetime

    from django.utils import timezone

    from apps.activity.models import RequestLog

    _seed()
    on_the_day = timezone.make_aware(datetime(2026, 1, 2, 12, 0))
    first = RequestLog.objects.order_by("pk").first()
    RequestLog.objects.filter(pk=first.pk).update(timestamp=on_the_day)
    no_period = {**SRC, "period_field": ""}
    _board(
        {"id": "n", "type": "metric", **SRC, "options": {"listen": {"channel": "day"}}},
        {"id": "m", "type": "metric", **no_period, "x": 3,
         "options": {"listen": {"channel": "day", "map": {"date": "timestamp"}}}},
        {"id": "none", "type": "metric", **no_period, "x": 6, "options": {"listen": {"channel": "day"}}},
    )
    assert ">1<" in _cell(client, "n", DAY)  # its period column, by default
    assert ">1<" in _cell(client, "m", DAY)  # the column its map names
    assert "no period column" in _cell(client, "none", DAY)
