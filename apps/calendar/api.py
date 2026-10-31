"""REST surface for calendars under ``/smallstack/calendar/api/``.

Bearer-or-session authenticated (the same ``_authenticate_api_request`` path
``/api/`` and the datasets routes use — JSON 401/403, never a login redirect)
and open to any signed-in user; per-calendar access is enforced by
``core.resolve_keys`` so a non-staff caller never learns a staff calendar
exists. Every route emits the normalised event dict ``core`` documents.

    GET  /smallstack/calendar/api/                       → calendars this caller may see
    GET  /smallstack/calendar/api/events/?ds=a&ds=b&start=&end=   → merged events
    GET  /smallstack/calendar/api/events.ics?ds=…         → the same window as an iCalendar feed
    GET  /smallstack/calendar/api/<key>/events/?start=&end=        → one calendar

``start``/``end`` are ISO dates (``end`` exclusive); they default to the
current month. ``?view=<pk>`` substitutes one of the caller's saved views for
the ``ds`` list. The window is capped at ``SMALLSTACK_CALENDAR_MAX_WINDOW_DAYS``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.smallstack.api import _authenticate_api_request

from .core import (
    CalendarDataset,
    CalendarEvent,
    collect_events,
    list_calendars,
    month_bounds,
    resolve_keys,
)


def _enabled() -> bool:
    return bool(getattr(settings, "SMALLSTACK_CALENDAR_ENABLED", True))


def max_window_days() -> int:
    return int(getattr(settings, "SMALLSTACK_CALENDAR_MAX_WINDOW_DAYS", 366))


def parse_window(request: HttpRequest) -> tuple[date, date]:
    """``(start, end)`` from ``?start=&end=`` — ISO dates, ``end`` exclusive.
    Defaults to the current month; raises ValueError on garbage or a window
    over the cap."""
    today = timezone.localdate()
    lower, upper = month_bounds(today)
    raw_start = (request.GET.get("start") or "").strip()
    raw_end = (request.GET.get("end") or "").strip()
    if raw_start:
        try:
            lower = date.fromisoformat(raw_start)
        except ValueError as exc:
            raise ValueError(f"start must be an ISO date, got {raw_start!r}") from exc
        if not raw_end:
            upper = lower + timedelta(days=31)
    if raw_end:
        try:
            upper = date.fromisoformat(raw_end)
        except ValueError as exc:
            raise ValueError(f"end must be an ISO date, got {raw_end!r}") from exc
    if upper <= lower:
        raise ValueError("end must be after start")
    if (upper - lower).days > max_window_days():
        raise ValueError(f"window exceeds {max_window_days()} days")
    return lower, upper


def _requested(request: HttpRequest, user: Any) -> tuple[list[CalendarDataset], list[str]]:
    """Calendars from ``?ds=`` (or a saved ``?view=``), split into
    visible / rejected."""
    from .views import requested_keys, view_or_none

    keys = requested_keys(request)
    if not keys and request.GET.get("view"):
        view = view_or_none(user, request.GET.get("view"))
        if view is None:
            raise Http404("No such view")
        keys = view.keys
    return resolve_keys(keys, user)


@method_decorator(csrf_exempt, name="dispatch")
class _CalendarApiView(View):
    """Bearer-or-session auth → JSON 401/403; any signed-in user."""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if not _enabled():
            raise Http404
        user, err = _authenticate_api_request(request)
        if err:
            return err
        request.api_user = user  # type: ignore[attr-defined]
        return super().dispatch(request, *args, **kwargs)


class CalendarListView(_CalendarApiView):
    def get(self, request: HttpRequest) -> JsonResponse:
        return JsonResponse({"results": list_calendars(request.api_user)})  # type: ignore[attr-defined]


class CalendarEventsView(_CalendarApiView):
    def get(self, request: HttpRequest) -> JsonResponse:
        user = request.api_user  # type: ignore[attr-defined]
        try:
            lower, upper = parse_window(request)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        cals, rejected = _requested(request, user)
        if rejected:
            return JsonResponse({"error": f"unknown calendar(s): {', '.join(rejected)}"}, status=400)
        events, counts, capped = collect_events(cals, lower, upper, request)
        return JsonResponse(
            {
                "start": lower.isoformat(),
                "end": upper.isoformat(),
                "calendars": [c.key for c in cals],
                "counts": counts,
                "capped": sorted(capped),
                "count": len(events),
                "results": [ev.as_dict() for ev in events],
            }
        )


class CalendarDatasetEventsView(_CalendarApiView):
    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        user = request.api_user  # type: ignore[attr-defined]
        cals, rejected = resolve_keys([key], user)
        if rejected:
            raise Http404("calendar not found")
        try:
            lower, upper = parse_window(request)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        events, counts, capped = collect_events(cals, lower, upper, request)
        return JsonResponse(
            {
                "key": key,
                "start": lower.isoformat(),
                "end": upper.isoformat(),
                "capped": key in capped,
                "count": len(events),
                "results": [ev.as_dict() for ev in events],
            }
        )


ICS_REALM = "SmallStack calendar: any username, your API token as the password"


class CalendarICSView(_CalendarApiView):
    """The selected calendars as an iCalendar feed — what a desktop or phone
    calendar app subscribes to. Default window: last month through three
    months ahead.

    A calendar app cannot send a Bearer header, so an unauthenticated request
    is answered with a ``WWW-Authenticate: Basic`` challenge: the app prompts
    for a username and password, and the API helper accepts the user's API
    token as the password (any username). Only this route challenges — a JSON
    route doing so would make browsers pop a native login dialog on a 401.
    """

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        response = super().dispatch(request, *args, **kwargs)
        if response.status_code == 401:
            response["WWW-Authenticate"] = f'Basic realm="{ICS_REALM}"'
        return response

    def get(self, request: HttpRequest) -> HttpResponse:
        user = request.api_user  # type: ignore[attr-defined]
        today = timezone.localdate()
        if not request.GET.get("start") and not request.GET.get("end"):
            lower = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            upper = month_bounds(today.replace(day=1) + timedelta(days=93))[1]
        else:
            try:
                lower, upper = parse_window(request)
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)
        cals, rejected = _requested(request, user)
        if rejected:
            return JsonResponse({"error": f"unknown calendar(s): {', '.join(rejected)}"}, status=400)
        events, _counts, _capped = collect_events(cals, lower, upper, request)
        labels = {c.key: c.label for c in cals}
        body = render_ics(events, labels, request)
        response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="smallstack-calendar.ics"'
        return response


# ---------------------------------------------------------------------------
# iCalendar rendering (RFC 5545 — the subset calendar apps actually read)
# ---------------------------------------------------------------------------


def _ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """Content lines are at most 75 octets; continuations start with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]
    out: list[str] = []
    chunk = b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(chunk) + len(b) > (75 if not out else 74):
            out.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += b
    if chunk:
        out.append(chunk.decode("utf-8"))
    return [out[0]] + [" " + rest for rest in out[1:]]


