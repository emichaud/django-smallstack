"""Repeating events: the dates a rule produces, and every surface reading them."""

from __future__ import annotations

from datetime import date, time

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.calendar.api import render_ics
from apps.calendar.core import collect_events, get_calendar
from apps.calendar.datasets import EVENTS_KEY, events_provider
from apps.calendar.models import Event
from apps.calendar.recurrence import describe, is_occurrence, occurrence_starts

User = get_user_model()


def dates(start, repeat, lower, upper, **kw):
    return list(occurrence_starts(start, repeat, lower, upper, **kw))


class TestRules:
    def test_weekly(self):
        assert dates(date(2026, 1, 5), "weekly", date(2026, 1, 1), date(2026, 1, 20)) == [
            date(2026, 1, 5),
            date(2026, 1, 12),
            date(2026, 1, 19),
        ]

    def test_it_never_starts_before_its_first_day(self):
        assert dates(date(2026, 1, 5), "daily", date(2025, 1, 1), date(2026, 1, 7)) == [
            date(2026, 1, 5),
            date(2026, 1, 6),
        ]

    def test_an_old_series_lands_on_its_own_days_in_a_later_window(self):
        got = dates(date(2020, 1, 6), "biweekly", date(2026, 1, 1), date(2026, 1, 31))
        assert got and all((d - date(2020, 1, 6)).days % 14 == 0 for d in got)

    def test_weekdays_skip_the_weekend(self):
        got = dates(date(2026, 1, 5), "weekdays", date(2026, 1, 5), date(2026, 1, 12))
        assert len(got) == 5 and all(d.weekday() < 5 for d in got)

    def test_the_31st_falls_on_the_last_day_of_a_shorter_month(self):
        assert dates(date(2026, 1, 31), "monthly", date(2026, 2, 1), date(2026, 5, 1)) == [
            date(2026, 2, 28),
            date(2026, 3, 31),
            date(2026, 4, 30),
        ]

    def test_a_clamped_date_doesnt_drift_afterwards(self):
        got = dates(date(2026, 1, 31), "monthly", date(2026, 1, 1), date(2027, 2, 1))
        assert date(2026, 3, 31) in got and len(got) == 13

    def test_the_same_weekday_each_month(self):
        # Jan 13, 2026 is the 2nd Tuesday.
        got = dates(date(2026, 1, 13), "monthly_weekday", date(2026, 1, 1), date(2026, 4, 1))
        assert got == [date(2026, 1, 13), date(2026, 2, 10), date(2026, 3, 10)]
        assert all(d.weekday() == 1 for d in got)

    def test_a_fifth_weekday_is_the_last_one_where_there_is_no_fifth(self):
        # Jan 30, 2026 is the 5th Friday; Feb 2026 has four.
        assert dates(date(2026, 1, 30), "monthly_weekday", date(2026, 2, 1), date(2026, 3, 1)) == [date(2026, 2, 27)]

    def test_feb_29_each_year(self):
        assert dates(date(2024, 2, 29), "yearly", date(2025, 1, 1), date(2029, 1, 1)) == [
            date(2025, 2, 28),
            date(2026, 2, 28),
            date(2027, 2, 28),
            date(2028, 2, 29),
        ]

    def test_until_is_the_last_date_it_may_start(self):
        assert dates(date(2026, 1, 5), "weekly", date(2026, 1, 1), date(2026, 3, 1), until=date(2026, 1, 12))[
            -1
        ] == date(2026, 1, 12)

    def test_a_multi_day_occurrence_reaches_into_a_window_it_started_before(self):
        assert dates(date(2026, 1, 5), "weekly", date(2026, 1, 7), date(2026, 1, 8), span_days=2) == [date(2026, 1, 5)]

    def test_skip(self):
        assert date(2026, 1, 12) not in dates(
            date(2026, 1, 5), "weekly", date(2026, 1, 1), date(2026, 2, 1), skip=frozenset({date(2026, 1, 12)})
        )

    def test_describe(self):
        e = Event(start_date=date(2026, 1, 13), repeat="monthly_weekday", repeat_until=date(2026, 6, 1))
        assert describe(e) == "Every month on the 2nd Tuesday, until Jun 1, 2026"


