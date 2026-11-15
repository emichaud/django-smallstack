---
name: access-control
description: "Read before adding a permission check or declaring a group — Django groups + permissions as the one model, register_group (groups shipped in code, kept in step), every access change recorded to AccessEvent + the log + the account's history, the /smallstack/access/ review (findings, per-user \"why\", exports), register_check, acting_as for directory syncs; REST at /smallstack/api/access/, MCP read tools + a membership proposal an approver decides, manage.py access"
license: MIT
metadata:
  source: "docs/skills/access-control.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/access-control.md` by `make skills-index` — edit the source, not this file.

# Skill: Access Control — groups, permissions, the audit trail and the review

How SmallStack decides who may do what, records every change to it, and shows
an auditor the result. Read before adding a permission check, declaring a
group, or answering "can X do Y, and why?".

## The model: Django's, with three additions

Access is Django's own: `is_staff` opens the `/smallstack/` area, `is_superuser`
bypasses every check, **Groups** bundle **Permissions**, and `user.has_perm()`
is the one question every page, REST route, MCP tool and `sc` verb asks. There
is no parallel role system. SmallStack adds:

1. **Groups declared in code** (`register_group`), created after `migrate` and
   kept in step, so a role is something you can read in the repository.
2. **A record of every change to access** (`AccessEvent`), written from model
   signals so it doesn't matter which surface made the change.
3. **The Access pages** at `/smallstack/access/`: who holds what and why, a
   least-privilege review, exports, and a per-user permission check.

Row-level rules (`get_list_queryset`, `can_update`, `check_object_permission`
on a `CRUDView`) are a separate layer, below this one; see `crud-views.md`.

## Check a permission

```python
# A CRUDView: every surface, per action (view / add / change / delete)
class TicketCRUDView(CRUDView):
    model_permissions = True

# A plain view
from django.contrib.auth.decorators import permission_required
@permission_required("tickets.change_ticket", raise_exception=True)
def reassign(request, pk): ...

# Anywhere
if request.user.has_perm("tickets.change_ticket"): ...
```

Name a permission of your own in the model's `Meta.permissions` and migrate:

```python
class Meta:
    permissions = [("reassign_ticket", "Can reassign a ticket to another agent")]
```

Prefer a named permission for an action (`approvals.decide`) over a flag
check (`is_staff`): a flag says who someone is, a permission says what they
may do, and only the second can be reviewed, granted to a group and mapped
from a directory.

## Declare a group

`apps/<app>/groups.py`, imported for every installed app at startup:

```python
from apps.access.registry import register_group

register_group(
    "Support agent",
    description="Works tickets and decides refunds under the limit.",
    permissions=[
        "tickets.view_ticket", "tickets.change_ticket", "tickets.reassign_ticket",
        "smallstack_approvals.view_approvalrequest",
    ],
    app_label="tickets",
)
```

After each `migrate` (`sync_groups`, which first creates every installed app's
permissions, so this holds on the first `migrate` of a new app too), the Group
exists with those permissions. A declared name with no such permission (a
typo) is logged and shown as *missing* drift on the group's page and in the
review. On later syncs a permission the declaration adds is added, one it drops
is removed, and one an administrator added by hand is **kept** and shown as
drift on the group's page. (The sync doesn't track who added what: a
permission an administrator added by hand that the code later declares and
then drops is removed with it.) In a test, `sync_groups()` (no arguments)
re-runs the sync. A declared name that no longer exists in code leaves its
group in place, marked "no longer declared". `SMALLSTACK_ACCESS_GROUPS_SYNC =
False` turns the sync off.

SmallStack ships five in `apps/smallstack/groups.py`: Access reviewer, User
manager, Log reader, Approver, Token manager. Membership is granted on the
Access pages, in Django admin, or by a directory mapping.

## What is recorded, and where it goes

Every change to access is recorded by `apps/access/signals.py`, whichever
surface made it (Django admin, the Access pages, the User Manager, a shell, a
`loaddata`, a directory sync):

