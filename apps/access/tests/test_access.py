"""The Access app: every change to access is recorded from every surface,
groups declared in code are kept in step, and the pages answer "what can this
person do, and why".
"""

from __future__ import annotations

import logging

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.urls import reverse

from apps.access import registry
from apps.access.context import acting_as
from apps.access.models import AccessEvent, ManagedGroup
from apps.access.registry import Finding, register_check, register_group, run_checks, sync_groups
from apps.access.services import effective_permissions, explain
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()
Kind = AccessEvent.Kind


def perm(name: str) -> Permission:
    app, codename = name.split(".")
    return Permission.objects.get(content_type__app_label=app, codename=codename)


@pytest.fixture
def admin(client):
    user = User.objects.create_superuser("root", password="p")
    client.force_login(user)
    return user


@pytest.fixture
def staff():
    return User.objects.create_user("staffer", password="p", is_staff=True)


# --- recording ------------------------------------------------------------------


def test_group_membership_is_recorded_from_either_side(staff, admin):
    group = Group.objects.create(name="Readers")
    AccessEvent.objects.all().delete()
    with acting_as(admin, "test"):
        staff.groups.add(group)
        group.user_set.remove(staff)
    kinds = list(AccessEvent.objects.order_by("pk").values_list("kind", "subject_label", "group_label", "actor_label"))
    assert kinds == [("group_added", "staffer", "Readers", "root"), ("group_removed", "staffer", "Readers", "root")]
    assert AccessEvent.objects.filter(source="test").count() == 2


def test_flags_permissions_and_group_permissions_are_recorded(staff):
    group = Group.objects.create(name="Ops")
    AccessEvent.objects.all().delete()
    staff.is_superuser = True
    staff.save()
    staff.user_permissions.add(perm("accounts.view_user"))
    group.permissions.add(perm("accounts.change_user"))
    staff.is_active = False
    staff.save()
    kinds = list(AccessEvent.objects.order_by("pk").values_list("kind", flat=True))
    assert kinds == ["superuser_on", "permission_added", "group_permission_added", "deactivated"]
    assert AccessEvent.objects.get(kind="permission_added").permission == "accounts.view_user"
    assert AccessEvent.objects.get(kind="group_permission_added").group_label == "Ops"


def test_a_change_reaches_the_log_and_the_accounts_history(staff, admin, caplog):
    group = Group.objects.create(name="Writers")
    with caplog.at_level(logging.INFO, logger="apps.access.record"), acting_as(admin, "web:/x/"):
        staff.groups.add(group)
    grant = [r for r in caplog.records if r.name == "apps.access.record" and "added staffer" in r.getMessage()]
    assert grant and grant[0].levelno == logging.WARNING  # a grant is a WARNING, so it reaches the log viewer
    assert grant[0].access_kind == "group_added" and grant[0].actor == "root"
    entry = LogEntry.objects.filter(object_id=str(staff.pk)).latest("pk")
    assert entry.user == admin and "added staffer to group 'Writers'" in entry.change_message


def test_deactivating_revokes_tokens_and_records_it(staff):
    token, _ = APIToken.create_token(user=staff, name="cli")
    staff.is_active = False
    staff.save()
    token.refresh_from_db()
    assert not token.is_active and token.revoked_at
    assert AccessEvent.objects.filter(kind="token_revoked", subject=staff, detail__token="cli").exists()


def test_recording_survives_a_deleted_user_and_group(staff):
    group = Group.objects.create(name="Gone")
    staff.groups.add(group)
    group.delete()
    name = staff.get_username()
    staff.delete()
    assert AccessEvent.objects.filter(kind="group_deleted", detail__group="Gone").exists()
    assert AccessEvent.objects.filter(kind="user_deleted", detail__username=name).exists()
    assert AccessEvent.objects.filter(kind="group_added", subject_label=name, group_label="Gone").exists()


# --- groups declared in code ------------------------------------------------------


def test_declared_groups_are_created_and_kept_in_step(monkeypatch):
    monkeypatch.setattr(registry, "_groups", {})
    register_group("Test readers", permissions=["accounts.view_user", "auth.view_group"], app_label="tests")
    sync_groups(source="test")
    group = Group.objects.get(name="Test readers")
    assert {p.codename for p in group.permissions.all()} == {"view_user", "view_group"}
    assert AccessEvent.objects.filter(group=group, kind="group_permission_added", source="test").count() == 2

    # An administrator adds one by hand; the code drops one. The sync removes
    # what the code dropped and keeps what the administrator added.
    group.permissions.add(perm("accounts.change_user"))
    register_group("Test readers", permissions=["accounts.view_user"], app_label="tests")
    sync_groups(source="test")
    assert {p.codename for p in group.permissions.all()} == {"view_user", "change_user"}
    assert ManagedGroup.objects.get(group=group).drift() == {"added": ["accounts.change_user"], "missing": []}


