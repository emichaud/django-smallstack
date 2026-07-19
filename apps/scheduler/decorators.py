"""The ``@scheduled`` decorator + its module-level registry.

Apps declare recurring jobs next to the task they run::

    from django.tasks import task
    from apps.scheduler import scheduled

    @scheduled(cron="0 6 * * *", name="Nightly fetch")   # or every="1d", or at=<dt>
    @task
    def nightly_fetch():
        ...

``@scheduled`` is applied *above* ``@task`` so the object it wraps is still the
enqueue-able Task — the decorator only records a spec into ``_SCHEDULE_REGISTRY``
and returns the task unchanged. ``registry.sync_code_jobs()`` later reconciles
each spec into a ``source="code"`` :class:`~apps.scheduler.models.ScheduledJob`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

# The wrapped object is returned unchanged, so preserve its type for callers.
T = TypeVar("T")

# Populated at import time by @scheduled; drained by registry.sync_code_jobs().
_SCHEDULE_REGISTRY: list["ScheduleSpec"] = []


@dataclass
class ScheduleSpec:
    task_path: str
    name: str
    schedule_type: str  # once | interval | cron
    interval_spec: str = ""
    anchor: str = ""  # "MM-DD" or ISO date; resolved to anchor_at at sync time
    cron_expression: str = ""
    run_at: datetime | None = None
    timezone: str = ""
    queue_name: str = "default"
    kwargs: dict = field(default_factory=dict)
    catch_up: str = "run_once"
    allow_overlap: bool = False


def _dotted_path(task_obj: Any) -> str:
    """Best-effort dotted path to the underlying task function."""
    func = getattr(task_obj, "func", task_obj)
    module = getattr(func, "__module__", "")
    qualname = getattr(func, "__qualname__", getattr(func, "__name__", ""))
    return f"{module}.{qualname}" if module else qualname


def scheduled(
    *,
    every: str = "",
    cron: str = "",
    at: datetime | None = None,
    anchor: str = "",
    name: str = "",
    timezone: str = "",
    queue_name: str = "default",
    catch_up: str = "run_once",
    allow_overlap: bool = False,
    **kwargs: Any,
) -> Callable[[T], T]:
    """Declare a recurring/one-off schedule for a ``@task``.

    Exactly one of ``every`` (interval), ``cron``, or ``at`` (once) must be set.
    Extra keyword arguments are stored as the task's enqueue kwargs. The DB row
    stays the runtime source of truth — ops can pause/retune without a redeploy;
    only the *cadence* is refreshed from code on each boot.
    """
    provided = [bool(every), bool(cron), at is not None]
    if sum(provided) != 1:
        raise ValueError("@scheduled needs exactly one of: every=, cron=, at=.")

    if every:
        stype, kw = "interval", {"interval_spec": every, "anchor": anchor}
    elif cron:
        stype, kw = "cron", {"cron_expression": cron}
    else:
        stype, kw = "once", {"run_at": at}

    def wrap(task_obj: T) -> T:
        path = _dotted_path(task_obj)
        _SCHEDULE_REGISTRY.append(
            ScheduleSpec(
                task_path=path,
                name=name or path.rsplit(".", 1)[-1],
                schedule_type=stype,
                timezone=timezone,
                queue_name=queue_name,
                kwargs=dict(kwargs),
                catch_up=catch_up,
                allow_overlap=allow_overlap,
                **kw,
            )
        )
        return task_obj

    return wrap
