"""Tests for the ``runbook`` management-command CLI (a thin skin over service.py)."""

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.runbook import service
from apps.runbook.models import Document, Runbook, Section


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def rb(db):
    return Runbook.objects.create(name="Ops", slug="ops")


def run(*argv, stdin=None, monkeypatch=None):
    """Invoke the CLI, returning captured stdout."""
    if stdin is not None:
        assert monkeypatch is not None
        monkeypatch.setattr("sys.stdin", StringIO(stdin))
    out = StringIO()
    call_command("runbook", *argv, stdout=out)
    return out.getvalue()


def write_page(runbook, key, body, tmp_path, **flags):
    """Helper: create/update a page via the CLI using -f to avoid stdin."""
    path = tmp_path / "body.md"
    path.write_text(body, encoding="utf-8")
    argv = ["write", f"{runbook}/{key}", "-f", str(path)]
    for k, v in flags.items():
        argv.append(f"--{k.replace('_', '-')}")
        if v is not True:
            argv.append(str(v))
    return run(*argv)


# -- dispatch -----------------------------------------------------------------

@pytest.mark.django_db
def test_unknown_subcommand_errors():
    with pytest.raises(CommandError, match="unknown subcommand"):
        run("frobnicate")


@pytest.mark.django_db
def test_no_subcommand_prints_help():
    out = run()
    assert "Subcommands:" in out


# -- ls -----------------------------------------------------------------------

@pytest.mark.django_db
def test_ls_lists_runbooks(rb):
    out = run("ls")
    assert "ops" in out and "RUNBOOK" in out


@pytest.mark.django_db
def test_ls_runbook_lists_pages(rb):
    service.put_document("ops", "one", body="# One", title="One")
    out = run("ls", "ops")
    assert "one" in out and "One" in out


@pytest.mark.django_db
def test_ls_unknown_runbook_errors(db):
    with pytest.raises(CommandError):
        run("ls", "nope")


@pytest.mark.django_db
def test_ls_excludes_archived_by_default(rb):
    service.put_document("ops", "live", body="a", title="Live")
    service.put_document("ops", "dead", body="b", title="Dead")
    service.archive_document(runbook="ops", key="dead")
    assert "dead" not in run("ls", "ops")
    assert "dead" in run("ls", "ops", "--all")


@pytest.mark.django_db
def test_ls_query_filters(rb):
    service.put_document("ops", "alpha", body="apples", title="Alpha")
    service.put_document("ops", "beta", body="oranges", title="Beta")
    out = run("ls", "ops", "-q", "apples")
    assert "alpha" in out and "beta" not in out


@pytest.mark.django_db
def test_ls_json_shape(rb):
    service.put_document("ops", "one", body="# One", title="One", source="bot")
    data = json.loads(run("ls", "ops", "--json"))
    assert data[0]["key"] == "one" and data[0]["source"] == "bot"


# -- toc ----------------------------------------------------------------------

@pytest.mark.django_db
def test_toc_groups_by_section(rb):
    Section.objects.create(runbook=rb, name="Runbooks", slug="runbooks", order=0)
    service.put_document("ops", "grouped", body="a", title="Grouped", section="runbooks")
    service.put_document("ops", "loose", body="b", title="Loose")
    out = run("toc", "ops")
    assert "Runbooks" in out and "(no section)" in out
    assert "grouped" in out and "loose" in out


@pytest.mark.django_db
def test_toc_json(rb):
    Section.objects.create(runbook=rb, name="S", slug="s", order=0)
    service.put_document("ops", "d", body="a", title="D", section="s")
    data = json.loads(run("toc", "ops", "--json"))
    assert data["runbook"] == "ops"
    assert data["sections"][0]["documents"][0]["key"] == "d"


# -- cat ----------------------------------------------------------------------

@pytest.mark.django_db
def test_cat_prints_body(rb):
    service.put_document("ops", "d", body="# Hello\n\nWorld", title="D")
    out = run("cat", "ops/d")
    assert "# Hello" in out and "World" in out


