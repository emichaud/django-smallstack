"""Calendar registry — which datasets carry the calendar protocol, and how.

A :class:`CalendarSpec` names the dataset columns that put a row on a date
grid. It is keyed by the dataset key, so a calendar dataset *is* a dataset:
everything the dataset contract offers (schema, rows, filters, REST, MCP, the
staff browser) keeps working, and the calendar reads the same rows through the
``queryset()`` seam. One spec per dataset — a dataset has one time axis; to
plot a second column, declare a second dataset over the same model.

Only stdlib is imported at module load, mirroring ``apps.datasets.registry``,
so an app's ``datasets.py`` can import ``calendar_dataset`` while Django is
still populating the app registry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger("smallstack.calendar")

#: Who may see a calendar dataset. ``staff`` is the secure default — the
#: bundled calendars plot operator data (token expiry, approvals, backups).
#: ``authenticated`` opens it to every signed-in user; such a dataset should
#: scope its rows per user through its ``request`` argument.
ACCESS_STAFF = "staff"
ACCESS_AUTHENTICATED = "authenticated"
ACCESS_LEVELS = (ACCESS_STAFF, ACCESS_AUTHENTICATED)

#: Chip tints a ``status`` resolver may return (anything else renders plain).
STATUS_VALUES = ("success", "warning", "danger")

#: Attribute name, dotted path, or ``(obj) -> value`` callable.
FieldRef = str | Callable[[Any], Any] | None

# key -> CalendarSpec. First-wins (see register_calendar()).
_calendar_registry: dict[str, "CalendarSpec"] = {}


@dataclass
class CalendarSpec:
    """The calendar protocol for one dataset.

    ``start`` and ``end`` are **column names** of the dataset (date or datetime
    columns) — they drive the month-window query, so they must be real columns
    the ORM can filter on. ``title``, ``subtitle`` and ``status`` are display
    resolvers evaluated per row: an attribute name, a dotted path, or a
    callable taking the row's model instance.
    """

    key: str
    start: str
    end: Optional[str] = None
    title: FieldRef = None
    subtitle: FieldRef = None
    status: FieldRef = None
    access: str = ACCESS_STAFF
    # Optional overrides; ``None`` falls back to the dataset's label/description.
    label: Optional[str] = None
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if self.access not in ACCESS_LEVELS:
            raise ValueError(f"calendar {self.key!r}: access must be one of {ACCESS_LEVELS}, got {self.access!r}")
        if not self.start:
            raise ValueError(f"calendar {self.key!r}: a start column is required")

    @property
    def ranged(self) -> bool:
        return bool(self.end)


def register_calendar(
    key: str,
    *,
    start: str,
    end: Optional[str] = None,
    title: FieldRef = None,
    subtitle: FieldRef = None,
    status: FieldRef = None,
    access: str = ACCESS_STAFF,
    label: Optional[str] = None,
    description: Optional[str] = None,
) -> CalendarSpec:
    """Attach the calendar protocol to the dataset registered under ``key``.

    Use this when the dataset is declared elsewhere (a bundled ``smallstack_*``
    dataset, or one of your own you don't want to re-decorate). The spec is
    validated against the dataset's columns lazily — at first use, through
    :meth:`apps.calendar.core.CalendarDataset.validate` — because the dataset
    may register after this call during autodiscovery. First-wins on key.
    """
    spec = CalendarSpec(
        key=key,
        start=start,
        end=end,
        title=title,
        subtitle=subtitle,
        status=status,
        access=access,
        label=label,
        description=description,
    )
    existing = _calendar_registry.get(key)
    if existing is not None:
        logger.warning("calendar %r already registered — keeping the first", key)
        return existing
    _calendar_registry[key] = spec
    return spec


def calendar_dataset(
    key: str,
    *,
    start: str,
    end: Optional[str] = None,
    title: FieldRef = None,
    subtitle: FieldRef = None,
    status: FieldRef = None,
    access: str = ACCESS_STAFF,
    **dataset_kwargs: Any,
) -> Callable[[Callable], Callable]:
    """Decorator: ``@dataset`` plus the calendar protocol, in one declaration.

    Every keyword ``@dataset`` accepts (``label``, ``description``, ``columns``,
    ``filterable``, ``enable_api``, ``enable_mcp``, ``link`` …) passes through
    unchanged; the calendar-specific ones are ``start``/``end`` (column names),
    ``title``/``subtitle``/``status`` (per-row resolvers) and ``access``::

        @calendar_dataset("ticket_due_dates", start="due_at", title="subject",
                          status="sla_status", access="authenticated",
                          label="Ticket due dates", enable_api=True)
        def ticket_due_dates(request):
            return Ticket.objects.filter(assignee=request.user)
    """
    from apps.datasets.registry import dataset

    register_dataset = dataset(key, **dataset_kwargs)

    def decorator(fn: Callable) -> Callable:
        register_dataset(fn)
        register_calendar(
            key,
            start=start,
            end=end,
            title=title,
            subtitle=subtitle,
            status=status,
            access=access,
        )
        return fn

    return decorator


def get_spec(key: str) -> Optional[CalendarSpec]:
    return _calendar_registry.get(key)


def all_specs() -> Iterator[CalendarSpec]:
    return iter(_calendar_registry.values())


def unregister(key: str) -> None:
    """Test helper — drop a calendar spec (the dataset itself is untouched)."""
    _calendar_registry.pop(key, None)
