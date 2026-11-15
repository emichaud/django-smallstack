"""Usage stats for API tokens.

Adapted from the upstream smallstack-tokenmgr package. Uses
apps.activity.RequestLog when installed; degrades gracefully when
it isn't.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Avg, Count
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_usage_stats(token, hours: int = 24) -> dict:
    """Per-token stats for the detail page."""
    cutoff = timezone.now() - timedelta(hours=hours)
    try:
        logs = token.request_logs.filter(timestamp__gte=cutoff)
    except Exception:
        logger.debug("No request logs for token usage stats (activity not installed?)", exc_info=True)
        return {"total_requests": 0, "status_breakdown": {}, "avg_response_time_ms": 0, "hours": hours}

    total = logs.count()
    status_breakdown: dict[int, int] = {}
    if total:
        for row in logs.values("status_code").annotate(count=Count("id")).order_by("status_code"):
            status_breakdown[row["status_code"]] = row["count"]

    avg_response = logs.aggregate(avg=Avg("response_time_ms"))["avg"]

    return {
        "total_requests": total,
        "status_breakdown": status_breakdown,
        "avg_response_time_ms": round(avg_response, 1) if avg_response else 0,
        "hours": hours,
    }


def get_overview_stats(user=None) -> dict:
    """Summary stats for the list page.

    When `user` is given and doesn't read every token (no
    ``smallstack.view_apitoken``), restrict counts to their tokens.
    """
    from apps.smallstack.models import APIToken

    from .mixins import may_read_all_tokens

    scoped = user is not None and not may_read_all_tokens(user)
    qs = APIToken.objects.all()
    if scoped:
        qs = qs.filter(user=user)

    total = qs.count()
    active = qs.filter(is_active=True).count()
    revoked = qs.filter(is_active=False).count()

    # 24h request volume across the visible tokens.
    cutoff_24h = timezone.now() - timedelta(hours=24)
    volume_24h = 0
    try:
        from apps.activity.models import RequestLog

        volume_qs = RequestLog.objects.filter(api_token__isnull=False, timestamp__gte=cutoff_24h)
        if scoped:
            volume_qs = volume_qs.filter(api_token__user=user)
        volume_24h = volume_qs.count()
    except Exception:
        logger.debug("No request logs for token volume (activity not installed?)", exc_info=True)
        volume_24h = 0

    return {
        "total_tokens": total,
        "active_tokens": active,
        "revoked_tokens": revoked,
        "volume_24h": volume_24h,
    }