@pytest.mark.django_db
def test_cat_by_uid(rb):
    r = service.put_document("ops", "d", body="body-x", title="D")
    out = run("cat", "--uid", r.uid)
    assert "body-x" in out


@pytest.mark.django_db
def test_cat_json_includes_metadata(rb):
    service.put_document("ops", "d", body="body-y", title="D")
    data = json.loads(run("cat", "ops/d", "--json"))
    assert data["key"] == "d" and "body-y" in data["content_markdown"]


@pytest.mark.django_db
def test_cat_not_found_errors(rb):
    with pytest.raises(CommandError):
        run("cat", "ops/missing")


@pytest.mark.django_db
def test_cat_runbook_only_ref_errors(rb):
    with pytest.raises(CommandError, match="addresses a runbook"):
        run("cat", "ops")


# -- write --------------------------------------------------------------------

@pytest.mark.django_db
def test_write_creates_title_defaults_to_key(rb, tmp_path):
    write_page("ops", "new-page", "# Body", tmp_path)
    doc = Document.objects.get(key="new-page")
    assert doc.title == "new-page" and doc.version == 1 and doc.via == "cli"


@pytest.mark.django_db
def test_write_from_stdin(rb, monkeypatch):
    run("write", "ops/piped", "--title", "Piped", stdin="# From stdin\n", monkeypatch=monkeypatch)
    assert service.get_document("ops", "piped", with_body=True).content_markdown.strip() == "# From stdin"


@pytest.mark.django_db
def test_write_new_version_bumps(rb, tmp_path):
    write_page("ops", "d", "v1", tmp_path, title="D")
    write_page("ops", "d", "v2", tmp_path)
    assert Document.objects.get(key="d").version == 2


@pytest.mark.django_db
def test_write_overwrite_keeps_version(rb, tmp_path):
    write_page("ops", "d", "v1", tmp_path, title="D")
    write_page("ops", "d", "v2", tmp_path, mode="overwrite")
    doc = Document.objects.get(key="d")
    assert doc.version == 1
    assert service.get_document("ops", "d", with_body=True).content_markdown.strip() == "v2"


@pytest.mark.django_db
def test_write_append(rb, tmp_path):
    write_page("ops", "log", "line1", tmp_path, title="Log")
    write_page("ops", "log", "line2", tmp_path, mode="append")
    body = service.get_document("ops", "log", with_body=True).content_markdown
    assert "line1" in body and "line2" in body


@pytest.mark.django_db
def test_write_expected_version_conflict(rb, tmp_path):
    write_page("ops", "d", "v1", tmp_path, title="D")
    with pytest.raises(CommandError, match="[Ee]xpected version"):
        write_page("ops", "d", "v2", tmp_path, expected_version=99)


@pytest.mark.django_db
def test_write_fail_mode(rb, tmp_path):
    write_page("ops", "d", "v1", tmp_path, title="D")
    with pytest.raises(CommandError, match="already exists"):
        write_page("ops", "d", "v2", tmp_path, mode="fail")


@pytest.mark.django_db
def test_write_auto_creates_runbook_and_section(db, tmp_path):
    write_page("fresh", "intro", "# Intro", tmp_path, title="Intro", section="guides")
    assert Runbook.objects.filter(slug="fresh").exists()
    assert Section.objects.filter(runbook__slug="fresh", slug="guides").exists()
    assert Document.objects.get(key="intro").section.slug == "guides"


@pytest.mark.django_db
def test_write_no_create_runbook_errors(db, tmp_path):
    with pytest.raises(CommandError, match="no runbook"):
        write_page("ghost", "p", "x", tmp_path, no_create_runbook=True)


# -- locked-doc authorization -------------------------------------------------

@pytest.mark.django_db
def test_write_locked_requires_authorization(rb, tmp_path):
    service.create_document(rb, body="orig", title="Locked", key="locked", locked=True)
    with pytest.raises(CommandError, match="locked"):
        write_page("ops", "locked", "new", tmp_path)
    # --bypass-lock overrides
    write_page("ops", "locked", "new", tmp_path, bypass_lock=True)
    assert service.get_document("ops", "locked", with_body=True).content_markdown.strip() == "new"


