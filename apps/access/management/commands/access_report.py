"""``manage.py access_report``: the least-privilege findings, for a terminal,
a cron job or a compliance run.

Exits 0 when nothing needs attention, 1 on a warning, 2 on a danger, so a
scheduled run can alert. ``--json`` writes the full snapshot (accounts,
groups, findings) for keeping as evidence.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.access.registry import run_checks
from apps.access.services import snapshot

EXIT = {"ok": 0, "info": 0, "warning": 1, "danger": 2}
MARK = {"ok": "✓", "info": "·", "warning": "!", "danger": "✗"}


class Command(BaseCommand):
    help = "Report least-privilege findings; exit 1 on a warning, 2 on a danger."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--json", action="store_true", help="write the full access snapshot as JSON")
        parser.add_argument("--rows", action="store_true", help="list the accounts or groups behind each finding")

    def handle(self, *args: Any, **opts: Any) -> None:
        if opts["json"]:
            json.dump(snapshot(), self.stdout, indent=2)
            self.stdout.write("")
            findings = run_checks()
        else:
            findings = run_checks()
            for f in findings:
                self.stdout.write(f"{MARK[f.severity]} {f.title}: {f.summary}")
                if opts["rows"]:
                    for row in f.rows:
                        self.stdout.write(f"    - {row['label']}  {row.get('meta', '')}".rstrip())
        worst = max((EXIT[f.severity] for f in findings), default=0)
        if worst:
            sys.exit(worst)
