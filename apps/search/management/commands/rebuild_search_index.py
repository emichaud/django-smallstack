"""Rebuild the search index for one or all indexed models.

Useful after a schema change, after enabling search on an existing
model (so already-saved rows get indexed), or to recover from a
corrupted index.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Rebuild the search index for one or all indexed CRUDViews."

    def add_arguments(self, parser):
        parser.add_argument(
            "target",
            nargs="?",
            help="Model label (e.g. 'support.Ticket'). Omit to rebuild all.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Rebuild every indexed model.",
        )

    def handle(self, *args, **options):
        from apps.search.backends import get_backend
        from apps.search.registry import all_views

        backend = get_backend()
        views = list(all_views())

        if not views:
            self.stdout.write(self.style.WARNING("No indexed CRUDViews — nothing to do."))
            return

        target_label = options.get("target")
        if not target_label and not options.get("all"):
            self.stdout.write(
                "Specify a model label (e.g. 'support.Ticket') or use --all.\n"
                f"Available: {', '.join(v.model_label for v in views)}"
            )
            return

        targets = views if options.get("all") else [v for v in views if v.model_label == target_label]
        if not targets:
            self.stdout.write(self.style.ERROR(
                f"No registered CRUDView for {target_label!r}. "
                f"Did you mean one of: {', '.join(v.model_label for v in views)}?"
            ))
            return

        for view in targets:
            self.stdout.write(f"Rebuilding {view.model_label} ({backend.name})...")
            count = backend.rebuild(view)
            self.stdout.write(self.style.SUCCESS(f"  indexed {count} rows"))
