"""The evidence pack: one dated bundle that answers an auditor's access
questions for a period.

Every sheet is read-only and built from what the Access app already records:
the accounts and their permissions, the change log, the directory
identities, the API tokens, the findings and the signed access reviews.
Nothing here changes anything. The page previews each sheet; the same
``build()`` feeds the CSV, JSON and ZIP exports, the CLI and REST, so what
the auditor downloads is what the reviewer previewed.

    pack = build(period_start, period_end, scope="privileged", generated_by=request.user)
    pack.sheet("leavers").rows        # list[dict]
    bundle_zip(pack)                   # bytes: cover.md + one CSV per sheet + evidence.json
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from apps.smallstack.models import APIToken

from . import reviews, services
from .models import AccessEvent, AccessReview, DirectoryIdentity, ManagedGroup
from .registry import run_checks

User = get_user_model()

#: Which control each sheet supports: the cover sheet's map, so the auditor
#: doesn't have to ask.
CONTROLS = {
    "roster": "SOC 2 CC6.1, CC6.3 · PCI DSS 7.2.1–7.2.3 · ISO 27001 A.5.15, A.5.18",
    "matrix": "SOC 2 CC6.1 · PCI DSS 7.2.2 · ISO 27001 A.5.15",
    "changes": "SOC 2 CC6.2, CC6.3 · PCI DSS 7.2.2, 8.2.4 · ISO 27001 A.5.18",
    "joiners": "SOC 2 CC6.2 · PCI DSS 8.2.1 · ISO 27001 A.5.16",
    "leavers": "SOC 2 CC6.3, CC6.5 · PCI DSS 8.2.5, 8.2.6 · ISO 27001 A.5.18",
    "authentication": "SOC 2 CC6.1 · PCI DSS 8.2.6, 8.3.4, 8.6 · ISO 27001 A.5.17, A.8.5",
    "credentials": "SOC 2 CC6.1 · PCI DSS 8.6.1–8.6.3 · ISO 27001 A.5.17",
    "findings": "SOC 2 CC6.1, CC6.3 · PCI DSS 7.2.4 · ISO 27001 A.5.18",
    "reviews": "SOC 2 CC6.3 · PCI DSS 7.2.4, 7.2.5 · ISO 27001 A.5.18",
}


#: The columns the print view shows per sheet (the CSV has them all): what
#: fits a printed page and what an auditor reads first.
PRINT_COLUMNS: dict[str, tuple[str, ...]] = {
    "roster": (
        "username",
        "email",
        "superuser",
        "staff",
        "groups",
        "sign_in",
        "last_login",
        "live_tokens",
        "last_grant",
        "last_granted_by",
        "last_granted_at",
    ),
    "leavers": (
        "username",
        "deactivated_at",
        "by",
        "source",
        "tokens_revoked",
        "sessions_ended",
        "live_tokens_now",
        "days_after_directory_last_saw_them",
    ),
    "findings": ("title", "severity", "count", "summary"),
    "reviews": (
        "review",
        "username",
        "staff",
        "superuser",
        "groups",
        "decision",
        "decided_by",
        "note",
        "signed_by",
        "signed_at",
    ),
}


#: Sheets that show the state when the pack is generated, not at period end
#: (the rest are bounded by the period), and the ones the scope filters. Said
#: on the page, in cover.md and in JSON so an auditor isn't left to guess (T4-6).
AS_OF_GENERATION = {"roster", "matrix", "credentials", "findings"}
#: Event sheets that also carry what holds now (a joiner's first sign-in, a
#: leaver's tokens still live): bounded by the period, read at generation.
AS_OF_MIXED = {"joiners", "leavers", "authentication"}  # sign-in methods now, failures in the period
SCOPED = {"roster"}


@dataclass
class Sheet:
    key: str
    title: str
    description: str
    columns: tuple[str, ...]
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: A few headline numbers shown above the table.
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def controls(self) -> str:
        return CONTROLS.get(self.key, "")

    @property
    def print_columns(self) -> tuple[str, ...]:
        return PRINT_COLUMNS.get(self.key, self.columns)

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def as_of(self) -> str:
        """``generated`` (the state when the pack was built), ``period`` (events
        within it) or ``mixed`` (events within it, with what holds now)."""
        if self.key in AS_OF_GENERATION:
            return "generated"
        return "mixed" if self.key in AS_OF_MIXED else "period"

    @property
    def scoped(self) -> bool:
        """Whether the pack's scope (privileged / all) filters this sheet."""
        return self.key in SCOPED

    @property
    def reading(self) -> str:
        when = {
            "generated": "as of generation",
            "mixed": "within the period, with what holds now",
        }.get(self.as_of, "within the period")
        return f"{when}; {'filtered by the scope' if self.scoped else 'every account, whatever the scope'}"


