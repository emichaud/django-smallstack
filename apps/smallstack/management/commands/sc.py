"""``sc`` — SmallStack's framework CLI: a fifth thin skin over the same operations as the
web/REST/MCP surfaces.

Git-style subcommands over the ``CRUDView`` registry (``manage.py sc <verb> …`` / ``sc <verb> …``
via the console shim). Read verbs (this module's P1 scope):

    sc ls                       # every registered CRUDView model (a → api, m → mcp, s → search)
    sc ls user -q alice --json  # rows of one model (search / --filter / --order / --limit)
    sc get user 3               # one object's detail fields
    sc describe user            # introspection: fields, search/filter fields, actions, flags
    sc search "acme"            # cross-model keyword search (via apps.search)

Reuses the transport-agnostic helpers the MCP factory already proves out (``apply_search`` /
``apply_filters`` / ``apply_ordering`` / ``serialize`` + ``get_list_queryset`` tenancy), so results
match the REST/MCP surfaces. Every read verb accepts ``--json``; failures exit non-zero.
"""

from __future__ import annotations

import argparse
import difflib
from collections import Counter
from typing import Any, Optional
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.management.base import BaseCommand, CommandError
from django.http import HttpRequest, QueryDict

from apps.smallstack.api import apply_filters, apply_ordering, apply_search, serialize
from apps.smallstack.cli_format import json_dump, table
from apps.smallstack.crud import CRUDView