def test_smallstacks_own_groups_exist_after_migrate():
    names = set(Group.objects.values_list("name", flat=True))
    assert {"Access reviewer", "User manager", "Log reader", "Approver", "Token manager"} <= names
    assert ManagedGroup.objects.filter(group__name="Log reader").exists()


def test_a_declaration_naming_a_missing_permission_is_reported(monkeypatch, caplog):
    monkeypatch.setattr(registry, "_groups", {})
    register_group("Typo", permissions=["accounts.view_user", "nope.nothing"])
    with caplog.at_level(logging.WARNING, logger="apps.access.registry"):
        summary = sync_groups(source="test")
    assert summary["missing_permissions"] == {"Typo": ["nope.nothing"]}
    assert Group.objects.get(name="Typo").permissions.count() == 1


# --- explain -----------------------------------------------------------------------


def test_effective_permissions_name_every_source(staff):
    group = Group.objects.create(name="Viewers")
    group.permissions.add(perm("accounts.view_user"))
    staff.groups.add(group)
    staff.user_permissions.add(perm("accounts.view_user"), perm("auth.view_group"))
    by_perm = {g.perm: g.sources for g in effective_permissions(staff)}
    assert by_perm == {"accounts.view_user": ["group:Viewers", "direct"], "auth.view_group": ["direct"]}
    verdict = explain(staff, "accounts.view_user")
    assert verdict.allowed and verdict.reasons == [
        "Member of group 'Viewers', which grants it.",
        "Granted directly on the account.",
    ]
    assert not explain(staff, "accounts.delete_user").allowed
    assert not explain(staff, "nope.nothing").exists
    staff.is_active = False
    staff.save()
    assert explain(staff, "accounts.view_user").reasons[0].startswith("The account is deactivated")


# --- findings -------------------------------------------------------------------------


def test_findings_see_the_risks(staff, settings):
    settings.SMALLSTACK_ACCESS_DORMANT_DAYS = 0
    staff.user_permissions.add(perm("accounts.view_user"))
    gone = User.objects.create_user("gone", password="p", is_active=True)
    APIToken.create_token(user=gone, name="old")
    User.objects.filter(pk=gone.pk).update(is_active=False)  # bypasses the signal, like legacy data
    by_key = {f.key: f for f in run_checks()}
    assert by_key["direct_permissions"].severity == "warning" and by_key["direct_permissions"].count == 1
    assert by_key["inactive_with_tokens"].severity == "danger"
    assert by_key["inactive_with_tokens"].rows[0]["label"] == "gone"
    assert by_key["superusers"].severity == "warning"  # none yet: keep a break-glass admin


def test_a_downstream_check_joins_the_list_and_a_failing_one_doesnt_take_it_down(monkeypatch):
    monkeypatch.setattr(registry, "_checks", dict(registry._checks))

    @register_check
    def tenant_isolation() -> Finding:
        return Finding("tenant_isolation", "Tenants", "danger", 1, "One tenant can see another.")

    @register_check
    def broken() -> Finding:
        raise RuntimeError("boom")

    findings = run_checks()
    assert findings[0].key == "tenant_isolation"  # worst first
    assert any(f.key == "broken" and "boom" in f.summary for f in findings)


def test_the_report_command_exits_by_severity(capsys, staff):
    with pytest.raises(SystemExit) as exc:  # no superuser at all: a warning
        call_command("access_report")
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Superusers" in out and "break-glass" in out
    User.objects.filter(pk=staff.pk).update(is_active=False)
    APIToken.create_token(user=staff, name="live")  # a live token on a deactivated account: danger
    with pytest.raises(SystemExit) as exc:
        call_command("access_report", "--rows")
    assert exc.value.code == 2
    assert "staffer" in capsys.readouterr().out


# --- pages --------------------------------------------------------------------------


