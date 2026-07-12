"""Tests for the ``sc`` framework CLI (P1: read verbs over the CRUDView registry)."""

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

User = get_user_model()
pytestmark = pytest.mark.django_db


def run(*argv):
    out = StringIO()
    call_command("sc", *argv, stdout=out)
    return out.getvalue()


# -- dispatch -----------------------------------------------------------------

def test_no_subcommand_prints_help():
    out = run()
    assert "Subcommands:" in out


def test_unknown_subcommand_errors():
    with pytest.raises(CommandError, match="unknown subcommand"):
        run("frobnicate")


# -- ls (models table of contents) --------------------------------------------

def test_ls_lists_registered_models():
    out = run("ls")
    assert "MODEL" in out and "FLAGS" in out
    assert "user" in out  # UserCRUDView is registered

def test_ls_models_json_carries_flags():
    data = json.loads(run("ls", "--json"))
    assert isinstance(data, list)
    user = next(e for e in data if e["model"] == "user")
    assert user["search"] is True          # UserCRUDView enable_search=True
    assert set(user) >= {"model", "label", "name", "api", "mcp", "search", "explorer"}


# -- ls <model> (rows) --------------------------------------------------------

def test_ls_rows(db):
    User.objects.create_user("alice", email="alice@example.com")
    out = run("ls", "user")
    assert "ID" in out and "alice" in out


def test_ls_query_searches(db):
    User.objects.create_user("alice")
    User.objects.create_user("bob")
    out = run("ls", "user", "-q", "alice")
    assert "alice" in out and "bob" not in out


def test_ls_json_and_limit(db):
    for i in range(3):
        User.objects.create_user(f"u{i}")
    data = json.loads(run("ls", "user", "--limit", "2", "--json"))
    assert len(data) == 2 and "id" in data[0] and "username" in data[0]


def test_ls_unknown_filter_errors(db):
    with pytest.raises(CommandError, match="unknown filter"):
        run("ls", "user", "--filter", "nope=1")


def test_ls_rows_query_count_is_constant(db):
    # The CLI must not N+1: query count for 2 rows == for 12 rows. Use a model
    # whose list fields are all scalar (no M2M) so we measure the CLI, not config.
    from apps.heartbeat.models import MonitoredEndpoint

    def _make(lo, hi):
        MonitoredEndpoint.objects.bulk_create(
            [MonitoredEndpoint(name=f"m{i}", slug=f"m{i}", service="svc", url="https://x") for i in range(lo, hi)]
        )

    _make(0, 2)
    with CaptureQueriesContext(connection) as ctx:
        run("ls", "monitoredendpoint")
    few = len(ctx)
    _make(2, 12)
    with CaptureQueriesContext(connection) as ctx:
        run("ls", "monitoredendpoint")
    assert len(ctx) == few


# -- get ----------------------------------------------------------------------

def test_get_shows_detail(db):
    u = User.objects.create_user("alice", email="alice@example.com")
    out = run("get", "user", str(u.pk))
    assert "alice" in out and "email" in out


def test_get_json(db):
    u = User.objects.create_user("alice")
    data = json.loads(run("get", "user", str(u.pk), "--json"))
    assert data["id"] == u.pk and data["username"] == "alice"


def test_get_not_found(db):
    with pytest.raises(CommandError, match="not found"):
        run("get", "user", "999999")


# -- describe -----------------------------------------------------------------

def test_describe_human():
    out = run("describe", "user")
    assert "user" in out and "fields:" in out and "username" in out


def test_describe_json():
    d = json.loads(run("describe", "user", "--json"))
    assert d["model"] == "user"
    assert "username" in d["search_fields"]
    assert any(f["name"] == "username" for f in d["fields"])
    assert "list_fields" in d and "actions" in d


# -- addressing ---------------------------------------------------------------

def test_resolve_app_model_form():
    out = run("describe", User._meta.label_lower)  # app.model token also resolves
    assert "user" in out


def test_resolve_unknown_suggests():
    with pytest.raises(CommandError, match="unknown model"):
        run("describe", "zzznope")


# -- search -------------------------------------------------------------------
# The CLI's `search` verb delegates to apps.search.registry.search_all; we mock it
# to test the verb's delegation + formatting without depending on the FTS index
# state (which the search engine's own tests already cover, and which is fragile
# across test ordering).

def _fake_hit(display="findme", rank=3.5):
    from apps.search.backends.base import SearchHit

    return SearchHit(model_label="accounts.User", model_verbose="User", object_id=1,
                     display=display, subtitle="", snippet="", url=None, rank=rank)


def test_search_cross_model(monkeypatch):
    monkeypatch.setattr("apps.search.registry.search_all", lambda *a, **k: [_fake_hit()])
    out = run("search", "findme")
    assert "findme" in out and "User" in out


def test_search_json(monkeypatch):
    monkeypatch.setattr("apps.search.registry.search_all", lambda *a, **k: [_fake_hit()])
    data = json.loads(run("search", "findme", "--json"))
    assert isinstance(data, list) and data[0]["display"] == "findme"


def test_search_unavailable_without_engine(monkeypatch):
    # If apps.search can't be imported, the verb fails cleanly (non-zero exit).
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "apps.search.registry":
            raise ImportError("no search")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(CommandError, match="search is unavailable"):
        run("search", "x")
