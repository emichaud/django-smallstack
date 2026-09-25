"""SmallStack approvals — a generic human-in-the-loop approval primitive.

The side-car gate: an app files an ApprovalRequest, a human decides in the
console (or an assignee via the embed card), and the app reacts through its
registered per-kind callback — plus a Django signal, a webhook event, and the
poll-able REST/MCP surfaces. What "approved" *means* stays app-owned.

    from apps.approvals import approval_kind          # declare a kind
    from apps.approvals import services as approvals  # file / decide

Registry symbols are stdlib-only and safe at import time; ``services`` touches
models and must be imported after app loading (normal view/task code is fine).
"""

from .registry import ApprovalKind, approval_kind, register_kind

__all__ = ["ApprovalKind", "approval_kind", "register_kind"]
