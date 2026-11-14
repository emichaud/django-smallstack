"""apps.tasks.tracing: automatic trace_id binding around task execution.

Two layers, tested separately:

- The receiver *logic* is tested by calling ``_bind_trace_for_task`` /
  ``_reset_trace_for_task`` directly, not via ``Signal.send()`` — the same
  ``task_started`` / ``task_finished`` signals also carry ``django_tasks``'s
  own built-in logging receivers (``log_task_started`` / ``log_task_finished``
  in ``django_tasks/signals.py``), which expect a real ``TaskResult`` (with
  ``.task.module_path`` and ``.status``). ``Signal.send()`` (unlike
  ``send_robust()``) lets a receiver's exception propagate and abort the
  whole dispatch, so driving a deliberately-broken stand-in through the real
  signal would as easily be testing that *other* package's robustness as
  this one's.
- Wiring tests confirm the functions above are connected to **both** signal
  pairs that can carry a task execution: ``django_tasks.signals`` (sent by
  ``django_tasks_db``'s ``db_worker.run_task()``, the production path) and
  ``django.tasks.signals`` (sent by Django's own backends, including the
  ``ImmediateBackend`` this project's test settings use). See tracing.py's
  module docstring for why there are two identically-named pairs.

  Because both are connected, the last test here can do the thing that
  matters most: enqueue a **real** task through the **real** configured
  backend and assert the trace ID was bound around its actual execution —
  no stand-ins, no hand-sent signals. Before both pairs were connected, that
  test was impossible to write under test settings, which is precisely how a
  silently-untraced path went unnoticed.
"""

from __future__ import annotations

import pytest
from django.tasks import task

from apps.smallstack.logging import bind_trace_id, get_trace_id, reset_trace_id
from apps.tasks import tracing


@pytest.fixture(autouse=True)
def clean_trace_context():
    """Guarantee no trace ID leaks between tests, here or into other files."""
    token = bind_trace_id("")
    yield
    reset_trace_id(token)


class _FakeTaskResult:
    def __init__(self, id):  # noqa: A002 - matches TaskResult's own attribute name
        self.id = id


# ---------------------------------------------------------------------------
# Receiver logic, called directly
# ---------------------------------------------------------------------------


def test_bind_then_reset_round_trips():
    assert get_trace_id() == ""

    tracing._bind_trace_for_task(sender=object, task_result=_FakeTaskResult("abc123"))
    assert get_trace_id() == "trace_task_abc123"

    tracing._reset_trace_for_task(sender=object, task_result=_FakeTaskResult("abc123"))
    assert get_trace_id() == ""


def test_missing_task_result_id_still_binds_something_and_resets_cleanly():
    tracing._bind_trace_for_task(sender=object, task_result=_FakeTaskResult(""))
    assert get_trace_id() == "trace_task_unknown"

    tracing._reset_trace_for_task(sender=object, task_result=_FakeTaskResult(""))
    assert get_trace_id() == ""


def test_bind_never_raises_for_a_broken_task_result():
    """Tracing must never be why a task fails to run — db_worker.run_task()
    calls task_started.send() *before* task.call(), so an exception here
    would stop the task from ever executing."""

    class Explodes:
        @property
        def id(self):
            raise RuntimeError("boom")

    tracing._bind_trace_for_task(sender=object, task_result=Explodes())  # must not raise
    assert get_trace_id() == "", "a failed bind must not leave a stale trace_id bound"


def test_reset_never_raises_for_a_broken_task_result():
    class Explodes:
        @property
        def id(self):
            raise RuntimeError("boom")

    tracing._bind_trace_for_task(sender=object, task_result=_FakeTaskResult("ok"))
    tracing._reset_trace_for_task(sender=object, task_result=Explodes())  # must not raise


def test_reset_with_an_empty_stack_does_not_raise():
    """task_finished firing without a matching task_started (shouldn't happen,
    but defensively) must not pop from an empty stack."""
    tracing._reset_trace_for_task(sender=object, task_result=_FakeTaskResult("orphan"))
    assert get_trace_id() == ""


def test_nested_start_stop_pairs_correctly_via_the_stack():
    """Defensive: the receivers use a stack, not a single slot, specifically
    so two starts before a matching finish can't silently mis-pair."""
    tracing._bind_trace_for_task(sender=object, task_result=_FakeTaskResult("outer"))
    tracing._bind_trace_for_task(sender=object, task_result=_FakeTaskResult("inner"))
    assert get_trace_id() == "trace_task_inner"

    tracing._reset_trace_for_task(sender=object, task_result=_FakeTaskResult("inner"))
    assert get_trace_id() == "trace_task_outer"

    tracing._reset_trace_for_task(sender=object, task_result=_FakeTaskResult("outer"))
    assert get_trace_id() == ""


