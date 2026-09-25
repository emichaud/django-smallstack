"""Staff log viewer.

The page an operator opens mid-incident when the log stream isn't reachable.
Its job is narrow: find the lines that explain what just went wrong. Everything
here serves scanning speed — newest first, severity readable without reading,
tracebacks loaded only when asked for.

The capture controls live on this page rather than in a settings screen because
"there's nothing here, turn the volume up" is the first thing you do when the
baseline WARNING didn't catch your bug.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib import messages
from django.db.models import Count
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.smallstack.audit import ADDITION, CHANGE, log_action
from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.pagination import paginate_queryset

from . import capture, queries
from .handlers import get_handlers
from .logger_match import prefix_q
from .models import LogRecord

logger = logging.getLogger(__name__)

# Ordered low to high — the filter is "this level and above", which is how
# operators think ("show me warnings and worse").
LEVEL_FILTERS = [
    ("", "All", 0),
    ("DEBUG", "Debug", logging.DEBUG),
    ("INFO", "Info", logging.INFO),
    ("WARNING", "Warning", logging.WARNING),
    ("ERROR", "Error", logging.ERROR),
    ("CRITICAL", "Critical", logging.CRITICAL),
]

TIME_RANGES = [
    ("", "All"),
    ("15m", "15 min"),
    ("1h", "1 hour"),
    ("24h", "24 hours"),
    ("7d", "7 days"),
]

_RANGE_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


class LogListView(StaffRequiredMixin, TemplateView):
    """The log table, its filters, and the capture-window controls."""

    template_name = "telemetry/logs.html"
    partial_template = "telemetry/partials/log_table.html"
    page_size = 50

    def get_filters(self) -> dict[str, str]:
        get = self.request.GET
        return {
            "level": get.get("level", "").upper(),
            "logger": get.get("logger", "").strip(),
            "q": get.get("q", "").strip(),
            "request_id": get.get("request_id", "").strip(),
            "trace_id": get.get("trace_id", "").strip(),
            "range": get.get("range", "").strip(),
        }

    def filtered_queryset(self, filters: dict[str, str]):
        qs = LogRecord.objects.all()

        level_no = dict((name, no) for name, _label, no in LEVEL_FILTERS).get(filters["level"])
        if level_no:
            qs = qs.filter(level_no__gte=level_no)

        if filters["logger"]:
            # Hierarchy-aware match so picking "apps.webhooks" also brings its
            # children ("apps.webhooks.tasks") without also pulling in an
            # unrelated sibling that happens to share a string prefix
            # ("apps.webhooks_admin"). Same predicate the DatabaseLogHandler's
            # own exclusion list uses — see logger_match.py.
            qs = qs.filter(prefix_q("logger", filters["logger"]))

        if filters["q"]:
            # Tracebacks are searched too — the exception class is usually what
            # you remember, and it lives in exc_text, not the message.
            from django.db.models import Q

            qs = qs.filter(Q(message__icontains=filters["q"]) | Q(exc_text__icontains=filters["q"]))

        if filters["request_id"]:
            qs = qs.filter(request_id=filters["request_id"])

        if filters["trace_id"]:
            qs = qs.filter(trace_id=filters["trace_id"])

        delta = _RANGE_DELTAS.get(filters["range"])
        if delta:
            qs = qs.filter(ts__gte=timezone.now() - delta)

        return qs.order_by("-ts", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self.get_filters()
        if filters["level"] and filters["level"] not in {name for name, _label, _no in LEVEL_FILTERS}:
            # Say so instead of rendering the unfiltered table as if it were
            # the filtered result — the API 400s on the same input. (Audit D10a.)
            messages.warning(self.request, f"Unknown level {filters['level']!r} ignored — showing all levels.")
            filters["level"] = ""
        qs = self.filtered_queryset(filters)

        page_obj = paginate_queryset(qs, self.request, page_size=self.page_size)

        # Counts ignore the level filter so the segmented control can show what
        # you'd get by switching — a zero tells you not to bother clicking.
        #
        # .order_by() with no arguments is load-bearing: the queryset is ordered
        # by ("-ts", "-pk"), and Django adds ordering fields to the GROUP BY of a
        # values().annotate(). That would group by (level, ts, pk) — one row per
        # record — and the counts would all come back as 1.
        count_filters = dict(filters, level="")
        counts = {
            row["level"]: row["n"]
            for row in self.filtered_queryset(count_filters).order_by().values("level").annotate(n=Count("pk"))
        }

        base_qs = self.querystring(dict(filters, level=""))
        level_options = []
        for name, label, level_no in LEVEL_FILTERS:
            if name:
                count = sum(n for lvl, n in counts.items() if _level_no(lvl) >= level_no)
            else:
                count = sum(counts.values())
            # Built here rather than assembled from six {% if %}s in the template.
            parts = [p for p in (f"level={name}" if name else "", base_qs) if p]
            level_options.append(
                {
                    "value": name,
                    "label": label,
                    "count": count,
                    "active": filters["level"] == name,
                    "url": "?" + "&".join(parts) if parts else "?",
                }
            )

        context.update(
            {
                "records": page_obj,
                "page_obj": page_obj,
                "filters": filters,
                "level_options": level_options,
                "time_ranges": [
                    {"value": value, "label": label, "active": filters["range"] == value}
                    for value, label in TIME_RANGES
                ],
                "logger_options": self.logger_options(),
                "querystring": self.querystring(filters),
                "has_filters": any(filters.values()),
                "total_stored": LogRecord.objects.count(),
                "live": self.request.GET.get("live") == "1",
                **capture_context(),
            }
        )
        return context

    def logger_options(self) -> list[str]:
        """The busiest logger names, for the filter dropdown.

        Same ``.order_by()`` caveat as the level counts — Meta.ordering would
        otherwise join the GROUP BY and give one group per record.
        """
        rows = LogRecord.objects.order_by().values("logger").annotate(n=Count("pk")).order_by("-n")[:40]
        return [row["logger"] for row in rows]

    def querystring(self, filters: dict[str, str]) -> str:
        """Active filters as a query fragment, for pagination and refresh links."""
        from urllib.parse import urlencode

        return urlencode({key: value for key, value in filters.items() if value})

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        if request.htmx:
            return TemplateResponse(request, self.partial_template, context)
        return TemplateResponse(request, self.template_name, context)


class LogDetailView(StaffRequiredMixin, View):
    """One record's traceback, extra fields, and correlation IDs.

    Loaded on demand rather than rendered into every row: a single traceback can
    be 20 KB, and fifty of them would dominate the page.
    """

    def get(self, request, pk):
        record = get_object_or_404(LogRecord, pk=pk)
        return render(
            request,
            "telemetry/partials/log_detail.html",
            {"log": record, "extra_items": sorted((record.extra or {}).items())},
        )


class CaptureControlView(StaffRequiredMixin, View):
    """Open or close a capture window from the page.

    POST because it changes what the deployment records. Audited — turning the
    verbosity up is exactly the kind of action you want attributable later.
    """

    def post(self, request):
        action = request.POST.get("action", "")
        redirect_to = reverse("telemetry:logs")

        if action == "start":
            try:
                level = queries.parse_capture_level(request.POST.get("level", "DEBUG"))
            except queries.TelemetryQueryError as exc:
                messages.error(request, f"Capture not started: {exc}.")
                return HttpResponseRedirect(redirect_to)
            try:
                minutes = int(request.POST.get("minutes", 15))
            except (TypeError, ValueError):
                minutes = 15

            window = capture.start(
                level=level,
                minutes=minutes,
                actor=request.user.get_username(),
                note=request.POST.get("note", "")[:200],
            )
            log_action(request.user, window, ADDITION, f"Opened {window.level} log capture")
            logger.info(
                "Log capture opened: level=%s until=%s by=%s",
                window.level,
                window.expires_at.isoformat(),
                request.user.get_username(),
            )
            messages.success(
                request,
                f"Capturing {window.level} until {timezone.localtime(window.expires_at):%H:%M}. "
                "Running processes pick this up within a few seconds.",
            )

        elif action == "stop":
            window = capture.active_window()
            closed = capture.stop()
            if closed and window:
                log_action(request.user, window, CHANGE, "Closed log capture early")
            logger.info("Log capture closed by %s (%d window(s))", request.user.get_username(), closed)
            messages.success(
                request,
                "Stopped capturing. Back to the baseline level." if closed else "No capture window was open.",
            )
        else:
            raise Http404

        return HttpResponseRedirect(redirect_to)


def _level_no(level_name: str) -> int:
    resolved = logging.getLevelName(str(level_name).upper())
    return resolved if isinstance(resolved, int) else 0


def capture_context() -> dict:
    """Current capture state, for the page header.

    Reads the handler's in-process view of things where it can — that is what is
    actually being captured right now, which may lag a just-opened window by a
    poll interval.
    """
    window = capture.active_window()
    handlers = get_handlers()
    stats = handlers[0].stats() if handlers else None

    return {
        "capture_window": window,
        "capture_baseline": logging.getLevelName(capture.baseline_level()),
        "capture_stats": stats,
        "capture_dropped": (stats or {}).get("dropped", 0),
    }