class Command(BaseCommand):
    help = "SmallStack framework CLI (ls, get, describe, search) over the CRUDView registry."

    # -- dispatch -------------------------------------------------------------

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("subcommand", nargs="?", help="ls | get | describe | search")
        # Not "args": Django pops an "args" dest and passes it positionally to handle().
        parser.add_argument("subargs", nargs=argparse.REMAINDER, help="Arguments for the subcommand.")

    def handle(self, *args: Any, **options: Any) -> None:
        sub = options.get("subcommand")
        dispatch = {
            "ls": self._cmd_ls,
            "get": self._cmd_get,
            "describe": self._cmd_describe,
            "search": self._cmd_search,
        }
        if sub is None:
            self.stdout.write(self.help)
            self.stdout.write("\nSubcommands: " + ", ".join(dispatch))
            self.stdout.write("Run 'sc ls' for the list of models.")
            return
        handler = dispatch.get(sub)
        if handler is None:
            raise CommandError(f"unknown subcommand {sub!r}; try one of: {', '.join(dispatch)}")
        handler(options.get("subargs") or [])

    # -- shared helpers -------------------------------------------------------

    def _parser(self, verb: str) -> argparse.ArgumentParser:
        return argparse.ArgumentParser(prog=f"manage.py sc {verb}")

    def _resolve_actor(self, username: Optional[str]):
        """A username → User (for tenancy/scoping), or None (trusted/unscoped)."""
        if not username:
            return None
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"no user with username {username!r}")
        return user

    def _fake_request(self, actor) -> HttpRequest:
        """Minimal HttpRequest so ``get_list_queryset(qs, request)`` sees the acting user."""
        req = HttpRequest()
        req.method = "GET"
        req.user = actor if actor is not None else AnonymousUser()
        req.GET = QueryDict("", mutable=False)
        req.META = {}
        return req

    # -- model addressing -----------------------------------------------------

    def _tokens_for(self, model, view) -> set[str]:
        """Every lowercased token that addresses this view."""
        meta = model._meta
        toks = {
            meta.model_name,
            f"{meta.app_label}.{meta.model_name}",
            str(meta.verbose_name),
            str(meta.verbose_name_plural),
        }
        for attr in ("mcp_singular", "mcp_plural"):
            val = getattr(view, attr, None)
            if val:
                toks.add(val)
        url_base = view._get_url_base()
        if url_base:
            toks.add(url_base)
            toks.add(url_base.rsplit("/", 1)[-1])
        return {t.lower().replace(" ", "") for t in toks if t}

    def _canonical_token(self, model) -> str:
        """The short display token (``model_name`` unless it collides → ``app.model``)."""
        counts = Counter(m._meta.model_name for m in CRUDView._registry)
        mn = model._meta.model_name
        return mn if counts[mn] == 1 else model._meta.label_lower

    def _resolve_view(self, token: str):
        needle = token.strip().lower().replace(" ", "")
        matches = [(m, v) for m, v in CRUDView._registry.items() if needle in self._tokens_for(m, v)]
        if len(matches) == 1:
            return matches[0][1]
        if not matches:
            all_tokens = sorted({t for m, v in CRUDView._registry.items() for t in self._tokens_for(m, v)})
            near = difflib.get_close_matches(needle, all_tokens, n=3)
            hint = f" did you mean: {', '.join(near)}?" if near else ""
            raise CommandError(f"unknown model {token!r}.{hint} (try 'sc ls')")
        labels = sorted(m._meta.label for m, _ in matches)
        raise CommandError(f"ambiguous model {token!r}; matches {', '.join(labels)}. Use the app.model form.")

    def _sorted_views(self) -> list[tuple[str, Any, type]]:
        """[(canonical_token, model, view)] sorted by token."""
        rows = [(self._canonical_token(m), m, v) for m, v in CRUDView._registry.items()]
        rows.sort(key=lambda r: r[0])
        return rows

    @staticmethod
    def _is_staff_gated(view) -> bool:
        from apps.smallstack.mixins import StaffRequiredMixin

        return any(m is StaffRequiredMixin or (isinstance(m, type) and issubclass(m, StaffRequiredMixin))
                   for m in getattr(view, "mixins", []) or [])

    @staticmethod
    def _is_explorer(view) -> bool:
        return "explorer" in (getattr(view, "__module__", "") or "").lower()

    @staticmethod
    def _cell(obj, field: str) -> str:
        val = getattr(obj, field, "")
        if hasattr(val, "pk"):
            val = str(val)
        text = "" if val is None else str(val)
        text = text.replace("\n", " ")
        return text if len(text) <= 48 else text[:47] + "…"

    # -- ls -------------------------------------------------------------------

    def _cmd_ls(self, argv: list[str]) -> None:
        parser = self._parser("ls")
        parser.add_argument("model", nargs="?", help="model token (omit to list registered models)")
        parser.add_argument("-q", "--query", help="text search over the model's search fields")
        parser.add_argument("--filter", action="append", default=[], metavar="k=v",
                            help="field filter (repeatable)")
        parser.add_argument("--order", help="comma-separated order fields ('-' prefix = desc)")
        parser.add_argument("--limit", type=int, help="max rows")
        parser.add_argument("--counts", action="store_true",
                            help="include a row count per model (one extra COUNT each)")
        parser.add_argument("--user", help="act as this username (tenancy scoping)")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        if not opts.model:
            self._ls_models(as_json=opts.json, counts=opts.counts)
            return

        view = self._resolve_view(opts.model)
        req = self._fake_request(self._resolve_actor(opts.user))
        qs = view.get_list_queryset(view._get_queryset(), req)

        if opts.query and view._resolve_search_fields():
            req.GET = QueryDict(urlencode({"q": opts.query}), mutable=False)
            qs = apply_search(qs, req, view)

        if opts.filter:
            pairs: dict[str, str] = {}
            for raw in opts.filter:
                if "=" not in raw:
                    raise CommandError(f"bad --filter {raw!r}; expected key=value")
                key, value = raw.split("=", 1)
                pairs[key] = value
            allowed = set(view._resolve_filter_fields())
            unknown = set(pairs) - allowed
            if unknown:
                raise CommandError(
                    f"unknown filter field(s): {', '.join(sorted(unknown))}. "
                    f"allowed: {', '.join(sorted(allowed)) or '(none)'}"
                )
            req.GET = QueryDict(urlencode(pairs), mutable=False)
            qs = apply_filters(qs, req, view)

        if opts.order:
            allowed_order = set(view._get_list_fields()) | {"pk", "id"}
            qs = apply_ordering(qs, opts.order, allowed_order)

        limit = opts.limit or view._resolve_paginate_by() or 50
        limit = max(1, min(int(limit), 500))
        fields = view._get_list_fields()
        # select_related FK columns present in the list so serialize() doesn't N+1.
        fk_names = []
        for f in fields:
            try:
                mf = view.model._meta.get_field(f)
            except Exception:
                continue
            if getattr(mf, "many_to_one", False):
                fk_names.append(f)
        if fk_names:
            qs = qs.select_related(*fk_names)
        rows_objs = list(qs[:limit])

        if opts.json:
            self.stdout.write(json_dump([serialize(o, fields) for o in rows_objs]))
            return
        if not rows_objs:
            self.stdout.write("(no rows)")
            return
        headers = ["ID"] + [f.upper() for f in fields]
        rows = [[str(o.pk)] + [self._cell(o, f) for f in fields] for o in rows_objs]
        self.stdout.write(table(rows, headers))

    def _ls_models(self, *, as_json: bool, counts: bool) -> None:
        data = []
        for token, model, view in self._sorted_views():
            entry = {
                "model": token,
                "label": model._meta.label,
                "name": str(model._meta.verbose_name),
                "api": bool(getattr(view, "enable_api", False)),
                "mcp": bool(getattr(view, "enable_mcp", False)),
                "search": bool(getattr(view, "enable_search", False)),
                "explorer": self._is_explorer(view),
            }
            if counts:
                entry["rows"] = view._get_queryset().count()
            data.append(entry)

        if as_json:
            self.stdout.write(json_dump(data))
            return
        if not data:
            self.stdout.write("(no registered CRUDView models)")
            return

        def flags(e):
            return "".join(c if e[k] else "-" for c, k in (("a", "api"), ("m", "mcp"), ("s", "search")))

        headers = ["MODEL", "FLAGS", "NAME"] + (["ROWS"] if counts else [])
        rows = []
        for e in data:
            row = [e["model"], flags(e), e["name"]]
            if counts:
                row.append(str(e["rows"]))
            rows.append(row)
        self.stdout.write(table(rows, headers))
        self.stdout.write("\nflags: a=api  m=mcp  s=search   ·   'sc describe <model>' for detail")

    # -- get ------------------------------------------------------------------

    def _cmd_get(self, argv: list[str]) -> None:
        parser = self._parser("get")
        parser.add_argument("model", help="model token")
        parser.add_argument("pk", help="primary key")
        parser.add_argument("--user", help="act as this username (tenancy scoping)")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        view = self._resolve_view(opts.model)
        req = self._fake_request(self._resolve_actor(opts.user))
        qs = view.get_list_queryset(view._get_queryset(), req)
        try:
            obj = qs.filter(pk=opts.pk).first()
        except (ValueError, TypeError):
            raise CommandError(f"invalid id {opts.pk!r} for {self._canonical_token(view.model)}")
        if obj is None:
            raise CommandError(f"{self._canonical_token(view.model)} {opts.pk!r} not found")

        result = serialize(obj, view._get_detail_fields())
        if opts.json:
            self.stdout.write(json_dump(result))
            return
        width = max(len(k) for k in result)
        for key, value in result.items():
            self.stdout.write(f"{key.ljust(width)}  {value}")

    # -- describe -------------------------------------------------------------

    def _cmd_describe(self, argv: list[str]) -> None:
        parser = self._parser("describe")
        parser.add_argument("model", help="model token")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        view = self._resolve_view(opts.model)
        model = view.model
        info = {
            "model": self._canonical_token(model),
            "label": model._meta.label,
            "verbose_name": str(model._meta.verbose_name),
            "url_base": view._get_url_base(),
            "explorer_synthesized": self._is_explorer(view),
            "staff_only": self._is_staff_gated(view),
            "api": bool(getattr(view, "enable_api", False)),
            "mcp": bool(getattr(view, "enable_mcp", False)),
            "search": bool(getattr(view, "enable_search", False)),
            "actions": [a.value for a in getattr(view, "actions", []) or []],
            "list_fields": list(view._get_list_fields()),
            "detail_fields": list(view._get_detail_fields()),
            "search_fields": list(view._resolve_search_fields()),
            "filter_fields": list(view._resolve_filter_fields()),
            "fields": [
                {"name": f.name, "type": f.get_internal_type(), "null": bool(f.null)}
                for f in model._meta.concrete_fields
            ],
        }
        if opts.json:
            self.stdout.write(json_dump(info))
            return

        self.stdout.write(f"{info['model']}  ({info['label']}) — {info['verbose_name']}")
        self.stdout.write(f"  url_base   : {info['url_base']}")
        badges = [b for b, on in (("api", info["api"]), ("mcp", info["mcp"]), ("search", info["search"]),
                                  ("staff-only", info["staff_only"]),
                                  ("explorer", info["explorer_synthesized"])) if on]
        self.stdout.write(f"  flags      : {', '.join(badges) or '(none)'}")
        self.stdout.write(f"  actions    : {', '.join(info['actions']) or '(none)'}")
        self.stdout.write(f"  list       : {', '.join(info['list_fields']) or '(none)'}")
        self.stdout.write(f"  search     : {', '.join(info['search_fields']) or '(none)'}")
        self.stdout.write(f"  filter     : {', '.join(info['filter_fields']) or '(none)'}")
        self.stdout.write("  fields:")
        for f in info["fields"]:
            self.stdout.write(f"    {f['name']:<24} {f['type']}{' (null)' if f['null'] else ''}")

    # -- search ---------------------------------------------------------------

    def _cmd_search(self, argv: list[str]) -> None:
        parser = self._parser("search")
        parser.add_argument("query", help="text to search across all searchable models")
        parser.add_argument("--limit", type=int, default=10, help="max hits per model (default 10)")
        parser.add_argument("--user", help="scope results to this username's visibility")
        parser.add_argument("--json", action="store_true")
        opts = parser.parse_args(argv)

        try:
            from apps.search.registry import search_all
        except ImportError:
            raise CommandError("search is unavailable (apps.search is not installed)")

        actor = self._resolve_actor(opts.user)  # None → trusted (sees everything)
        hits = search_all(opts.query, limit_per_model=opts.limit, user=actor)
        if opts.json:
            self.stdout.write(json_dump([h.as_dict() for h in hits]))
            return
        if not hits:
            self.stdout.write("(no matches)")
            return
        rows = [[h.model_verbose, f"{h.rank:.3f}", (h.display or "")[:60]] for h in hits]
        self.stdout.write(table(rows, ["TYPE", "RANK", "RESULT"]))