| Change | Event kind |
|---|---|
| Group membership | `group_added`, `group_removed` |
| A permission on an account | `permission_added`, `permission_removed` |
| A permission on a group | `group_permission_added`, `group_permission_removed` |
| `is_staff`, `is_superuser`, `is_active` flips | `staff_on/off`, `superuser_on/off`, `activated`, `deactivated` |
| Accounts and groups created or deleted | `user_created`, `user_deleted`, `group_created`, `group_deleted` (the name kept in the account / group column); a deleted group's members also get `group_removed` |
| A group renamed | `group_renamed` (`detail.from` / `detail.to`) |
| An API token revoked (any path: Token Manager, Access, admin, Explorer, REST logout, OAuth, `sc`) | `token_revoked` (`detail.token_id`, the token's owner as the account) |
| Deactivation's side effects | `token_revoked`, `sessions_ended` |

Either side of a relation counts: `user.groups.add(g)` and `g.user_set.add(user)`,
`user.user_permissions.add(p)` and `p.user_set.add(user)`. **Not recorded**,
because Django sends no signal for them: `QuerySet.update()` (for example
`User.objects.filter(...).update(is_staff=True)`, which also skips the token
revocation on `is_active=False`), bulk writes to the through tables
(`bulk_create` / `delete` on `User.groups.through`), and `loaddata` setting
the flags (fixtures load raw). Make access changes through `save()` and the
m2m managers.

Each event goes to three places:

- **`AccessEvent`** (the durable evidence): kind, actor, subject, group,
  permission, source (`web:/path/`, `shell`, `migrate`, `directory:entra`),
  the request id, and names as text so the row outlives a deleted user.
- **The log**, under `apps.access.record`: WARNING for a grant (so it reaches
  `/smallstack/logs/` at its default level), INFO for a removal, with the
  request id and the fields as structured extras.
- **The account's History** (`LogEntry`), when a person made the change.

**Deactivating an account revokes its live API tokens and ends its sessions**
(`revoke_access`), recorded as events. An account that may not sign in must
not keep working through a token minted earlier.

### Attributing changes made outside a request

`ActorMiddleware` names the signed-in user as the actor. Code that changes
access elsewhere says who and where:

```python
from apps.access.context import acting_as

with acting_as(None, "directory:entra"):
    user.groups.set(mapped_groups)
```

## The Access pages

| Page | Answers |
|---|---|
| **Overview** | Counts, the least-privilege findings with drill-downs, recent changes, exports |
| **Users** | Each account's flags, groups, direct permissions, tokens, last sign-in |
| **User** | Everything the account can do and **why** (`via group:X`, `via direct`, `via superuser`); a **Check a permission** box that answers as `has_perm` does, with the reason; groups with when and by whom; tokens; the account's events |
| **Groups** / **Group** | Members (with who added them), permissions by app, drift from the declaration, the group's events |
| **Changes** | Every event, filterable, exportable |

**Reading the Access pages (and the REST reads) needs only the staff flag**:
any staff account sees every account, permission and change. The *Access
reviewer* group exists for accounts that read the same data through Django
admin or Explorer, which check model permissions; it doesn't gate these pages.

**Changing a membership** needs a staff account holding `accounts.change_user`,
and, to **add** someone, every permission the group grants: a User manager
can't hand out (or take) more than they hold. Superusers may add to any group;
removing needs only the first rule. The same rule applies on every surface
(the pages, REST, an approval, the CLI), because all of them call
`services.set_membership`. Revoking tokens needs `smallstack.change_apitoken`:
anyone may revoke their own, revoking another account's needs the permission
(Token Manager, Access, Django admin, Explorer), and only a superuser revokes a
superuser's.

**Accounts themselves** (the User Manager at `/smallstack/manage/users/`):
creating needs `accounts.add_user`, editing (fields, staff and active flags, a
reset link, an unlock) needs `accounts.change_user`, deleting needs
`accounts.delete_user`; only a superuser may change a superuser's account.
Inviting by email (`/smallstack/accounts/invite/`) needs `accounts.add_user`
too, and making the invitee staff there needs `accounts.change_user`.
Staff without them see the pages read-only. In Django admin, only a superuser
may set *Superuser status*, *Groups* or *User permissions*.

### Findings (least privilege)

Built in, in `apps/access/checks.py`: superusers; dormant privileged accounts;
permissions granted directly rather than through a group; deactivated
accounts with live tokens; dormant accounts; staff with no group; groups that
drifted from their declaration; empty groups; auth-level API tokens. The
dormancy window is `SMALLSTACK_ACCESS_DORMANT_DAYS` (90).

Add one in `apps/<app>/access_checks.py`:

```python
from django.urls import reverse

from apps.access.registry import Finding, register_check

@register_check
def cross_tenant_members() -> Finding:
    users = [...]  # the accounts behind the number
    rows = [
        {"label": u.username,
         "href": reverse("access:user_detail", kwargs={"pk": u.pk}),  # where "Show" goes
         "meta": "in two tenants"}
        for u in users
    ]
    return Finding(
        key="cross_tenant_members",       # unique; also the drill-down URL slug
        title="Accounts in two tenants",
        severity="warning" if rows else "ok",   # "ok" | "info" | "warning" | "danger"
        count=len(rows),
        summary=f"{len(rows)} account(s) belong to more than one tenant.",
        rows=rows,                        # each {"label", "href", "meta"}
        advice="One account per tenant; invite a second account instead.",
    )
```

`severity` decides the order on the overview (danger first) and
`access_report`'s exit code (1 for a warning, 2 for a danger; `info` and `ok`
exit 0). A row's `href` is a page in your app or on the Access pages (an
account's `access:user_detail`, a group's `access:group_detail`); the
drill-down links each row there.

