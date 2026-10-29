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

#: A provider: ``(lower, upper, request) -> iterable of CalendarEvent`` for the
#: half-open day window ``[lower, upper)``. The alternative to the column
#: protocol for calendars whose dates are computed rather than stored — rule-
#: generated holidays, milestones of a long-lived record, anything folded or
#: filtered in Python. Build events with ``CalendarEvent.make(...)``.
Provider = Callable[..., Any]

#: Number of categorical colour tokens the theme defines (``--series-1`` …).
SERIES_COUNT = 8

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
    start: Optional[str] = None
    end: Optional[str] = None
    title: FieldRef = None
    subtitle: FieldRef = None
    status: FieldRef = None
    # Struck through on the board, kept rather than hidden — a cancelled window
    # is still information. Resolver → truthy.
    cancelled: FieldRef = None
    # A small picture beside the row (a face, a logo): resolver → URL or "".
    image: FieldRef = None
    access: str = ACCESS_STAFF
    # Optional overrides; ``None`` falls back to the dataset's label/description.
    label: Optional[str] = None
    description: Optional[str] = None
    # Computed calendars: a provider replaces the column protocol entirely.
    # ``spans`` says its events are ranges (for the picker's hint only).
    provider: Optional[Provider] = None
    spans: bool = False
    # Pin this calendar to one of the theme's ``--series-N`` colours (1–8).
    # Unpinned calendars take the remaining slots in list order.
    color: Optional[int] = None

    def __post_init__(self) -> None:
        if self.access not in ACCESS_LEVELS:
            raise ValueError(f"calendar {self.key!r}: access must be one of {ACCESS_LEVELS}, got {self.access!r}")
        if not self.start and self.provider is None:
            raise ValueError(f"calendar {self.key!r}: a start column or a provider is required")
        if self.start and self.provider is not None:
            raise ValueError(f"calendar {self.key!r}: give a start column OR a provider, not both")
        if self.color is not None and not (1 <= int(self.color) <= SERIES_COUNT):
            raise ValueError(f"calendar {self.key!r}: color must be 1–{SERIES_COUNT}, got {self.color!r}")

    @property
    def ranged(self) -> bool:
        return bool(self.end) or self.spans


def register_calendar(
    key: str,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    title: FieldRef = None,
    subtitle: FieldRef = None,
    status: FieldRef = None,
    cancelled: FieldRef = None,
    image: FieldRef = None,
    access: str = ACCESS_STAFF,
    label: Optional[str] = None,
    description: Optional[str] = None,
    provider: Optional[Provider] = None,
    spans: bool = False,
    color: Optional[int] = None,
) -> CalendarSpec:
    """Attach the calendar protocol to ``key``.

    Two shapes. **Column-backed** — ``key`` is a registered dataset and
    ``start`` (plus optional ``end``) name its date columns; the spec is
    validated against the dataset's columns lazily, at first use, because the
    dataset may register after this call during autodiscovery. **Provider-
    backed** — ``provider(lower, upper, request)`` returns the events for a
    window itself and no dataset is needed; ``label`` is then the calendar's
    name (``key`` titled if omitted). First-wins on key.
    """
    spec = CalendarSpec(
        key=key,
        start=start,
        end=end,
        title=title,
        subtitle=subtitle,
        status=status,
        cancelled=cancelled,
        image=image,
        access=access,
        label=label,
        description=description,
        provider=provider,
        spans=spans,
        color=color,
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
    cancelled: FieldRef = None,
    image: FieldRef = None,
    access: str = ACCESS_STAFF,
    color: Optional[int] = None,
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
            cancelled=cancelled,
            image=image,
            access=access,
            color=color,
        )
        return fn

    return decorator


def calendar_provider(
    key: str,
    *,
    label: str = "",
    description: str = "",
    access: str = ACCESS_STAFF,
    spans: bool = False,
    color: Optional[int] = None,
) -> Callable[[Provider], Provider]:
    """Decorator: a **computed** calendar — the function IS the source.

    For dates that are derived rather than stored: holidays expanded from
    recurrence rules, the start and end milestones of a long-lived record, a
    rota folded onto the night it starts, a mirror of another system. The
    function takes the half-open day window ``(lower, upper, request)`` and
    returns an iterable of :class:`~apps.calendar.core.CalendarEvent` — build
    them with ``CalendarEvent.make(...)``. No dataset, no model required::

        @calendar_provider("company_holidays", label="Company holidays", access="authenticated")
        def company_holidays(lower, upper, request):
            for name, day in resolve_holidays(lower, upper):
                yield CalendarEvent.make("company_holidays", f"{name}:{day}", name, day)
    """

    def decorator(fn: Provider) -> Provider:
        register_calendar(
            key,
            provider=fn,
            label=label or key.replace("_", " ").capitalize(),
            description=description,
            access=access,
            spans=spans,
            color=color,
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