@dataclass
class Evidence:
    period_start: date
    period_end: date
    scope: str
    generated_at: datetime
    generated_by: str
    system: str
    sheets: list[Sheet] = field(default_factory=list)

    def sheet(self, key: str) -> Sheet:
        for s in self.sheets:
            if s.key == key:
                return s
        raise KeyError(key)

    @property
    def period_label(self) -> str:
        return f"{self.period_start:%b %d, %Y} – {self.period_end:%b %d, %Y}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "scope": self.scope,
            "generated_at": self.generated_at.isoformat(),
            "generated_by": self.generated_by,
            "sheets": {
                s.key: {
                    "title": s.title,
                    "description": s.description,
                    "controls": s.controls,
                    "as_of": s.as_of,
                    "scoped": s.scoped,
                    "summary": s.summary,
                    "columns": list(s.columns),
                    "rows": s.rows,
                }
                for s in self.sheets
            },
        }


# --- Sheets ------------------------------------------------------------------------

SheetBuilder = Callable[[datetime, datetime, str], Sheet]


def _bounds(period_start: date, period_end: date) -> tuple[datetime, datetime]:
    return reviews._period_bounds(period_start, period_end)


def _iso(value: Any) -> str:
    """A timestamp as the sheets show it: local time to the second, which
    reads in a spreadsheet; the cover names the zone."""
    if not value:
        return ""
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _last_grant(user: Any) -> AccessEvent | None:
    """What last widened this account's access (a group, staff or superuser
    grant): who did it and when."""
    return (
        AccessEvent.objects.filter(
            subject=user,
            kind__in=[AccessEvent.Kind.GROUP_ADDED, AccessEvent.Kind.STAFF_ON, AccessEvent.Kind.SUPERUSER_ON],
        )
        .order_by("-at")
        .first()
    )


def roster_sheet(start: datetime, end: datetime, scope: str) -> Sheet:
    """Every account in scope and what makes it privileged, with who granted
    the latest widening and when: the sheet an auditor reads first."""
    identities: dict[int, list[DirectoryIdentity]] = {}
    for identity in DirectoryIdentity.objects.all():
        identities.setdefault(identity.user_id, []).append(identity)
    tokens = dict(
        APIToken.objects.filter(is_active=True).values_list("user").annotate(n=Count("pk")).values_list("user", "n")
    )
    rows = []
    for user in reviews.roster_users(scope):
        perms = user.get_all_permissions()
        last = _last_grant(user)
        seen = identities.get(user.pk, [])
        rows.append(
            {
                "username": user.get_username(),
                "email": user.email or "",
                "name": user.get_full_name() if user.get_full_name() != user.get_username() else "",
                "superuser": user.is_superuser,
                "staff": user.is_staff,
                "groups": "; ".join(sorted(g.name for g in user.groups.all())),
                "privileged_permissions": (
                    "(superuser)" if user.is_superuser else "; ".join(sorted(reviews.PRIVILEGED_PERMISSIONS & perms))
                ),
                "permission_count": len(perms),
                "sign_in": "directory" if seen else ("password" if user.has_usable_password() else "none"),
                "directory": "; ".join(f"{i.provider} {i.last_seen_at:%Y-%m-%d}" for i in seen),
                "last_login": _iso(user.last_login),
                "live_tokens": tokens.get(user.pk, 0),
                "last_grant": last.get_kind_display() if last else "",
                "last_granted_by": (last.actor_label or last.source) if last else "",
                "last_granted_at": _iso(last.at) if last else "",
            }
        )
    return Sheet(
        "roster",
        "Privileged roster" if scope == AccessReview.Scope.PRIVILEGED else "Account roster",
        "Every active account in scope: what makes it privileged, how it signs in, and who last widened its access.",
        (
            "username",
            "email",
            "name",
            "superuser",
            "staff",
            "groups",
            "privileged_permissions",
            "permission_count",
            "sign_in",
            "directory",
            "last_login",
            "live_tokens",
            "last_grant",
            "last_granted_by",
            "last_granted_at",
        ),
        rows,
        {
            "accounts": len(rows),
            "superusers": sum(1 for r in rows if r["superuser"]),
            "staff": sum(1 for r in rows if r["staff"]),
            "via_directory": sum(1 for r in rows if r["sign_in"] == "directory"),
        },
    )


