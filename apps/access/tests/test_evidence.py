"""The evidence pack: read-only sheets built from what the app records, the
same build behind the preview page, the CSV/JSON/ZIP exports, the CLI and REST."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date, timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command
from django.urls import reverse
from django.utils import timezone

from apps.access import directory, evidence, reviews
from apps.access.context import acting_as
from apps.access.models import AccessEvent, EvidenceBundle
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE = "/smallstack/api/access/"
START, END = date(2026, 7, 1), date(2026, 9, 30)


def at(day: str) -> str:
    return f"2026-{day}T12:00:00Z"


@pytest.fixture
def world(root, manager, alice, readers):
    """A period with a joiner, a leaver, a grant, a token and a signed review."""
    # A grant in the period, by root, from the web.
    with acting_as(root, "web:/smallstack/access/"):
        alice.groups.add(readers)
    AccessEvent.objects.filter(subject=alice, kind="group_added").update(at=at("08-10"))
    # A grant with no actor from a shell.
    with acting_as(None, "shell"):
        manager.groups.add(readers)
    AccessEvent.objects.filter(subject=manager, kind="group_added").update(at=at("08-11"))
    # The fixture's own staff/permission grants on manager happened "before the period".
    AccessEvent.objects.filter(subject=manager).exclude(kind="group_added").update(at=at("01-05"))
    # A joiner through the directory.
    identity = directory.resolve_identity("entra", "oid-new", email="new@example.com", name="New Joiner")
    joiner = identity.user
    User.objects.filter(pk=joiner.pk).update(date_joined=at("07-15"))
    AccessEvent.objects.filter(subject=joiner, kind="user_created").update(at=at("07-15"))
    # A leaver with a token, deactivated by root in the period.
    with acting_as(root, "web:/smallstack/manage/users/"):
        leaver = User.objects.create_user("leaver", password="p", is_staff=True)
        APIToken.create_token(user=leaver, name="old laptop")
        leaver.is_active = False
        leaver.save()
    AccessEvent.objects.filter(subject=leaver).update(at=at("09-01"))
    User.objects.filter(pk=leaver.pk).update(date_joined=at("01-01"))
    # A password beside a directory identity on root (an SSO bypass).
    directory.resolve_identity("entra", "oid-root", email="root@example.com").user  # new account, not root
    directory.resolve_identity("okta", "oid-r2").user
    # A live token without expiry.
    APIToken.create_token(user=manager, name="ci")
    # A signed review for the period.
    attester = User.objects.create_user("attester", password="p", is_staff=True)
    attester.groups.add(Group.objects.get(name="Access attester"))
    attester = User.objects.get(pk=attester.pk)
    attester2 = User.objects.create_user("attester2", password="p", is_staff=True)
    attester2.groups.add(Group.objects.get(name="Access attester"))
    attester2 = User.objects.get(pk=attester2.pk)
    review = reviews.open_review(period_start=START, period_end=END, scope="privileged", actor=attester)
    reviews.decide(review.items.get(user_label="manager"), "flagged", actor=attester, note="check")
    reviews.confirm_all(review, actor=attester)
    reviews.decide(review.items.get(user_label="attester"), "confirmed", actor=attester2)
    reviews.sign(review, actor=attester, typed_name="attester")
    return {"joiner": joiner, "leaver": leaver, "review": review, "attester": attester}


def test_the_pack_has_every_sheet_with_its_control_map(world, root):
    pack = evidence.build(START, END, scope="privileged", generated_by=root)
    assert [s.key for s in pack.sheets] == list(evidence.sheet_keys())
    assert pack.generated_by == "root" and pack.period_label == "Jul 01, 2026 – Sep 30, 2026"
    for s in pack.sheets:
        assert s.controls and s.title and s.description
        assert all(set(r) == set(s.columns) for r in s.rows), s.key
    data = pack.as_dict()
    assert set(data["sheets"]) == set(evidence.sheet_keys()) and data["scope"] == "privileged"


def test_roster_names_who_last_widened_each_account(world, root, manager):
    sheet = evidence.build(START, END, generated_by=root, only=["roster"]).sheet("roster")
    by = {r["username"]: r for r in sheet.rows}
    assert "alice" not in by and "leaver" not in by, "privileged and active only"
    assert by["manager"]["last_grant"] == "Added to group" and by["manager"]["last_granted_by"] == "shell"
    assert by["manager"]["live_tokens"] == 1 and by["manager"]["sign_in"] == "password"
    assert by["root"]["superuser"] and sheet.summary["superusers"] == 1
    everyone = evidence.build(START, END, scope="all", generated_by=root, only=["roster"]).sheet("roster")
    assert "alice" in {r["username"] for r in everyone.rows}


def test_changes_counts_grants_without_actor_and_by_month(world, root):
    sheet = evidence.build(START, END, generated_by=root, only=["changes"]).sheet("changes")
    assert sheet.summary["grants_without_actor"] == 1
    assert sheet.summary["by_month"]["2026-08"] == {"grants": 2, "removals": 0}
    assert sheet.summary["by_month"]["2026-09"]["removals"] == 1  # the deactivation
    kinds = {r["kind"] for r in sheet.rows}
    assert {"group_added", "deactivated", "token_revoked", "user_created"} <= kinds
    outside = evidence.build(date(2025, 1, 1), date(2025, 3, 31), generated_by=root, only=["changes"])
    assert outside.sheet("changes").count == 0


def test_joiners_and_leavers(world, root):
    pack = evidence.build(START, END, generated_by=root, only=["joiners", "leavers"])
    joiners = {r["username"]: r for r in pack.sheet("joiners").rows}
    assert joiners["new@example.com"]["via_directory"] == "entra" and joiners["new@example.com"]["created_by"] == (
        "directory:entra"
    )
    assert pack.sheet("joiners").summary["via_directory"] == 1
    leavers = pack.sheet("leavers").rows
    assert len(leavers) == 1
    row = leavers[0]
    assert row["username"] == "leaver" and row["by"] == "root" and row["tokens_revoked"] == 1
    assert row["sessions_ended"] == 0 and row["live_tokens_now"] == 0 and row["account_exists"]
    assert pack.sheet("leavers").summary["with_live_tokens_now"] == 0


def test_authentication_flags_a_password_beside_a_directory_identity(world, root, alice):
    sheet = evidence.build(START, END, generated_by=root, only=["authentication"]).sheet("authentication")
    by = {r["username"]: r for r in sheet.rows}
    assert by["new@example.com"]["sign_in"] == "directory" and not by["new@example.com"]["usable_password"]
    assert by["alice"]["sign_in"] == "password" and not by["alice"]["password_beside_directory"]
    assert "leaver" not in by, "inactive accounts aren't listed"
    directory.resolve_identity("entra", "oid-alice", email="alice@example.com")  # links alice, who has a password
    sheet = evidence.build(START, END, generated_by=root, only=["authentication"]).sheet("authentication")
    by = {r["username"]: r for r in sheet.rows}
    assert by["alice"]["password_beside_directory"] and sheet.summary["password_beside_directory"] == 1
    assert sheet.summary["failure_log_kept"] is False


def test_credentials_sheet(world, root, manager):
    sheet = evidence.build(START, END, generated_by=root, only=["credentials"]).sheet("credentials")
    by = {(r["owner"], r["name"]): r for r in sheet.rows}
    assert by[("manager", "ci")]["active"] and not by[("manager", "ci")]["expires_at"]
    assert not by[("leaver", "old laptop")]["active"] and by[("leaver", "old laptop")]["revoked_at"]
    assert sheet.summary["active_without_expiry"] >= 1 and sheet.summary["active_on_inactive_owner"] == 0


def test_findings_and_reviews_sheets(world, root):
    pack = evidence.build(START, END, generated_by=root, only=["findings", "reviews"])
    findings = pack.sheet("findings")
    assert {"superusers", "review_overdue"} <= {r["key"] for r in findings.rows}
    assert findings.summary["worst"] in ("danger", "warning", "info", "ok")
    rs = pack.sheet("reviews")
    assert rs.summary["signed_reviews"] == 1 and rs.summary["flagged"] == 1
    assert {r["decision"] for r in rs.rows} == {"confirmed", "flagged"}
    assert all(r["signed_by"] == "attester" for r in rs.rows)
    # A review outside the period doesn't travel with the pack.
    other = evidence.build(date(2025, 1, 1), date(2025, 3, 31), generated_by=root, only=["reviews"])
    assert other.sheet("reviews").count == 0


def test_build_validates(root):
    with pytest.raises(ValueError, match="scope must be"):
        evidence.build(START, END, scope="some")
    with pytest.raises(ValueError, match="ends before"):
        evidence.build(END, START)


def test_the_bundle_holds_a_cover_every_csv_and_the_json(world, root):
    pack = evidence.build(START, END, generated_by=root)
    data = evidence.bundle_zip(pack)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert names == {"cover.md", "evidence.json"} | {f"{k}.csv" for k in evidence.sheet_keys()}
        cover = zf.read("cover.md").decode()
        assert "SOC 2" in cover and "Privileged roster" in cover and "leavers.csv" in cover
        roster = zf.read("roster.csv").decode().splitlines()
        assert roster[0] == ",".join(pack.sheet("roster").columns)
        assert json.loads(zf.read("evidence.json"))["sheets"]["leavers"]["summary"]["leavers"] == 1
    assert evidence.bundle_name(pack) == "access-evidence-20260701-20260930"


def test_csv_cells_are_formula_safe(world, root):
    u = User.objects.create_user("=cmd", password="p", is_staff=True)
    sheet = evidence.build(START, END, generated_by=root, only=["roster"]).sheet("roster")
    text = evidence.sheet_csv(sheet)
    assert "'=cmd" in text and "\n=cmd" not in text
    u.delete()


# --- The page and the exports -------------------------------------------------------


def test_the_page_previews_each_sheet_and_defaults_to_the_last_quarter(client, staffer, world):
    client.force_login(staffer)
    page = client.get(reverse("access:evidence")).content.decode()
    q = reviews.recent_quarters(1)[0]
    assert "Access evidence" in page and q.label in page and "Bundle (ZIP)" in page
    assert f"from={q.start.isoformat()}&amp;to={q.end.isoformat()}" in page
    qs = f"from={START}&to={END}&scope=privileged"
    for key in evidence.sheet_keys():
        resp = client.get(reverse("access:evidence") + f"?{qs}&tab={key}")
        assert resp.status_code == 200, key
    leavers = client.get(reverse("access:evidence") + f"?{qs}&tab=leavers").content.decode()
    assert "leaver" in leavers and "tokens_revoked" in leavers and "This sheet (CSV)" in leavers
    assert client.get(reverse("access:evidence") + "?tab=nope").status_code == 404
    # A quarter key wins over the dates.
    resp = client.get(reverse("access:evidence") + f"?period={q.key}&from=2020-01-01&to=2020-02-01")
    assert q.label in resp.content.decode()


def test_the_exports_match_the_preview(client, staffer, world):
    client.force_login(staffer)
    qs = f"from={START}&to={END}&scope=privileged"
    csv_text = client.get(reverse("access:evidence_csv", kwargs={"key": "leavers"}) + f"?{qs}").getvalue().decode()
    assert csv_text.startswith("username,deactivated_at") and "leaver" in csv_text
    assert client.get(reverse("access:evidence_csv", kwargs={"key": "nope"}) + f"?{qs}").status_code == 404
    data = client.get(reverse("access:evidence_json") + f"?{qs}").json()
    assert data["sheets"]["leavers"]["summary"]["leavers"] == 1
    resp = client.get(reverse("access:evidence_zip") + f"?{qs}")
    assert resp["Content-Type"] == "application/zip"
    assert "access-evidence-20260701-20260930.zip" in resp["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert "cover.md" in zf.namelist()
    printed = client.get(reverse("access:evidence_print") + f"?{qs}").content.decode()
    assert "Access evidence" in printed and "Leavers" in printed and "Access reviews" in printed


def test_the_page_needs_an_access_reader(client, alice, world):
    client.force_login(alice)
    assert client.get(reverse("access:evidence")).status_code in (302, 403)
    assert client.get(reverse("access:evidence_zip")).status_code in (302, 403)


# --- CLI and REST --------------------------------------------------------------------------


def test_the_cli_writes_the_bundle(world, tmp_path):
    out = StringIO()
    call_command("access", "evidence", "--from", str(START), "--to", str(END), stdout=out)
    assert "Privileged roster" in out.getvalue() and "Leavers" in out.getvalue()
    target = tmp_path / "pack.zip"
    out = StringIO()
    call_command("access", "evidence", "--from", str(START), "--to", str(END), "--out", str(target), stdout=out)
    assert target.exists() and "Wrote" in out.getvalue()
    with zipfile.ZipFile(target) as zf:
        assert "leavers.csv" in zf.namelist()
    out = StringIO()
    call_command("access", "evidence", "--from", str(START), "--to", str(END), "--json", stdout=out)
    assert json.loads(out.getvalue())["generated_by"] == "cli"
    with pytest.raises(CommandError, match="YYYY-MM-DD"):
        call_command("access", "evidence", "--from", "July", "--to", str(END), stdout=StringIO())
    with pytest.raises(CommandError, match="scope must be"):
        call_command("access", "evidence", "--from", str(START), "--to", str(END), "--scope", "x", stdout=StringIO())


def test_rest_returns_the_pack_or_the_bundle(client, staffer, alice, world):
    from .test_api import bearer

    assert client.get(BASE + "evidence/?from=2026-07-01&to=2026-09-30", **bearer(alice, "")).status_code == 403
    assert client.get(BASE + "evidence/", **bearer(staffer, "")).status_code == 400
    data = client.get(BASE + "evidence/?from=2026-07-01&to=2026-09-30", **bearer(staffer, "")).json()
    assert data["sheets"]["roster"]["summary"]["accounts"] >= 2 and data["generated_by"] == "staffer"
    resp = client.get(BASE + "evidence/?from=2026-07-01&to=2026-09-30&format=zip", **bearer(staffer, ""))
    assert resp.status_code == 200 and resp["Content-Type"] == "application/zip"


def test_leaver_with_a_token_still_live_is_counted(root):
    """The events are the proof: a deactivation whose tokens weren't revoked
    at the same moment (a bulk update, say) shows up with live_tokens_now."""
    gone = User.objects.create_user("gone", password="p", is_staff=True)
    with acting_as(root, "web:/x/"):
        gone.is_active = False
        gone.save()  # revokes nothing, there are no tokens yet
    APIToken.create_token(user=gone, name="late")  # minted after, still live
    now = timezone.now().date()
    sheet = evidence.build(now - timedelta(days=1), now, generated_by=root, only=["leavers"]).sheet("leavers")
    assert sheet.rows[0]["live_tokens_now"] == 1 and sheet.summary["with_live_tokens_now"] == 1


# --- Round-2 fixes (Test Lab evaluation 45) ----------------------------------------


@pytest.fixture
def extra_sheet(monkeypatch):
    """An app's own sheet, registered the documented way; the registry is
    restored after the test."""
    monkeypatch.setattr(evidence, "_SHEETS", list(evidence._SHEETS))
    monkeypatch.setattr(evidence, "CONTROLS", dict(evidence.CONTROLS))
    monkeypatch.setattr(evidence, "PRINT_COLUMNS", dict(evidence.PRINT_COLUMNS))

    def service_accounts(start, end, scope):
        return evidence.Sheet(
            key="service_accounts",
            title="Service accounts",
            description="Accounts that exist for a machine, not a person.",
            columns=("username", "owner"),
            rows=[{"username": "=ci-bot", "owner": "platform"}],
        )

    evidence.register_sheet("service_accounts", service_accounts, controls="SOC 2 CC6.2")
    return "service_accounts"


def test_an_app_registers_a_sheet_and_it_appears_everywhere(client, staffer, world, extra_sheet):
    """T4-4: a sheet registered after evidence.py loaded shows on the page, in
    the CSV route, the JSON and the ZIP, with its controls line."""
    pack = evidence.build(START, END)
    assert pack.sheet(extra_sheet).count == 1 and pack.sheet(extra_sheet).controls == "SOC 2 CC6.2"
    client.force_login(staffer)
    qs = f"from={START}&to={END}&scope=privileged"
    page = client.get(f"/smallstack/access/evidence/?{qs}&tab={extra_sheet}")
    assert page.status_code == 200 and "Service accounts" in page.content.decode()
    csv_resp = client.get(f"/smallstack/access/evidence/{extra_sheet}.csv?{qs}")
    csv_body = b"".join(csv_resp.streaming_content).decode()
    assert "'=ci-bot" in csv_body  # formula-safe like the built-in sheets
    assert extra_sheet in client.get(f"/smallstack/access/evidence.json?{qs}").json()["sheets"]
    with zipfile.ZipFile(io.BytesIO(evidence.bundle_zip(pack))) as zf:
        assert f"{extra_sheet}.csv" in zf.namelist()


def test_register_sheet_refuses_a_built_in_or_bad_key(extra_sheet):
    with pytest.raises(ValueError, match="built-in"):
        evidence.register_sheet("roster", lambda s, e, sc: None)
    with pytest.raises(ValueError, match="slug"):
        evidence.register_sheet("Bad Key", lambda s, e, sc: None)


@pytest.fixture
def attester_for_store(db):
    from django.contrib.auth.models import Group

    user = get_user_model().objects.create_user("storer", password="p", is_staff=True)
    user.groups.add(Group.objects.get(name="Access attester"))
    return user


def test_bad_period_or_scope_is_refused_not_replaced(client, staffer, attester_for_store, world):
    """T4-1: REST and the exports answer 400 with the reason; the page says
    what it shows instead; storing stores nothing."""
    client.force_login(staffer)
    token = APIToken.create_token(user=staffer, name="t41", access_level="readonly")[1]
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    bad = {
        "from=2026-13-40&to=2026-09-30": "must be dates",
        "from=2026-09-30&to=2026-07-01": "ends before it starts",
        "from=2026-07-01&to=2026-09-30&scope=bogus": "scope must be",
        "from=2026-07-01&to=2026-09-30&format=xml": "format must be",
    }
    for qs, reason in bad.items():
        resp = client.get(f"{BASE}evidence/?{qs}", **auth)
        assert resp.status_code == 400 and reason in resp.json()["errors"]["__all__"][0], qs
    for qs, reason in list(bad.items())[:3]:
        routes = ("evidence.json", "evidence.zip", "evidence/roster.csv")
        for route in (f"/smallstack/access/{r}" for r in routes):
            resp = client.get(f"{route}?{qs}")
            assert resp.status_code == 400 and reason in resp.content.decode(), (route, qs)
    page = client.get("/smallstack/access/evidence/?from=2026-09-30&to=2026-07-01")
    assert page.status_code == 200 and "ends before it starts" in page.content.decode()
    # A good period is untouched.
    ok = client.get(f"{BASE}evidence/?from=2026-07-01&to=2026-09-30&scope=all", **auth).json()
    assert ok["period_start"] == "2026-07-01" and ok["scope"] == "all"
    client.force_login(attester_for_store)
    before = EvidenceBundle.objects.count()
    reversed_period = {"from": "2026-09-30", "to": "2026-07-01", "period": "custom"}
    client.post("/smallstack/access/evidence/packs/store/", reversed_period)
    assert EvidenceBundle.objects.count() == before


def test_the_cli_store_follows_the_page_rule_and_says_cli(world, staffer, attester_for_store):
    """T4-3: ``--store --user`` needs an attester or a superuser, as the page
    does; a store with no ``--user`` is labelled ``cli``, not ``schedule``."""
    args = ["access", "evidence", "--from", str(START), "--to", str(END), "--store"]
    with pytest.raises(CommandError, match="access.sign_accessreview"):
        call_command(*args, "--user", staffer.username, stdout=StringIO())
    manual = EvidenceBundle.objects.filter(reason=EvidenceBundle.Reason.MANUAL)
    assert not manual.exists()
    call_command(*args, "--user", attester_for_store.username, stdout=StringIO())
    assert manual.get().built_by == attester_for_store
    call_command(*args, stdout=StringIO())
    assert manual.latest("pk").built_by_label == "cli"