@pytest.mark.django_db
class TestSeries:
    @pytest.fixture
    def author(self):
        return User.objects.create_user("rc-author", password="x")

    def series(self, author, **kw):
        defaults = {"title": "Ops meeting", "start_date": date(2026, 1, 5), "repeat": "weekly", "created_by": author}
        e = Event(**{**defaults, **kw})
        e.full_clean()
        e.save()
        return e

    def provided(self, author, lower, upper):
        from apps.dashboards.metrics import request_for

        return list(events_provider(lower, upper, request_for(author)))

    def test_it_appears_on_every_date_in_the_window(self, author):
        self.series(author)
        got = self.provided(author, date(2026, 1, 1), date(2026, 2, 1))
        assert [e.start_date.day for e in got] == [5, 12, 19, 26]

    def test_a_series_that_began_long_ago_still_shows(self, author):
        self.series(author, start_date=date(2020, 1, 6))
        assert self.provided(author, date(2026, 1, 1), date(2026, 2, 1))

    def test_ids_are_stable_and_distinct_so_a_subscribed_calendar_keeps_them(self, author):
        e = self.series(author)
        got = self.provided(author, date(2026, 1, 1), date(2026, 2, 1))
        assert len({x.id for x in got}) == 4 and got[0].id == f"{e.pk}-20260105"
        assert got[0].id == self.provided(author, date(2026, 1, 5), date(2026, 1, 6))[0].id

    def test_times_carry_to_each_date(self, author):
        self.series(author, all_day=False, start_time=time(9, 30), end_time=time(10, 0))
        second = self.provided(author, date(2026, 1, 1), date(2026, 2, 1))[1]
        assert not second.all_day and second.start.hour == 9 and second.start.day == 12 and second.end.day == 12

    def test_a_multi_day_one_keeps_its_length(self, author):
        self.series(author, end_date=date(2026, 1, 6))
        second = self.provided(author, date(2026, 1, 1), date(2026, 2, 1))[1]
        assert (second.start_date.day, second.end_date.day) == (12, 13)

    def test_a_one_off_keeps_its_plain_id(self, author):
        e = self.series(author, repeat="")
        assert self.provided(author, date(2026, 1, 1), date(2026, 2, 1))[0].id == e.pk

    def test_a_private_series_stays_private(self, author):
        from apps.dashboards.metrics import request_for

        self.series(author, visibility="private")
        other = User.objects.create_user("rc-other", password="x")
        assert not list(events_provider(date(2026, 1, 1), date(2026, 2, 1), request_for(other)))

    def test_cancelling_the_series_strikes_every_date(self, author):
        self.series(author, cancelled=True)
        assert all(e.cancelled for e in self.provided(author, date(2026, 1, 1), date(2026, 2, 1)))

    def test_ics_has_one_entry_per_date(self, author):
        self.series(author)
        ics = render_ics(self.provided(author, date(2026, 1, 1), date(2026, 2, 1)), {EVENTS_KEY: "Events"})
        assert ics.count("BEGIN:VEVENT") == 4 and len({x for x in ics.splitlines() if x.startswith("UID:")}) == 4

    def test_it_reaches_the_merged_calendar(self, author):
        from apps.dashboards.metrics import request_for

        self.series(author)
        cal = get_calendar(EVENTS_KEY)
        assert len(collect_events([cal], date(2026, 1, 1), date(2026, 2, 1), request_for(author))[0]) == 4

    @pytest.mark.parametrize(
        "kw, field",
        [
            ({"repeat_until": date(2025, 1, 1)}, "repeat_until"),
            ({"end_date": date(2026, 1, 12)}, "end_date"),  # 8 days long, repeating weekly
        ],
    )
    def test_bad_rules_are_refused(self, author, kw, field):
        with pytest.raises(ValidationError) as err:
            self.series(author, **kw)
        assert field in err.value.message_dict

    def test_clearing_the_rule_clears_what_hangs_off_it(self, author):
        e = self.series(author, repeat_until=date(2026, 3, 1), skip_dates=["2026-01-12"])
        e.repeat = ""
        e.full_clean()
        assert e.repeat_until is None and e.skip_dates == []

    def test_is_over(self, author):
        assert not self.series(author).is_over(date(2030, 1, 1))
        assert self.series(author, repeat_until=date(2026, 2, 1)).is_over(date(2026, 3, 1))

    def test_skip_and_restore_a_date(self, client, author):
        e = self.series(author)
        client.force_login(author)
        url = reverse("calendar_event_skip", kwargs={"pk": e.pk})
        assert client.post(url, {"date": "2026-01-12"}).status_code == 302
        assert [x.start_date.day for x in self.provided(author, date(2026, 1, 1), date(2026, 2, 1))] == [5, 19, 26]
        assert client.post(url, {"date": "2026-01-12", "restore": "1"}).status_code == 302
        assert len(self.provided(author, date(2026, 1, 1), date(2026, 2, 1))) == 4

    def test_a_date_outside_the_series_cant_be_skipped(self, client, author):
        e = self.series(author)
        client.force_login(author)
        url = reverse("calendar_event_skip", kwargs={"pk": e.pk})
        assert client.post(url, {"date": "2026-01-13"}).status_code == 404
        assert client.post(url, {"date": "2025-12-29"}).status_code == 404
        assert client.post(url, {"date": "junk"}).status_code == 404

    def test_only_its_author_or_staff_can_skip(self, client, author):
        e = self.series(author)
        client.force_login(User.objects.create_user("rc-other", password="x"))
        assert (
            client.post(reverse("calendar_event_skip", kwargs={"pk": e.pk}), {"date": "2026-01-12"}).status_code == 403
        )
        assert Event.objects.get(pk=e.pk).skip_dates == []

    def test_a_private_series_is_404_to_others(self, client, author):
        e = self.series(author, visibility="private")
        client.force_login(User.objects.create_user("rc-other", password="x"))
        assert (
            client.post(reverse("calendar_event_skip", kwargs={"pk": e.pk}), {"date": "2026-01-12"}).status_code == 404
        )

    def test_the_page_names_a_real_date_and_ignores_a_made_up_one(self, client, author):
        e = self.series(author)
        client.force_login(author)
        page = client.get(e.get_absolute_url() + "?on=2026-01-12").content.decode()
        assert "January 12, 2026" in page and "Skip this date" in page and "Every week on Monday" in page
        assert "Skip this date" not in client.get(e.get_absolute_url() + "?on=2026-01-13").content.decode()

    def test_the_form_saves_a_series(self, client, author):
        client.force_login(author)
        response = client.post(
            reverse("calendar/events-create"),
            {
                "title": "Weekly",
                "start_date": "2026-01-05",
                "all_day": "on",
                "repeat": "weekly",
                "visibility": "members",
            },
        )
        assert response.status_code == 302
        assert Event.objects.get(title="Weekly").repeat == "weekly"

    def test_is_occurrence_respects_skips_and_the_first_day(self, author):
        e = self.series(author, skip_dates=["2026-01-12"])
        assert is_occurrence(e, date(2026, 1, 19)) and not is_occurrence(e, date(2026, 1, 12))
        assert not is_occurrence(e, date(2025, 12, 29))

    def test_the_mcp_tool_skips_and_restores(self, author):
        from types import SimpleNamespace
        from unittest import mock

        from apps.calendar.mcp_tools import _skip_date_handler

        e = self.series(author)
        with mock.patch("apps.mcp.server.current_context", return_value=SimpleNamespace(user=author)):
            assert _skip_date_handler({"id": e.pk, "date": "2026-01-12"})["skip_dates"] == ["2026-01-12"]
            assert _skip_date_handler({"id": e.pk, "date": "2026-01-12", "restore": True})["skip_dates"] == []
            assert "isn't a date" in _skip_date_handler({"id": e.pk, "date": "2026-01-13"})["error"]
            assert "no event" in _skip_date_handler({"id": "junk", "date": "2026-01-12"})["error"]
        other = User.objects.create_user("rc-other", password="x")
        with mock.patch("apps.mcp.server.current_context", return_value=SimpleNamespace(user=other)):
            assert "author or staff" in _skip_date_handler({"id": e.pk, "date": "2026-01-12"})["error"]


