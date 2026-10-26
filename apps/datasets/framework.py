"""The bundled framework datasets — one lightweight view per shipped module.

Every SmallStack module that creates data (requests, log records, heartbeats,
scheduled-job runs, webhook deliveries, notifications, approvals, blog posts,
runbook documents, …) declares a read-only ``@dataset`` over it in its own
``datasets.py``, through :func:`framework_dataset`. That gives downstream
reporting tools a uniform browse/report seam — ``get_dataset("smallstack_…")``
in-process, ``/smallstack/datasets/smallstack_…/`` over REST (staff-gated,
``?format=csv`` for export) — without each project re-deriving the column
lists or discovering which fields are safe to show.

The helper exists to make three things uniform:

* **Keys are namespaced** ``smallstack_<thing>``. The registry is first-wins,
  so a bare ``notifications`` key here would silently shadow a downstream
  project's own dataset of the same name.
* **Columns are an explicit allow-list.** A dataset projects rows onto its
  declared columns, so what is *not* listed can never leak: password and
  token hashes, webhook secrets, OAuth codes, raw payloads and bodies.
* **Exposure follows two settings.** ``SMALLSTACK_FRAMEWORK_DATASETS_ENABLED``
  (default on) registers them at all; ``SMALLSTACK_FRAMEWORK_DATASETS_MCP``
  (default off) additionally publishes each as a staff-tier MCP tool.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, TypeVar

from django.conf import settings

from .registry import all_defs, dataset

#: Every bundled dataset key starts with this.
FRAMEWORK_PREFIX = "smallstack_"

F = TypeVar("F", bound=Callable[..., object])


def framework_datasets_enabled() -> bool:
    return bool(getattr(settings, "SMALLSTACK_FRAMEWORK_DATASETS_ENABLED", True))


def framework_datasets_mcp() -> bool:
    return bool(getattr(settings, "SMALLSTACK_FRAMEWORK_DATASETS_MCP", False))


def is_framework_dataset(key: str) -> bool:
    return key.startswith(FRAMEWORK_PREFIX)


def framework_dataset_keys() -> list[str]:
    """Keys of the bundled datasets currently registered (sorted)."""
    return sorted(d.key for d in all_defs() if is_framework_dataset(d.key))


def framework_dataset(
    key: str,
    *,
    label: str,
    description: str,
    columns: list[str],
    filterable: Optional[list[str]] = None,
    measures: Optional[list[tuple[str, str, str, str]]] = None,
    link: Any = None,
) -> Callable[[F], F]:
    """``@dataset`` with the framework conventions applied.

    ``key`` must carry the ``smallstack_`` prefix (asserted, so a typo can't
    squat on a downstream name). ``columns`` is required — the allow-list is
    the point. REST is always on (the route is staff-gated); MCP follows
    ``SMALLSTACK_FRAMEWORK_DATASETS_MCP``. When
    ``SMALLSTACK_FRAMEWORK_DATASETS_ENABLED`` is off the decorator registers
    nothing and returns the function untouched. ``link`` is passed through to
    ``@dataset`` — leave it unset to link rows to the model's CRUDView page.
    """
    if not is_framework_dataset(key):
        raise ValueError(f"framework dataset key must start with {FRAMEWORK_PREFIX!r}: {key!r}")
    if not columns:
        raise ValueError(f"framework dataset {key!r} must declare its columns")

    if not framework_datasets_enabled():

        def passthrough(fn: F) -> F:
            return fn

        return passthrough

    register = dataset(
        key,
        label=label,
        description=description,
        columns=list(columns),
        filterable=filterable,
        measures=measures,
        enable_api=True,
        enable_mcp=framework_datasets_mcp(),
        mcp_access="staff",
        link=link,
    )

    def decorate(fn: F) -> F:
        register(fn)  # registers; returns fn unchanged
        return fn

    return decorate
