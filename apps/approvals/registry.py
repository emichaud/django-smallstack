"""The approval-kind registry — code-declared kinds, datasets-registry shape.

A *kind* is what makes an approval request meaningful to the app that filed
it: a label for humans, a callback for the decision, an optional eligibility
hook, a default TTL, and a card template. Downstream apps declare kinds in
their ``approvals.py`` module (autodiscovered at startup):

    from apps.approvals import approval_kind

    @approval_kind("calendar.publish", label="Publish calendar schedule",
                   default_expires_in=timedelta(days=3))
    def on_publish_decision(req):
        ...  # runs after ANY terminal transition — read req.status

Only stdlib is imported at module scope, so this file is safe to import from
package ``__init__`` and during app loading.

Unknown kinds are tolerated (webhooks hooks.py spirit): a request whose kind
has no registry entry still renders (default card, key as label) and can be
decided — its callback is simply a no-op, with a logged warning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Iterator

logger = logging.getLogger("smallstack.approvals")

# on_decision receives the ApprovalRequest AFTER a terminal transition
# (approved / rejected / canceled / expired) — it reads req.status.
DecisionCallback = Callable[[Any], None]
# can_decide(user, req) -> bool. NARROWS the default policy only (ANDed) —
# a hook can never widen past the self-approval / assignee / staff gates.
EligibilityHook = Callable[[Any, Any], bool]


@dataclass
class ApprovalKind:
    key: str
    label: str = ""
    description: str = ""
    # A callable, or a dotted path string ("apps.x.approvals.on_decision") —
    # dotted is import-order-safe (scheduler task_path idiom).
    on_decision: DecisionCallback | str | None = None
    can_decide: EligibilityHook | None = None
    default_expires_in: timedelta | None = None
    # Explicit card template; otherwise approvals/kinds/<key dots→dashes>.html
    # then approvals/kinds/default.html.
    context_template: str = ""
    # Where this kind sends its humans: a callable ``fn(req) -> str`` (or a
    # dotted path to one) returning an internal path. Every channel approvals
    # owns — both emails and both bell rows — uses this one value, so a kind
    # that owns its own review page (an embedded {% approval_card %}) can point
    # participants there instead of the shared console. None ⇒ the console.
    landing_url: Callable[[Any], str] | str | None = None
    # Who a REMOTE caller (REST/MCP) may name as an assignee: a list of
    # usernames, or a predicate ``fn(user) -> bool``. None (the default) refuses
    # remote assignee selection outright, so opening the filing endpoint to an
    # agent can never be used to route a request at an arbitrary account.
    assignable: list[str] | Callable[[Any], bool] | None = None
    # Extra email recipients on request + decision.
    notify: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.key.replace(".", " ").replace("_", " ").title()


_kind_registry: dict[str, ApprovalKind] = {}
_on_register_hooks: list[Callable[[ApprovalKind], None]] = []


def register_kind(kind: ApprovalKind) -> ApprovalKind:
    """Register a kind; first-wins on duplicate keys (autodiscovery may run
    more than once), with a logged warning."""
    existing = _kind_registry.get(kind.key)
    if existing is not None:
        if existing is not kind:
            logger.warning("approval kind %r already registered — keeping the first", kind.key)
        return existing
    _kind_registry[kind.key] = kind
    for hook in _on_register_hooks:
        try:
            hook(kind)
        except Exception:  # noqa: BLE001 — a hook must not break registration
            logger.exception("approvals: register hook failed for %r", kind.key)
    return kind


def approval_kind(
    key: str,
    *,
    label: str = "",
    description: str = "",
    can_decide: EligibilityHook | None = None,
    default_expires_in: timedelta | None = None,
    context_template: str = "",
    notify: list[str] | None = None,
    landing_url: Callable[[Any], str] | str | None = None,
    assignable: list[str] | Callable[[Any], bool] | None = None,
) -> Callable[[DecisionCallback], DecisionCallback]:
    """Decorator: the decorated function becomes the kind's on_decision
    callback. Returns the function unchanged (@scheduled idiom)."""

    def wrap(fn: DecisionCallback) -> DecisionCallback:
        register_kind(
            ApprovalKind(
                key=key,
                label=label,
                description=description,
                on_decision=fn,
                can_decide=can_decide,
                default_expires_in=default_expires_in,
                context_template=context_template,
                notify=list(notify or []),
                landing_url=landing_url,
                assignable=assignable,
            )
        )
        return fn

    return wrap


def get_kind(key: str) -> ApprovalKind | None:
    return _kind_registry.get(key)


def all_kinds() -> Iterator[ApprovalKind]:
    return iter(sorted(_kind_registry.values(), key=lambda k: k.key))


def known_keys() -> list[str]:
    return sorted(_kind_registry)


def add_register_hook(hook: Callable[[ApprovalKind], None]) -> None:
    """Fires for FUTURE register() calls only — process already-registered
    kinds yourself first (datasets/search registry convention)."""
    if hook not in _on_register_hooks:
        _on_register_hooks.append(hook)


def resolve_on_decision(kind: ApprovalKind | None) -> DecisionCallback | None:
    """Resolve the callback, importing dotted paths lazily. None-safe."""
    if kind is None or kind.on_decision is None:
        return None
    if callable(kind.on_decision):
        return kind.on_decision
    try:
        from importlib import import_module

        module_path, attr = kind.on_decision.rsplit(".", 1)
        resolved = getattr(import_module(module_path), attr)
        if not callable(resolved):
            raise TypeError(f"{kind.on_decision} is not callable")
        return resolved
    except Exception:  # noqa: BLE001 — surfaced via callback_error downstream
        logger.exception("approvals: cannot resolve on_decision %r", kind.on_decision)
        return None


def resolve_landing_url(kind: ApprovalKind | None, req: Any) -> str:
    """The kind's landing path for ``req``, or "" to fall back to the console.

    Never raises: a downstream app's broken hook must not break an email or a
    notification. Accepts a callable or a dotted path (import-order-safe, same
    idiom as ``on_decision``).
    """
    target = getattr(kind, "landing_url", None)
    if target is None:
        return ""
    try:
        if not callable(target):
            from importlib import import_module

            module_path, attr = str(target).rsplit(".", 1)
            target = getattr(import_module(module_path), attr)
        url = target(req)
        return url if isinstance(url, str) and url.startswith("/") else ""
    except Exception:  # noqa: BLE001 — fall back to the console
        logger.exception("approvals: landing_url failed for %r", getattr(kind, "key", None))
        return ""


def unregister(key: str) -> None:
    """Test helper."""
    _kind_registry.pop(key, None)


def clear_kinds_for_tests() -> None:
    _kind_registry.clear()
