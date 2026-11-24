from typing import Any

from django.apps import AppConfig


class AccessConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.access"
    label = "access"
    verbose_name = "Access"

    def ready(self) -> None:
        from django.db.models.signals import post_migrate
        from django.utils.module_loading import autodiscover_modules

        from apps.smallstack import dashboard
        from apps.smallstack.navigation import nav

        from . import cadence, checks, signals, system_checks  # noqa: F401  — receivers, findings, system checks
        from .dashboard_widgets import AccessReviewWidget, AccessWidget

        # Groups, findings and evidence sheets apps declare:
        # apps/<app>/groups.py, access_checks.py and access_evidence.py.
        autodiscover_modules("groups", "access_checks", "access_evidence")
        post_migrate.connect(_sync_groups_after_migrate, dispatch_uid="access_sync_groups")
        # The access.review.signed webhook event, in the endpoint picker.
        cadence.register_event()

        nav.register(
            section="admin",
            label="Access",
            url_name="access:index",
            icon_svg=(
                '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                '<path d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16-4-4 '
                '1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/></svg>'
            ),
            staff_required=True,
            # Reading access needs accounts.view_user; hide a link that would 403.
            visible=lambda request: _can_read_access(request.user),
            order=5,
        )
        dashboard.register(AccessWidget())
        dashboard.register(AccessReviewWidget())


def _can_read_access(user: Any) -> bool:
    from .services import can_read_access

    return can_read_access(user)


def _sync_groups_after_migrate(sender: Any, **kwargs: Any) -> None:
    """Once per migrate (this app's own signal, when every table exists):
    create and update the groups apps declare. Never fails a migrate.

    Django creates each app's permissions in that app's own ``post_migrate``,
    in ``INSTALLED_APPS`` order, so on a first migrate the apps after this one
    (and, depending on receiver order, some before) have none yet. Create
    every app's content types and permissions first (both are idempotent), so
    a declared group gets everything it names on the deploy that adds it."""
    if getattr(sender, "label", "") != "access":
        return
    from django.conf import settings

    if not getattr(settings, "SMALLSTACK_ACCESS_GROUPS_SYNC", True):
        return
    import logging

    from django.apps import apps as global_apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes

    from .registry import sync_groups

    using = kwargs.get("using", "default")
    try:
        for app_config in global_apps.get_app_configs():
            create_contenttypes(app_config, verbosity=0, using=using)
            create_permissions(app_config, verbosity=0, using=using)
        sync_groups()
    except Exception:
        logging.getLogger(__name__).exception("access: group sync after migrate failed")