# ---------------------------------------------------------------------------
# Wiring: the functions above are actually connected to the real signals
# ---------------------------------------------------------------------------


class _Task:
    module_path = "apps.tasks.tests.fake_task"


class _RealisticTaskResult:
    """Complete enough to satisfy every receiver connected to these signals,
    including the packages' own built-in logging receivers (which read
    ``.task.module_path`` and ``.status``). ``Signal.send()`` — unlike
    ``send_robust()`` — lets a receiver's exception abort the whole dispatch,
    so an incomplete stand-in would fail for the wrong reason."""

    id = "wired-abc"
    task = _Task()
    status = "RUNNING"


def _available_signal_modules() -> list[str]:
    """Every task-signals module importable on THIS install.

    ``django_tasks_db`` <= 0.12 shipped its own ``django_tasks`` package and
    its ``db_worker`` sent those signals; 0.13 dropped it for Django's
    built-in ``django.tasks``. So "both pairs exist" was only true for one
    dependency generation — the durable invariant is that tracing subscribes
    to *every pair that does* exist, which is what these tests assert.
    """
    import importlib

    found = []
    for name in ("django_tasks.signals", "django.tasks.signals"):
        try:
            importlib.import_module(name)
        except ImportError:
            continue
        found.append(name)
    return found


def test_at_least_one_task_signal_pair_is_available():
    """Guards the guard: if this ever returns nothing, the parametrised test
    below would vacuously pass by collecting zero cases."""
    assert _available_signal_modules(), "no task-signals module importable at all"


def test_every_available_signal_pair_is_subscribed():
    """Subscribing to fewer pairs than exist is a SILENT failure — trace_id
    just goes empty when the TASKS backend changes, with no exception to
    notice. Catches both "a dependency added a pair we ignore" and "a pair
    went away and we still hard-code it". See tracing.py's module docstring."""
    assert len(tracing.SIGNAL_PAIRS) == len(_available_signal_modules())


@pytest.mark.parametrize("signals_module", _available_signal_modules())
def test_receivers_are_connected_to_every_available_task_signal_pair(signals_module):
    """Each available pair really binds and resets the trace id."""
    import importlib

    mod = importlib.import_module(signals_module)

    assert get_trace_id() == ""
    mod.task_started.send(sender=object, task_result=_RealisticTaskResult())
    try:
        assert get_trace_id() == "trace_task_wired-abc"
    finally:
        mod.task_finished.send(sender=object, task_result=_RealisticTaskResult())
    assert get_trace_id() == ""


def test_connections_are_idempotent_when_the_module_is_imported_twice():
    """apps.py imports tracing from ready(); an autoreloader or a test
    importing it directly must not register the receivers a second time —
    a double bind would leave a stale trace_id after one reset."""
    import importlib

    importlib.reload(tracing)

    # Whichever pair this install actually has (see _available_signal_modules).
    mod = importlib.import_module(_available_signal_modules()[-1])
    task_started, task_finished = mod.task_started, mod.task_finished

    task_started.send(sender=object, task_result=_RealisticTaskResult())
    task_finished.send(sender=object, task_result=_RealisticTaskResult())
    assert get_trace_id() == "", "receivers fired more than once per signal"


# ---------------------------------------------------------------------------
# The real thing: a real task, enqueued through the real configured backend
# ---------------------------------------------------------------------------


# Module level, not nested in the test: Django's Task backends reject a
# non-module-level function (``is_module_level_function``), because a worker in
# another process has to import it by path.
_probe_observations: dict = {}


@task()
def _traced_probe_task() -> str:
    """Records the trace ID visible from inside a real task body."""
    _probe_observations["trace_id"] = get_trace_id()
    return "done"


@pytest.mark.django_db
def test_a_real_enqueued_task_runs_with_a_trace_id_bound():
    """End-to-end through whatever backend ``TASKS`` is configured with — no
    hand-sent signals, no stand-ins. Under test settings that's Django's
    ImmediateBackend, which executes inline on enqueue(); under dev/production
    it's django_tasks_db's worker. Both are covered because tracing.py
    subscribes to every signal pair available on the install.

    This is the test that could not exist before that change: test settings
    use the backend whose signals tracing.py wasn't listening to, so the real
    path was untested and a regression in it would have gone unnoticed.
    """
    _probe_observations.clear()

    assert get_trace_id() == ""
    _traced_probe_task.enqueue()

    seen = _probe_observations.get("trace_id", "")
    assert seen != "", "no trace_id was bound around the task body"
    assert seen.startswith("trace_task_")
    assert get_trace_id() == "", "trace_id leaked past the task's execution"
