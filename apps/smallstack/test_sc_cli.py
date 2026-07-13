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
    assert "user" in out and "fields" in out and "username" in out and "writable" in out


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


# -- writes (new / set / rm) --------------------------------------------------
# MonitoredEndpoint is staff-gated, so writes require a staff --user — this also
# exercises the staff-gate + audit path (same as REST/MCP).

REQUIRED = {"name": "Mon", "method": "GET", "url": "https://example.com",
            "expected_status": "200", "timeout_seconds": "10"}


def _staff(username="staffy"):
    return User.objects.create_user(username, is_staff=True)


def _endpoint(**over):
    from apps.heartbeat.models import MonitoredEndpoint

    defaults = dict(name="M", slug="s", service="custom", url="https://example.com", method="GET",
                    expected_status=200, timeout_seconds=10)
    defaults.update(over)
    return MonitoredEndpoint.objects.create(**defaults)


def _new_argv(**over):
    fields = {**REQUIRED, **over}
    return ["new", "monitoredendpoint", *[f"--{k}={v}" for k, v in fields.items()], "--user", "staffy"]


def test_new_creates(db):
    from apps.heartbeat.models import MonitoredEndpoint

    _staff()
    run(*_new_argv(slug="new1"))
    assert MonitoredEndpoint.objects.filter(slug="new1").exists()


def test_new_staff_gate(db):
    argv = ["new", "monitoredendpoint", *[f"--{k}={v}" for k, v in {**REQUIRED, "slug": "x"}.items()]]
    with pytest.raises(CommandError, match="staff-only"):
        run(*argv)


def test_new_validation_fail(db):
    _staff()
    fields = {k: v for k, v in {**REQUIRED, "slug": "vf"}.items() if k != "url"}  # omit required url
    argv = ["new", "monitoredendpoint", *[f"--{k}={v}" for k, v in fields.items()], "--user", "staffy"]
    with pytest.raises(CommandError, match="validation failed"):
        run(*argv)


def test_new_writes_audit_entry(db):
    from django.contrib.admin.models import LogEntry

    _staff()
    before = LogEntry.objects.count()
    run(*_new_argv(slug="aud"))
    assert LogEntry.objects.count() == before + 1


def test_set_updates(db):
    _staff()
    m = _endpoint(slug="up1", enabled=True)
    run("set", "monitoredendpoint", str(m.pk), "--enabled=false", "--user", "staffy")
    m.refresh_from_db()
    assert m.enabled is False


def test_set_not_found(db):
    _staff()
    with pytest.raises(CommandError, match="not found"):
        run("set", "monitoredendpoint", "999999", "--enabled=false", "--user", "staffy")


def test_rm_requires_force(db):
    from apps.heartbeat.models import MonitoredEndpoint

    _staff()
    m = _endpoint(slug="rm1")
    with pytest.raises(CommandError, match="--force"):
        run("rm", "monitoredendpoint", str(m.pk), "--user", "staffy")
    assert MonitoredEndpoint.objects.filter(pk=m.pk).exists()


def test_rm_deletes_with_force(db):
    from apps.heartbeat.models import MonitoredEndpoint

    _staff()
    m = _endpoint(slug="rm2")
    run("rm", "monitoredendpoint", str(m.pk), "--force", "--user", "staffy")
    assert not MonitoredEndpoint.objects.filter(pk=m.pk).exists()


# -- operational verbs (thin fronts over management commands) ------------------

SC_CALL = "apps.smallstack.management.commands.sc.call_command"


def _capture_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(SC_CALL, lambda cmd, *a, **k: calls.append((cmd, a)))
    return calls


def test_doctor_all_runs_three(monkeypatch):
    calls = _capture_calls(monkeypatch)
    run("doctor", "all")
    assert [c[0] for c in calls] == ["api_doctor", "mcp_doctor", "search_doctor"]


def test_doctor_one_passes_flags(monkeypatch):
    calls = _capture_calls(monkeypatch)
    run("doctor", "search", "--json")
    assert calls == [("search_doctor", ("--json",))]


def test_doctor_bare_flag_means_all(monkeypatch):
    calls = _capture_calls(monkeypatch)
    run("doctor", "--json")
    assert [c[0] for c in calls] == ["api_doctor", "mcp_doctor", "search_doctor"]


def test_doctor_unknown_errors(monkeypatch):
    _capture_calls(monkeypatch)
    with pytest.raises(CommandError, match="unknown doctor"):
        run("doctor", "bogus")


def test_backup_dispatches(monkeypatch):
    calls = _capture_calls(monkeypatch)
    run("backup")
    assert calls[0][0] == "backup_db"


