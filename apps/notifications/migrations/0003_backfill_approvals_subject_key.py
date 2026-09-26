"""Backfill ``subject_key`` on approvals notifications created before 0002.

F-42. Migration 0002 added ``subject_key`` and left existing rows with ``''``.
:func:`apps.notifications.services.resolve` addresses rows **by** ``subject_key``,
so the "Approval needed" rows that motivated the retirement feature — the ones
already sitting unread in every approver's bell when the upgrade lands — could
never be retired. Only requests filed *after* the migration were addressable.

On the reference install that was 105 of 105 unread ``approvals.requested`` rows,
several of them pointing at requests that were already decided. So on every
existing install the badge stayed permanently inflated by exactly the backlog the
feature was built to clear, with no way for an operator to tell which rows were
un-retirable — and a release note claiming "stale bells are retired" would have
been wrong for every upgrader.

Two passes, both idempotent so this can be re-run as a one-off:

1. Derive ``subject_key`` from ``url`` for ``kind__startswith="approvals."`` rows.
   The URL shape is stable (``/smallstack/approvals/requests/<pk>/``) and the
   derivation is the same one ``receivers.subject_key()`` uses.
2. Mark read any backfilled row whose request has already reached a terminal
   state. That is what the operator actually wants from "retire stale bells", and
   it is the half a forward-only fix cannot do.
"""

from __future__ import annotations

import re

from django.db import migrations

# /smallstack/approvals/requests/<pk>/ — also tolerates a query string or an
# absolute URL, since kinds may set their own landing_url.
_PK_FROM_URL = re.compile(r"/approvals/requests/(\d+)/")

TERMINAL_STATUSES = ("approved", "rejected", "canceled", "expired")


def backfill(apps, schema_editor):
    Notification = apps.get_model("smallstack_notifications", "Notification")
    rows = Notification.objects.filter(
        kind__startswith="approvals.", subject_key=""
    ).exclude(url="")

    to_update = []
    request_pks: set[int] = set()
    for row in rows.iterator(chunk_size=500):
        match = _PK_FROM_URL.search(row.url or "")
        if not match:
            continue
        pk = int(match.group(1))
        row.subject_key = f"approvals.request:{pk}"
        to_update.append(row)
        request_pks.add(pk)
    if to_update:
        Notification.objects.bulk_update(to_update, ["subject_key"], batch_size=500)

    # Pass 2 — rows whose request is already finished were never going to become
    # actionable again, so retire them.
    #
    # Scope note: this filters on `subject_key__in=keys`, i.e. on the *subjects*
    # pass 1 touched — not on the individual rows it rewrote. So an unread
    # "Approval needed" bell created AFTER 0002 (a second recipient on the same
    # terminal request) is marked read too. That is the intended outcome — the
    # request is decided, so the bell is stale whenever it was written — but it
    # is wider than "only the rows this migration addressed". (F-56)
    if not request_pks:
        return
    try:
        ApprovalRequest = apps.get_model("smallstack_approvals", "ApprovalRequest")
    except LookupError:  # pragma: no cover — approvals not installed
        return
    terminal = set(
        ApprovalRequest.objects.filter(
            pk__in=request_pks, status__in=TERMINAL_STATUSES
        ).values_list("pk", flat=True)
    )
    if not terminal:
        return
    keys = [f"approvals.request:{pk}" for pk in terminal]
    from django.utils import timezone

    Notification.objects.filter(
        subject_key__in=keys, read_at__isnull=True, kind="approvals.requested"
    ).update(read_at=timezone.now())


def noop_reverse(apps, schema_editor):
    """Deliberately not reversible in data terms.

    Clearing ``subject_key`` again would re-break retirement, and un-reading rows
    is not information we have. The schema change is in 0002; this migration only
    fills in values, so rolling it back is a no-op.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("smallstack_notifications", "0002_notification_subject_key_and_more"),
        ("smallstack_approvals", "0001_initial"),
    ]

    operations = [migrations.RunPython(backfill, noop_reverse)]