def test_pages_need_staff_and_view_user(client, staff):
    assert client.get(reverse("access:index")).status_code == 302
    client.force_login(User.objects.create_user("member", password="p"))
    assert client.get(reverse("access:index")).status_code == 403
    client.force_login(staff)
    assert client.get(reverse("access:index")).status_code == 403  # staff alone no longer reads (S2-1)
    staff.user_permissions.add(perm("accounts.view_user"))
    staff = User.objects.get(pk=staff.pk)
    client.force_login(staff)
    for name, kwargs in [
        ("index", {}),
        ("users", {}),
        ("groups", {}),
        ("events", {}),
        ("user_detail", {"pk": staff.pk}),
    ]:
        assert client.get(reverse(f"access:{name}", kwargs=kwargs)).status_code == 200, name


def test_the_user_page_explains_and_checks(client, admin, staff):
    group = Group.objects.create(name="Viewers")
    group.permissions.add(perm("accounts.view_user"))
    with acting_as(admin, "web:/setup/"):
        staff.groups.add(group)
    page = client.get(reverse("access:user_detail", kwargs={"pk": staff.pk}) + "?perm=accounts.view_user")
    html = page.content.decode()
    assert "via group:Viewers" in html
    assert "added" in html and "by root" in html
    assert "<strong>staffer may</strong>" in html and "Member of group &#x27;Viewers&#x27;" in html


def test_membership_changes_need_the_change_user_permission(client, staff):
    group = Group.objects.create(name="Viewers")
    client.force_login(staff)
    url = reverse("access:user_groups", kwargs={"pk": staff.pk})
    assert client.post(url, {"action": "add", "group": group.pk}).status_code == 403
    staff.user_permissions.add(perm("accounts.change_user"))
    client.force_login(User.objects.get(pk=staff.pk))
    assert client.post(url, {"action": "add", "group": group.pk}).status_code == 302
    event = AccessEvent.objects.get(kind="group_added", subject=staff)
    assert event.actor == staff and event.source == f"web:{url}"


def test_exports_carry_the_evidence(client, admin, staff):
    group = Group.objects.create(name="Viewers")
    group.permissions.add(perm("accounts.view_user"))
    staff.groups.add(group)
    csv_body = b"".join(client.get(reverse("access:matrix_csv")).streaming_content).decode()
    assert "staffer" in csv_body and "accounts.view_user" in csv_body and "group:Viewers" in csv_body
    data = client.get(reverse("access:snapshot_json")).json()
    assert {u["username"]: u["groups"] for u in data["users"]}["staffer"] == ["Viewers"]
    assert any(g["name"] == "Viewers" and g["permissions"] == ["accounts.view_user"] for g in data["groups"])
    assert "findings" in data and "generated_at" in data
    events = b"".join(client.get(reverse("access:events_csv") + "?kind=grants").streaming_content).decode()
    assert "group_added" in events and "staffer" in events


def test_the_finding_drilldown_lists_the_rows(client, admin, staff):
    staff.user_permissions.add(perm("accounts.view_user"))
    body = client.get(reverse("access:finding", kwargs={"key": "direct_permissions"})).content.decode()
    assert "staffer" in body and reverse("access:user_detail", kwargs={"pk": staff.pk}) in body
    assert client.get(reverse("access:finding", kwargs={"key": "nope"})).status_code == 404


# --- the Access tab on the User Manager, and the way over from Activity ------------


def test_the_user_managers_edit_page_has_an_access_tab(client, admin, staff):
    group = Group.objects.create(name="Viewers")
    with acting_as(admin, "web:/setup/"):
        staff.groups.add(group)
    html = client.get(reverse("manage/users-update", kwargs={"pk": staff.pk})).content.decode()
    assert 'data-tab="access">Access</button>' in html
    assert "Viewers" in html and "Added to group" in html and "by root" not in html  # the tab shows date · actor
    assert reverse("access:user_detail", kwargs={"pk": staff.pk}) in html
    assert reverse("access:group_detail", kwargs={"pk": group.pk}) in html


def test_top_pages_carry_the_full_path_and_a_link(client, admin, staff):
    from apps.activity.models import RequestLog

    long_path = "/smallstack/datasets/browse/smallstack_dashboards.metrics/with/a/long/tail/"
    RequestLog.objects.create(user=staff, path=long_path, method="GET", status_code=200, response_time_ms=3)
    html = client.get(reverse("manage/users-update", kwargs={"pk": staff.pk})).content.decode()
    assert f'title="{long_path}"' in html  # the hover shows what the ellipsis hides
    assert "path=" in html and "tab=recent" in html


def test_the_activity_user_page_links_to_access(client, admin, staff):
    html = client.get(reverse("activity:user_detail", kwargs={"pk": staff.pk})).content.decode()
    assert reverse("access:user_detail", kwargs={"pk": staff.pk}) in html