### Evidence for an audit

- **Export access (CSV)**: one row per account × permission × source, every
  account included.
- **Snapshot (JSON)**: accounts, groups (with drift) and findings, dated.
- **Changes → Export (CSV)**: the events, with the current filter.
- `manage.py access_report [--rows] [--json]`: the findings in a terminal or
  a cron job; exits 1 on a warning and 2 on a danger, so a scheduled run can
  alert. `--json` writes the snapshot for keeping.

## Automation: REST, MCP and the CLI

Everything the pages show is readable by a script or an agent, and the one
write, membership, goes through one function on every surface:

```python
from apps.access import services

services.set_membership(user, group, True, actor=request.user, source="my-sync")
# → True when it changed, False when it already held. services.MembershipRefused
#   (a PermissionError) when actor isn't staff, lacks accounts.change_user, or
#   (adding) lacks a permission the group grants. actor=None is a local command.
#   The m2m signal records it from `source`.
services.user_payload(user)            # the user page as JSON
services.explanation_payload(user, "accounts.change_user")
services.resolve_user("alice")         # username, email or id; LookupError on a miss
```

**REST** (`/smallstack/api/access/`, tag *Access* in `/api/docs/`; reads need a
staff account, any token tier):

| | |
|---|---|
| `GET users/?q=&show=` | accounts with groups, direct-permission and token counts |
| `GET users/{user}/` | one account: groups (since, by whom), every permission with sources, changes |
| `GET users/{user}/check/?perm=app.codename` | `has_perm` with the reasons |
| `PUT` / `DELETE users/{user}/groups/{group}/` | add / remove; **auth-level token, a staff owner holding `accounts.change_user`** (and, to add, every permission the group grants); idempotent (`changed`) |
| `GET groups/`, `GET groups/{group}/` | permissions, members, drift against the declaration |
| `GET findings/` | the review, with `worst` |
| `GET events/?who=&kind=&limit=` | the change log |

**MCP.** Three read tools at the staff tier, `access_explain_user`,
`access_check_permission`, `access_findings`, and one write tool that only
*proposes*: `access_request_membership(username, group, member, reason)` files
an `access.membership` approval (`apps/access/approvals.py`). Only that tool
files the kind (it is registered with `remote_filing=False`, so the generic
REST create endpoint and MCP `request_approval` refuse it). A person holding
`accounts.change_user` decides it in the console; the card shows the account
and group the approval will change, read from the database, the reason and the
agent that asked. Approving runs `set_membership` **in the
approver's name**, recorded as `mcp:approval:<id>`; rejecting, canceling or
expiring (three days) changes nothing. An approval that would change nothing
(the approver lacks a permission the group grants, the user or group is gone,
the context names someone else) is refused when it is decided, with the reason,
and the request stays pending for someone who can approve it, or a rejection. The agent polls `get_approval` until `status` leaves
`pending`. `SMALLSTACK_ACCESS_MCP_WRITES=False` removes the write tool. This is
the shape to copy for any agent-driven access change: never let a token write
access directly; let it ask.

**CLI.** `manage.py access` (or `sc access`): `explain <user> [--json]`,
`check <user> <app.codename>` (exit 1 when not held), `grant` / `revoke <user>
<group> [--user ACTOR] [--reason …]`, `groups`, `findings`. Without `--user` a
change is recorded from `cli` with no actor, a local administrator's shell
change; with it, the named person must be staff and pass the same rule as the
pages (`accounts.change_user`, and every permission of a group they add to).

## Preparing for single sign-on

Nothing here depends on how people sign in. A directory (Entra, Okta, Google)
becomes one more thing that assigns Groups: a sign-in backend turns its claims
into memberships inside `acting_as(None, "directory:<name>")`, so the events
say `directory:entra` as the source and the review reads the same. Map the
directory's app roles onto group names; never grant superuser from a
directory, and keep one local break-glass administrator.

## Don't

- Don't add a second way to say "may": no `is_admin` booleans on profiles, no
  role strings on models. Declare a permission, put it in a group.
- Don't grant permissions directly to an account when a group would do; the
  review flags it.
- Don't change `apps/smallstack/groups.py` downstream: declare your own group
  in your app's `groups.py`, or add members to the shipped ones.
- Don't write `AccessEvent` rows yourself; change the Django model and the
  signal records it.
