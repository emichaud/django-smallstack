"""A unix-style CLI over the runbook document service.

One ``manage.py runbook`` command with git-style subcommands. Every verb is a
thin skin over ``smallstack_runbook.service`` — the same write path the web UI,
REST API, and MCP tools use — so versioning, provenance, locking, and domain
events behave identically here.

    manage.py runbook ls                       # list runbooks
    manage.py runbook ls ops                    # list pages in a runbook
    manage.py runbook toc ops                   # table of contents (sections → pages)
    manage.py runbook cat ops/backup-report     # print a page's markdown to stdout
    echo "# Notes" | manage.py runbook write ops/notes --title Notes   # body from stdin
    manage.py runbook rm ops/notes              # archive (soft-delete)
    manage.py runbook mv ops/notes archive/     # re-place a page
    manage.py runbook log ops/notes             # version history
    manage.py runbook stat ops/notes            # page metadata
    manage.py runbook sections ops              # list/create sections

Pages are addressed by the unix-path alias ``<runbook>/<key>`` or, canonically,
by ``--uid``. Read/list verbs accept ``--json`` for machine consumption.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from typing import Any, Optional

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.runbook import service
from apps.runbook.models import Document, Runbook, Section


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


def _asdict(obj: Any) -> dict[str, Any]:
    return dataclasses.asdict(obj)


def _table(rows: list[list[str]], headers: list[str]) -> str:
    """Render a simple left-aligned monospace table (headers + rows)."""
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    widths = [max(len(str(cell)) for cell in col) for col in cols]
    line = lambda cells: "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))  # noqa: E731
    out = [line(headers)]
    if rows:
        for row in rows:
            out.append(line(row))
    return "\n".join(out)


class Command(BaseCommand):
    help = "Unix-style CLI over runbook documents (ls, cat, write, rm, mv, log, stat, toc, sections)."

    # -- Top-level dispatch ---------------------------------------------------

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("subcommand", nargs="?", help="ls | toc | cat | write | rm | mv | log | stat | sections")
        # Not named "args": Django's run_from_argv pops an "args" dest and passes
        # it as positional *args to handle(), which would hide it from options.
        parser.add_argument("subargs", nargs=argparse.REMAINDER, help="Arguments for the subcommand.")

    def handle(self, *args: Any, **options: Any) -> None:
        sub = options.get("subcommand")
        dispatch = {
            "ls": self._cmd_ls,
            "toc": self._cmd_toc,
            "cat": self._cmd_cat,
            "write": self._cmd_write,
            "rm": self._cmd_rm,
            "mv": self._cmd_mv,
            "log": self._cmd_log,
            "stat": self._cmd_stat,
            "sections": self._cmd_sections,
        }
        if sub is None:
            self.stdout.write(self.help)
            self.stdout.write("\nSubcommands: " + ", ".join(dispatch))
            return
        handler = dispatch.get(sub)
        if handler is None:
            raise CommandError(f"unknown subcommand {sub!r}; try one of: {', '.join(dispatch)}")
        try:
            handler(options.get("subargs") or [])
        except service.DocumentServiceError as exc:
            # Surface every service error as a non-zero exit so pipelines fail loudly.
            raise CommandError(str(exc)) from exc

    # -- Shared helpers -------------------------------------------------------

    def _parser(self, verb: str) -> argparse.ArgumentParser:
        return argparse.ArgumentParser(prog=f"manage.py runbook {verb}")

    def _resolve_actor(self, username: Optional[str]):
        if not username:
            return None
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"no user with username {username!r}")
        return user

    def _split_ref(self, path: str) -> tuple[str, Optional[str]]:
        """``runbook`` or ``runbook/tail`` → ``(runbook, tail|None)`` (first slash only)."""
        runbook, _, tail = path.partition("/")
        if not runbook:
            raise CommandError(f"invalid reference {path!r}: expected 'runbook' or 'runbook/key'")
        return runbook, (tail or None)

    def _resolve_doc(self, ref: Optional[str], uid: Optional[str]) -> Document:
        """Resolve a Document by ``--uid`` or a ``runbook/key`` path."""
        if uid:
            doc = Document.objects.filter(uid=uid).first()
        else:
            if not ref:
                raise CommandError("provide a 'runbook/key' reference or --uid")
            runbook, key = self._split_ref(ref)
            if not key:
                raise CommandError(f"{ref!r} addresses a runbook, not a page; use 'runbook/key'")
            doc = Document.objects.filter(runbook__slug=runbook, key=key).first()
        if doc is None:
            raise CommandError(f"document not found: {uid or ref}")
        return doc

    # -- ls -------------------------------------------------------------------

    def _cmd_ls(self, argv: list[str]) -> None:
        parser = self._parser("ls")
        parser.add_argument("ref", nargs="?", help="runbook or runbook/section (omit to list runbooks)")
        parser.add_argument("--all", action="store_true", help="include archived pages")
        parser.add_argument("--source", help="filter by provenance source")
        parser.add_argument("--doc-type", help="filter by doc_type")
        parser.add_argument("-q", "--query", help="search title + content")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        if not opts.ref:
            self._ls_runbooks(as_json=opts.json)
            return

        runbook, section = self._split_ref(opts.ref)
        service._resolve_runbook(runbook)  # raises RunbookNotFound with a clear message
        docs = service.list_documents(
            runbook=runbook,
            section=section,
            source=opts.source or None,
            doc_type=opts.doc_type or None,
            query=opts.query or None,
            include_archived=opts.all,
        )
        if opts.json:
            self.stdout.write(_json_dump([_asdict(d) for d in docs]))
            return
        if not docs:
            self.stdout.write("(no pages)")
            return
        rows = [
            [d.key or f"uid:{d.uid[:8]}", f"v{d.version}", d.title,
             d.source or "-", d.updated_at.strftime("%Y-%m-%d")]
            for d in docs
        ]
        self.stdout.write(_table(rows, ["KEY", "VER", "TITLE", "SOURCE", "UPDATED"]))

    def _ls_runbooks(self, *, as_json: bool) -> None:
        runbooks = Runbook.objects.all()
        if as_json:
            payload = [
                {
                    "slug": rb.slug,
                    "name": rb.name,
                    "description": rb.description,
                    "sections": rb.sections.count(),
                    "pages": rb.documents.filter(is_archived=False).count(),
                    "is_template": rb.is_template,
                }
                for rb in runbooks
            ]
            self.stdout.write(_json_dump(payload))
            return
        if not runbooks:
            self.stdout.write("(no runbooks)")
            return
        rows = [
            [rb.slug, str(rb.documents.filter(is_archived=False).count()),
             str(rb.sections.count()), rb.name]
            for rb in runbooks
        ]
        self.stdout.write(_table(rows, ["RUNBOOK", "PAGES", "SECTIONS", "NAME"]))

    # -- toc ------------------------------------------------------------------

    def _cmd_toc(self, argv: list[str]) -> None:
        parser = self._parser("toc")
        parser.add_argument("runbook", help="runbook slug")
        parser.add_argument("--all", action="store_true", help="include archived pages")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        rb = service._resolve_runbook(opts.runbook)
        docs = service.list_documents(runbook=rb.slug, include_archived=opts.all)
        by_section: dict[Optional[str], list[service.DocumentSummary]] = {}
        for d in docs:
            doc = Document.objects.get(pk=d.id)
            key = doc.section.slug if doc.section_id else None
            by_section.setdefault(key, []).append(d)

        sections = list(rb.sections.all())
        if opts.json:
            payload = {
                "runbook": rb.slug,
                "name": rb.name,
                "sections": [
                    {
                        "slug": sec.slug,
                        "name": sec.name,
                        "order": sec.order,
                        "documents": [_asdict(d) for d in by_section.get(sec.slug, [])],
                    }
                    for sec in sections
                ],
                "sectionless": [_asdict(d) for d in by_section.get(None, [])],
            }
            self.stdout.write(_json_dump(payload))
            return

        self.stdout.write(f"{rb.slug} — {rb.name}")
        blocks = [(sec.name, by_section.get(sec.slug, [])) for sec in sections]
        blocks.append(("(no section)", by_section.get(None, [])))
        for name, group in blocks:
            if not group:
                continue
            self.stdout.write(f"  {name}")
            for d in group:
                self.stdout.write(f"    • {d.key or 'uid:' + d.uid[:8]:24} {d.title}")

    # -- cat ------------------------------------------------------------------

    def _cmd_cat(self, argv: list[str]) -> None:
        parser = self._parser("cat")
        parser.add_argument("ref", nargs="?", help="runbook/key")
        parser.add_argument("--uid", help="canonical uid (overrides ref)")
        parser.add_argument("--json", action="store_true", help="emit metadata + body as JSON")
        opts = parser.parse_args(argv)

        if opts.uid:
            result = service.get_document(uid=opts.uid, with_body=True)
        else:
            if not opts.ref:
                raise CommandError("provide a 'runbook/key' reference or --uid")
            runbook, key = self._split_ref(opts.ref)
            if not key:
                raise CommandError(f"{opts.ref!r} addresses a runbook, not a page; use 'runbook/key'")
            result = service.get_document(runbook, key, with_body=True)

        if opts.json:
            self.stdout.write(_json_dump(_asdict(result)))
            return
        # Print the raw body verbatim so it pipes cleanly into another command.
        self.stdout.write(result.content_markdown or "")

    # -- write ----------------------------------------------------------------

    def _read_body(self, file_arg: Optional[str]) -> str:
        if file_arg in (None, "-"):
            return sys.stdin.read()
        with open(file_arg, encoding="utf-8") as handle:
            return handle.read()

    def _cmd_write(self, argv: list[str]) -> None:
        parser = self._parser("write")
        parser.add_argument("ref", help="runbook/key")
        parser.add_argument("-f", "--file", help="read body from FILE ('-' or omit = stdin)")
        parser.add_argument("--title", help="page title (defaults to key on create)")
        parser.add_argument("--section", help="section slug (auto-created if missing)")
        parser.add_argument(
            "--mode", choices=["new_version", "overwrite", "append", "fail"], default="new_version",
            help="what to do if the page already exists (default: new_version)",
        )
        parser.add_argument("--expected-version", type=int, help="optimistic lock against the current head")
        parser.add_argument("--source", default="", help="provenance label")
        parser.add_argument("--doc-type", default="", help="document type label")
        parser.add_argument("--locked", action="store_true", help="mark the page locked")
        parser.add_argument("--unlocked", action="store_true", help="clear the locked flag")
        parser.add_argument("--user", help="act as this username (for locked-doc authorization)")
        parser.add_argument("--bypass-lock", action="store_true", help="write through a locked page")
        parser.add_argument("--no-create-runbook", action="store_true",
                            help="error instead of auto-creating a missing runbook/section")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        runbook_slug, key = self._split_ref(opts.ref)
        if not key:
            raise CommandError(f"{opts.ref!r} addresses a runbook, not a page; use 'runbook/key'")
        if opts.locked and opts.unlocked:
            raise CommandError("pass at most one of --locked / --unlocked")

        actor = self._resolve_actor(opts.user)
        body = self._read_body(opts.file)

        # mkdir -p: ensure the runbook (and named section) exist before the write.
        rb = Runbook.objects.filter(slug=runbook_slug).first()
        if rb is None:
            if opts.no_create_runbook:
                raise CommandError(f"no runbook {runbook_slug!r} (drop --no-create-runbook to auto-create)")
            rb = Runbook.objects.create(name=runbook_slug, slug=runbook_slug)
        if opts.section:
            Section.objects.get_or_create(runbook=rb, slug=opts.section, defaults={"name": opts.section})

        locked = True if opts.locked else (False if opts.unlocked else None)
        result = service.put_document(
            rb.slug, key,
            body=body,
            title=opts.title,
            section=opts.section,
            on_exists=opts.mode,
            expected_version=opts.expected_version,
            source=opts.source,
            doc_type=opts.doc_type,
            locked=locked,
            via="cli",
            actor=actor,
            bypass_lock=opts.bypass_lock,
        )
        if opts.json:
            self.stdout.write(_json_dump(_asdict(result)))
            return
        self.stdout.write(self.style.SUCCESS(f"wrote {result.runbook}/{result.key} (v{result.version}) → {result.url}"))

    # -- rm -------------------------------------------------------------------

    def _cmd_rm(self, argv: list[str]) -> None:
        parser = self._parser("rm")
        parser.add_argument("ref", nargs="?", help="runbook/key")
        parser.add_argument("--uid", help="canonical uid (overrides ref)")
        parser.add_argument("--force", action="store_true", help="hard-delete instead of archive")
        parser.add_argument("--user", help="act as this username")
        parser.add_argument("--bypass-lock", action="store_true")
        opts = parser.parse_args(argv)

        actor = self._resolve_actor(opts.user)
        doc = self._resolve_doc(opts.ref, opts.uid)
        label = f"{doc.runbook.slug}/{doc.key}" if doc.runbook_id and doc.key else f"uid:{doc.uid}"
        service.delete_document(document=doc, force=opts.force, actor=actor, bypass_lock=opts.bypass_lock)
        verb = "deleted" if opts.force else "archived"
        self.stdout.write(self.style.SUCCESS(f"{verb} {label}"))

    # -- mv -------------------------------------------------------------------

    def _cmd_mv(self, argv: list[str]) -> None:
        parser = self._parser("mv")
        parser.add_argument("src", help="runbook/key")
        parser.add_argument("dest", nargs="?", help="dest-runbook[/section] ('-' or omit = detach)")
        parser.add_argument("--section", help="target section slug (overrides one in dest)")
        parser.add_argument("--uid", help="address the source page by uid")
        parser.add_argument("--user", help="act as this username")
        parser.add_argument("--bypass-lock", action="store_true")
        opts = parser.parse_args(argv)

        actor = self._resolve_actor(opts.user)
        doc = self._resolve_doc(opts.src, opts.uid)

        to_runbook: Optional[str]
        to_section: Optional[str] = opts.section
        if not opts.dest or opts.dest == "-":
            to_runbook = None
        else:
            to_runbook, dest_section = self._split_ref(opts.dest)
            if to_section is None:
                to_section = dest_section

        result = service.move_document(
            document=doc, to_runbook=to_runbook, to_section=to_section,
            actor=actor, bypass_lock=opts.bypass_lock,
        )
        dest_label = f"{result.runbook}/{result.key}" if result.runbook else f"(detached) uid:{result.uid}"
        self.stdout.write(self.style.SUCCESS(f"moved → {dest_label}"))

    # -- log ------------------------------------------------------------------

    def _cmd_log(self, argv: list[str]) -> None:
        parser = self._parser("log")
        parser.add_argument("ref", nargs="?", help="runbook/key")
        parser.add_argument("--uid", help="canonical uid (overrides ref)")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        doc = self._resolve_doc(opts.ref, opts.uid)
        versions = list(doc.versions.all())  # ordered -version
        if opts.json:
            payload = [
                {
                    "version": v.version,
                    "source": v.source,
                    "via": v.via,
                    "created_by": v.created_by.username if v.created_by_id else None,
                    "created_at": v.created_at,
                    "description": v.description,
                }
                for v in versions
            ]
            self.stdout.write(_json_dump(payload))
            return
        if not versions:
            self.stdout.write("(no versions)")
            return
        rows = [
            [f"v{v.version}", v.via or "-", v.source or "-",
             v.created_by.username if v.created_by_id else "-",
             v.created_at.strftime("%Y-%m-%d %H:%M")]
            for v in versions
        ]
        self.stdout.write(_table(rows, ["VER", "VIA", "SOURCE", "BY", "WHEN"]))

    # -- stat -----------------------------------------------------------------

    def _cmd_stat(self, argv: list[str]) -> None:
        parser = self._parser("stat")
        parser.add_argument("ref", nargs="?", help="runbook/key")
        parser.add_argument("--uid", help="canonical uid (overrides ref)")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        doc = self._resolve_doc(opts.ref, opts.uid)
        result = service.get_document(uid=str(doc.uid))
        if opts.json:
            self.stdout.write(_json_dump(_asdict(result)))
            return
        fields = _asdict(result)
        del fields["content_markdown"]
        width = max(len(k) for k in fields)
        for k, v in fields.items():
            self.stdout.write(f"{k.ljust(width)}  {v}")

    # -- sections -------------------------------------------------------------

    def _cmd_sections(self, argv: list[str]) -> None:
        parser = self._parser("sections")
        parser.add_argument("runbook", help="runbook slug")
        parser.add_argument("--create", metavar="SLUG", help="create a section with this slug")
        parser.add_argument("--name", help="section name (with --create; defaults to slug)")
        parser.add_argument("--order", type=int, default=0, help="section order (with --create)")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        rb = service._resolve_runbook(opts.runbook)
        if opts.create:
            section, created = Section.objects.get_or_create(
                runbook=rb, slug=opts.create,
                defaults={"name": opts.name or opts.create, "order": opts.order},
            )
            verb = "created" if created else "exists"
            self.stdout.write(self.style.SUCCESS(f"{verb}: section {rb.slug}/{section.slug} ({section.name})"))
            return

        sections = list(rb.sections.all())
        if opts.json:
            payload = [
                {"slug": s.slug, "name": s.name, "order": s.order,
                 "pages": s.documents.filter(is_archived=False).count()}
                for s in sections
            ]
            self.stdout.write(_json_dump(payload))
            return
        if not sections:
            self.stdout.write("(no sections)")
            return
        rows = [[s.slug, str(s.order), str(s.documents.filter(is_archived=False).count()), s.name] for s in sections]
        self.stdout.write(_table(rows, ["SECTION", "ORDER", "PAGES", "NAME"]))