def _ics_dt(value: date | datetime, *, all_day: bool) -> tuple[str, str]:
    """``(property suffix, formatted value)`` — DATE for all-day, UTC
    DATE-TIME otherwise."""
    if all_day or not isinstance(value, datetime):
        return ";VALUE=DATE", value.strftime("%Y%m%d")
    if timezone.is_aware(value):
        value = value.astimezone(dt_timezone.utc)
    return "", value.strftime("%Y%m%dT%H%M%SZ")


def _uid_domain(request: HttpRequest | None) -> str:
    """The right-hand side of every ``UID``. Stable across hosts, ports and envs.

    RFC 5545 §3.8.4.7 wants a UID that is globally unique *and* persistent: it is
    how a subscribed client recognises an event it already has. Deriving it from
    ``request.get_host()`` makes it neither — the same row answered
    ``…@localhost:8055`` to one caller and ``…@localhost`` to another, differing
    only by the port. A feed is subscribed once and polled for months, so the
    day the host changes (dev → prod, a new domain, a proxy forwarding a
    different Host) every event re-appears as new: duplicates accumulate and the
    originals stop updating, because nothing matches them any more.

    ``SITE_DOMAIN`` is the configured identity of the deployment and does not
    move when the request does — the same reasoning ``rss.md`` gives for feed
    ``unique_id``s ("must survive a slug change and a database restore"). The
    request host is kept only as a last resort, so a deployment that has not set
    ``SITE_DOMAIN`` still emits something usable.
    """
    domain = str(getattr(settings, "SITE_DOMAIN", "") or "").strip()
    if not domain:
        for name in ("SITE_URL", "SMALLSTACK_SITE_URL", "BASE_URL"):
            url = str(getattr(settings, name, "") or "").strip()
            if url.startswith(("http://", "https://")):
                domain = urlsplit(url).netloc
                break
    if not domain and request is not None:
        domain = request.get_host()
    # Strip the port: :8000 and :8055 are the same deployment, and a UID that
    # changes when the port does is the bug this function exists to prevent.
    domain = domain.split("/")[0].rsplit(":", 1)[0] if domain else ""
    return domain or "smallstack"


def render_ics(events: list[CalendarEvent], labels: dict[str, str], request: HttpRequest | None = None) -> str:
    brand = getattr(settings, "BRAND_NAME", "SmallStack")
    host = _uid_domain(request)
    stamp = timezone.now().astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{_ics_text(brand)}//SmallStack Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_text(brand + ' calendar')}",
    ]
    for ev in events:
        suffix, start = _ics_dt(ev.start, all_day=ev.all_day)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{ev.calendar}-{ev.id}@{host}",
            f"DTSTAMP:{stamp}",
            f"DTSTART{suffix}:{start}",
        ]
        if ev.all_day:
            # DTEND is exclusive for all-day events: the day after the last day.
            lines.append(f"DTEND;VALUE=DATE:{(ev.end_date + timedelta(days=1)).strftime('%Y%m%d')}")
        elif ev.end is not None:
            _, end = _ics_dt(ev.end, all_day=False)
            lines.append(f"DTEND:{end}")
        lines.append(f"SUMMARY:{_ics_text(('CANCELLED: ' if ev.cancelled else '') + ev.title)}")
        lines.append("STATUS:CANCELLED" if ev.cancelled else "STATUS:CONFIRMED")
        desc = labels.get(ev.calendar, ev.calendar)
        if ev.subtitle:
            desc += "\n" + ev.subtitle
        lines.append(f"DESCRIPTION:{_ics_text(desc)}")
        lines.append(f"CATEGORIES:{_ics_text(labels.get(ev.calendar, ev.calendar))}")
        if ev.status:
            lines.append(f"X-SMALLSTACK-STATUS:{ev.status}")
        if ev.url:
            url = request.build_absolute_uri(ev.url) if request is not None else ev.url
            lines.append(f"URL:{url}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"
