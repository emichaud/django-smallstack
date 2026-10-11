"""Regenerate (or check) ``docs/skills/index.json`` from the README skill tables."""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.smallstack import skills_index


class Command(BaseCommand):
    help = (
        "Rebuild docs/skills/index.json from the tables in docs/skills/README.md. "
        "With --check, report drift instead of writing (exit 1 if out of sync)."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--check",
            action="store_true",
            help="Don't write — fail if the index is stale or a skill file is unregistered.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        root = skills_index.skills_dir()

        # A fork is free to drop the agent-skill tree entirely; that isn't a failure.
        if not (root / skills_index.README_NAME).exists():
            self.stdout.write(f"No {root}/{skills_index.README_NAME} — nothing to index.")
            return

        drift = skills_index.check(root)

        if options["check"]:
            if drift.ok:
                count = len(skills_index.parse_readme(root))
                self.stdout.write(self.style.SUCCESS(f"Skill index in sync ({count} skills)."))
                return
            for problem in drift.describe():
                self.stderr.write(self.style.ERROR(problem))
            raise CommandError(f"{len(drift.describe())} skill-index problem(s).")

        for name in drift.unregistered:
            self.stderr.write(
                self.style.WARNING(f"{name}: no README row — add one so agents can find it.")
            )
        for name in drift.dangling:
            self.stderr.write(self.style.WARNING(f"{name}: README row has no file on disk."))

        path = skills_index.write_index(root)
        count = len(skills_index.build_index(root)["skills"])
        self.stdout.write(self.style.SUCCESS(f"Wrote {path} ({count} skills)."))
