"""Package-level settings with sensible defaults."""

from typing import Optional

from django.conf import settings

RUNBOOK_BASE_TEMPLATE = getattr(settings, "RUNBOOK_BASE_TEMPLATE", "base.html")
RUNBOOK_STAFF_REQUIRED = getattr(settings, "RUNBOOK_STAFF_REQUIRED", True)
RUNBOOK_URL_PREFIX = getattr(settings, "RUNBOOK_URL_PREFIX", "runbook/")

# -- Retention global defaults (lowest tier; doc + runbook values override) ----
# Human documents default to unlimited history and no expiry. Machine/generated
# documents default to a bounded-but-persistent 100 versions with TTL opt-in.
RUNBOOK_GENERATED_MAX_VERSIONS: Optional[int] = getattr(settings, "RUNBOOK_GENERATED_MAX_VERSIONS", 100)
RUNBOOK_GENERATED_MAX_VERSION_AGE_DAYS: Optional[int] = getattr(
    settings, "RUNBOOK_GENERATED_MAX_VERSION_AGE_DAYS", None
)
RUNBOOK_GENERATED_TTL_DAYS: Optional[int] = getattr(settings, "RUNBOOK_GENERATED_TTL_DAYS", None)


def global_max_versions(is_generated: bool) -> Optional[int]:
    return RUNBOOK_GENERATED_MAX_VERSIONS if is_generated else None


def global_max_version_age_days(is_generated: bool) -> Optional[int]:
    return RUNBOOK_GENERATED_MAX_VERSION_AGE_DAYS if is_generated else None


def global_ttl_days(is_generated: bool) -> Optional[int]:
    return RUNBOOK_GENERATED_TTL_DAYS if is_generated else None
