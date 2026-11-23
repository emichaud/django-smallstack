from __future__ import annotations

from typing import Any

from apps.smallstack.displays import DashboardWidget

_SHIELD = (
    '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
    '<path d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16-4-4 '
    '1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/></svg>'
)


class AccessWidget(DashboardWidget):
    """Findings that need a look, on the /smallstack/ dashboard."""

    title = "Access"
    icon = _SHIELD
    order = 35
    url_name = "access:index"

    def visible_to(self, user: Any) -> bool:
        from .services import can_read_access

        return can_read_access(user)

    def get_data(self, model_class: type | None = None) -> dict[str, Any]:
        from .registry import run_checks

        findings = run_checks()
        worst = [f for f in findings if f.severity in ("danger", "warning")]
        if worst:
            return {
                "headline": f"{len(worst)} finding{'s' if len(worst) != 1 else ''}",
                "detail": worst[0].title,
                "status": "error" if worst[0].severity == "danger" else "warning",
            }
        return {"headline": "No findings", "detail": "Least privilege holds", "status": "ok"}


class AccessReviewWidget(DashboardWidget):
    """The periodic review: the last complete quarter signed, open and due,
    or not reviewed — and when the next one comes due."""

    title = "Access review"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M19 3h-4.18C14.4 1.84 13.3 1 12 1s-2.4.84-2.82 2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 '
        "2-2V5a2 2 0 0 0-2-2zm-7 0a1 1 0 1 1 0 2 1 1 0 0 1 0-2zm-2 14-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 "
        '8z"/></svg>'
    )
    order = 36
    url_name = "access:reviews"

    @property
    def on_dashboard(self) -> bool:  # type: ignore[override]
        """Published to the /smallstack/ dashboard only when the cadence is
        on: a deployment that runs reports on demand gets no card nagging
        about quarters (Add card → Widget places it by hand). Settings only,
        no query: the board's sync asks on every load. Once placed, the card
        stays (Edit layout removes it)."""
        from . import cadence

        return cadence.enabled()

    def visible_to(self, user: Any) -> bool:
        from .services import can_read_access

        return can_read_access(user)

    def get_data(self, model_class: type | None = None) -> dict[str, Any]:
        from . import cadence, reviews

        s = cadence.status()
        period = s["period"]
        extra = {
            "period_start": period.start.isoformat(),
            "period_end": period.end.isoformat(),
            "due": s["due"].isoformat(),
            "days_until_due": s["days_until_due"],
            "next_close": s["next_close"].isoformat(),
            "cadence": s["cadence"],
            "signed_review": s["signed"].pk if s["signed"] else None,
            "open_review": s["open"].pk if s["open"] else None,
        }
        if s["signed"] is not None:
            return {
                "headline": f"{period.label} signed",
                "detail": f"by {s['signed'].signed_by_label} · next closes {s['next_close']:%b %d}",
                "status": "ok",
                "extra": extra,
            }
        days = s["days_until_due"]
        if days >= 0:
            when = f"due in {days} day{'s' if days != 1 else ''}"
        else:
            when = f"overdue {-days} day{'s' if days != -1 else ''}"
        if s["open"] is not None:
            counts = reviews.live_counts(s["open"])
            # A due date is the cadence's; a review opened by hand is just open.
            return {
                "headline": f"{period.label} {when}" if s["enabled"] else f"{period.label} open",
                "detail": f"{counts['pending']} of {counts['items']} pending",
                "status": "error" if s["enabled"] and days < 0 else "warning",
                "extra": extra,
            }
        if not s["enabled"]:
            # Reviews are opened by hand here; a quarter nobody chose to review isn't overdue.
            last = s["last_signed"]
            return {
                "headline": f"{period.label} not reviewed",
                "detail": f"last signed {last.period_label}" if last else "reviews are opened on demand",
                "status": "ok",
                "extra": extra,
            }
        return {
            "headline": f"{period.label} not reviewed",
            "detail": when,
            "status": "error" if days < 0 else "warning",
            "extra": extra,
        }
