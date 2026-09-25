"""The kind registry — first-wins, the decorator contract, hooks, dotted paths.

No DB needed: the registry is plain code (that's the point — kinds are
declarations, not rows).
"""

from __future__ import annotations

from datetime import timedelta

from apps.approvals.registry import (
    ApprovalKind,
    add_register_hook,
    approval_kind,
    get_kind,
    known_keys,
    register_kind,
    resolve_on_decision,
    unregister,
)


def test_first_wins_on_duplicate_keys():
    first = ApprovalKind(key="t.dup", label="First")
    second = ApprovalKind(key="t.dup", label="Second")
    try:
        assert register_kind(first) is first
        # duplicate: the FIRST registration survives, the call returns it
        assert register_kind(second) is first
        assert get_kind("t.dup").label == "First"
    finally:
        unregister("t.dup")


def test_reregistering_the_same_object_is_silent_idempotence():
    kind = ApprovalKind(key="t.same")
    try:
        register_kind(kind)
        assert register_kind(kind) is kind  # autodiscovery may run twice
    finally:
        unregister("t.same")


def test_decorator_returns_function_unchanged_and_becomes_callback():
    def my_callback(req):
        pass

    try:
        returned = approval_kind("t.deco", label="Deco", default_expires_in=timedelta(hours=1))(
            my_callback
        )
        assert returned is my_callback  # @scheduled idiom — still usable directly
        kind = get_kind("t.deco")
        assert kind.on_decision is my_callback
        assert kind.default_expires_in == timedelta(hours=1)
    finally:
        unregister("t.deco")


def test_label_autotitles_from_key():
    kind = ApprovalKind(key="calendar.publish_draft")
    assert kind.label == "Calendar Publish Draft"


def test_known_keys_sorted():
    try:
        register_kind(ApprovalKind(key="t.zz"))
        register_kind(ApprovalKind(key="t.aa"))
        keys = known_keys()
        assert keys.index("t.aa") < keys.index("t.zz")
    finally:
        unregister("t.zz")
        unregister("t.aa")


def test_register_hook_fires_for_future_kinds_and_failure_is_swallowed():
    seen: list[str] = []
    add_register_hook(lambda kind: seen.append(kind.key))
    add_register_hook(lambda kind: 1 / 0)  # a broken hook must not break registration
    try:
        register_kind(ApprovalKind(key="t.hooked"))
        assert "t.hooked" in seen
        assert get_kind("t.hooked") is not None  # survived the broken hook
    finally:
        unregister("t.hooked")


def test_resolve_on_decision_handles_all_shapes():
    fn = lambda req: None  # noqa: E731
    assert resolve_on_decision(None) is None
    assert resolve_on_decision(ApprovalKind(key="t.none")) is None
    assert resolve_on_decision(ApprovalKind(key="t.fn", on_decision=fn)) is fn
    # dotted path resolves lazily
    resolved = resolve_on_decision(
        ApprovalKind(key="t.dot", on_decision="apps.approvals.tests.test_registry._sink")
    )
    assert resolved is _sink
    # bad dotted path → None (surfaced downstream via callback_error), not a raise
    assert resolve_on_decision(ApprovalKind(key="t.bad", on_decision="no.such.module.fn")) is None
    # dotted path to a non-callable → None
    assert (
        resolve_on_decision(
            ApprovalKind(key="t.attr", on_decision="apps.approvals.tests.test_registry._NOT_CALLABLE")
        )
        is None
    )


_NOT_CALLABLE = "just a string"


def _sink(req) -> None:
    pass