def test_status_and_index_dispatch(monkeypatch):
    calls = _capture_calls(monkeypatch)
    run("status", "check")
    run("status", "maintenance", "list")
    run("index", "rebuild", "--all")
    run("index", "sync")
    assert [c[0] for c in calls] == ["heartbeat", "maintenance", "rebuild_search_index", "sync_help_index"]


def test_index_usage_error(monkeypatch):
    _capture_calls(monkeypatch)
    with pytest.raises(CommandError, match="usage: sc index"):
        run("index", "bogus")


def test_token_create_dispatches(monkeypatch):
    calls = _capture_calls(monkeypatch)
    run("token", "create", "alice", "--name", "x")
    assert calls[0][0] == "create_api_token" and "alice" in calls[0][1]


def _make_token(username="tokuser", active=True, name="t"):
    from apps.smallstack.models import APIToken

    u = User.objects.create_user(username)
    raw, prefix, hashed = APIToken._generate_raw_key()
    return APIToken.objects.create(user=u, name=name, prefix=prefix, hashed_key=hashed,
                                   access_level="readonly", is_active=active)


def test_token_list(db):
    tok = _make_token()
    out = run("token", "list")
    assert "PREFIX" in out and tok.prefix in out


def test_token_revoke(db):
    tok = _make_token(active=True)
    run("token", "revoke", tok.prefix)
    tok.refresh_from_db()
    assert tok.is_active is False


def test_token_revoke_unknown_errors(db):
    with pytest.raises(CommandError, match="no active token"):
        run("token", "revoke", "nope")


def test_token_usage_error(db):
    with pytest.raises(CommandError, match="usage: sc token"):
        run("token", "wat")


def test_commands_lists_grouped():
    out = run("commands")
    assert "runbook" in out and "api_doctor" in out and "backup_db" in out


def test_commands_json():
    data = json.loads(run("commands", "--json"))
    assert "runbook" in data
    names = {c["command"] for cmds in data.values() for c in cmds}
    assert "api_doctor" in names


# -- regression: testing-agent findings ---------------------------------------

def test_get_omits_password_and_m2m(db):
    # #1: sc get must not leak the password hash (or dump M2M managers).
    u = User.objects.create_user("alice", email="a@x.com", password="secret123")
    data = json.loads(run("get", "user", str(u.pk), "--json"))
    assert "password" not in data
    assert "groups" not in data and "user_permissions" not in data
    assert data["username"] == "alice"  # normal fields still present


def test_new_unknown_field_errors(db):
    # #2: a typo'd --field on create errors instead of silently dropping.
    _staff()
    argv = ["new", "monitoredendpoint",
            *[f"--{k}={v}" for k, v in {**REQUIRED, "slug": "uf1"}.items()],
            "--bogus=1", "--user", "staffy"]
    with pytest.raises(CommandError, match="unknown field"):
        run(*argv)


def test_set_unknown_field_errors(db):
    # #2: the dangerous one — a typo'd --field on update must not no-op silently.
    _staff()
    m = _endpoint(slug="uf2")
    with pytest.raises(CommandError, match="unknown field"):
        run("set", "monitoredendpoint", str(m.pk), "--enalbed=false", "--user", "staffy")


def test_ls_order_desc_space_form(db):
    # #3: --order -field (space form, leading dash) must parse, not error.
    User.objects.create_user("aaa")
    User.objects.create_user("zzz")
    out = run("ls", "user", "--order", "-username", "--limit", "1")
    assert "zzz" in out and "aaa" not in out


def test_counts_agree_with_rows_unscoped(db):
    # #5: without --user, --counts and ls use the same (unscoped) queryset.
    _make_token()  # 1 token, owned by a user (APIToken list is tenancy-scoped)
    counts = json.loads(run("ls", "--counts", "--json"))
    n = next(e["rows"] for e in counts if e["model"] == "apitoken")
    rows = json.loads(run("ls", "apitoken", "--json"))
    assert n == len(rows) == 1


def test_ls_order_by_non_list_field(db):
    # #2 polish: ordering by any concrete field (not just list columns) works.
    User.objects.create_user("u1", first_name="Aaa")
    User.objects.create_user("u2", first_name="Zzz")
    data = json.loads(run("ls", "user", "--order", "-first_name", "--limit", "1", "--json"))
    assert data[0]["username"] == "u2"


def test_describe_marks_writable_fields():
    # #3 polish: describe distinguishes writable (form) fields from display/filter-only ones.
    d = json.loads(run("describe", "monitoredendpoint", "--json"))
    assert "service" in d["filter_fields"] and "service" not in d["write_fields"]
    svc = next(f for f in d["fields"] if f["name"] == "service")
    assert svc["writable"] is False
    name = next(f for f in d["fields"] if f["name"] == "name")
    assert name["writable"] is True
