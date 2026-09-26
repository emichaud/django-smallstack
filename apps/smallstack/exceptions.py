"""Exceptions the API layer knows how to translate into the JSON envelope.

A feature that ships a master on/off switch needs a way to say "I am off" that
every ``@api_view`` endpoint — including endpoints in *downstream* apps that
merely call into it — turns into an honest status code rather than a 500.

Before this existed, ``apps/approvals`` caught its own ``ApprovalsDisabled`` in
its own two handlers and declared a ``503`` in its own OpenAPI block. Both were
unreachable (the routes are unmounted whenever the exception can be raised)
while the *reachable* failure — any downstream app's endpoint calling
``services.request_approval()`` with approvals switched off — was an unhandled
**500**. (F-31; same shape as the ``Http404`` translation F-17 added.)
"""

from __future__ import annotations


class FeatureDisabled(Exception):
    """A feature's master switch is off (→ ``503 Service Unavailable``).

    Subclass it in the feature's own exception hierarchy — e.g.
    ``class ApprovalsDisabled(ApprovalError, FeatureDisabled)`` — and
    :func:`apps.smallstack.api.api_view` will translate it for every endpoint in
    the project, present and future. ``str(exc)`` becomes the client-visible
    message, so raise it with text an operator can act on (name the setting).
    """

    #: Optional machine-readable hint, surfaced as ``code`` in the envelope.
    code: str = "feature_disabled"