@pytest.mark.django_db
def test_write_locked_superuser_via_user_flag(rb, tmp_path):
    get_user_model().objects.create_superuser(username="root", password="x")
    service.create_document(rb, body="orig", title="Locked", key="locked", locked=True)
    write_page("ops", "locked", "changed", tmp_path, user="root")
    assert service.get_document("ops", "locked", with_body=True).content_markdown.strip() == "changed"


@pytest.mark.django_db
def test_write_unknown_user_errors(rb, tmp_path):
    with pytest.raises(CommandError, match="no user"):
        write_page("ops", "d", "x", tmp_path, user="ghost")


# -- rm -----------------------------------------------------------------------

@pytest.mark.django_db
def test_rm_archives_by_default(rb):
    service.put_document("ops", "d", body="a", title="D")
    run("rm", "ops/d")
    assert Document.objects.get(key="d").is_archived is True


@pytest.mark.django_db
def test_rm_force_hard_deletes(rb):
    service.put_document("ops", "d", body="a", title="D")
    run("rm", "ops/d", "--force")
    assert not Document.objects.filter(key="d").exists()


# -- mv -----------------------------------------------------------------------

@pytest.mark.django_db
def test_mv_replaces_into_section(rb):
    Section.objects.create(runbook=rb, name="Arch", slug="arch", order=0)
    service.put_document("ops", "d", body="a", title="D")
    run("mv", "ops/d", "ops", "--section", "arch")
    assert Document.objects.get(key="d").section.slug == "arch"


@pytest.mark.django_db
def test_mv_detaches(rb):
    service.put_document("ops", "d", body="a", title="D")
    run("mv", "ops/d", "-")
    doc = Document.objects.get(title="D")
    assert doc.runbook_id is None and doc.key is None


@pytest.mark.django_db
def test_mv_to_other_runbook(rb):
    Runbook.objects.create(name="Archive", slug="archive")
    service.put_document("ops", "d", body="a", title="D")
    run("mv", "ops/d", "archive")
    assert Document.objects.get(title="D").runbook.slug == "archive"


# -- log ----------------------------------------------------------------------

@pytest.mark.django_db
def test_log_lists_versions_newest_first(rb):
    service.put_document("ops", "d", body="v1", title="D")
    service.put_document("ops", "d", body="v2", on_exists="new_version")
    out = run("log", "ops/d")
    assert "v2" in out and "v1" in out
    assert out.index("v2") < out.index("v1")


@pytest.mark.django_db
def test_log_json(rb):
    service.put_document("ops", "d", body="v1", title="D", source="bot")
    data = json.loads(run("log", "ops/d", "--json"))
    assert data[0]["version"] == 1 and data[0]["source"] == "bot"


# -- stat ---------------------------------------------------------------------

@pytest.mark.django_db
def test_stat_shows_metadata_without_body(rb):
    service.put_document("ops", "d", body="secret-body", title="D")
    out = run("stat", "ops/d")
    assert "uid" in out and "version" in out
    assert "secret-body" not in out


@pytest.mark.django_db
def test_stat_json(rb):
    service.put_document("ops", "d", body="a", title="D")
    data = json.loads(run("stat", "ops/d", "--json"))
    assert data["key"] == "d" and data["content_markdown"] is None


# -- sections -----------------------------------------------------------------

@pytest.mark.django_db
def test_sections_list(rb):
    Section.objects.create(runbook=rb, name="One", slug="one", order=0)
    out = run("sections", "ops")
    assert "one" in out and "One" in out


@pytest.mark.django_db
def test_sections_create(rb):
    run("sections", "ops", "--create", "newsec", "--name", "New Section")
    sec = Section.objects.get(runbook=rb, slug="newsec")
    assert sec.name == "New Section"


@pytest.mark.django_db
def test_sections_create_json_idempotent(rb):
    run("sections", "ops", "--create", "s")
    run("sections", "ops", "--create", "s")  # second time: exists, no error
    assert Section.objects.filter(runbook=rb, slug="s").count() == 1


# -- rb shim (console script) -------------------------------------------------