def matrix_sheet(start: datetime, end: datetime, scope: str) -> Sheet:
    rows = list(services.access_matrix_rows())
    return Sheet(
        "matrix",
        "Access matrix",
        "One row per account × permission × source (superuser / group / direct), every account included.",
        services.MATRIX_COLUMNS,
        rows,
        {"rows": len(rows), "accounts": len({r["username"] for r in rows})},
    )


def changes_sheet(start: datetime, end: datetime, scope: str) -> Sheet:
    events = list(AccessEvent.objects.filter(at__range=(start, end)).order_by("at"))
    directory_group_ids = set(
        ManagedGroup.objects.filter(directory_role__isnull=False).values_list("group_id", flat=True)
    )
    by_month: dict[str, dict[str, int]] = {}
    no_actor = 0
    local_directory = 0
    rows = []
    for e in events:
        month = by_month.setdefault(f"{e.at:%Y-%m}", {"grants": 0, "removals": 0})
        if e.is_grant:
            month["grants"] += 1
        elif e.kind in (
            AccessEvent.Kind.GROUP_REMOVED,
            AccessEvent.Kind.PERMISSION_REMOVED,
            AccessEvent.Kind.GROUP_PERMISSION_REMOVED,
            AccessEvent.Kind.STAFF_OFF,
            AccessEvent.Kind.SUPERUSER_OFF,
            AccessEvent.Kind.DEACTIVATED,
        ):
            month["removals"] += 1
        if e.is_grant and not e.actor_label and not e.source.startswith(("directory:", "migrate")):
            no_actor += 1
        if (
            e.group_id in directory_group_ids
            and e.kind in (AccessEvent.Kind.GROUP_ADDED, AccessEvent.Kind.GROUP_REMOVED)
            and not e.source.startswith(("directory:", "migrate"))
        ):
            local_directory += 1
        rows.append(
            {
                "at": _iso(e.at),
                "kind": e.kind,
                "grant": e.is_grant,
                "actor": e.actor_label or "system",
                "subject": e.subject_label,
                "group": e.group_label,
                "permission": e.permission,
                "source": e.source,
                "request_id": e.request_id,
            }
        )
    return Sheet(
        "changes",
        "Access changes",
        "Every change to access in the period, with who made it and from where. "
        "Grants with no actor came from a shell or a script; a local change to a directory-managed group is one "
        "the directory will undo.",
        ("at", "kind", "grant", "actor", "subject", "group", "permission", "source", "request_id"),
        rows,
        {
            "changes": len(rows),
            "grants": sum(1 for r in rows if r["grant"]),
            "grants_without_actor": no_actor,
            "local_changes_to_directory_groups": local_directory,
            "by_month": by_month,
        },
    )


