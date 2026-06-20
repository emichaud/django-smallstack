"""Access levels for cross-model search.

The level a CRUDView declares (via ``search_access = ...``) determines
who can find rows from that view in :func:`apps.search.registry.search_all`.

Three levels, each a strict superset of the prior:

  * ``STAFF`` (default) — only users with ``is_staff = True`` see hits.
    Use this for any data that the project's own permission boundary
    would gate (User records, API tokens, audit logs, etc.).

  * ``AUTHENTICATED`` — any signed-in user sees hits. Pair with
    ``search_visibility`` to scope rows per user when the data should
    be readable by everyone signed in but not equal — e.g.
    "users see their own tickets only".

  * ``ANONYMOUS`` — anyone sees hits, including signed-out visitors.
    Use this for genuinely public content (a product catalogue,
    published articles). Anything not opted in stays gated.

The bundled help index sits outside this model — it is always shown,
to everyone, because it is documentation by nature. The same is true
for any other source the registry treats as "open by default".

Adding a new level (e.g. ``TEAM``) is a single string constant here
plus a clause in :func:`apps.search.registry._user_can_see`. The
public API does not change.
"""

from __future__ import annotations


class SearchAccess:
    """Sentinel constants for ``search_access`` on a CRUDView."""

    STAFF = "staff"
    AUTHENTICATED = "authenticated"
    ANONYMOUS = "anonymous"

    _ALL = (STAFF, AUTHENTICATED, ANONYMOUS)

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls._ALL