def test_shim_find_manage_py_walks_up(tmp_path):
    from apps.runbook import shim

    (tmp_path / "manage.py").write_text("")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert shim.find_manage_py(deep) == tmp_path / "manage.py"


def test_shim_find_manage_py_missing(tmp_path):
    from apps.runbook import shim

    assert shim.find_manage_py(tmp_path) is None


def test_shim_main_execs_runbook(tmp_path, monkeypatch):
    from apps.runbook import shim

    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    captured = {}

    class _Result:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Result()

    from apps.smallstack import cli_format

    monkeypatch.setattr(cli_format.subprocess, "run", fake_run)
    assert shim.main(["ls", "ops", "--json"]) == 0
    assert captured["cmd"][1].endswith("manage.py")
    assert captured["cmd"][2:] == ["runbook", "ls", "ops", "--json"]


def test_shim_main_no_manage_py(tmp_path, monkeypatch):
    from apps.runbook import shim

    monkeypatch.chdir(tmp_path)
    assert shim.main(["ls"]) == 2


# ---------------------------------------------------------------------------
# N+1 regression guards: query count must stay constant as the dataset grows.
# ---------------------------------------------------------------------------
from django.db import connection  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402


def _query_count(*argv):
    with CaptureQueriesContext(connection) as ctx:
        run(*argv)
    return len(ctx.captured_queries)


def test_toc_query_count_is_constant(db, tmp_path):
    def build(slug, n_pages):
        rb = Runbook.objects.create(name=slug, slug=slug)
        Section.objects.create(runbook=rb, slug="s", name="S")
        for i in range(n_pages):
            write_page(slug, f"p{i}", "# x", tmp_path, section="s")
        return slug

    build("small", 2)
    build("large", 12)
    assert _query_count("toc", "small") == _query_count("toc", "large")


def test_sections_query_count_is_constant(db, tmp_path):
    rb = Runbook.objects.create(name="ops", slug="ops")
    for i in range(2):
        Section.objects.create(runbook=rb, slug=f"a{i}", name=f"A{i}", order=i)
        write_page("ops", f"p{i}", "# x", tmp_path, section=f"a{i}")
    few = _query_count("sections", "ops")
    for i in range(2, 12):
        Section.objects.create(runbook=rb, slug=f"a{i}", name=f"A{i}", order=i)
        write_page("ops", f"p{i}", "# x", tmp_path, section=f"a{i}")
    assert _query_count("sections", "ops") == few


def test_ls_runbooks_query_count_is_constant(db, tmp_path):
    Runbook.objects.create(name="a", slug="a")
    Runbook.objects.create(name="b", slug="b")
    few = _query_count("ls")
    for i in range(10):
        slug = f"x{i}"
        rb = Runbook.objects.create(name=slug, slug=slug)
        Section.objects.create(runbook=rb, slug="s", name="S")
        write_page(slug, "p", "# x", tmp_path, section="s")
    assert _query_count("ls") == few


# -- cp -----------------------------------------------------------------------

@pytest.mark.django_db
def test_cp_duplicates_page(rb, tmp_path):
    write_page("ops", "src", "# Source body", tmp_path)
    out = run("cp", "ops/src", "ops/dst")
    assert "copied ops/src → ops/dst" in out
    assert service.get_document("ops", "dst", with_body=True).content_markdown == "# Source body"
    # Source is untouched.
    assert service.get_document("ops", "src", with_body=True).content_markdown == "# Source body"


@pytest.mark.django_db
def test_cp_refuses_to_clobber_without_force(rb, tmp_path):
    write_page("ops", "src", "# A", tmp_path)
    write_page("ops", "dst", "# B", tmp_path)
    with pytest.raises(CommandError, match="already exists"):
        run("cp", "ops/src", "ops/dst")


@pytest.mark.django_db
def test_cp_force_overwrites(rb, tmp_path):
    write_page("ops", "src", "# A", tmp_path)
    write_page("ops", "dst", "# B", tmp_path)
    run("cp", "ops/src", "ops/dst", "--force")
    assert service.get_document("ops", "dst", with_body=True).content_markdown == "# A"