def joiners_sheet(start: datetime, end: datetime, scope: str) -> Sheet:
    created = {
        e.subject_id: e
        for e in AccessEvent.objects.filter(kind=AccessEvent.Kind.USER_CREATED, at__range=(start, end))
        if e.subject_id
    }
    rows = []
    for user in User.objects.filter(date_joined__range=(start, end)).order_by("date_joined"):
        event = created.get(user.pk)
        first_grant = AccessEvent.objects.filter(subject=user, kind__in=AccessEvent.GRANTS).order_by("at").first()
        identity = DirectoryIdentity.objects.filter(user=user).order_by("first_seen_at").first()
        rows.append(
            {
                "username": user.get_username(),
                "email": user.email or "",
                "joined": _iso(user.date_joined),
                "created_by": (event.actor_label or event.source) if event else "",
                "via_directory": identity.provider if identity else "",
                "staff": user.is_staff,
                "superuser": user.is_superuser,
                "groups": "; ".join(sorted(g.name for g in user.groups.all())),
                "first_grant": _iso(first_grant.at) if first_grant else "",
                "first_granted_by": (first_grant.actor_label or first_grant.source) if first_grant else "",
                "first_login": _iso(user.last_login) if user.last_login else "",
                "active": user.is_active,
            }
        )
    return Sheet(
        "joiners",
        "Joiners",
        "Accounts created in the period: by whom or which directory, and the first time their access was widened.",
        (
            "username",
            "email",
            "joined",
            "created_by",
            "via_directory",
            "staff",
            "superuser",
            "groups",
            "first_grant",
            "first_granted_by",
            "first_login",
            "active",
        ),
        rows,
        {"joiners": len(rows), "via_directory": sum(1 for r in rows if r["via_directory"])},
    )


def leavers_sheet(start: datetime, end: datetime, scope: str) -> Sheet:
    """Deactivations in the period, and whether the account's tokens and
    sessions went at the same moment (the events prove it), and how long
    after the directory last vouched for them."""
    rows = []
    deactivations = AccessEvent.objects.filter(kind=AccessEvent.Kind.DEACTIVATED, at__range=(start, end)).order_by("at")
    for e in deactivations:
        window = (e.at - timedelta(minutes=1), e.at + timedelta(minutes=1))
        same = AccessEvent.objects.filter(subject_label=e.subject_label, at__range=window)
        tokens_revoked = same.filter(kind=AccessEvent.Kind.TOKEN_REVOKED).count()
        sessions = same.filter(kind=AccessEvent.Kind.SESSIONS_ENDED).first()
        live_tokens_now = APIToken.objects.filter(user_id=e.subject_id, is_active=True).count() if e.subject_id else 0
        identity = (
            DirectoryIdentity.objects.filter(user_id=e.subject_id).order_by("-last_seen_at").first()
            if e.subject_id
            else None
        )
        lag = (e.at - identity.last_seen_at).days if identity and identity.last_seen_at <= e.at else ""
        rows.append(
            {
                "username": e.subject_label,
                "deactivated_at": _iso(e.at),
                "by": e.actor_label or "system",
                "source": e.source,
                "tokens_revoked": tokens_revoked,
                "sessions_ended": (sessions.detail or {}).get("count", 0) if sessions else 0,
                "live_tokens_now": live_tokens_now,
                "directory_last_seen": _iso(identity.last_seen_at) if identity else "",
                "days_after_directory_last_saw_them": lag,
                "account_exists": bool(e.subject_id),
            }
        )
    return Sheet(
        "leavers",
        "Leavers",
        "Accounts deactivated in the period: who did it, from where, and whether tokens and sessions were revoked "
        "at the same moment. An account with live tokens after deactivation is a finding.",
        (
            "username",
            "deactivated_at",
            "by",
            "source",
            "tokens_revoked",
            "sessions_ended",
            "live_tokens_now",
            "directory_last_seen",
            "days_after_directory_last_saw_them",
            "account_exists",
        ),
        rows,
        {
            "leavers": len(rows),
            "with_live_tokens_now": sum(1 for r in rows if r["live_tokens_now"]),
        },
    )


def _failures(start: datetime, end: datetime) -> dict[str, dict[str, int]]:
    """Failed sign-ins and lockouts per username in the period, from axes'
    failure log when it is kept (``AXES_ENABLE_ACCESS_FAILURE_LOG``)."""
    out: dict[str, dict[str, int]] = {}
    try:
        from axes.models import AccessFailureLog
    except Exception:
        return out
    qs = (
        AccessFailureLog.objects.filter(attempt_time__range=(start, end))
        .values("username")
        .annotate(n=Count("pk"), locked=Count("pk", filter=Q(locked_out=True)))
    )
    for row in qs:
        out[row["username"] or ""] = {"failures": row["n"], "lockouts": row["locked"]}
    return out


