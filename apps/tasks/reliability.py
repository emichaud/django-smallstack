"""Retries with backoff for ``django.tasks`` on the django-tasks-db backend.

``django-tasks-db`` has no attempts: a task that raises ends ``FAILED``. This
module adds retries on top without touching the engine. Declare a policy
above ``@task`` (the same convention as ``@scheduled``)::

    from django.tasks import task
    from apps.tasks.reliability import retry_policy

    @retry_policy(max_attempts=3, backoff=5, backoff_max=600, retry_on=(OSError,))
    @task(queue_name="email")
    def send_email_task(...): ...

When an attempt fails, :func:`maybe_retry` enqueues a **fresh copy** of the
task (same args, queue, priority, backend) with ``run_after = now + delay``,
and records a :class:`~apps.tasks.models.TaskAttempt` linking it to the chain.
Every attempt is its own ``DBTaskResult`` row, so every traceback is kept.

Three paths call :func:`maybe_retry`:

- ``signals.py`` — the worker's ``task_finished`` signal, right after a
  failure (the normal path);
- ``reaper.py`` — right after it fails a task whose worker died
  (``cause=lost``) — governed by the policy's ``retry_lost``;
- :func:`repair_missed_retries` — a sweep (run with every reaper pass) for
  failures whose retry never got enqueued, e.g. the worker died between
  recording the failure and sending the signal.

The unique ``TaskAttempt.parent_id`` makes those paths race-safe: the enqueue
and the attempt row commit together, so a second retry of the same attempt
rolls back instead of duplicating.

**Retries are opt-in** (``SMALLSTACK_TASKS_DEFAULT_MAX_ATTEMPTS = 1``):
execution is at-least-once, so only tasks that are safe to repeat should
retry. A task with no policy fails exactly as it did before.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeVar
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.tasks import TaskResultStatus
from django.utils import timezone
from django.utils.module_loading import import_string
from django_tasks_db.models import DBTaskResult

from .exceptions import BOOKKEEPING_PATHS, INTERRUPTED_PATHS, RETRY_SUPERSEDED_PATH, WORKER_LOST_PATH
from .models import TaskAttempt

logger = logging.getLogger(__name__)

T = TypeVar("T")

# How far back the repair sweep looks for failures with no retry, and how long
# it leaves a fresh failure alone (the signal receiver is about to handle it).
REPAIR_WINDOW = timedelta(hours=1)
REPAIR_GRACE = timedelta(seconds=30)
REPAIR_BATCH = 100


@dataclass(frozen=True)
class RetryPolicy:
    """How a task retries. ``None`` fields fall back to the settings defaults."""

    max_attempts: int | None = None
    backoff: float | None = None
    backoff_max: float | None = None
    retry_on: tuple[type[BaseException], ...] = (Exception,)
    # Retry when the worker died (reaped as WorkerLost) or was force-stopped
    # mid-task (SystemExit/KeyboardInterrupt), not only when the task raised.
    retry_lost: bool = True

    def attempts(self) -> int:
        if self.max_attempts is not None:
            return self.max_attempts
        return int(getattr(settings, "SMALLSTACK_TASKS_DEFAULT_MAX_ATTEMPTS", 1))

    def delay(self, attempt: int) -> float:
        """Seconds to wait before attempt ``attempt + 1``: doubling, capped, jittered.

        Equal jitter (half fixed, half random) spreads a burst of failures out
        without ever retrying immediately.
        """
        initial = self.backoff if self.backoff is not None else _setting("SMALLSTACK_TASKS_BACKOFF_SECONDS", 5)
        cap = (
            self.backoff_max if self.backoff_max is not None else _setting("SMALLSTACK_TASKS_BACKOFF_MAX_SECONDS", 600)
        )
        base = min(cap, initial * 2 ** max(0, attempt - 1))
        return base / 2 + random.uniform(0, base / 2)  # noqa: S311 - jitter, not crypto


DEFAULT_POLICY = RetryPolicy()

# The policy a chain gets when an *operator* pinned a budget (pin_max_attempts —
# e.g. a ScheduledJob with max_retries > 0) onto a task that declares no
# @retry_policy of its own. Identical to DEFAULT_POLICY except that it will not
# re-run an attempt whose worker died.
#
# Re-running a task the worker was killed *inside* is an at-least-once decision
# about a task body nobody marked repeatable: it may have already written half
# its side effects. A developer writing @retry_policy(...) is asserting the task
# is safe to repeat, so retry_lost=True is theirs to choose. An operator typing a
# number into the scheduler form is asking "try the failure again" and cannot
# know whether the body is idempotent — so the operator control must never be
# more aggressive than the explicit decorator. A task that *raised* reported its
# own failure, which is exactly what the operator asked to retry.
IMPLICIT_PINNED_POLICY = RetryPolicy(retry_lost=False)

# task path (Task.module_path, == DBTaskResult.task_path) -> policy.
_POLICIES: dict[str, RetryPolicy] = {}


def _setting(name: str, default: float) -> float:
    return float(getattr(settings, name, default))


def retry_policy(
    *,
    max_attempts: int | None = None,
    backoff: float | None = None,
    backoff_max: float | None = None,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    retry_lost: bool = True,
) -> Callable[[T], T]:
    """Declare how a ``@task`` retries. Apply it *above* ``@task``.

    ``max_attempts`` counts the first run (3 = one run + up to two retries).
    ``backoff`` is the **upper bound** of the first delay in seconds, not the
    delay itself: each wait is jittered uniformly into ``[bound/2, bound]``, so
    ``backoff=5`` waits 2.5–5s. The bound doubles per attempt up to
    ``backoff_max``. ``retry_on`` limits retries to those exception classes
    (and their subclasses). Returns the task unchanged.
    """
    if max_attempts is not None and max_attempts < 1:
        raise ValueError("max_attempts counts the first run and must be >= 1")
    policy = RetryPolicy(
        max_attempts=max_attempts,
        backoff=backoff,
        backoff_max=backoff_max,
        retry_on=tuple(retry_on),
        retry_lost=retry_lost,
    )

    def decorator(task_obj: T) -> T:
        path = getattr(task_obj, "module_path", None)
        if not isinstance(path, str):
            raise TypeError("@retry_policy must be applied above @task (it decorates a Task, not a function)")
        _POLICIES[path] = policy
        return task_obj

    return decorator


def policy_for(task_path: str) -> RetryPolicy:
    """The policy for ``task_path``, importing it first so its decorator has run.

    The reaper and repair sweep can see a task whose module this process never
    imported; importing it registers any ``@retry_policy`` it declares.
    """
    if task_path not in _POLICIES:
        try:
            import_string(task_path)
        except Exception:  # noqa: BLE001 - an unimportable task gets the defaults
            logger.debug("tasks: could not import %s to read its retry policy", task_path, exc_info=True)
    return _POLICIES.get(task_path, DEFAULT_POLICY)


@dataclass(frozen=True)
class AttemptInfo:
    root_id: UUID
    attempt: int
    max_attempts: int | None  # per-chain override, if any


def attempt_info(result_id: UUID | str) -> AttemptInfo:
    """Where ``result_id`` sits in its chain (attempt 1 of itself if unrecorded)."""
    row = TaskAttempt.objects.filter(result_id=result_id).first()
    if row is None:
        return AttemptInfo(root_id=UUID(str(result_id)), attempt=1, max_attempts=None)
    return AttemptInfo(root_id=row.root_id, attempt=row.attempt, max_attempts=row.max_attempts)


def pin_max_attempts(result_id: UUID | str, max_attempts: int) -> None:
    """Override the retry budget for the chain starting at ``result_id``.

    For callers that know better than the task's decorator for one enqueue
    (the scheduler's per-job ``max_retries``). Call right after enqueueing, in
    the same transaction, so no worker can claim and fail the task first.

    This pins the **attempt count only**. Which exceptions retry (``retry_on``),
    whether a worker death retries (``retry_lost``) and the backoff still come
    from the task's own ``@retry_policy`` — and when the task has none, from
    :data:`IMPLICIT_PINNED_POLICY`, which is deliberately more conservative than
    ``DEFAULT_POLICY``.
    """
    TaskAttempt.objects.update_or_create(
        result_id=result_id,
        defaults={"root_id": result_id, "attempt": 1, "max_attempts": max_attempts},
    )


def _classify(row: DBTaskResult, cause: str) -> str:
    if row.exception_class_path == WORKER_LOST_PATH:
        return TaskAttempt.Cause.LOST
    if row.exception_class_path in INTERRUPTED_PATHS:
        return TaskAttempt.Cause.INTERRUPTED
    return cause


def _matches(exception_class_path: str, retry_on: tuple[type[BaseException], ...]) -> bool:
    try:
        exc_class = import_string(exception_class_path)
    except Exception:  # noqa: BLE001 - can't resolve it; only a catch-all matches
        return any(cls in (Exception, BaseException) for cls in retry_on)
    return isinstance(exc_class, type) and issubclass(exc_class, retry_on)


@dataclass(frozen=True)
class _Decision:
    cause: str
    policy: RetryPolicy
    info: AttemptInfo
    budget: int


def _decide(row: DBTaskResult, cause: str) -> _Decision | None:
    """The retry decision for a ``FAILED`` row, or ``None`` if it won't be retried."""
    if row.status != TaskResultStatus.FAILED:
        return None
    if row.exception_class_path in BOOKKEEPING_PATHS:
        # A row that records a decision, not an execution. Retrying it would
        # undo the decision — see BOOKKEEPING_PATHS. Gated here rather than in
        # any one caller because this is the single funnel every retry path
        # (signal receiver, reaper, repair sweep) goes through.
        return None
    cause = _classify(row, cause)
    policy = policy_for(row.task_path)
    info = attempt_info(row.id)
    if info.max_attempts is not None and policy is DEFAULT_POLICY:
        # Operator-pinned budget, no @retry_policy on the task: don't re-run a
        # worker death nobody declared repeatable. See IMPLICIT_PINNED_POLICY.
        policy = IMPLICIT_PINNED_POLICY
    budget = info.max_attempts if info.max_attempts is not None else policy.attempts()
    if info.attempt >= budget:
        return None
    if cause in (TaskAttempt.Cause.LOST, TaskAttempt.Cause.INTERRUPTED):
        if not policy.retry_lost:
            return None
    elif not _matches(row.exception_class_path, policy.retry_on):
        return None
    return _Decision(cause=cause, policy=policy, info=info, budget=budget)


def maybe_retry(
    result_id: UUID | str, cause: str = TaskAttempt.Cause.FAILED, *, now: datetime | None = None
) -> str | None:
    """Enqueue the next attempt of a failed task if its policy allows.

    Returns the new result id, or ``None`` when no retry was enqueued (not
    failed, budget spent, exception not retryable, or another path already
    retried this attempt).
    """
    row = DBTaskResult.objects.filter(id=result_id).first()
    decision = _decide(row, cause) if row is not None else None
    if row is None or decision is None:
        return None
    cause, policy, info, budget = decision.cause, decision.policy, decision.info, decision.budget

    now = now or timezone.now()
    delay = policy.delay(info.attempt)
    try:
        task_obj: Any = import_string(row.task_path)
        with transaction.atomic():
            new = task_obj.using(
                queue_name=row.queue_name,
                priority=row.priority,
                backend=row.backend_name,
                run_after=now + timedelta(seconds=delay),
            ).enqueue(*row.args_kwargs.get("args", []), **row.args_kwargs.get("kwargs", {}))
            TaskAttempt.objects.create(
                result_id=new.id,
                root_id=info.root_id,
                parent_id=row.id,
                attempt=info.attempt + 1,
                cause=cause,
                max_attempts=info.max_attempts,
            )
    except IntegrityError:
        # Another path retried this attempt first (unique parent_id).
        return None
    logger.info(
        "tasks: retrying %s (%s) as %s: attempt %d of %d in %.0fs (%s)",
        row.id,
        row.task_path,
        new.id,
        info.attempt + 1,
        budget,
        delay,
        cause,
        extra={"task_id": str(row.id), "retry_id": str(new.id), "task_path": row.task_path},
    )
    return str(new.id)


# How far back the late-completion sweep looks for a reaped attempt that
# finished anyway. Wider than REPAIR_WINDOW because the pause that caused the
# reap (a stopped container, a snapshotted VM) can outlast an hour by a lot.
LATE_COMPLETION_WINDOW = timedelta(days=1)


@dataclass(frozen=True)
class LateCompletion:
    """A reaped attempt that completed anyway: proof the chain ran twice."""

    parent_id: str
    retry_id: str
    task_path: str
    status: str
    retry_cancelled: bool


def _mark_superseded(
    parent_id: UUID | str,
    *,
    status: str,
    task_path: str,
    completed_at: datetime,
    now: datetime,
) -> LateCompletion | None:
    """Record that a reaped attempt completed anyway, and log it loudly.

    Returns ``None`` when another path already recorded this one — the UPDATE is
    conditional on ``parent_completed_at`` still being NULL, so the signal
    receiver and the sweep can both run without double-counting.

    **Only a ``cause=lost`` child qualifies**, which is the same predicate
    :func:`detect_late_completions` uses. A child row means "something retried
    this attempt"; only a *reap* also means "and we declared the attempt dead
    while it might still have been running", which is the premise of a late
    completion. Retrying because the task raised (``failed``), or because a human
    asked (``manual``), carries no such claim — the attempt had already reported
    its own outcome.

    Without the filter, any second delivery of one finished task to the receiver
    reads its own freshly-enqueued retry as proof of a late completion, and
    **cancels a legitimate retry** (``READY -> FAILED/RetrySuperseded``,
    ``retry_cancelled=True``) on top of recording a double execution that never
    happened. The spurious marker is the visible half; the lost work is the
    defect. ``Cause.MANUAL`` is already in the model, so a manual-retry feature
    would reach this without any second delivery at all: a human retrying what
    looks stuck is the same race the reaper runs.

    ``interrupted`` is excluded with ``failed`` and ``manual`` on purpose: that
    cause comes from the worker recording ``SystemExit``/``KeyboardInterrupt`` as
    it exits, and a process on its way out does not come back to complete.
    """
    reaped_child = {"parent_id": parent_id, "parent_completed_at__isnull": True, "cause": TaskAttempt.Cause.LOST}
    child = TaskAttempt.objects.filter(**reaped_child).values_list("result_id", flat=True).first()
    if child is None:
        return None
    marked = TaskAttempt.objects.filter(**reaped_child).update(
        parent_completed_at=completed_at, parent_status=str(status)[:16]
    )
    if not marked:
        return None

    # Best-effort cancel of a retry that hasn't started. Conditional on READY, so
    # a retry already RUNNING is untouched — and this is *not* the correctness
    # story: by the time a paused worker resumes, its replacement has usually
    # started or finished, and cancelling it then would not un-execute it.
    cancelled = bool(
        DBTaskResult.objects.filter(id=child, status=TaskResultStatus.READY).update(
            status=TaskResultStatus.FAILED,
            finished_at=now,
            return_value=None,
            exception_class_path=RETRY_SUPERSEDED_PATH,
            traceback=(
                f"RetrySuperseded: attempt {parent_id} was declared lost and replaced by this retry, "
                f"but then completed ({status}) before this retry started"
            ),
        )
    )
    if cancelled:
        TaskAttempt.objects.filter(parent_id=parent_id).update(retry_cancelled=True)
    logger.warning(
        "tasks: %s of %s — attempt %s was reaped as WorkerLost and retried as %s, "
        "then completed anyway (%s). %s",
        "REAPED-THEN-COMPLETED" if cancelled else "DOUBLE EXECUTION",
        task_path,
        parent_id,
        child,
        status,
        (
            "The retry was cancelled before it started, so the task ran once."
            if cancelled
            else "The retry had already started: the task ran more than once."
        ),
        extra={"task_path": task_path, "task_id": str(parent_id), "retry_id": str(child)},
    )
    return LateCompletion(
        parent_id=str(parent_id),
        retry_id=str(child),
        task_path=task_path,
        status=str(status),
        retry_cancelled=cancelled,
    )


def retry_of(result_id: UUID | str) -> UUID | None:
    """The result id of the retry enqueued for ``result_id``, or ``None``.

    One indexed lookup on the unique ``TaskAttempt.parent_id``. Used by the
    log receiver to tell "failed, being retried" from "failed, final" without
    re-deriving the retry decision.
    """
    return TaskAttempt.objects.filter(parent_id=result_id).values_list("result_id", flat=True).first()


def record_late_completion(result_id: UUID | str, *, now: datetime | None = None) -> LateCompletion | None:
    """Did ``result_id`` finish *after* something already retried it? Record it.

    Called from the ``task_finished`` receiver for every terminal result, which
    is the earliest moment this is knowable. One indexed lookup on the unique
    ``TaskAttempt.parent_id``: a normally-failing attempt has no child yet (its
    retry is enqueued moments later, by the same receiver), so this is a single
    miss on the hot path.
    """
    now = now or timezone.now()
    row = (
        DBTaskResult.objects.filter(id=result_id)
        .values_list("status", "task_path", "finished_at")
        .first()
    )
    if row is None:
        return None
    status, task_path, finished_at = row
    if status in (TaskResultStatus.READY, TaskResultStatus.RUNNING):
        return None
    return _mark_superseded(
        result_id, status=status, task_path=task_path, completed_at=finished_at or now, now=now
    )


def detect_late_completions(*, now: datetime | None = None, limit: int = REPAIR_BATCH) -> list[LateCompletion]:
    """Sweep for reaped attempts that completed without the signal being seen.

    The receiver only fires if the worker survives long enough to report. A
    worker that is SIGKILLed between ``set_successful()`` and sending the signal
    still executed the task, so the record would be lost — this catches it on
    the next reaper pass. Idempotent: ``_mark_superseded`` only counts the first
    writer.
    """
    now = now or timezone.now()
    # parent_id is nullable on the model (a pinned first attempt has none), but a
    # cause=lost row always has one — it exists *because* something was retried.
    # Filtered explicitly rather than assumed.
    candidates = [
        parent_id
        for parent_id in TaskAttempt.objects.filter(
            cause=TaskAttempt.Cause.LOST,
            parent_completed_at__isnull=True,
            parent_id__isnull=False,
            created_at__gte=now - LATE_COMPLETION_WINDOW,
        ).values_list("parent_id", flat=True)[:limit]
        if parent_id is not None
    ]
    if not candidates:
        return []
    found: list[LateCompletion] = []
    rows = DBTaskResult.objects.filter(
        id__in=candidates, status__in=(TaskResultStatus.SUCCESSFUL, TaskResultStatus.FAILED)
    ).values_list("id", "status", "task_path", "exception_class_path", "finished_at")
    for rid, status, task_path, exc_path, finished_at in rows:
        if status == TaskResultStatus.FAILED and exc_path == WORKER_LOST_PATH:
            continue  # still carries the reaper's verdict; it never came back
        late = _mark_superseded(
            rid, status=status, task_path=task_path, completed_at=finished_at or now, now=now
        )
        if late is not None:
            found.append(late)
    return found


@dataclass(frozen=True)
class ChainOutcome:
    """Where a chain of attempts stands, read from its first result id.

    ``status`` is the latest attempt's engine status (``READY`` / ``RUNNING`` /
    ``SUCCESSFUL`` / ``FAILED``), or ``RETRYING`` while the latest attempt
    failed but another is on its way: the signal receiver is about to enqueue
    it, or the repair sweep will. ``row`` is the latest attempt's result.

    ``executed_more_than_once`` means an earlier attempt in this chain reached a
    terminal state after being declared lost and replaced, **and its replacement
    had already started** — the chain forked and both branches ran. The latest
    attempt is still the outcome, but a caller that records "one run" must be
    able to learn the truth was more than one; the scheduler puts it in the run
    message. ``superseded_attempt``/``superseded_status`` say which attempt
    completed late and how it ended.

    When the replacement was still ``READY`` it is cancelled instead, and then
    the chain executed *once*: the walk stops at the attempt that completed, so
    a job whose late attempt succeeded is reported ``SUCCESSFUL`` — not
    ``FAILED`` from the cancelled retry, and with no alarming note, because
    nothing went wrong that the operator needs to act on.
    """

    status: str
    row: DBTaskResult
    attempt: int
    executed_more_than_once: bool = False
    superseded_attempt: int | None = None
    superseded_status: str = ""
    # A cancelled retry has a descendant: something re-enqueued a row that exists
    # only to record a cancellation. `_decide` refuses bookkeeping rows as retry
    # input, so this should be unreachable — it is reported rather than assumed
    # away, because the one time it happened the chain went quiet (U4).
    resurrected_cancelled_retry: bool = False

    def double_execution_note(self) -> str:
        """One short phrase for a run message. Empty when the chain ran once."""
        if self.resurrected_cancelled_retry:
            return "ran again unexpectedly: a cancelled retry was re-enqueued and continued"
        if not self.executed_more_than_once:
            return ""
        which = f"attempt {self.superseded_attempt}" if self.superseded_attempt else "an earlier attempt"
        ended = f" ({self.superseded_status})" if self.superseded_status else ""
        return f"ran more than once: {which} completed{ended} after being declared lost"


RETRYING = "RETRYING"

# Chains are bounded by max_attempts; this only guards a corrupt parent loop.
_MAX_CHAIN = 1000


def chain_outcome(result_id: UUID | str, *, now: datetime | None = None) -> ChainOutcome | None:
    """Follow ``result_id``'s retries to the latest attempt and report its state.

    ``None`` if the result doesn't exist (e.g. pruned). A failed latest attempt
    counts as ``RETRYING`` only while it's still inside the repair sweep's
    window: past that, nothing will retry it, so it is final.
    """
    current = str(result_id)
    attempt = 1
    superseded_attempt: int | None = None
    superseded_status = ""
    forked = False
    resurrected = False
    for _ in range(_MAX_CHAIN):
        # The supersession marker is carried in the same walk, so detecting a
        # fork costs no extra queries. A child row's parent_completed_at refers
        # to `current` — the attempt it replaced.
        child = (
            TaskAttempt.objects.filter(parent_id=current)
            .values_list("result_id", "attempt", "parent_completed_at", "parent_status", "retry_cancelled")
            .first()
        )
        if child is None:
            break
        child_id, child_attempt, parent_completed_at, parent_status, retry_cancelled = child
        if parent_completed_at is not None:
            superseded_attempt = attempt
            superseded_status = parent_status or ""
            if retry_cancelled:
                # A cancelled retry never ran, so it is not this chain's outcome
                # and the chain executed once: `current` — which completed after
                # being declared lost — is the ground truth, so stop here.
                #
                # Unless something re-enqueued it anyway. `_decide` now refuses
                # bookkeeping rows as retry input, so a descendant here should be
                # impossible; if one exists the machinery has misbehaved and the
                # descendant really did run. Walking on is what keeps that from
                # being invisible — terminating here is exactly how U4's
                # duplicate execution reported `attempt=1` and an empty note.
                if not TaskAttempt.objects.filter(parent_id=child_id).exists():
                    break
                resurrected = True
            else:
                forked = True
        current, attempt = str(child_id), child_attempt
    row = DBTaskResult.objects.filter(id=current).first()
    if row is None:
        return None
    status = str(row.status)
    if status == TaskResultStatus.FAILED:
        now = now or timezone.now()
        recent = row.finished_at is None or row.finished_at >= now - REPAIR_WINDOW
        if recent and _decide(row, TaskAttempt.Cause.FAILED) is not None:
            status = RETRYING
    return ChainOutcome(
        status=status,
        row=row,
        attempt=attempt,
        # A resurrection counts as a second execution only once it has actually
        # run — a still-READY one hasn't yet, and a false double-execution flag
        # is worse than none. It is reported either way via the flag below.
        executed_more_than_once=forked or (resurrected and status != TaskResultStatus.READY),
        superseded_attempt=superseded_attempt,
        superseded_status=superseded_status,
        resurrected_cancelled_retry=resurrected,
    )


def repair_missed_retries(*, now: datetime | None = None) -> int:
    """Retry recent failures whose retry never got enqueued. Returns retries made.

    Looks at ``FAILED`` rows finished between ``REPAIR_WINDOW`` and
    ``REPAIR_GRACE`` ago that no attempt row names as its parent, narrowed to
    tasks that can retry at all (a policy allowing more than one attempt, or a
    chain with a pinned budget). Capped at ``REPAIR_BATCH`` per pass.
    """
    now = now or timezone.now()
    recent = (
        DBTaskResult.objects.filter(
            status=TaskResultStatus.FAILED,
            finished_at__gte=now - REPAIR_WINDOW,
            finished_at__lte=now - REPAIR_GRACE,
        )
        .exclude(id__in=TaskAttempt.objects.filter(parent_id__isnull=False).values("parent_id"))
        # Bookkeeping rows are not failed attempts. `_decide` refuses them too —
        # that is the load-bearing gate — but excluding them here stops the sweep
        # re-examining the same rows on every pass, from every worker, for an hour.
        .exclude(exception_class_path__in=BOOKKEEPING_PATHS)
    )
    retryable_paths = [
        path
        for path in recent.order_by().values_list("task_path", flat=True).distinct()
        if policy_for(path).attempts() > 1
    ]
    pinned = TaskAttempt.objects.filter(max_attempts__gt=1).values("result_id")
    candidates = (
        recent.filter(Q(task_path__in=retryable_paths) | Q(id__in=pinned))
        .order_by("finished_at")
        .values_list("id", flat=True)[:REPAIR_BATCH]
    )
    retried = 0
    for result_id in list(candidates):
        try:
            if maybe_retry(result_id, now=now):
                retried += 1
        except Exception:  # noqa: BLE001 - one bad row must not stop the sweep
            logger.warning("tasks: repair retry of %s failed", result_id, exc_info=True)
    return retried
