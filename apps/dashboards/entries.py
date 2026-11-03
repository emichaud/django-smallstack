"""Writing a hand-entered metric's values. One seam for the page, REST and MCP."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import Metric, MetricEntry
from .snapshots import recapture_for_value

#: What the value column can hold (DecimalField(max_digits=20, decimal_places=4)).
_LIMIT = Decimal(10) ** 16


def parse_entry(raw_date: Any, raw_value: Any) -> tuple[date | None, Decimal | None, dict[str, str]]:
    """``(day, value, errors)`` from submitted text. A bad value is refused, never
    read as zero; so is a future date, which would become the "latest" value now."""
    errors: dict[str, str] = {}
    day: date | None = None
    value: Decimal | None = None
    try:
        day = date.fromisoformat(str(raw_date or "").strip())
    except ValueError:
        errors["date"] = "Enter a date as YYYY-MM-DD."
    else:
        if day > timezone.localdate():
            errors["date"] = "That date hasn't happened yet."
    # Thousands separators and a trailing % are how people copy these numbers.
    text = str("" if raw_value is None else raw_value).strip().replace(",", "").rstrip("%")
    try:
        value = Decimal(text)
    except InvalidOperation:
        errors["value"] = "Enter a number."
    else:
        if not value.is_finite() or abs(value) >= _LIMIT:
            errors["value"] = "Enter a number under 10 quadrillion."
            value = None
    return day, value, errors


def record_entry(metric: Metric, day: date, value: Decimal, note: str = "", *, by: Any = None) -> MetricEntry:
    """Set *metric*'s value for *day*, replacing any earlier one for that date."""
    if not metric.is_manual:
        raise ValueError(f"{metric.name} isn't entered by hand.")
    with transaction.atomic():
        entry, _created = MetricEntry.objects.update_or_create(
            metric=metric,
            date=day,
            defaults={"value": value.quantize(Decimal("0.0001")), "note": note[:200], "entered_by": by},
        )
        recapture_for_value(metric, day, by=by)
    return entry


def delete_entry(metric: Metric, day: date, *, by: Any = None) -> bool:
    """Remove *metric*'s value for *day*. Whether there was one."""
    with transaction.atomic():
        deleted, _detail = MetricEntry.objects.filter(metric=metric, date=day).delete()
        if deleted:
            recapture_for_value(metric, day, by=by)
    return bool(deleted)