def authentication_sheet(start: datetime, end: datetime, scope: str) -> Sheet:
    identities: dict[int, list[DirectoryIdentity]] = {}
    for identity in DirectoryIdentity.objects.all():
        identities.setdefault(identity.user_id, []).append(identity)
    failures = _failures(start, end)
    rows = []
    for user in User.objects.filter(is_active=True).order_by("username"):
        seen = identities.get(user.pk, [])
        password = user.has_usable_password()
        rows.append(
            {
                "username": user.get_username(),
                "staff": user.is_staff,
                "superuser": user.is_superuser,
                "sign_in": "directory" if seen else ("password" if password else "none"),
                "directory_providers": "; ".join(i.provider for i in seen),
                "usable_password": password,
                "password_beside_directory": bool(seen and password),
                "last_login": _iso(user.last_login),
                "failed_sign_ins": failures.get(user.get_username(), {}).get("failures", 0),
                "lockouts": failures.get(user.get_username(), {}).get("lockouts", 0),
            }
        )
    return Sheet(
        "authentication",
        "Authentication",
        "How each active account signs in. An account with a usable password beside a directory identity can "
        "bypass single sign-on; failed sign-ins and lockouts come from the sign-in failure log when it is kept.",
        (
            "username",
            "staff",
            "superuser",
            "sign_in",
            "directory_providers",
            "usable_password",
            "password_beside_directory",
            "last_login",
            "failed_sign_ins",
            "lockouts",
        ),
        rows,
        {
            "accounts": len(rows),
            "via_directory": sum(1 for r in rows if r["sign_in"] == "directory"),
            "password_only": sum(1 for r in rows if r["sign_in"] == "password"),
            "password_beside_directory": sum(1 for r in rows if r["password_beside_directory"]),
            "failure_log_kept": bool(getattr(settings, "AXES_ENABLE_ACCESS_FAILURE_LOG", False)),
        },
    )


def credentials_sheet(start: datetime, end: datetime, scope: str) -> Sheet:
    rows = []
    for t in APIToken.objects.select_related("user").order_by("-is_active", "user__username", "name"):
        rows.append(
            {
                "name": t.name,
                "owner": t.user.get_username(),
                "owner_active": t.user.is_active,
                "access_level": t.access_level,
                "token_type": t.token_type,
                "created_at": _iso(t.created_at),
                "expires_at": _iso(t.expires_at),
                "last_used_at": _iso(t.last_used_at),
                "requests": t.request_count,
                "active": t.is_active,
                "revoked_at": _iso(t.revoked_at),
                "created_in_period": bool(t.created_at and start <= t.created_at <= end),
                "revoked_in_period": bool(t.revoked_at and start <= t.revoked_at <= end),
            }
        )
    return Sheet(
        "credentials",
        "API credentials",
        "Every API token: owner, tier, created, expiry, last use, and whether it was issued or revoked in the period.",
        (
            "name",
            "owner",
            "owner_active",
            "access_level",
            "token_type",
            "created_at",
            "expires_at",
            "last_used_at",
            "requests",
            "active",
            "revoked_at",
            "created_in_period",
            "revoked_in_period",
        ),
        rows,
        {
            "tokens": len(rows),
            "active": sum(1 for r in rows if r["active"]),
            "active_without_expiry": sum(1 for r in rows if r["active"] and not r["expires_at"]),
            "active_on_inactive_owner": sum(1 for r in rows if r["active"] and not r["owner_active"]),
            "issued_in_period": sum(1 for r in rows if r["created_in_period"]),
            "revoked_in_period": sum(1 for r in rows if r["revoked_in_period"]),
        },
    )


def findings_sheet(start: datetime, end: datetime, scope: str) -> Sheet:
    findings = run_checks()
    rows = [
        {"key": f.key, "title": f.title, "severity": f.severity, "count": f.count, "summary": f.summary}
        for f in findings
    ]
    order = {"danger": 3, "warning": 2, "info": 1, "ok": 0}
    worst = max((f.severity for f in findings), key=lambda s: order[s], default="ok")
    return Sheet(
        "findings",
        "Findings",
        "The least-privilege findings as they stand now. A stored bundle from the period's start is the "
        "before-picture; keep one per period.",
        ("key", "title", "severity", "count", "summary"),
        rows,
        {"worst": worst, **{s: sum(1 for f in findings if f.severity == s) for s in ("danger", "warning", "info")}},
    )


