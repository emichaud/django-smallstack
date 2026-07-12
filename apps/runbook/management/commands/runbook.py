"""A unix-style CLI over the runbook document service.

One ``manage.py runbook`` command with git-style subcommands. Every verb is a
thin skin over ``apps.runbook.service`` — the same write path the web UI,
REST API, and MCP tools use — so versioning, provenance, locking, and domain
events behave identically here.

    manage.py runbook ls                       # list runbooks
    manage.py runbook ls ops                    # list pages in a runbook
    manage.py runbook toc ops                   # table of contents (sections → pages)
    manage.py runbook find "backup window"      # ranked full-text search across runbooks
    manage.py runbook cat ops/backup-report     # print a page's markdown to stdout
    manage.py runbook cat ops/backup-report@3   # print an earlier version
    echo "# Notes" | manage.py runbook write ops/notes --title Notes   # body from stdin
    manage.py runbook cp ops/notes ops/notes-copy   # duplicate a page (own images)
    manage.py runbook rm ops/notes              # archive (soft-delete)
    manage.py runbook restore ops/notes         # un-archive
    manage.py runbook mv ops/notes archive/     # re-place a page
    manage.py runbook revert ops/notes --to 3   # roll back to version 3
    manage.py runbook log ops/notes             # version history
    manage.py runbook stat ops/notes            # page metadata
    manage.py runbook mkdir ops --name Operations   # create an empty runbook
    manage.py runbook sections ops              # list/create sections
    manage.py runbook publish ops               # make a runbook public (unpublish → private)

Pages are addressed by the unix-path alias ``<runbook>/<key>`` or, canonically,
by ``--uid``. An earlier version is addressed with ``<runbook>/<key>@<n>``.
Every verb accepts ``--json`` for machine consumption; failures exit non-zero.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Optional

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from apps.runbook import service
from apps.runbook.models import Document, Runbook, Section
from apps.smallstack.cli_format import asdict as _asdict
from apps.smallstack.cli_format import json_dump as _json_dump
from apps.smallstack.cli_format import table as _table


class Command(BaseCommand):
    help = (
        "Unix-style CLI over runbook documents "
        "(ls, toc, find, cat, write, cp, rm, restore, mv, revert, log, stat, mkdir, sections, publish, unpublish)."
    )

    # -- Top-level dispatch ---------------------------------------------------

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "subcommand", nargs="?",
            help="ls | toc | find | cat | write | cp | rm | restore | mv | revert | "
                 "log | stat | mkdir | sections | publish | unpublish",
        )
        # Not named "args": Django's run_from_argv pops an "args" dest and passes
        # it as positional *args to handle(), which would hide it from options.
        parser.add_argument("subargs", nargs=argparse.REMAINDER, help="Arguments for the subcommand.")

    def handle(self, *args: Any, **options: Any) -> None:
        sub = options.get("subcommand")
        dispatch = {
            "ls": self._cmd_ls,
            "toc": self._cmd_toc,
            "cat": self._cmd_cat,
            "find": self._cmd_find,
            "write": self._cmd_write,
            "cp": self._cmd_cp,
            "rm": self._cmd_rm,
            "restore": self._cmd_restore,
            "mv": self._cmd_mv,
            "revert": self._cmd_revert,
            "log": self._cmd_log,
            "stat": self._cmd_stat,
            "mkdir": self._cmd_mkdir,
            "sections": self._cmd_sections,
            "publish": self._cmd_publish,
            "unpublish": self._cmd_unpublish,
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

    def _split_version(self, ref: Optional[str]) -> tuple[Optional[str], Optional[int]]:
        """``runbook/key@3`` → ``("runbook/key", 3)``; no ``@`` → ``(ref, None)``."""
        if not ref or "@" not in ref:
            return ref, None
        base, _, tail = ref.rpartition("@")
        if not tail.isdigit():
            raise CommandError(f"invalid version in {ref!r}: expected 'runbook/key@<number>'")
        return base, int(tail)

    def _read_version_file(self, version: Any) -> str:
        version.file.open("rb")
        try:
            return version.file.read().decode("utf-8", errors="replace")
        finally:
            version.file.close()

    def _doc_label(self, doc: Document) -> str:
        return f"{doc.runbook.slug}/{doc.key}" if doc.runbook_id and doc.key else f"uid:{doc.uid}"

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
        # Annotate page/section counts in one query rather than two .count()s per row.
        # distinct=True keeps the two joins from inflating each other's counts.
        runbooks = Runbook.objects.annotate(
            n_pages=Count("documents", filter=Q(documents__is_archived=False), distinct=True),
            n_sections=Count("sections", distinct=True),
        )
        if as_json:
            payload = [
                {
                    "slug": rb.slug,
                    "name": rb.name,
                    "description": rb.description,
                    "sections": rb.n_sections,
                    "pages": rb.n_pages,
                    "is_template": rb.is_template,
                }
                for rb in runbooks
            ]
            self.stdout.write(_json_dump(payload))
            return
        if not runbooks:
            self.stdout.write("(no runbooks)")
            return
        rows = [[rb.slug, str(rb.n_pages), str(rb.n_sections), rb.name] for rb in runbooks]
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
        # One query maps every page to its section slug (NULL → sectionless),
        # instead of a Document.objects.get() per page.
        section_by_id = dict(
            Document.objects.filter(pk__in=[d.id for d in docs]).values_list("pk", "section__slug")
        )
        by_section: dict[Optional[str], list[service.DocumentSummary]] = {}
        for d in docs:
            by_section.setdefault(section_by_id.get(d.id), []).append(d)

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
        parser.add_argument("ref", nargs="?", help="runbook/key[@version]")
        parser.add_argument("--uid", help="canonical uid (overrides ref)")
        parser.add_argument("--version", type=int, help="read this version instead of the head")
        parser.add_argument("--json", action="store_true", help="emit metadata + body as JSON")
        opts = parser.parse_args(argv)

        ref, at_version = self._split_version(opts.ref)
        version = opts.version if opts.version is not None else at_version
        doc = self._resolve_doc(ref, opts.uid)

        if version is not None:
            old = doc.versions.filter(version=version).first()
            if old is None:
                raise CommandError(f"{self._doc_label(doc)} has no version {version}")
            body = self._read_version_file(old)
            if opts.json:
                self.stdout.write(_json_dump({
                    "uid": str(doc.uid), "runbook": doc.runbook.slug if doc.runbook_id else None,
                    "key": doc.key, "version": version, "content_markdown": body,
                }))
                return
            self.stdout.write(body)
            return

        result = service.get_document(uid=str(doc.uid), with_body=True)
        if opts.json:
            self.stdout.write(_json_dump(_asdict(result)))
            return
        # Print the raw body verbatim so it pipes cleanly into another command.
        self.stdout.write(result.content_markdown or "")

    # -- find -----------------------------------------------------------------

    def _ranked_find(self, query: str, limit: int) -> Optional[list[Any]]:
        """Ranked full-text hits via the shared search engine, or None when
        ``apps.search`` isn't installed / Document isn't registered."""
        try:
            from apps.search import registry
            from apps.search.backends import get_backend
        except ImportError:
            return None
        view = registry.get_view(Document)
        if view is None:
            return None
        return get_backend().query(view, query, limit=limit)

    def _cmd_find(self, argv: list[str]) -> None:
        parser = self._parser("find")
        parser.add_argument("query", help="text to search for (ranked full-text across runbooks)")
        parser.add_argument("--limit", type=int, default=20, help="max results (default 20)")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        hits = self._ranked_find(opts.query, opts.limit)
        if hits is not None:
            docs = {
                d.pk: d
                for d in Document.objects.filter(pk__in=[h.object_id for h in hits]).select_related("runbook")
            }
            results = []
            for h in hits:
                d = docs.get(h.object_id)
                if d is None:
                    continue
                results.append({"ref": self._doc_label(d), "title": h.display or d.title,
                                "rank": round(h.rank, 4), "snippet": h.snippet, "uid": str(d.uid)})
            ranked = True
        else:
            # apps.search absent — fall back to a substring scan across all runbooks.
            summaries = service.list_documents(query=opts.query)[: opts.limit]
            results = [{"ref": f"{s.runbook}/{s.key}" if s.runbook else f"uid:{s.uid[:8]}",
                        "title": s.title, "rank": None, "snippet": "", "uid": s.uid}
                       for s in summaries]
            ranked = False

        if opts.json:
            self.stdout.write(_json_dump(results))
            return
        if not results:
            self.stdout.write("(no matches)")
            return
        if ranked:
            rows = [[r["ref"], f'{r["rank"]:.3f}', r["title"]] for r in results]
            self.stdout.write(_table(rows, ["REF", "RANK", "TITLE"]))
        else:
            rows = [[r["ref"], r["title"]] for r in results]
            self.stdout.write(_table(rows, ["REF", "TITLE"]))

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

    # -- cp -------------------------------------------------------------------

    def _cmd_cp(self, argv: list[str]) -> None:
        parser = self._parser("cp")
        parser.add_argument("src", nargs="?", help="runbook/key (source page)")
        parser.add_argument("dest", help="runbook/key (destination page)")
        parser.add_argument("--section", help="target section slug")
        parser.add_argument("--title", help="title for the copy (defaults to source title)")
        parser.add_argument("-f", "--force", action="store_true", help="overwrite dest if it already exists")
        parser.add_argument("--uid", help="address the source page by uid")
        parser.add_argument("--user", help="act as this username")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        actor = self._resolve_actor(opts.user)
        src = self._resolve_doc(opts.src, opts.uid)
        dest_runbook, dest_key = self._split_ref(opts.dest)
        if not dest_key:
            raise CommandError(f"{opts.dest!r} addresses a runbook, not a page; use 'runbook/key'")

        # mkdir -p the destination runbook (and named section), mirroring `write`.
        rb = Runbook.objects.filter(slug=dest_runbook).first()
        if rb is None:
            rb = Runbook.objects.create(name=dest_runbook, slug=dest_runbook)
        if opts.section:
            Section.objects.get_or_create(runbook=rb, slug=opts.section, defaults={"name": opts.section})

        result = service.copy_document(
            src, to_runbook=rb.slug, to_key=dest_key, title=opts.title,
            section=opts.section, on_exists=("overwrite" if opts.force else "fail"), via="cli", actor=actor,
        )
        if opts.json:
            self.stdout.write(_json_dump(_asdict(result)))
            return
        self.stdout.write(self.style.SUCCESS(
            f"copied {self._doc_label(src)} → {result.runbook}/{result.key} (v{result.version})"))

    # -- rm -------------------------------------------------------------------

    def _cmd_rm(self, argv: list[str]) -> None:
        parser = self._parser("rm")
        parser.add_argument("ref", nargs="?", help="runbook/key")
        parser.add_argument("--uid", help="canonical uid (overrides ref)")
        parser.add_argument("--force", action="store_true", help="hard-delete instead of archive")
        parser.add_argument("--user", help="act as this username")
        parser.add_argument("--bypass-lock", action="store_true")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        actor = self._resolve_actor(opts.user)
        doc = self._resolve_doc(opts.ref, opts.uid)
        label = self._doc_label(doc)
        service.delete_document(document=doc, force=opts.force, actor=actor, bypass_lock=opts.bypass_lock)
        verb = "deleted" if opts.force else "archived"
        if opts.json:
            self.stdout.write(_json_dump({"ref": label, "action": verb}))
            return
        self.stdout.write(self.style.SUCCESS(f"{verb} {label}"))

    # -- restore --------------------------------------------------------------

    def _cmd_restore(self, argv: list[str]) -> None:
        parser = self._parser("restore")
        parser.add_argument("ref", nargs="?", help="runbook/key")
        parser.add_argument("--uid", help="canonical uid (overrides ref)")
        parser.add_argument("--user", help="act as this username")
        parser.add_argument("--bypass-lock", action="store_true")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        actor = self._resolve_actor(opts.user)
        doc = self._resolve_doc(opts.ref, opts.uid)
        result = service.unarchive_document(document=doc, actor=actor, bypass_lock=opts.bypass_lock)
        if opts.json:
            self.stdout.write(_json_dump(_asdict(result)))
            return
        self.stdout.write(self.style.SUCCESS(f"restored {self._doc_label(doc)}"))

    # -- mv -------------------------------------------------------------------

    def _cmd_mv(self, argv: list[str]) -> None:
        parser = self._parser("mv")
        parser.add_argument("src", help="runbook/key")
        parser.add_argument("dest", nargs="?", help="dest-runbook[/section] ('-' or omit = detach)")
        parser.add_argument("--section", help="target section slug (overrides one in dest)")
        parser.add_argument("--uid", help="address the source page by uid")
        parser.add_argument("--user", help="act as this username")
        parser.add_argument("--bypass-lock", action="store_true")
        parser.add_argument("--json", action="store_true")
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
        if opts.json:
            self.stdout.write(_json_dump(_asdict(result)))
            return
        dest_label = f"{result.runbook}/{result.key}" if result.runbook else f"(detached) uid:{result.uid}"
        self.stdout.write(self.style.SUCCESS(f"moved → {dest_label}"))

    # -- revert ---------------------------------------------------------------

    def _cmd_revert(self, argv: list[str]) -> None:
        parser = self._parser("revert")
        parser.add_argument("ref", nargs="?", help="runbook/key")
        parser.add_argument("--uid", help="canonical uid (overrides ref)")
        parser.add_argument("--to", type=int, required=True, metavar="N", help="version number to roll back to")
        parser.add_argument("--user", help="act as this username")
        parser.add_argument("--bypass-lock", action="store_true")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        actor = self._resolve_actor(opts.user)
        doc = self._resolve_doc(opts.ref, opts.uid)
        doc = service.restore_version(doc, version=opts.to, actor=actor, via="cli", bypass_lock=opts.bypass_lock)
        result = service.get_document(uid=str(doc.uid))
        if opts.json:
            self.stdout.write(_json_dump(_asdict(result)))
            return
        self.stdout.write(self.style.SUCCESS(
            f"reverted {self._doc_label(doc)} to v{opts.to} → new head v{result.version}"))

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

        # One query with an annotated page count, not a .count() per section.
        sections = list(rb.sections.annotate(n_pages=Count("documents", filter=Q(documents__is_archived=False))))
        if opts.json:
            payload = [
                {"slug": s.slug, "name": s.name, "order": s.order, "pages": s.n_pages}
                for s in sections
            ]
            self.stdout.write(_json_dump(payload))
            return
        if not sections:
            self.stdout.write("(no sections)")
            return
        rows = [[s.slug, str(s.order), str(s.n_pages), s.name] for s in sections]
        self.stdout.write(_table(rows, ["SECTION", "ORDER", "PAGES", "NAME"]))

    # -- mkdir ----------------------------------------------------------------

    def _cmd_mkdir(self, argv: list[str]) -> None:
        parser = self._parser("mkdir")
        parser.add_argument("ref", help="runbook  or  runbook/section")
        parser.add_argument("--name", help="runbook display name (defaults to the slug)")
        parser.add_argument("--description", default="", help="runbook description")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        runbook_slug, section_slug = self._split_ref(opts.ref)
        rb, rb_created = Runbook.objects.get_or_create(
            slug=runbook_slug, defaults={"name": opts.name or runbook_slug, "description": opts.description},
        )
        made = [f"runbook {rb.slug}"] if rb_created else []
        if section_slug:
            sec, sec_created = Section.objects.get_or_create(
                runbook=rb, slug=section_slug, defaults={"name": section_slug},
            )
            if sec_created:
                made.append(f"section {rb.slug}/{sec.slug}")

        if opts.json:
            self.stdout.write(_json_dump({"runbook": rb.slug, "section": section_slug, "created": made}))
            return
        self.stdout.write(self.style.SUCCESS("created " + ", ".join(made)) if made else f"exists: {opts.ref}")

    # -- publish / unpublish --------------------------------------------------

    def _cmd_publish(self, argv: list[str]) -> None:
        self._set_visibility(argv, verb="publish", public=True)

    def _cmd_unpublish(self, argv: list[str]) -> None:
        self._set_visibility(argv, verb="unpublish", public=False)

    def _set_visibility(self, argv: list[str], *, verb: str, public: bool) -> None:
        parser = self._parser(verb)
        parser.add_argument("runbook", help="runbook slug")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        rb = service._resolve_runbook(opts.runbook)
        if rb.is_public != public:
            rb.is_public = public
            rb.save(update_fields=["is_public"])
        if opts.json:
            self.stdout.write(_json_dump({"runbook": rb.slug, "is_public": rb.is_public}))
            return
        self.stdout.write(self.style.SUCCESS(f"{rb.slug} is now {'public' if public else 'private'}"))
