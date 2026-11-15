"""The REST surface at /smallstack/api/access/: reads for staff, the one
write through the shared membership service, recorded from ``rest``."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.access.models import AccessEvent
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE = "/smallstack/api/access/"


def bearer(user, level="auth"):
    _token, raw = APIToken.create_token(user=user, name=f"t-{level}", access_level=level)
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


# --- reads --------------------------------------------------------------------------


def test_reads_need_a_staff_account(client, alice, staffer):
    assert client.get(BASE + "users/").status_code == 401
    assert client.get(BASE + "users/", **bearer(alice, "")).status_code == 403
    assert client.get(BASE + "users/", **bearer(staffer, "")).status_code == 200


def test_the_user_payload_explains_every_permission(client, staffer, alice, readers, root):
    from apps.access.context import acting_as

    with acting_as(root, "test"):
        alice.groups.add(readers)
    data = client.get(BASE + "users/alice/", **bearer(staffer, "")).json()
    assert data["username"] == "alice" and data["active"] and not data["staff"]
    assert data["groups"] == [
        {"name": "Readers", "since": data["groups"][0]["since"], "added_by": "root", "source": "test"}
    ]
    assert data["groups"][0]["since"]
    assert {
        "permission": "accounts.view_user",
        "name": "Can view user",
        "app": "accounts",
        "sources": ["group:Readers"],
    } in data["permissions"]
    assert data["permission_count"] == 1 and data["direct_permissions"] == []
    assert data["events"][0]["kind"] == "group_added"
    # By email too; a miss is a JSON 404, not an HTML page.
    assert client.get(BASE + "users/alice@example.com/", **bearer(staffer, "")).json()["username"] == "alice"
    missing = client.get(BASE + "users/nobody/", **bearer(staffer, ""))
    assert missing.status_code == 404 and "nobody" in missing.json()["errors"]["__all__"][0]


def test_the_check_endpoint_gives_has_perm_with_reasons(client, staffer, alice, readers):
    alice.groups.add(readers)
    data = client.get(BASE + "users/alice/check/?perm=accounts.view_user", **bearer(staffer, "")).json()
    assert data["allowed"] is True and data["exists"] is True
    assert data["reasons"] == ["Member of group 'Readers', which grants it."]
    denied = client.get(BASE + "users/alice/check/?perm=accounts.delete_user", **bearer(staffer, "")).json()
    assert denied["allowed"] is False
    assert client.get(BASE + "users/alice/check/?perm=nonsense", **bearer(staffer, "")).status_code == 400


def test_users_groups_findings_and_events_have_their_shapes(client, staffer, alice, readers):
    alice.groups.add(readers)
    h = bearer(staffer, "")
    users = client.get(BASE + "users/?q=read", **h).json()
    assert users["count"] == 1 and users["results"][0]["groups"] == ["Readers"]
    assert client.get(BASE + "users/?show=nope", **h).status_code == 400
    groups = client.get(BASE + "groups/", **h).json()["results"]
    row = next(g for g in groups if g["name"] == "Readers")
    assert row["permissions"] == ["accounts.view_user"] and row["member_count"] == 1 and "members" not in row
    assert client.get(BASE + "groups/Readers/", **h).json()["members"] == ["alice"]
    assert client.get(BASE + "groups/Nope/", **h).status_code == 404
    findings = client.get(BASE + "findings/", **h).json()
    assert findings["worst"] in ("ok", "info", "warning", "danger")
    assert {"key", "title", "severity", "count", "summary", "advice", "rows"} <= set(findings["findings"][0])
    events = client.get(BASE + "events/?kind=grants", **h).json()
    assert events["results"][0]["kind"] == "group_added" and events["results"][0]["grant"] is True


# --- the write ----------------------------------------------------------------------


def test_put_and_delete_change_membership_recorded_from_rest(client, root, alice, readers):
    h = bearer(root)  # an auth-level token of a superuser
    url = BASE + "users/alice/groups/Readers/"
    first = client.put(url, **h)
    assert first.status_code == 200 and first.json() == {
        "username": "alice",
        "group": "Readers",
        "member": True,
        "changed": True,
    }
    assert alice.groups.filter(pk=readers.pk).exists()
    event = AccessEvent.objects.get(kind="group_added", subject=alice)
    assert (event.actor, event.source) == (root, "rest")
    assert client.put(url, **h).json()["changed"] is False
    assert client.delete(url, **h).json() == {"username": "alice", "group": "Readers", "member": False, "changed": True}
    assert not alice.groups.exists()
    assert AccessEvent.objects.filter(kind="group_removed", subject=alice, actor=root, source="rest").exists()


def test_the_write_needs_an_auth_level_token_and_change_user(client, manager, staffer, alice, readers):
    url = BASE + "users/alice/groups/Readers/"
    # The right permission, but a login-level token: the account endpoints' bar.
    refused = client.put(url, **bearer(manager, ""))
    assert refused.status_code == 403 and "Auth-level token" in refused.json()["errors"]["__all__"][0]
    # The right token, without the permission.
    refused = client.put(url, **bearer(staffer))
    assert refused.status_code == 403 and "accounts.change_user" in refused.json()["errors"]["__all__"][0]
    assert not alice.groups.exists()
    # Both: allowed, attributed to the manager.
    assert client.put(url, **bearer(manager)).json()["changed"] is True
    assert AccessEvent.objects.get(kind="group_added").actor == manager
    assert client.put(BASE + "users/alice/groups/Nope/", **bearer(manager)).status_code == 404


def test_the_endpoints_are_in_the_openapi_schema(client, root):
    client.force_login(root)
    paths = client.get("/api/schema/openapi.json").json()["paths"]
    access = sorted(p for p in paths if "/api/access/" in p)
    assert any(p.endswith("/api/access/users/{user}/groups/{group}/") for p in access)
    write = next(paths[p] for p in access if p.endswith("{user}/groups/{group}/"))
    assert {"put", "delete"} <= set(write)
    assert any(p.endswith("/api/access/findings/") for p in access)