def reviews_sheet(start: datetime, end: datetime, scope: str) -> Sheet:
    """Signed access reviews whose period overlaps this one, one row per
    reviewed account, so the attestation travels with the pack."""
    rows: list[dict[str, Any]] = []
    signed = AccessReview.objects.filter(
        status=AccessReview.Status.SIGNED, period_start__lte=end.date(), period_end__gte=start.date()
    ).order_by("period_start", "pk")
    for review in signed:
        rows.extend(reviews.review_csv_rows(review))
    return Sheet(
        "reviews",
        "Access reviews",
        "The signed attestations covering the period: who reviewed each account, what they decided, and who signed.",
        reviews.REVIEW_CSV_COLUMNS,
        rows,
        {
            "signed_reviews": signed.count(),
            "accounts_reviewed": len(rows),
            "remove": sum(1 for r in rows if r["decision"] == "remove"),
            "flagged": sum(1 for r in rows if r["decision"] == "flagged"),
        },
    )


#: The sheets, in order: the nine built in, then any an app registers with
#: :func:`register_sheet` (from ``apps/<app>/access_evidence.py``, which the
#: Access app autodiscovers). Read through :func:`sheets` / :func:`sheet_keys`,
#: which see registrations made after this module loaded (T4-4).
_SHEETS: list[tuple[str, SheetBuilder]] = [
    ("roster", roster_sheet),
    ("matrix", matrix_sheet),
    ("changes", changes_sheet),
    ("joiners", joiners_sheet),
    ("leavers", leavers_sheet),
    ("authentication", authentication_sheet),
    ("credentials", credentials_sheet),
    ("findings", findings_sheet),
    ("reviews", reviews_sheet),
]


def register_sheet(
    key: str,
    builder: SheetBuilder,
    *,
    controls: str = "",
    print_columns: Iterable[str] | None = None,
    as_of: str = "period",
    scoped: bool = False,
) -> SheetBuilder:
    """Add a sheet to the evidence pack: ``builder(start, end, scope) -> Sheet``
    (``start``/``end`` are aware datetimes bounding the period). It then
    appears as a tab on the page, as a CSV in the bundle, in the JSON, the CLI
    and REST. ``controls`` is the line on the cover's controls map;
    ``print_columns`` the subset the print view shows (all columns otherwise).
    Re-registering a key replaces it; a built-in key can't be replaced.
    Returns ``builder`` so it can be used as a decorator's target."""
    import re

    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,40}", key):
        raise ValueError(f"Evidence sheet key {key!r} must be a lowercase slug.")
    if as_of not in ("period", "generated", "mixed"):
        raise ValueError("as_of is 'period', 'generated' or 'mixed'.")  # checked before anything registers (G4-8)
    if key in _BUILTIN_KEYS or key == "cover":
        raise ValueError(f"{key!r} is a built-in evidence sheet (or the page's cover tab).")
    _SHEETS[:] = [(k, b) for k, b in _SHEETS if k != key] + [(key, builder)]
    if controls:
        CONTROLS[key] = controls
    if print_columns is not None:
        PRINT_COLUMNS[key] = tuple(print_columns)
    (AS_OF_GENERATION.add if as_of == "generated" else AS_OF_GENERATION.discard)(key)
    (AS_OF_MIXED.add if as_of == "mixed" else AS_OF_MIXED.discard)(key)
    (SCOPED.add if scoped else SCOPED.discard)(key)
    return builder


def sheets() -> list[tuple[str, SheetBuilder]]:
    """Every sheet, built-in first, as ``(key, builder)``."""
    return list(_SHEETS)


def sheet_keys() -> tuple[str, ...]:
    return tuple(key for key, _ in _SHEETS)


_BUILTIN_KEYS = frozenset(sheet_keys())


