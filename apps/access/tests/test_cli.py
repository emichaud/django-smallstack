"""``manage.py access`` (and ``sc access``): the same service, recorded from ``cli``."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.access.models import AccessEvent

pytestmark = pytest.mark.django_db


def run(*args):
    out = StringIO()
    call_command("access", *args, stdout=out)
    return out.getvalue()


def test_grant_and_revoke_from_the_shell(alice, readers, root):
    assert "alice added to Readers" in run("grant", "alice", "Readers")
    event = AccessEvent.objects.get(kind="group_added", subject=alice)
    assert event.actor is None and event.source == "cli"
    assert "nothing changed" in run("grant", "alice", "Readers")
    assert "alice removed from Readers" in run(
        "revoke", "alice", "Readers", "--user", "root", "--reason", "left the rota"
    )
    removed = AccessEvent.objects.get(kind="group_removed", subject=alice)
    assert removed.actor == root and removed.source == "cli: left the rota"


def test_the_actor_must_hold_change_user(alice, readers, staffer):
    with pytest.raises(CommandError, match="accounts.change_user"):
        run("grant", "alice", "Readers", "--user", "staffer")
    assert not alice.groups.exists()
    with pytest.raises(CommandError, match="No group"):
        run("grant", "alice", "Nope")
    with pytest.raises(CommandError, match="No user"):
        run("grant", "nobody", "Readers")


def test_explain_check_and_groups(alice, readers):
    alice.groups.add(readers)
    text = run("explain", "alice")
    assert "groups: Readers" in text and "accounts.view_user" in text and "group:Readers" in text
    data = json.loads(run("explain", "alice", "--json"))
    assert data["permission_count"] == 1
    assert "alice may accounts.view_user" in run("check", "alice", "accounts.view_user")
    with pytest.raises(SystemExit) as exc:
        run("check", "alice", "accounts.delete_user")
    assert exc.value.code == 1
    groups = run("groups")
    assert "Readers" in groups and "ad hoc" in groups
    assert any(g["name"] == "Readers" and g["members"] == ["alice"] for g in json.loads(run("groups", "--json")))


def test_sc_fronts_it(alice, readers):
    out = StringIO()
    call_command("sc", "access", "grant", "alice", "Readers", stdout=out)
    assert "alice added to Readers" in out.getvalue()
