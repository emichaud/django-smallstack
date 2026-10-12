"""Drain newsletter sends from the command line.

The same service the scheduled tick uses, so a cron-driven deployment and a
worker-driven one behave identically. Synchronous, with a meaningful exit
code, so it can be wired to a cron job that alerts on failure.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.blog import service
from apps.blog.models import Issue


class Command(BaseCommand):
    help = (
        "Send queued newsletter batches. With --issue, queue and send one "
        "issue; otherwise drain whatever is already in flight."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--issue", help="An issue uid to queue and send.")
        parser.add_argument("--batch-size", type=int, default=None)
        parser.add_argument("--max-batches", type=int, default=None)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the audience size and send nothing.",
        )
        parser.add_argument(
            "--reap",
            action="store_true",
            help="Only return orphaned claims to the queue, then exit.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["reap"]:
            count = service.reap_stale_claims()
            self.stdout.write(self.style.SUCCESS(f"Returned {count} orphaned delivery(s)."))
            return

        if options["issue"]:
            try:
                issue = Issue.objects.select_related("blog").get(uid=options["issue"])
            except (Issue.DoesNotExist, ValueError, TypeError) as exc:
                raise CommandError(f"No issue with uid {options['issue']!r}.") from exc

            if options["dry_run"]:
                try:
                    # actor=None: a CLI run is a trusted internal caller.
                    result = service.queue_issue(issue, dry_run=True, actor=None)
                except service.BlogServiceError as exc:
                    raise CommandError(str(exc)) from exc
                self.stdout.write(
                    f"Would send “{result['subject']}” to {result['recipients']} subscriber(s)."
                )
                return

            if issue.status in {Issue.Status.DRAFT, Issue.Status.SCHEDULED}:
                try:
                    service.queue_issue(issue, actor=None)
                except service.BlogServiceError as exc:
                    raise CommandError(str(exc)) from exc
                self.stdout.write(f"Queued {issue.recipient_count} recipient(s).")

        service.reap_stale_claims()
        results = service.process_sending_issues(
            batch_size=options["batch_size"], max_batches=options["max_batches"]
        )

        if not results:
            self.stdout.write("Nothing to send.")
            return

        sent = sum(r["sent"] for r in results)
        failed = sum(r["failed"] for r in results)
        retry = sum(r["retry"] for r in results)
        summary = f"Sent {sent}, failed {failed}, retrying {retry}, across {len(results)} batch(es)."
        self.stdout.write(self.style.SUCCESS(summary) if not failed else self.style.WARNING(summary))