@pytest.mark.django_db
def test_cp_creates_missing_destination_runbook(rb, tmp_path):
    write_page("ops", "src", "# A", tmp_path)
    run("cp", "ops/src", "archive/copied")
    assert Runbook.objects.filter(slug="archive").exists()


# -- cat @version -------------------------------------------------------------

@pytest.mark.django_db
def test_cat_reads_old_version(rb, tmp_path):
    write_page("ops", "p", "version one", tmp_path)
    write_page("ops", "p", "version two", tmp_path)  # new_version by default
    assert run("cat", "ops/p").strip() == "version two"
    assert run("cat", "ops/p@1").strip() == "version one"
    assert run("cat", "ops/p", "--version", "1").strip() == "version one"


@pytest.mark.django_db
def test_cat_unknown_version_errors(rb, tmp_path):
    write_page("ops", "p", "x", tmp_path)
    with pytest.raises(CommandError, match="has no version 9"):
        run("cat", "ops/p@9")


@pytest.mark.django_db
def test_cat_bad_version_syntax_errors(rb, tmp_path):
    write_page("ops", "p", "x", tmp_path)
    with pytest.raises(CommandError, match="invalid version"):
        run("cat", "ops/p@abc")


# -- revert -------------------------------------------------------------------

@pytest.mark.django_db
def test_revert_rolls_back_as_new_version(rb, tmp_path):
    write_page("ops", "p", "one", tmp_path)
    write_page("ops", "p", "two", tmp_path)
    out = run("revert", "ops/p", "--to", "1")
    assert "new head v3" in out
    result = service.get_document("ops", "p", with_body=True)
    assert result.content_markdown == "one"
    assert result.version == 3  # history preserved, not rewritten


@pytest.mark.django_db
def test_revert_unknown_version_errors(rb, tmp_path):
    write_page("ops", "p", "x", tmp_path)
    with pytest.raises(CommandError, match="no version 5"):
        run("revert", "ops/p", "--to", "5")


# -- restore (un-archive) -----------------------------------------------------

@pytest.mark.django_db
def test_restore_unarchives(rb, tmp_path):
    write_page("ops", "p", "x", tmp_path)
    run("rm", "ops/p")
    assert service.get_document("ops", "p").is_archived is True
    out = run("restore", "ops/p")
    assert "restored ops/p" in out
    assert service.get_document("ops", "p").is_archived is False


# -- mkdir --------------------------------------------------------------------

@pytest.mark.django_db
def test_mkdir_creates_runbook():
    out = run("mkdir", "newbook", "--name", "New Book")
    assert "created runbook newbook" in out
    assert Runbook.objects.get(slug="newbook").name == "New Book"


@pytest.mark.django_db
def test_mkdir_creates_section_under_runbook(rb):
    out = run("mkdir", "ops/procedures")
    assert "section ops/procedures" in out
    assert Section.objects.filter(runbook=rb, slug="procedures").exists()


@pytest.mark.django_db
def test_mkdir_is_idempotent(rb):
    out = run("mkdir", "ops")
    assert "exists" in out


# -- publish / unpublish ------------------------------------------------------

@pytest.mark.django_db
def test_publish_and_unpublish(rb):
    assert rb.is_public is False
    run("publish", "ops")
    rb.refresh_from_db()
    assert rb.is_public is True
    run("unpublish", "ops")
    rb.refresh_from_db()
    assert rb.is_public is False


# -- find ---------------------------------------------------------------------

@pytest.mark.django_db
def test_find_matches_content(rb, tmp_path):
    write_page("ops", "backup", "How to run the nightly backup window", tmp_path)
    write_page("ops", "deploy", "Deploy the app with kamal", tmp_path)
    out = run("find", "backup")
    assert "ops/backup" in out
    assert "ops/deploy" not in out


@pytest.mark.django_db
def test_find_json_is_a_list(rb, tmp_path):
    write_page("ops", "backup", "nightly backup window", tmp_path)
    payload = json.loads(run("find", "backup", "--json"))
    assert isinstance(payload, list)
    assert any(hit["ref"] == "ops/backup" for hit in payload)
