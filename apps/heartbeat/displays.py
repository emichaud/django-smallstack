"""Custom display classes for heartbeat Explorer views."""

import datetime
from decimal import Decimal

from django.db.models import Avg, Sum
from django.utils import timezone

from apps.smallstack.displays import DetailDisplay, ListDisplay


class WeeklySummaryDisplay(ListDisplay):
    """Monday–Sunday calendar view of daily uptime summaries."""

    name = "weekly"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19'
        "c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11z"
        'M9 10H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2z"/>'
        "</svg>"
    )
    template_name = "heartbeat/displays/weekly_summary.html"

    def get_context(self, queryset, crud_config, request):
        from .models import HeartbeatDaily, HeartbeatEpoch

        today = timezone.localdate()
        target, minimum = HeartbeatEpoch.get_sla_targets()

        # Monday of the current week (ISO weekday: Monday=0)
        monday = today - datetime.timedelta(days=today.weekday())
        sunday = monday + datetime.timedelta(days=6)

        # Fetch records for the week
        records = {d.date: d for d in HeartbeatDaily.objects.filter(date__gte=monday, date__lte=sunday)}

        # Build 7-day grid (Mon–Sun), filling gaps with empty days
        days = []
        week_ok = 0
        week_fail = 0
        week_ms_total = 0
        week_ms_count = 0
        for i in range(7):
            date = monday + datetime.timedelta(days=i)
            d = records.get(date)
            is_future = date > today

            if d:
                total = d.ok_count + d.fail_count
                uptime = float(d.uptime_pct)
                meets_sla = uptime >= minimum
                week_ok += d.ok_count
                week_fail += d.fail_count
                if d.avg_response_ms:
                    week_ms_total += d.avg_response_ms
                    week_ms_count += 1
                days.append(
                    {
                        "date": date,
                        "weekday": date.strftime("%A"),
                        "short_date": date.strftime("%-m/%-d"),
                        "uptime": uptime,
                        "uptime_fmt": f"{uptime:.1f}" if uptime < 100 else "100",
                        "meets_sla": meets_sla,
                        "total": total,
                        "total_fmt": _fmt_count(total),
                        "avg_ms": d.avg_response_ms,
                        "fail": d.fail_count,
                        "has_data": True,
                        "is_today": date == today,
                        "is_future": False,
                    }
                )
            else:
                days.append(
                    {
                        "date": date,
                        "weekday": date.strftime("%A"),
                        "short_date": date.strftime("%-m/%-d"),
                        "uptime": 0,
                        "uptime_fmt": "—",
                        "meets_sla": False,
                        "total": 0,
                        "total_fmt": "—",
                        "avg_ms": 0,
                        "fail": 0,
                        "has_data": False,
                        "is_today": date == today,
                        "is_future": is_future,
                    }
                )

        # Week aggregate
        week_total = week_ok + week_fail
        week_uptime = round(week_ok / week_total * 100, 2) if week_total else 0
        week_avg_ms = round(week_ms_total / week_ms_count) if week_ms_count else 0

        return {
            "days": days,
            "monday": monday,
            "sunday": sunday,
            "sla_target": target,
            "sla_minimum": minimum,
            "week_uptime": week_uptime,
            "week_total": week_total,
            "week_total_fmt": _fmt_count(week_total),
            "week_avg_ms": week_avg_ms,
            "week_fail": week_fail,
            "week_meets_sla": week_uptime >= minimum if week_total else None,
        }


class SLACompareDisplay(DetailDisplay):
    """Shows how a single day's uptime compares to SLA target and minimum."""

    name = "sla"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M12 2L4 5v6.09c0 5.05 3.41 9.76 8 10.91 4.59-1.15 8-5.86 8-10.91V5l-8-3z'
        'm-1.06 13.54L7.4 12l1.41-1.41 2.12 2.12 4.24-4.24 1.41 1.41-5.64 5.66z"/>'
        "</svg>"
    )
    template_name = "heartbeat/displays/sla_compare.html"

    def get_context(self, obj, crud_config, request):
        from .models import HeartbeatEpoch

        _, minimum = HeartbeatEpoch.get_sla_targets()
        uptime = float(obj.uptime_pct)
        total_checks = obj.ok_count + obj.fail_count
        meets_sla = uptime >= minimum
        delta = round(uptime - minimum, 3)

        # Breakdown bar widths
        ok_pct = round(obj.ok_count / total_checks * 100, 1) if total_checks else 0

        return {
            "uptime": uptime,
            "sla_minimum": minimum,
            "meets_sla": meets_sla,
            "delta": delta,
            "delta_abs": abs(delta),
            "ok_count": obj.ok_count,
            "fail_count": obj.fail_count,
            "total_checks": total_checks,
            "ok_pct": ok_pct,
            "avg_ms": obj.avg_response_ms,
            "date": obj.date,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uptime_status(uptime_pct, target=99.9, minimum=99.5):
    """Return 'excellent', 'warning', or 'critical' based on thresholds."""
    val = float(uptime_pct)
    if val >= float(target):
        return "excellent"
    if val >= float(minimum):
        return "warning"
    return "critical"


def _month_stats(start, end):
    """Aggregate HeartbeatDaily stats for a date range."""
    from .models import HeartbeatDaily

    agg = HeartbeatDaily.objects.filter(date__gte=start, date__lte=end).aggregate(
        total_ok=Sum("ok_count"),
        total_fail=Sum("fail_count"),
        total_maint=Sum("maintenance_count"),
        avg_ms=Avg("avg_response_ms"),
    )
    ok = agg["total_ok"] or 0
    fail = agg["total_fail"] or 0
    total = ok + fail
    uptime = Decimal(str(round(ok / total * 100, 3))) if total else Decimal("0")

    return {
        "ok": ok,
        "fail": fail,
        "total": total,
        "maintenance": agg["total_maint"] or 0,
        "avg_ms": round(agg["avg_ms"] or 0),
        "uptime": uptime,
        "days": (end - start).days + 1,
    }


def _fmt_count(n):
    """Format a number with k/M suffix for compact display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _build_sparkline(daily_qs, max_checks):
    """Build sparkline bar data from a list of HeartbeatDaily objects."""
    bars = []
    for d in daily_qs:
        total = d.ok_count + d.fail_count
        pct = round(total / max_checks * 100) if max_checks else 0
        bars.append(
            {
                "date": d.date,
                "count": total,
                "pct": max(pct, 3),  # min 3% so bars are visible
                "uptime": float(d.uptime_pct),
                "status": _uptime_status(d.uptime_pct),
            }
        )
    return bars