def build(
    period_start: date,
    period_end: date,
    *,
    scope: str = "privileged",
    generated_by: Any = None,
    only: Iterable[str] | None = None,
) -> Evidence:
    """The pack for the period. ``only`` limits the sheets built (the page
    previews one at a time); the cover is always derivable from the result."""
    if scope not in AccessReview.Scope.values:
        raise ValueError(f"scope must be one of {', '.join(AccessReview.Scope.values)}.")
    if period_end < period_start:
        raise ValueError("The period ends before it starts.")
    start, end = _bounds(period_start, period_end)
    wanted = set(only) if only is not None else set(sheet_keys())
    who = generated_by.get_username() if getattr(generated_by, "pk", None) is not None else str(generated_by or "cli")
    pack = Evidence(
        period_start=period_start,
        period_end=period_end,
        scope=scope,
        generated_at=timezone.now(),
        generated_by=who,
        system=str(getattr(settings, "BRAND_NAME", "SmallStack")),
    )
    for key, builder in sheets():
        if key in wanted:
            sheet = builder(start, end, scope)
            if sheet.key != key:
                # The registered key is the sheet's address (tab, CSV); a
                # builder that names its Sheet otherwise would 500 there (G2-4).
                sheet.key = key
            pack.sheets.append(sheet)
    return pack


# --- Exports ---------------------------------------------------------------------------


def _scoped_note(pack: Evidence) -> str:
    scoped = [s.title for s in pack.sheets if s.scoped]
    return f" (only {', '.join(scoped)} {'is' if len(scoped) == 1 else 'are'})." if scoped else "."


def cover_markdown(pack: Evidence) -> str:
    lines = [
        f"# Access evidence — {pack.system}",
        "",
        f"Period: {pack.period_label}  ",
        f"Scope: {pack.scope}  ",
        f"Generated: {timezone.localtime(pack.generated_at):%Y-%m-%d %H:%M} by {pack.generated_by}  ",
        f"Times: {timezone.get_current_timezone_name()}",
        "",
        "| Sheet | Rows | Reflects | Supports | File |",
        "|---|---:|---|---|---|",
    ]
    for s in pack.sheets:
        lines.append(f"| {s.title} | {s.count} | {s.reading} | {s.controls} | `{s.key}.csv` |")
    lines += ["", "## Headline numbers", ""]
    for s in pack.sheets:
        if s.summary:
            flat = ", ".join(f"{k} {v}" for k, v in s.summary.items() if not isinstance(v, dict))
            lines.append(f"- **{s.title}**: {flat}")
    lines += [
        "",
        "## How to read it",
        "",
        "- Every row is read from the system's own records at generation time; nothing is typed in by hand.",
        "- *Reflects* says whether a sheet is the state when the pack was generated or the events within the "
        "period, and whether the scope filters it" + _scoped_note(pack),
        "- `changes.csv` is the continuous log (every grant and removal, with actor, source and request id).",
        "- `reviews.csv` is the periodic control: a named attester's decision on each privileged account, signed.",
        "- `evidence.json` holds every sheet with its summary, for tooling.",
        "",
    ]
    return "\n".join(lines)


_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")


def _safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_FORMULA_LEADS):
        return "'" + value
    return value


def sheet_csv(sheet: Sheet) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(sheet.columns), extrasaction="ignore")
    writer.writeheader()
    for row in sheet.rows:
        writer.writerow({k: _safe(v) for k, v in row.items()})
    return out.getvalue()


def bundle_zip(pack: Evidence) -> bytes:
    """``cover.md``, one CSV per sheet, ``evidence.json``."""
    buf = io.BytesIO()
    stamp = pack.generated_at
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        info = lambda name: zipfile.ZipInfo(name, date_time=stamp.timetuple()[:6])  # noqa: E731
        zf.writestr(info("cover.md"), cover_markdown(pack))
        for s in pack.sheets:
            zf.writestr(info(f"{s.key}.csv"), sheet_csv(s))
        zf.writestr(info("evidence.json"), json.dumps(pack.as_dict(), indent=2, default=str))
    return buf.getvalue()


def bundle_name(pack: Evidence) -> str:
    return f"access-evidence-{pack.period_start:%Y%m%d}-{pack.period_end:%Y%m%d}"
