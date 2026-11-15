"""``manage.py access`` (also ``sc access``): who may do what, from a shell.

    access explain <user> [--json]        groups, every permission with its sources
    access check <user> <app.codename>    has_perm, with the reasons; exit 1 when not
    access grant <user> <group> [--user ACTOR] [--reason …]
    access revoke <user> <group> [--user ACTOR] [--reason …]
    access groups [--json]                groups, members, drift against the code
    access findings [--rows] [--json]     the least-privilege review (access_report)

``grant``/``revoke`` run the same membership service as the Access pages, REST
and an approved MCP request, so the change is checked and recorded the same
way. ``--user`` names the person it is attributed to (they must hold
``accounts.change_user``); without it the change is recorded from ``cli`` with
no actor, as a local admin's shell change.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.access import services


class Command(BaseCommand):
    help = "Access from the shell: explain, check, grant, revoke, groups, findings."

    def add_arguments(self, parser: CommandParser) -> None:
        subs = parser.add_subparsers(dest="verb", required=True)
        explain = subs.add_parser("explain", help="what an account can do, and why")
        explain.add_argument("who")
        explain.add_argument("--json", action="store_true")
        check = subs.add_parser("check", help="whether an account holds one permission")
        check.add_argument("who")
        check.add_argument("perm", help="app_label.codename")
        check.add_argument("--json", action="store_true")
        for verb, text in (("grant", "add an account to a group"), ("revoke", "remove an account from a group")):
            sub = subs.add_parser(verb, help=text)
            sub.add_argument("who")
            sub.add_argument("group")
            sub.add_argument("--user", dest="actor", help="the person this change is attributed to")
            sub.add_argument("--reason", default="", help="kept in the record")
        groups = subs.add_parser("groups", help="groups, members and drift")
        groups.add_argument("--json", action="store_true")
        findings = subs.add_parser("findings", help="the least-privilege review")
        findings.add_argument("--rows", action="store_true")
        findings.add_argument("--json", action="store_true")

    def handle(self, *args: Any, **opts: Any) -> None:
        verb = opts["verb"]
        handler = getattr(self, f"_{verb}")
        handler(opts)

    def _dump(self, data: Any) -> None:
        json.dump(data, self.stdout, indent=2, default=str)
        self.stdout.write("")

    def _user(self, ref: str) -> Any:
        try:
            return services.resolve_user(ref)
        except LookupError as exc:
            raise CommandError(str(exc)) from exc

    def _group(self, ref: str) -> Any:
        try:
            return services.resolve_group(ref)
        except LookupError as exc:
            raise CommandError(str(exc)) from exc

    def _explain(self, opts: dict[str, Any]) -> None:
        user = self._user(opts["who"])
        data = services.user_payload(user)
        if opts["json"]:
            self._dump(data)
            return
        flags = [
            f
            for f, on in (("active", data["active"]), ("staff", data["staff"]), ("superuser", data["superuser"]))
            if on
        ]
        self.stdout.write(
            f"{data['username']}  {' '.join(flags) or 'inactive'}  last sign-in {data['last_login'] or 'never'}"
        )
        self.stdout.write("groups: " + (", ".join(g["name"] for g in data["groups"]) or "none"))
        if data["direct_permissions"]:
            self.stdout.write("direct permissions: " + ", ".join(data["direct_permissions"]))
        self.stdout.write(f"{data['permission_count']} permission(s); {data['active_tokens']} live token(s)")
        for perm in data["permissions"]:
            self.stdout.write(f"  {perm['permission']:<48} via {', '.join(perm['sources'])}")

    def _check(self, opts: dict[str, Any]) -> None:
        if "." not in opts["perm"]:
            raise CommandError("perm must be app_label.codename")
        user = self._user(opts["who"])
        data = services.explanation_payload(user, opts["perm"])
        if opts["json"]:
            self._dump(data)
        else:
            verdict = "may" if data["allowed"] else "may not"
            self.stdout.write(f"{data['username']} {verdict} {data['permission']}")
            for reason in data["reasons"]:
                self.stdout.write(f"  - {reason}")
        if not data["allowed"]:
            sys.exit(1)

    def _membership(self, opts: dict[str, Any], member: bool) -> None:
        user = self._user(opts["who"])
        group = self._group(opts["group"])
        actor = self._user(opts["actor"]) if opts.get("actor") else None
        source = "cli" if not opts.get("reason") else f"cli: {opts['reason']}"[:200]
        try:
            changed = services.set_membership(user, group, member, actor=actor, source=source)
        except PermissionError as exc:
            raise CommandError(str(exc)) from exc
        verb = "added to" if member else "removed from"
        if changed:
            self.stdout.write(self.style.SUCCESS(f"{user.get_username()} {verb} {group.name}"))
        else:
            self.stdout.write(
                f"{user.get_username()} was already {'in' if member else 'out of'} {group.name}; nothing changed"
            )

    def _grant(self, opts: dict[str, Any]) -> None:
        self._membership(opts, True)

    def _revoke(self, opts: dict[str, Any]) -> None:
        self._membership(opts, False)

    def _groups(self, opts: dict[str, Any]) -> None:
        rows = [services.group_payload(g) for g in services.groups_with_counts()]
        if opts["json"]:
            self._dump(rows)
            return
        for row in rows:
            drift = row["drift"]
            note = ""
            if drift and (drift.get("missing") or drift.get("added")):
                note = f"  drift: -{len(drift.get('missing', []))} +{len(drift.get('added', []))}"
            declared = "code" if row["declared_in_code"] else "ad hoc"
            counts = f"{row['member_count']:>3} member(s) {len(row['permissions']):>3} permission(s)"
            self.stdout.write(f"{row['name']:<28} {counts}  {declared}{note}")

    def _findings(self, opts: dict[str, Any]) -> None:
        args = [flag for flag in ("--rows", "--json") if opts.get(flag.strip("-"))]
        call_command("access_report", *args, stdout=self.stdout, stderr=self.stderr)
