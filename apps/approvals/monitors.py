"""Approvals status monitor — is the gate actually working?

Two silent failure modes, both of which look fine from inside the app:

1. **Nobody is draining the email queue.** A decision enqueues its mail on the
   ``email`` queue and returns; with the shipped database-backed task backend
   ``enqueue()`` never raises, so "no exception" proved nothing and an install
   without a ``db_worker`` sent *no* approval email at all — silently, forever.
   (F-07.)
2. **Nobody is running the expiry sweep.** Lazy expiry is bounded per request
   (F-12), so a large overdue backlog needs the scheduled job. An unbounded
   backlog means rows that say "pending" and aren't.

Both are operator-configuration facts, which is exactly what a status monitor is
for: cheap to check, visible on ``/smallstack/status/overview/``, and it says so
out loud rather than pretending.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.smallstack.monitors import CheckResult, Monitor, Service

SERVICE_KEY = "approvals"

_ICON = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
    '<path d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z'
    'm-2 16-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/></svg>'
)


class ApprovalsService(Service):
    key = SERVICE_KEY
    title = "Approvals"
    description = "Human-in-the-loop gate"
    category = "core"
    order = 47
    icon = _ICON
    detail_url_name = "approvals/requests-list"


class ApprovalsFanoutMonitor(Monitor):
    """DOWN when approval mail is piling up unsent, or expiry is far behind."""

    key = "approvals-fanout"
    service = SERVICE_KEY
    title = "Approval notifications going out"
    order = 10
    detail_url_name = "approvals/requests-list"

    def _stale_after(self) -> timedelta:
        minutes = int(
            getattr(settings, "SMALLSTACK_APPROVALS_EMAIL_BACKLOG_MINUTES", 15)
        )
        return timedelta(minutes=minutes)

    def _queued_emails(self) -> tuple[int, int]:
        """``(stale, total)`` approval-email tasks still sitting READY.

        ``stale`` is the subset older than the grace window — the only part that
        means "nothing is draining this". ``total`` exists so the healthy note can
        say what is actually true: reporting "email queue drained" while messages
        are queued-but-young described the opposite of the situation, on the one
        channel that fails silently. (Test round 2026-09-26, E2.)

        ``(-1, -1)`` when the task backend keeps no inspectable queue, and when the
        email channel is switched off — with nothing being enqueued, a backlog is
        not a thing that can exist, and any rows left from before the switch are
        not an operator's problem to act on. (E1.)
        """
        if not getattr(settings, "SMALLSTACK_APPROVALS_EMAILS_ENABLED", True):
            return (-1, -1)
        try:
            from django_tasks_db.models import DBTaskResult
        except Exception:  # noqa: BLE001 — a different task backend
            return (-1, -1)
        queued = DBTaskResult.objects.filter(
            task_path__startswith="apps.approvals.tasks.notify_", status="READY"
        )
        cutoff = timezone.now() - self._stale_after()
        return (queued.filter(enqueued_at__lt=cutoff).count(), queued.count())

    def _email_links_are_broken(self) -> bool:
        """True when the email channel is on but SITE_DOMAIN is still a local default.

        Only a *configuration* check — no network. Skipped when emails are off (no
        links are being sent) and when DEBUG is on (localhost is correct there).
        """
        if not getattr(settings, "SMALLSTACK_APPROVALS_EMAILS_ENABLED", True):
            return False
        if getattr(settings, "DEBUG", False):
            return False
        domain = str(getattr(settings, "SITE_DOMAIN", "localhost:8000") or "")
        host = domain.split("/")[0].split(":")[0].lower()
        return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1", ""}

    def check(self) -> CheckResult:
        from .models import ApprovalRequest

        if not getattr(settings, "SMALLSTACK_APPROVALS_ENABLED", True):
            return CheckResult.up(note="Approvals disabled")

        # Collect EVERY problem rather than returning on the first. The
        # SITE_DOMAIN branch used to return before the backlog was even looked
        # at, so an install with both faults learned about the second only after
        # fixing the first — two deploys to discover two one-line config facts.
        # (Test round 2026-09-26, E3.)
        problems: list[str] = []
        notes: list[str] = []

        # Every approval email builds an ABSOLUTE url from SITE_DOMAIN, because
        # the mail is sent from a signal receiver or a task and so has no request
        # to derive the host from. On the default (`localhost:8000`) the link in
        # "Approval needed: …" is dead — which matters most for the headline
        # non-staff story, "assignees decide via the emailed console link". (F-33.)
        if self._email_links_are_broken():
            problems.append(
                "approval emails link to "
                f"{getattr(settings, 'SITE_DOMAIN', 'localhost:8000')} — set "
                "SITE_DOMAIN to this install's real host, or the console link "
                "in every approval email is dead. Set "
                "SMALLSTACK_APPROVALS_EMAILS_ENABLED=False if you do not use "
                "the email channel."
            )

        stale_mail, queued_mail = self._queued_emails()
        if stale_mail > 0:
            problems.append(
                f"{stale_mail} approval email task(s) queued and unrun — "
                "start a worker on the 'email' queue "
                "(manage.py db_worker --queue-name email), or set "
                "SMALLSTACK_APPROVALS_EMAILS_INLINE=True."
            )
        elif queued_mail > 0:
            # Queued but young: healthy, and say so accurately.
            notes.append(f"{queued_mail} email(s) queued, within the grace window")
        elif queued_mail == 0:
            notes.append("email queue clear")

        overdue = ApprovalRequest.objects.overdue().count()
        limit = int(getattr(settings, "SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT", 25))
        if overdue > max(limit, 1) * 4:
            problems.append(
                f"{overdue} overdue request(s) still marked pending — the "
                "'Approvals: expire overdue requests' job is not running."
            )
        elif overdue:
            notes.append(f"{overdue} overdue awaiting sweep")

        if problems:
            return CheckResult.down(note=" · ".join(problems))

        pending = ApprovalRequest.objects.actionable().count()
        notes.append(f"{pending} awaiting a human")
        return CheckResult.up(note=" · ".join(notes))
