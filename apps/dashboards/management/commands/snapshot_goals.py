"""Save goal-list weeks: ``manage.py snapshot_goals`` (last week, every list),
``--week 2026-11-02`` (any day of the week), ``--list <slug>`` (one list),
``--fill 8`` (the past 8 weeks that have none; ``--replace`` retakes them)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser


class Command(BaseCommand):
    help = "Save goal lists' weekly snapshots (the week just ended, unless told otherwise)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--due", action="store_true", help="Capture every tracked period that's due, as the hourly job does."
        )
        parser.add_argument("--list", dest="slug", default="", help="Only this goal list (slug).")
        parser.add_argument("--week", default="", help="The week to save: any day of it, or 2026-W45.")
        parser.add_argument("--fill", type=int, default=0, help="Save the past N weeks that have no snapshot.")
        parser.add_argument("--replace", action="store_true", help="With --fill, retake weeks that have one.")

    def handle(self, *args: Any, **options: Any) -> None:
        from apps.dashboards.models import GoalList
        from apps.dashboards.weeks import (
            backfill,
            parse_week,
            snapshot_last_week,
            snapshot_user,
            take_snapshot,
            week_label,
        )

        if options["due"]:
            from apps.dashboards.snapshots import capture_due

            self.stdout.write(f"Took {capture_due()} capture(s).")
            return
        lists = list(GoalList.objects.filter(slug=options["slug"])) if options["slug"] else None
        if options["slug"] and not lists:
            raise CommandError(f"No goal list {options['slug']!r}.")
        if options["fill"]:
            total = sum(
                backfill(g, options["fill"], replace=options["replace"])
                for g in (lists or GoalList.objects.all())
                if snapshot_user(g) is not None
            )
            self.stdout.write(f"Saved {total} week(s).")
            return
        if options["week"]:
            start = parse_week(options["week"])
            if start is None:
                raise CommandError(f"Not a week: {options['week']!r}.")
            done = 0
            for g in lists or GoalList.objects.all():
                if snapshot_user(g) is None:
                    continue
                try:
                    take_snapshot(g, start)
                except ValueError as exc:
                    raise CommandError(str(exc)) from exc
                done += 1
            self.stdout.write(f"Saved the week of {week_label(start)} for {done} goal list(s).")
            return
        self.stdout.write(f"Saved last week for {snapshot_last_week(lists=lists)} goal list(s).")
