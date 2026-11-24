"""``manage.py access`` (also ``sc access``): who may do what, from a shell.

    access explain <user> [--json]        groups, every permission with its sources
    access check <user> <app.codename>    has_perm, with the reasons; exit 1 when not
    access grant <user> <group> [--user ACTOR] [--reason …]
    access revoke <user> <group> [--user ACTOR] [--reason …]
    access groups [--json]                groups, members, drift against the code
    access group new <name> | rename <group> <name> | rm <group>      [--user ACTOR] [--reason …]
    access group grant <group> <app.codename> | revoke <group> <app.codename>
    access group role <group> <Role.Key> [--staff]   directory-managed ("" makes it local again)
                                          the groups themselves: what the group page does
    access perm rm <user> <app.codename> [--user ACTOR]
                                          a direct permission off an account (grant through a group)
    access findings [--rows] [--json]     the least-privilege findings (access_report)
    access directory-manifest [--provider entra|generic] [--json]
                                          the roles a directory administrator creates
    access review open --from DATE --to DATE [--scope privileged|all] [--user ACTOR]
    access review list [--json]           every review, open and signed
    access review show <id> [--json|--csv]  one review with its roster and decisions

    access evidence --from DATE --to DATE [--scope privileged|all] [--out FILE.zip | --store | --json]
                                          the audit pack: cover + one CSV per sheet + JSON
    access packs [--scope …] [--json]     the stored packs, with their SHA-256
    access cadence [--status] [--json]    run the review cadence once (open a closed
                                          quarter's review, remind, escalate), or just report

Deciding and signing a review happen on the Reviews page only: an
attestation is a person's act, so there is no shell, REST or MCP path for it.
``cadence`` is what the daily scheduled job runs; a deployment without the
scheduler calls it from cron.

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


def _status_payload(s: dict[str, Any]) -> dict[str, Any]:
    job = s["job"]
    return {
        "cadence": s["cadence"],
        "enabled": s["enabled"],
        "scope": s["scope"],
        "period": {"label": s["period"].label, "start": s["period"].start, "end": s["period"].end},
        "signed_review": s["signed"].pk if s["signed"] else None,
        "open_review": s["open"].pk if s["open"] else None,
        "due": s["due"],
        "days_until_due": s["days_until_due"],
        "last_signed_review": s["last_signed"].pk if s["last_signed"] else None,
        "next_close": s["next_close"],
        "schedule": {"name": job.name, "enabled": job.enabled} if job is not None else None,
    }


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
        group = subs.add_parser("group", help="create, rename, delete a group, or change what it grants")
        group_subs = group.add_subparsers(dest="group_verb", required=True)
        for verb, text, args in (
            ("new", "create a group", ["name"]),
            ("rename", "rename a group", ["group", "name"]),
            ("rm", "delete a group (its members keep their accounts)", ["group"]),
            ("grant", "give the group a permission (app_label.codename)", ["group", "perm"]),
            ("revoke", "take a permission from the group", ["group", "perm"]),
            ("role", 'make the group directory-managed with this role ("" makes it local again)', ["group", "role"]),
        ):
            sub = group_subs.add_parser(verb, help=text)
            for arg in args:
                sub.add_argument(arg)
            sub.add_argument("--user", dest="actor", help="the person this change is attributed to")
            sub.add_argument("--reason", default="", help="kept in the record")
            if verb == "role":
                sub.add_argument("--staff", action="store_true", help="the directory makes members staff")
        permission = subs.add_parser("perm", help="a direct permission on an account")
        perm_subs = permission.add_subparsers(dest="perm_verb", required=True)
        perm_rm = perm_subs.add_parser("rm", help="take a direct permission off an account (grant through a group)")
        perm_rm.add_argument("who")
        perm_rm.add_argument("perm", help="app_label.codename")
        perm_rm.add_argument("--user", dest="actor", help="the person this change is attributed to")
        perm_rm.add_argument("--reason", default="", help="kept in the record")
        findings = subs.add_parser("findings", help="the least-privilege findings")
        findings.add_argument("--rows", action="store_true")
        findings.add_argument("--json", action="store_true")
        manifest = subs.add_parser(
            "directory-manifest", help="the app roles and groups a directory administrator creates"
        )
        manifest.add_argument("--provider", default="generic", help="entra or generic (default)")
        manifest.add_argument("--json", action="store_true")
        review = subs.add_parser("review", help="periodic access reviews (attestations)")
        review_subs = review.add_subparsers(dest="review_verb", required=True)
        open_ = review_subs.add_parser("open", help="open a review and freeze its roster")
        open_.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
        open_.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
        open_.add_argument("--scope", default="privileged", help="privileged (default) or all")
        open_.add_argument("--user", dest="actor", help="the attester opening it (recorded)")
        open_.add_argument("--note", default="")
        listing = review_subs.add_parser("list", help="every review")
        listing.add_argument("--json", action="store_true")
        show = review_subs.add_parser("show", help="one review, roster and decisions")
        show.add_argument("id", type=int)
        show.add_argument("--json", action="store_true")
        show.add_argument("--csv", action="store_true")
        evidence = subs.add_parser("evidence", help="the audit evidence pack for a period")
        evidence.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
        evidence.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
        evidence.add_argument("--scope", default="privileged", help="privileged (default) or all")
        evidence.add_argument("--out", help="write the ZIP bundle here (default: a summary on stdout)")
        evidence.add_argument("--json", action="store_true", help="print the whole pack as JSON")
        evidence.add_argument(
            "--store", action="store_true", help="keep it on the server as a dated pack with its SHA-256"
        )
        evidence.add_argument("--user", dest="actor", help="who stored it (recorded with --store)")
        packs = subs.add_parser("packs", help="the stored evidence packs, newest first")
        packs.add_argument("--scope", default="", help="privileged or all (default: both)")
        packs.add_argument("--json", action="store_true")
        cadence = subs.add_parser(
            "cadence", help="run the review cadence once: open a closed quarter's review, remind, escalate"
        )
        cadence.add_argument("--status", action="store_true", help="only say where the control stands")
        cadence.add_argument("--json", action="store_true")

    def handle(self, *args: Any, **opts: Any) -> None:
        verb = opts["verb"].replace("-", "_")
        handler = getattr(self, f"_{verb}")
        handler(opts)

    def _dump(self, data: Any) -> None:
        # One write: json.dump onto the OutputWrapper wrote each chunk on its
        # own line, splitting the JSON with newlines (T2-6).
        self.stdout.write(json.dumps(data, indent=2, default=str))

    def _user(self, ref: str) -> Any:
        try:
            return services.resolve_user(ref)
        except LookupError as exc:
            raise CommandError(str(exc)) from exc

    def _resolve_group(self, ref: str) -> Any:
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
        group = self._resolve_group(opts["group"])
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

    def _group(self, opts: dict[str, Any]) -> None:
        """The group page's writes, through the same services."""
        verb = opts["group_verb"]
        actor = self._user(opts["actor"]) if opts.get("actor") else None
        source = "cli" if not opts.get("reason") else f"cli: {opts['reason']}"[:200]
        try:
            if verb == "new":
                group = services.create_group(opts["name"], actor=actor, source=source)
                self.stdout.write(self.style.SUCCESS(f"Group {group.name} created (#{group.pk})"))
                return
            group = self._resolve_group(opts["group"])
            if verb == "rename":
                before = group.name
                if services.rename_group(group, opts["name"], actor=actor, source=source):
                    self.stdout.write(self.style.SUCCESS(f"{before} renamed to {group.name}"))
                else:
                    self.stdout.write(f"{group.name} already has that name; nothing changed")
            elif verb == "role":
                role = opts["role"].strip()
                n = group.user_set.count()
                if not services.set_directory_role(group, role, staff=opts["staff"], actor=actor, source=source):
                    self.stdout.write(
                        f"{group.name} already {'has role ' + role if role else 'is local'}; nothing changed"
                    )
                elif role:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"{group.name} is directory-managed with role {role}; its {n} member(s) keep it until "
                            "their next directory sign-in"
                        )
                    )
                else:
                    self.stdout.write(self.style.SUCCESS(f"{group.name} is local again; its {n} member(s) stay"))
            elif verb == "rm":
                name, members = group.name, group.user_set.count()
                services.delete_group(group, actor=actor, source=source)
                self.stdout.write(self.style.SUCCESS(f"Group {name} deleted; {members} member(s) keep their accounts"))
            else:
                held = verb == "grant"
                changed = services.set_group_permission(group, opts["perm"], held, actor=actor, source=source)
                if changed:
                    verb_text = "added to" if held else "removed from"
                    self.stdout.write(self.style.SUCCESS(f"{opts['perm']} {verb_text} {group.name}"))
                else:
                    self.stdout.write(
                        f"{group.name} already {'had' if held else 'lacked'} {opts['perm']}; nothing changed"
                    )
        except PermissionError as exc:
            raise CommandError(str(exc)) from exc

    def _perm(self, opts: dict[str, Any]) -> None:
        user = self._user(opts["who"])
        actor = self._user(opts["actor"]) if opts.get("actor") else None
        source = "cli" if not opts.get("reason") else f"cli: {opts['reason']}"[:200]
        try:
            changed = services.remove_direct_permission(user, opts["perm"], actor=actor, source=source)
        except PermissionError as exc:
            raise CommandError(str(exc)) from exc
        if changed:
            self.stdout.write(self.style.SUCCESS(f"direct {opts['perm']} removed from {user.get_username()}"))
        else:
            self.stdout.write(f"{user.get_username()} didn't hold {opts['perm']} directly; nothing changed")

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
            role = f"  directory: {row['directory_role']}" if row.get("directory_role") else ""
            self.stdout.write(f"{row['name']:<28} {counts}  {declared}{role}{note}")

    def _findings(self, opts: dict[str, Any]) -> None:
        args = [flag for flag in ("--rows", "--json") if opts.get(flag.strip("-"))]
        call_command("access_report", *args, stdout=self.stdout, stderr=self.stderr)

    def _review(self, opts: dict[str, Any]) -> None:
        import csv
        from datetime import date

        from apps.access import reviews
        from apps.access.models import AccessReview

        verb = opts["review_verb"]
        if verb == "open":
            try:
                start, end = date.fromisoformat(opts["start"]), date.fromisoformat(opts["end"])
            except ValueError as exc:
                raise CommandError("--from and --to take YYYY-MM-DD.") from exc
            actor = self._user(opts["actor"]) if opts.get("actor") else None
            try:
                opened = reviews.open_review(
                    period_start=start,
                    period_end=end,
                    scope=opts["scope"],
                    actor=actor,
                    note=opts["note"],
                    source=AccessReview.Via.CLI,
                )
            except PermissionError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                self.style.SUCCESS(
                    f"Review #{opened.pk} opened ({opened.scope}, {opened.period_label}) with "
                    f"{opened.items.count()} account(s). Decide and sign it on the Reviews page."
                )
            )
            return
        if verb == "list":
            rows = [reviews.review_payload(r, items=False) for r in AccessReview.objects.all()]
            if opts["json"]:
                self._dump(rows)
                return
            for r in rows:
                s = r["summary"]
                signed = f"signed {r['signed_at'][:10]} by {r['signed_by']}" if r["signed_by"] else "open"
                self.stdout.write(
                    f"#{r['id']:<4} {r['period_start']} – {r['period_end']}  {r['scope']:<10} {signed:<36} "
                    f"{s.get('items', 0)} account(s): {s.get('confirmed', 0)} ok, {s.get('remove', 0)} remove, "
                    f"{s.get('flagged', 0)} flagged"
                )
            if not rows:
                self.stdout.write("No reviews.")
            return
        found = AccessReview.objects.filter(pk=opts["id"]).first()
        if found is None:
            raise CommandError(f"No review #{opts['id']}.")
        review: AccessReview = found
        if opts["csv"]:
            writer = csv.DictWriter(self.stdout, fieldnames=list(reviews.REVIEW_CSV_COLUMNS))
            writer.writeheader()
            for row in reviews.review_csv_rows(review):
                writer.writerow(row)
            return
        data = reviews.review_payload(review)
        if opts["json"]:
            self._dump(data)
            return
        s = data["summary"]
        self.stdout.write(f"{review}  {review.status}")
        self.stdout.write(f"opened {data['opened_at'][:16]} by {data['opened_by'] or 'cli'}")
        if review.is_signed:
            self.stdout.write(f"signed {data['signed_at'][:16]} by {data['signed_by']} as {data['signed_name']!r}")
        self.stdout.write(
            f"{s.get('items', 0)} account(s): {s.get('confirmed', 0)} confirmed, {s.get('remove', 0)} remove, "
            f"{s.get('flagged', 0)} flagged{', ' + str(s.get('pending', 0)) + ' pending' if 'pending' in s else ''}"
        )
        for item in data["items"]:
            f = item["facts"]
            flags = "superuser" if f.get("superuser") else ("staff" if f.get("staff") else "")
            new = "new " if item.get("new") else "    "
            self.stdout.write(
                f"  {new}{item['username']:<28} {item['decision']:<10} {flags:<10} {', '.join(f.get('groups', []))}"
                + (f"  — {item['note']}" if item["note"] else "")
            )

    def _evidence(self, opts: dict[str, Any]) -> None:
        from datetime import date
        from pathlib import Path

        from apps.access import evidence

        try:
            start, end = date.fromisoformat(opts["start"]), date.fromisoformat(opts["end"])
            pack = evidence.build(start, end, scope=opts["scope"], generated_by="cli")
        except ValueError as exc:
            raise CommandError(
                str(exc) if "scope" in str(exc) or "ends" in str(exc) else "--from and --to take YYYY-MM-DD."
            ) from exc
        if opts.get("store"):
            from apps.access import cadence, reviews
            from apps.access.models import EvidenceBundle

            actor = self._user(opts["actor"]) if opts.get("actor") else None
            if actor is not None:
                # The named person must pass the page's rule for storing a
                # pack (an attester or a superuser), as --user does for
                # grant/revoke and review open (T4-3).
                refusal = reviews.open_refusal(actor)
                if refusal:
                    raise CommandError(refusal)
            bundle = cadence.store_bundle(
                start, end, opts["scope"], reason=EvidenceBundle.Reason.MANUAL, actor=actor, label="cli"
            )
            if opts["json"]:
                self._dump(cadence.bundle_payload(bundle))
                return
            self.stdout.write(
                self.style.SUCCESS(
                    f"Stored pack #{bundle.pk} for {bundle.period_label} ({bundle.scope}): {bundle.size:,} bytes, "
                    f"sha256 {bundle.sha256}"
                )
            )
            return
        if opts.get("out"):
            path = Path(opts["out"])
            path.write_bytes(evidence.bundle_zip(pack))
            self.stdout.write(
                self.style.SUCCESS(f"Wrote {path} ({', '.join(f'{s.key} {s.count}' for s in pack.sheets)})")
            )
            return
        if opts["json"]:
            self._dump(pack.as_dict())
            return
        self.stdout.write(f"Access evidence · {pack.system} · {pack.period_label} · {pack.scope}")
        for s in pack.sheets:
            headline = ", ".join(f"{k} {v}" for k, v in s.summary.items() if not isinstance(v, dict))
            self.stdout.write(f"  {s.title:<20} {s.count:>6}  {headline}")
        self.stdout.write("--out FILE.zip writes the bundle; --store keeps it on the server; --json prints it all.")

    def _packs(self, opts: dict[str, Any]) -> None:
        from apps.access import cadence
        from apps.access.models import EvidenceBundle

        qs = EvidenceBundle.objects.all()
        if opts["scope"]:
            qs = qs.filter(scope=opts["scope"])
        rows = [cadence.bundle_payload(b) for b in qs]
        if opts["json"]:
            self._dump(rows)
            return
        for r in rows:
            who = r["built_by"] or "schedule"
            self.stdout.write(
                f"#{r['id']:<4} {r['period_start']} – {r['period_end']}  {r['scope']:<10} {r['reason']:<14} "
                f"built {r['built_at'][:16]} by {who:<12} {r['size']:>9,} B  sha256 {r['sha256'][:16]}…"
            )
        if not rows:
            self.stdout.write("No stored packs. The schedule stores one when a quarter closes and when a review is")
            self.stdout.write("signed; `access evidence --from --to --store` stores one now.")

    def _cadence(self, opts: dict[str, Any]) -> None:
        from apps.access import cadence

        if not opts["status"]:
            result = cadence.tick()
            if opts["json"]:
                self._dump({**result, "status": _status_payload(cadence.status())})
                return
            if result.get("skipped"):
                self.stdout.write(result["skipped"])
            else:
                self.stdout.write(
                    f"opened review #{result['opened']}, stored pack #{result['bundle']}"
                    if result["opened"]
                    else "nothing to open"
                )
                self.stdout.write(
                    f"reminded {len(result['reminded'])}, escalated {len(result['escalated'])}, "
                    f"pruned {result['pruned']} pack(s)"
                )
        s = cadence.status()
        if opts["json"]:
            self._dump(_status_payload(s))
            return
        job = s["job"]
        if not s["enabled"]:
            self.stdout.write(
                "Cadence: off — attestation is on demand (`access review open`, the Reviews page). "
                "SMALLSTACK_ACCESS_REVIEW_CADENCE=quarterly turns the schedule on."
            )
        else:
            schedule = (
                f"scheduled ({job.name}, {'enabled' if job.enabled else 'paused'})"
                if job is not None
                else "no scheduler row: run `access cadence` from cron"
            )
            self.stdout.write(f"Cadence: {s['cadence']} · scope {s['scope']} · {schedule}")
        due = f", due {s['due']} ({s['days_until_due']} day(s))" if s["enabled"] else ""
        if s["signed"] is not None:
            signed = s["signed"]
            self.stdout.write(f"{s['period'].label}: signed by {signed.signed_by_label} (review #{signed.pk})")
        elif s["open"] is not None:
            self.stdout.write(f"{s['period'].label}: review #{s['open'].pk} open{due}")
        else:
            self.stdout.write(f"{s['period'].label}: not reviewed{due}")
        self.stdout.write(f"Current quarter closes {s['next_close']}.")

    def _directory_manifest(self, opts: dict[str, Any]) -> None:
        from apps.access import directory

        try:
            data = directory.manifest(opts["provider"])
        except LookupError as exc:
            raise CommandError(str(exc)) from exc
        if opts["json"]:
            self._dump(data)
            return
        roles = directory.manifest_roles()
        if not roles:
            self.stdout.write("No group declares a directory_role. Add one with register_group(..., directory_role=…).")
            return
        self.stdout.write(f"{'Role':<28} {'Group':<24} {'Directory group':<40} staff")
        for r in roles:
            self.stdout.write(f"{r.role:<28} {r.group:<24} {r.directory_group:<40} {'yes' if r.staff else ''}")
        self.stdout.write("")
        formats = ", ".join(directory.manifest_providers())
        self.stdout.write(f"--json gives the {opts['provider']} shape; formats: {formats}.")
