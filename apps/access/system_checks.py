"""Django system checks for access declarations (``manage.py check``), so a
typo in a declaration fails CI rather than only logging (T2-8)."""

from __future__ import annotations

from typing import Any

from django.core.checks import Tags, Warning, register


@register(Tags.compatibility)
def check_directory_role_overlays(app_configs: Any = None, **kwargs: Any) -> list[Warning]:
    """``map_directory_role`` naming a group no ``register_group`` declares:
    the role reaches nobody and the manifest omits it."""
    from .registry import unmatched_overlays

    return [
        Warning(
            f"map_directory_role({name!r}, ...) names a group no register_group() declares; "
            "the directory role reaches nobody.",
            hint="Use the exact declared group name (see `manage.py access groups`).",
            id="access.W001",
        )
        for name in unmatched_overlays()
    ]
