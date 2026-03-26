"""Custom detail displays for the profile app."""

from datetime import timedelta

from django.utils import timezone

from apps.smallstack.displays import DetailDisplay


class UserActivityDisplay(DetailDisplay):
    """30/60/90-day activity bar chart for a user profile."""

    name = "activity"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z'
        'M9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z"/>'
        "</svg>"
    )
    template_name = "profile/displays/user_activity.html"

    def get_context(self, obj, crud_config, request):
        from apps.activity.models import RequestLog

        user = obj.user
        now = timezone.now()

        # Build per-period stats
        periods = [
            ("30 days", 30),
            ("60 days", 60),
            ("90 days", 90),
        ]

        bars = []
        max_count = 0
        for label, days in periods:
            count = RequestLog.objects.filter(
                user=user,
                timestamp__gte=now - timedelta(days=days),
            ).count()
            if count > max_count:
                max_count = count
            bars.append({"label": label, "days": days, "count": count})

        # Calculate bar percentages relative to max
        for bar in bars:
            bar["pct"] = round((bar["count"] / max_count * 100) if max_count else 0)

        # Daily breakdown for the last 30 days (for the sparkline)
        daily = []
        for i in range(29, -1, -1):
            day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            count = RequestLog.objects.filter(
                user=user,
                timestamp__gte=day_start,
                timestamp__lt=day_end,
            ).count()
            daily.append(
                {
                    "date": day_start,
                    "count": count,
                }
            )

        daily_max = max((d["count"] for d in daily), default=0)
        for d in daily:
            d["pct"] = round((d["count"] / daily_max * 100) if daily_max else 0)

        return {
            "bars": bars,
            "daily": daily,
            "daily_max": daily_max,
            "total_90": bars[2]["count"] if len(bars) > 2 else 0,
        }