@pytest.mark.django_db
class TestObviousSeries:
    @pytest.fixture
    def author(self):
        return User.objects.create_user("rc-obvious", password="x")

    def event(self, author, **kw):
        fields = {"title": "Standup", "start_date": date(2026, 11, 3), "repeat": "weekly", "created_by": author, **kw}
        event = Event(**fields)
        event.full_clean()
        event.save()
        return event

    def test_a_weekday_series_starts_on_a_weekday(self, author):
        with pytest.raises(ValidationError) as err:
            self.event(author, start_date=date(2026, 11, 7), repeat="weekdays")
        assert "start_date" in err.value.message_dict

    def test_moving_a_series_drops_a_skip_it_no_longer_has(self, author):
        event = self.event(author)
        event.set_skipped(date(2026, 11, 24), True)
        event.start_date = date(2026, 11, 4)
        event.full_clean()
        assert event.skip_dates == []

    def test_a_skip_it_still_has_stays(self, author):
        event = self.event(author)
        event.set_skipped(date(2026, 11, 24), True)
        event.title = "Renamed"
        event.full_clean()
        assert event.skip_dates == ["2026-11-24"]

    def test_the_form_offers_doesnt_repeat(self):
        from apps.calendar.forms import EventForm

        assert list(EventForm().fields["repeat"].choices)[0] == ("", "Doesn't repeat")

    def test_each_refusal_says_why(self, author):
        from apps.calendar.recurrence import skip_problem

        event = self.event(author)
        assert skip_problem(event, date(2026, 11, 10), False) == ""
        assert "isn't a date" in skip_problem(event, date(2026, 11, 11), False)
        assert "isn't skipped" in skip_problem(event, date(2026, 11, 10), True)
        event.set_skipped(date(2026, 11, 10), True)
        assert "already skipped" in skip_problem(event, date(2026, 11, 10), False)
        assert skip_problem(event, date(2026, 11, 10), True) == ""
        once = self.event(author, repeat="", start_date=date(2026, 12, 1))
        assert "doesn't repeat" in skip_problem(once, date(2026, 12, 1), False)
