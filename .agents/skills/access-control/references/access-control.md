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
   least-privilege findings, periodic access reviews, exports, and a
   per-user permission check. (*Findings* are the continuous checks below;
   a *review* is always the periodic attestation a person signs.)

Row-level rules (`get_list_queryset`, `can_update`, `check_object_permission`
on a `CRUDView`) are a separate layer, below this one; see `crud-views.md`.

## Start from user, staff and admin; add groups only where they earn it

Every SmallStack app already has three tiers, and most access questions fit
one of them. Fit the app into these first, and declare a group only for a job
they can't express. The app decides, but the default is the simplest model
that is true.

| Tier | Who | How the code asks | What it opens |
|---|---|---|---|
| **User** | any signed-in account | `LoginRequiredMixin`, plus a queryset scoped to the user (`get_list_queryset`) | their own things: "my tickets", "my posts", profile, tokens |
| **Staff** | `is_staff` | `StaffRequiredMixin` / `@staff_required` | the `/smallstack/` area and the app's management pages |
| **Admin** | `is_superuser` | nothing (passes every `has_perm`) | everything; keep it to a few break-glass accounts |

**Add a group when staff is too coarse.** That means two kinds of staff need
different things: support may reassign tickets but not issue refunds, or an
editor publishes posts but doesn't manage users. Then:

1. Check the permission in code (`has_perm("tickets.refund_ticket")`, or
   `model_permissions = True` on the CRUDView), so the gate is in the code and
   not in a template `if`.
2. Declare **one group per job**, named for the job ("Support agent",
   "Blog editor"), in the app's `groups.py`, holding only what that job needs.
   Set `staff=True` when its members work in the staff area.
3. Add a custom permission (`Meta.permissions`) only for an action the four
   model permissions (view/add/change/delete) can't say, such as `refund` or
   `publish`.

**Prefer, in order:**

- **User-scoped data over a permission.** "Users see only their own rows" is
  a queryset filter, not a group.
- **Staff alone, when every staff member should have it.** A small internal
  tool often needs no groups at all: a staff page is gated by
  `StaffRequiredMixin`.
- **One group per job, not per page or per action.** Three groups a reviewer
  can read beat twelve nobody can.
- **A shipped group, reused.** If SmallStack's *Approver* or *User manager*
  already describes the job, add members to it rather than declaring a copy.

**Don't invent a fourth tier.** That means no "manager" flag, no role field on
the profile and no "admin lite": a manager is a group. Don't make someone
superuser to get one permission; give them the group that holds it.
(Superusers and directory accounts that are also superusers are flagged in
the findings.)

When you're unsure, choose the simpler tier and leave a one-line comment
saying what would justify a group. Splitting a group later is easy. Taking
access away from people who got used to it isn't.

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

SmallStack ships six in `apps/smallstack/groups.py`: Access reviewer, Access
attester, User manager, Log reader, Approver, Token manager. Membership is
granted on the Access pages, in Django admin, or by a directory mapping.

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
| An access review signed | `review_signed` (the review, its counts, the signer; written by `reviews.sign`) |
| An API token deleted while live | `token_revoked` first (the delete revokes it), on any surface |

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
| **Users** | Each account's role, groups, direct permissions, live tokens, last sign-in, joined. Filter pills with counts (Active / Staff / Deactivated / All), search, every column sortable (`?ordering=`, `-` reverses; never-signed-in last), rows per page — all links and GET, the state in the address, the card swapping over htmx |
| **User** | Everything the account can do and **why** (`via group:X`, `via direct`, `via superuser`); a **Check a permission** box that answers as `has_perm` does, with the reason; groups with when and by whom; tokens; the account's events |
| **Groups** / **Group** | Create a group (*New group* opens a dialog; a refusal shows in it, success lands on the group's page); members (with who added them) and permissions by app, each added and removed several at a time with a filterable picker (the cards swap in place over htmx); *Membership*: local or directory-managed (role key, *Make local*); rename, delete, drift from the declaration, the group's events. Nothing here needs Django admin |
| **Changes** | Every event: search by account, group or permission; a pill per family (grants, removals, accounts, groups, tokens & sessions, reviews — `?kind=`, a single kind still works), every column sortable (`?ordering=`), rows per page, CSV export of what's filtered. The same `kind`/`ordering` values work on `GET /smallstack/api/access/events/` |
| **Reviews** / **Review** | Periodic access reviews: open one, decide each account, sign; CSV / JSON / print view (see *Access reviews* below) |
| **Evidence** | The one-touch audit pack for a period: nine sheets previewed one at a time, CSV / ZIP / JSON / print (see *The evidence pack* below) |

**Reading the Access pages, the REST reads and the MCP read tools needs a
staff account holding `accounts.view_user`** (`services.can_read_access`;
superusers always pass): reading access is reading accounts, the permission
Django admin and Explorer ask for the same rows. The shipped *Access reviewer*
and *User manager* groups grant it. The same rule holds for the User Manager's
list and pages, `GET /api/auth/users/` and user search hits. The exception is
the **Timezones dashboard** (`/smallstack/manage/users/timezones/`), a team
scheduling tool open to every active staff account with its own sidebar link:
without `view_user` it shows username, display name, avatar and time zone only
(no staff badge or *Staff only* filter, no edit link, and the search doesn't
match email). Other accounts'
API tokens (the Token Manager's list, detail and search hits) need
`smallstack.view_apitoken` (the *Token manager* group); everyone sees their own.
The dashboard's *API Tokens* card stays visible to all staff: it shows
system-wide counts (active, total, revoked, per level) and nothing per token,
no name, owner or label, on the card or in `/api/dashboard/widgets/`.

**Changing a membership** needs a staff account holding `accounts.change_user`,
and, to **add** someone, every permission the group grants: a User manager
can't hand out (or take) more than they hold. Superusers may add to any group;
removing needs only the first rule. The same rule applies on every surface
(the pages, REST, an approval, the CLI), because all of them call
`services.set_membership`. Revoking tokens needs `smallstack.change_apitoken`:
anyone may revoke their own, revoking another account's needs the permission
(Token Manager, Access, Django admin, Explorer), and only a superuser revokes a
superuser's.

**Groups themselves** (`services.create_group` / `rename_group` /
`set_group_permission` / `delete_group`, what Django admin's group form did):
a staff account holding `auth.add_group`, `auth.change_group` or
`auth.delete_group` respectively (`services.group_refusal`), and to **give a
group a permission**, the actor must hold it themselves — the same subset
rule as adding a member, so nobody hands out more than they have (the
picker only offers what the viewer holds; a superuser holds all). A group
**declared in code** can't be renamed or deleted on the page (the sync would
make it again; change `groups.py`), though its permissions can, shown as
drift. A **directory-managed** group changes nowhere but its declaration and
the directory. A local group can be **marked directory-managed** on its
page, over REST or with `access group role` (`services.set_directory_role`; see
`directory-sso.md`); its members then come from the directory at sign-in.
Every write runs inside `acting_as`, so the signals record it
(`group_created`, `group_renamed`, `group_permission_added` / `_removed`,
`group_deleted`). **Direct permissions** on an account can be taken off on
the user page (`services.remove_direct_permission`: `accounts.change_user`,
only a superuser for a superuser's) and never added there — a direct grant is
what the *Direct permissions* finding reports; use a group. The same writes
exist over REST (`POST /smallstack/api/access/groups/`, `PATCH` / `DELETE
…/groups/{group}/`, `PUT` / `DELETE …/groups/{group}/permissions/{perm}/`,
`DELETE …/users/{user}/permissions/{perm}/`; an auth-level token, 403 for
who's asking and 400 for what they sent) and from the shell (`access group
new|rename|rm|grant|revoke|role`, `access perm rm`; `--user` applies the actor's
rules, without it a local command keeps only the group's own).

**Which role cuts off an account, and where.** The Access user page's *Revoke
tokens & sign out* (every live token revoked, every session ended) is for a
**User manager**: it needs `accounts.view_user` to open the page and then
`accounts.change_user` **or** `smallstack.change_apitoken` to press it
(`services.revoke_all_refusal`, which both the button and the POST ask). With
`change_user` it follows deactivation's rules, since deactivating would revoke
the same tokens anyway (`account_flags_refusal`: a wider non-superuser is
fine). On either permission, only a superuser acts on a superuser, and nobody
uses it on their own account (revoke your own tokens on the Token Manager).
Every revoke is recorded as a `token_revoked` event. A **Token manager** has
no `view_user`, so it revokes an account's tokens one by one on the **Token
Manager** (`/smallstack/tokens/`); it can't end sessions. A User manager can
also **deactivate** the account, which does both and stops sign-in.

**Accounts themselves** (the User Manager at `/smallstack/manage/users/`):
creating needs `accounts.add_user`, editing (fields, staff and active flags, a
reset link, an unlock) needs `accounts.change_user`, deleting needs
`accounts.delete_user`; only a superuser may change a superuser's account.
**Who can sign in as an account is the subset rule too:** changing another
account's password, email or username, or sending it a password link, also
needs every permission that account holds (`services.sign_in_refusal`; your
own account is exempt). That applies on the User Manager, `/api/auth/users/`,
Django admin and Explorer; the fields are locked, with the reason, otherwise.
Inviting by email (`/smallstack/accounts/invite/`) needs `accounts.add_user`
too. Making a new account staff, on the create page, the invite page or
Explorer's create form, also needs `accounts.change_user` (the box is dropped
and a posted `is_staff` ignored otherwise).
Staff without them see the pages read-only. In Django admin, only a superuser
may set *Superuser status*, *Groups* or *User permissions*. **Django admin and
Explorer follow the User Manager's account rules**
(`services.account_flags_refusal`): only a superuser changes or deletes a
superuser's account (it opens read-only for anyone else, and a POST is
refused), nobody deactivates or deletes their own account or removes their own
staff access, and nobody deactivates, demotes or deletes the last active
superuser. A wider non-superuser account's staff and active flags stay
editable with `change_user`, as on the User Manager. Explorer asks a
ModelAdmin's per-object `has_change_permission(request, obj)` and
`has_delete_permission(request, obj)` when it declares them.

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

The **evidence pack** (below) is the one-touch answer: every sheet an auditor
asks for, for a period, with the controls each supports. The three older
exports are its parts and stay for quick questions:

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
staff account holding `accounts.view_user`, any token tier; 403 says so otherwise):

| | |
|---|---|
| `GET users/?q=&show=` | accounts with groups, direct-permission and token counts |
| `GET users/{user}/` | one account: groups (since, by whom), every permission with sources, changes |
| `GET users/{user}/check/?perm=app.codename` | `has_perm` with the reasons |
| `PUT` / `DELETE users/{user}/groups/{group}/` | add / remove; **auth-level token, a staff owner holding `accounts.change_user`** (and, to add, every permission the group grants); idempotent (`changed`) |
| `GET groups/`, `GET groups/{group}/` | permissions, members, drift against the declaration |
| `GET findings/` | the review, with `worst` |
| `GET events/?who=&kind=&limit=` | the change log |

**MCP.** Three read tools, at any token tier as the REST reads, for staff
callers holding `accounts.view_user` (hidden from, and refusing with
`forbidden`, anyone else),
`access_explain_user`, `access_check_permission`, `access_findings`, and one write tool that only
*proposes*: `access_request_membership(username, group, member, reason)` files
an `access.membership` approval (`apps/access/approvals.py`). Only that tool
files the kind (it is registered with `remote_filing=False`, so the generic
REST create endpoint and MCP `request_approval` refuse it). A person holding
`accounts.change_user` decides it in the console (never the account it acts
on, which also can't cancel it); only staff holding `accounts.view_user` or
`change_user` see it, and its notices go to the people who could decide it; the card shows the account
and group the approval will change, read from the database, the reason and the
agent that asked. Approving runs `set_membership` **in the
approver's name**, recorded as `mcp:approval:<id>`; rejecting, canceling or
expiring (three days) changes nothing. An approval that would change nothing
(the approver lacks a permission the group grants, the user or group is gone,
the context names someone else, the account is already in or out of the group)
is refused when it is decided, with the reason,
and the request stays pending for someone who can approve it, or a rejection. The agent polls `get_approval` until `status` leaves
`pending`. `SMALLSTACK_ACCESS_MCP_WRITES=False` removes the write tool. This is
the shape to copy for any agent-driven access change: never let a token write
access directly; let it ask.

The write tool reveals no access state to a caller who can't read it (no
`accounts.view_user`): it files "add alice to Readers" whether or not alice is
already in Readers (the decide-time check above refuses the pointless one),
doesn't list the groups on a miss, doesn't look an account up by email, and
leaves the group's permission count out of the request's context. A caller
holding `view_user` gets the precise `unchanged` error instead. Any tool you add
that acts on an account should keep the same line: what it answers must not
tell the caller more than the read tools would.

**CLI.** `manage.py access` (or `sc access`): `explain <user> [--json]`,
`check <user> <app.codename>` (exit 1 when not held), `grant` / `revoke <user>
<group> [--user ACTOR] [--reason …]`, `groups`, `findings`. Without `--user` a
change is recorded from `cli` with no actor, a local administrator's shell
change; with it, the named person must be staff and pass the same rule as the
pages (`accounts.change_user`, and every permission of a group they add to).

## Access reviews (attestation)

The change log is the *detective* control: continuous, automatic. A review
is the *governance* control over it: once a period, a named attester opens a
review, which **freezes the roster** of accounts holding access at that
moment, decides each row, and **signs**. The signed review is immutable
evidence that a person looked, on a date, and what they concluded (SOC 2
CC6.1–6.3, PCI DSS 7.2.4, ISO 27001 A.5.18). **Nothing in it changes access.**

- **Who**: the shipped *Access attester* group (`access.sign_accessreview` +
  the read permissions). `reviews.attester_refusal(user)` is the rule: active
  staff holding it, **not a superuser** (a superuser is what the review
  examines). A superuser may *open* a review, not decide or sign. *Access
  reviewer* reads reviews, decides nothing.
- **Scope**: `privileged` (default: superusers, staff, and holders of any
  `reviews.PRIVILEGED_PERMISSIONS`, the ones that change access or
  credentials) or `all` (every active account). One open review per scope.
- **Each row** (`AccessReviewItem.facts`, frozen): flags, groups, direct
  permissions, counts, sign-in method (directory / password / none), last
  sign-in, live tokens, directory sightings, grants in the period (from the
  events). Rows new since the last signed review of the scope sort first.
- **Decisions**: *confirm*, *flag* (with a note), *remove*. An attester
  can't confirm or remove **their own row**; they flag it for another
  attester. *Remove* files an `access.review_remove` approval; a person
  holding `accounts.change_user` approves it in the console and the account
  is deactivated **in the approver's name** (tokens revoked, sessions ended,
  recorded as any deactivation). The item keeps `follow_up = approval:<id>`.
  Only the requester, or someone who could decide it, may cancel the
  approval, and never the account it removes (the kind's `can_cancel` hook).
  If it is rejected, canceled or expires, deciding *remove* again on an open
  review files a new one.
- **Signing**: every row decided, the attester types their username or full
  name (case and surrounding spaces don't matter; what they typed is kept),
  and the review records signer, time, typed name, client IP and the request
  ids of the opening (`request_id`) and the signing (`signed_request_id`), writes a `review_signed` `AccessEvent` with the counts, and
  **locks**: `save()`/`delete()` on the review or its items, and
  `QuerySet.update()`/`delete()` over them, raise `ReviewLocked`; Django admin
  is read-only. (A data migration that must rewrite history uses
  `AccessReview._base_manager`.)
- **Findings**: *Access review overdue* (info until a first review is ever
  signed, then warning for one missed quarter, danger for two), *Review
  decisions not yet acted on* (flagged rows, and *remove* rows whose account
  is still active, whatever became of the approval: pending, rejected,
  canceled, expired; the row shows which), *Privileged accounts not yet
  reviewed* (new since the last signed roster).
- **Surfaces**: `/smallstack/access/reviews/` (open, decide, sign, CSV, JSON,
  print view for the PDF-wanting auditor); `manage.py access review
  open|list|show`; `GET /smallstack/api/access/reviews/[{id}/]`. **Deciding
  and signing exist on the page only**: no shell, REST or MCP write, because
  an attestation is a person's act. `opened_via` records whether the page,
  the CLI or the schedule opened it; the schedule's cadence (opening,
  reminders, escalation, the `access.review.signed` webhook) is a section
  below.

```python
from apps.access import reviews

review = reviews.open_review(period_start=start, period_end=end, scope="privileged", actor=attester)
reviews.decide(item, "confirmed", actor=attester, note="still on the help desk")
reviews.confirm_all(review, actor=attester)          # skips the attester's own row
reviews.sign(review, actor=attester, typed_name="Ann Attester")   # ReviewRefused with the reason otherwise
reviews.review_payload(review); reviews.review_csv_rows(review)
```

## The evidence pack (one-touch audit report)

`/smallstack/access/evidence/` builds, for a period and a scope, the sheets
an auditor asks for, previews each one, and exports what was previewed. It is
**read-only**: every row is read from the records above at generation time
(`apps/access/evidence.py`, `build()`), and the page, the CSV/JSON/ZIP
exports, the CLI and REST all use that one build.

| Sheet | Answers | Supports |
|---|---|---|
| Privileged roster | who holds privileged access, how they sign in, who last widened it and when | SOC 2 CC6.1/6.3 · PCI 7.2 · ISO A.5.15/5.18 |
| Access matrix | user × permission × source | CC6.1 · PCI 7.2.2 |
| Access changes | every event in the period; grants vs removals by month; grants with no actor; local changes to directory groups | CC6.2/6.3 · PCI 7.2.2, 8.2.4 |
| Joiners | accounts created: by whom or which directory, first grant, first sign-in | CC6.2 · PCI 8.2.1 |
| Leavers | deactivations: by whom, tokens/sessions revoked at the same moment (proved by the events), lag after the directory last saw them, tokens still live | CC6.3/6.5 · PCI 8.2.5/8.2.6 |
| Authentication | sign-in method per account; a usable password beside a directory identity (an SSO bypass); failed sign-ins and lockouts when the axes failure log is kept | CC6.1 · PCI 8.2.6, 8.3.4, 8.6 |
| API credentials | every token: owner, tier, created, expiry, last use, issued/revoked in period | CC6.1 · PCI 8.6 |
| Findings | the least-privilege findings as they stand now (the stored pack the schedule keeps when a quarter closes is the before-picture) | CC6.1/6.3 · PCI 7.2.4 |
| Access reviews | the signed attestations covering the period, one row per reviewed account | CC6.3 · PCI 7.2.4/7.2.5 |

- **Period**: a quarter pill (`?period=<start>_<end>`, wins) or *Custom*
  with `from`/`to` dates; default the last complete quarter. **Scope** pills
  as for reviews. Tabs are `?tab=<sheet>` (plus `packs`, the stored packs);
  rows paginate with *Rows per page*; headings are the column keys spaced
  out (the CSV keeps the keys); a cell wraps only when it's long. A bad date, a period that ends before it
  starts or an unknown scope is refused with the reason (400 on REST and the
  exports, a message on the page, nothing stored), never replaced by another
  period.
- **Exports**: *This sheet (CSV)*, *Bundle (ZIP)* = `cover.md` (period,
  counts, the controls map, how to read it) + one CSV per sheet +
  `evidence.json`, *JSON*, *Print view* (cover, roster, leavers, findings,
  reviews on one printable page). CSV cells are formula-safe.
- `manage.py access evidence --from --to [--scope] [--out pack.zip | --store | --json]`;
  `GET /smallstack/api/access/evidence/?from=&to=&scope=[&format=zip]`.
  Reading needs `accounts.view_user`, as every Access read does.
- **Stored packs** (`EvidenceBundle`): *Store this pack* on the page,
  `--store` on the CLI, and the schedule (below) keep a pack on the server
  as built, dated, with its **SHA-256** and per-sheet counts — so a copy
  handed to an auditor can be checked against what the system produced
  (`sha256sum` on the download matches; the download also carries
  `X-Content-SHA256`). Storing needs what opening a review needs (an
  attester or a superuser); downloading is an Access read. Files live under
  `MEDIA_ROOT/access/evidence/`, a private media prefix: the public
  `/media/` route refuses them, only the access-checked view serves them.
  `SMALLSTACK_ACCESS_EVIDENCE_KEEP` (default 24) is kept per scope **and
  reason** (`period_closed`, `review_signed`, `manual`), oldest deleted first,
  so packs stored on request never push out an attested one; 0 keeps every
  one. `access evidence --store --user <name>` needs what the page needs; with
  no `--user` the pack is recorded as built by `cli`. `manage.py access packs [--json]`,
  `GET /smallstack/api/access/evidence/packs/[{id}/][?format=zip]`.
- **Add a sheet** from your app in `apps/<app>/access_evidence.py`
  (autodiscovered, like `access_checks.py`); it then appears as a tab, a CSV in
  the bundle, in JSON, the CLI and REST:

  ```python
  from apps.access.evidence import Sheet, register_sheet

  def service_accounts(start, end, scope) -> Sheet:   # aware datetimes bounding the period
      rows = [...]
      return Sheet(key="service_accounts", title="Service accounts",
                   description="Accounts that exist for a machine.", columns=("username", "owner"), rows=rows)

  register_sheet("service_accounts", service_accounts, controls="SOC 2 CC6.2")
  ```

  Keys are lowercase slugs; a built-in key (or `cover`) can't be replaced,
  and the sheet is filed under the key you register whatever its `Sheet.key`.
  Say what it reflects: `as_of="generated"` for the state when the pack is
  built (default `"period"`, events within it) and `scoped=True` when the
  scope filters it; both show on the page and in `cover.md`.

## By the schedule (the review cadence)

**Off by default, and most deployments leave it off.** Reviews are opened
from the Reviews page whenever one is wanted and the evidence pack is built
for any period on demand; nothing is scheduled, nobody is notified, the
dashboard shows no card. A deployment on an auditor's calendar, where a
control that depends on someone remembering isn't operating, sets
`SMALLSTACK_ACCESS_REVIEW_CADENCE=quarterly`. The **cadence**
(`apps/access/cadence.py`) is then a daily scheduled job, *Access: review
cadence* (`@scheduled`, 06:10 local; `manage.py access cadence` runs the
same tick from cron on a deployment without the scheduler), that:

1. **Opens the review when a quarter closes.** The first tick after the last
   complete quarter has no signed review covering it (and no review of the
   scope is already open) opens one, `opened_via = schedule`, with no actor —
   so the roster is frozen on a predictable date whoever is on holiday.
2. **Stores the quarter's evidence pack** at that moment (`reason =
   period_closed`): the before-picture of the findings and the roster as the
   period ended.
3. **Tells the attesters** — every active staff account holding
   `access.sign_accessreview` that isn't a superuser — in-app (`notify()`,
   kind `access.review.opened`, `subject_key access.review:<id>`) and by
   branded email, with the due date (period end + `SMALLSTACK_ACCESS_REVIEW_DUE_DAYS`,
   default 30). No attester at all is a logged warning and an email to
   nobody — fix the group, not the job.
4. **Reminds** while any review stays open (opened by the schedule *or by
   hand*): every `SMALLSTACK_ACCESS_REVIEW_REMINDER_DAYS` (default 7; 0 = never),
   kind `access.review.reminder`, counted on the review (`reminders`, which
   the escalation notice adds one to). With no attester to tell, nothing is
   counted and the warning says so.
5. **Escalates** once past due: one `access.review.overdue` notice to the
   attesters plus `SMALLSTACK_ACCESS_REVIEW_ESCALATION_EMAILS` (the security
   lead, the GRC mailbox), `escalated_at` set, and the *Access review overdue*
   finding's row names the open review, its pending count and the due date.
   A review opened late (the quarter closed weeks ago) is escalated on the
   *next* tick, not the one that opened it.

**Signing stays a person's act**: the tick decides nothing and signs nothing,
and there is still no shell, REST or MCP write for either. What a signing
sets in motion (`cadence.after_signed`, called from `reviews.sign`, each step
unable to fail the signing): the "review due" bells are retired
(`resolve(subject_key)`), the **attested pack** is stored (`reason =
review_signed`, in the signer's name — the one to hand the auditor), and the
**`access.review.signed` webhook event** goes out to every endpoint whose
filter matches (`access.review.*`, `*`). Its envelope is a CRUDView's —
`event`, `action: "signed"`, `model: "access.accessreview"`, `id`,
`occurred_at`, `data` (the review payload with its `summary`), `event_id`,
`origin`, `resource` — so the GRC tool's receiver handles it like any other.
The event is declared with `webhooks.services.register_event`, so the
endpoint picker offers it. Deliveries run on the `webhooks` task queue: run
`manage.py db_worker --queue-name webhooks` (a plain `db_worker` serves only
`default`, and the deliveries wait as *pending*). `resource.url` is absolute
only when `SITE_URL` (or `SMALLSTACK_WEBHOOK_ORIGIN`) is set, and `null`
otherwise; set it, or a receiver can't follow the link. The emailed links to
the review use `SITE_URL` too, since the tick runs outside any request.

- **Where it shows**: the *By the schedule* card on the Reviews page (off: one
  line saying attestation is on demand and how to turn the cadence on; on:
  the scheduler row enabled/paused, the last complete quarter's state, due
  date, who can sign, next run); the *Access review* card on the
  `/smallstack/` dashboard (*Q3 2026 signed · by ann* / *due in 12 days* /
  *overdue 5 days*) — placed on the board only once the cadence is on
  (*Add card → Widget* adds it by hand otherwise), and never "overdue" while
  the cadence is off; `GET /smallstack/api/access/reviews/cadence/`;
  `manage.py access cadence --status`.
- **Settings**: `SMALLSTACK_ACCESS_REVIEW_CADENCE` (default `""`, off: no
  job, no notifications, no card; `quarterly` turns it on — the scheduler
  registers the job on its next tick or `migrate`, not at a restart), `SMALLSTACK_ACCESS_REVIEW_SCOPE` (`privileged` / `all`),
  `SMALLSTACK_ACCESS_REVIEW_DUE_DAYS`, `SMALLSTACK_ACCESS_REVIEW_REMINDER_DAYS`,
  `SMALLSTACK_ACCESS_REVIEW_ESCALATION_EMAILS`, `SMALLSTACK_ACCESS_EVIDENCE_KEEP`.
  The scheduler row itself can be paused from `/smallstack/scheduler/` like
  any job.
- **Testing** (`apps/access/tests/test_cadence.py`): `cadence.tick(today=date(...))`
  drives every branch without a worker; `mail.outbox` and
  `Notification.objects` show the two channels; patch
  `webhooks.services._enqueue_delivery` to assert the `WebhookDelivery` row
  without an HTTP call.

## Directory-managed groups (single sign-on)

Nothing above depends on how people sign in. A directory (Entra, Okta, Google,
a proxy such as Cloudflare Access or oauth2-proxy) becomes one more thing that
assigns Groups, under one rule: **the directory decides who, code decides
what.** The full recipe, with the per-provider claim shapes, is
`directory-sso.md`; the model is this.

A declaration carries the stable key the directory sends for the group:

```python
register_group(
    "Event planner",
    permissions=["events.plan_event"],
    directory_role="Events.Planner",   # the Entra app-role value / Okta group name
    staff=True,                        # members are staff (optional)
    app_label="events",
)

# A group declared elsewhere (one SmallStack ships): give it a role without
# copying its permission list, whatever the import order.
from apps.access.registry import map_directory_role
map_directory_role("Access reviewer", "Access.Reviewer")
```

`directory_role` is `[A-Za-z0-9._-]{1,100}` (no spaces; Entra's rule, and a
key that fits every provider), unique across groups, stored on
`ManagedGroup.directory_role` (NULL for a local group). With it the group is
**directory-managed**:

- **Membership is set at sign-in.** The sign-in code calls
  `apps.access.directory.sign_in(provider, subject, roles, email=…, name=…)`
  (or `resolve_identity` then `sync_roles`). `sync_roles` sets the user's
  directory-managed groups to exactly the roles sent, never touches a group
  without a role, sets `is_staff` when a group declared `staff=True` is among
  them (and never unsets it, or touches `is_superuser`), and records every
  change from `directory:<provider>`. **`roles=None` (the claim is missing)
  changes nothing** and logs; `[]` strips, because the directory said so.
- **The account is keyed by the provider's subject**, not the email:
  `DirectoryIdentity(provider, subject)` → user, created on first sight (no
  usable password, not staff). An existing account with the same email is
  linked once (`SMALLSTACK_DIRECTORY_LINK_BY_EMAIL`, default on) and the
  subject is pinned from then on, so a reissued mailbox can't take it over.
  `last_roles` and `last_seen_at` are kept on the identity for the review.
- **Local changes are refused** on every surface (`services.directory_refusal`
  inside `set_membership`: the pages hide the forms, REST/CLI/approvals return
  the reason, the MCP proposal tool refuses to file one; Django admin's user
  form refuses the group and its group pages open it read-only and won't
  delete it). A change made by code in a shell is recorded and shown as a
  finding. `SMALLSTACK_DIRECTORY_LOCAL_OVERRIDE = True` lifts it; the
  next sign-in sets membership back regardless.
- **`SMALLSTACK_DIRECTORY_ROLE_MAP = {"sent-value": "Declared.Role"}`**
  translates a provider whose values can't be the key (a Google group email).
- **Findings**: a directory-managed group changed locally (warning); superuser
  granted from a directory source (danger); role values no group carries
  (warning); declared groups still local while the directory is in use (info);
  accounts the directory hasn't vouched for in `SMALLSTACK_ACCESS_DORMANT_DAYS`
  that hold a live token (warning); directory accounts that keep a usable
  local password, a second way in the directory can't close (warning).
  `manage.py check` warns (`access.W001`) when `map_directory_role` names a
  group no declaration matches.
- **`manage.py access directory-manifest --provider entra --json`** emits what
  the directory administrator creates: for Entra the `appRoles` array (ids
  `uuid5(namespace, role)`, so a rerun updates rather than duplicates) and the
  group to create and assign to each role, named
  `SMALLSTACK_DIRECTORY_GROUP_PREFIX + group` (default `APP - <BRAND_NAME> - `).
  `--provider generic` is the plain list; add a provider with
  `@register_manifest_formatter("okta")`.

Never grant superuser from a directory; keep one local break-glass
administrator outside it.

## Don't

- Don't add a second way to say "may": no `is_admin` booleans on profiles, no
  role strings on models. Declare a permission, put it in a group.
- Don't declare a group the user/staff/admin tiers already cover, or one per
  page or action; one group per job, and only when staff is too coarse.
- Don't make an account superuser to give it one permission; give it the
  group that holds the permission.
- Don't grant permissions directly to an account when a group would do; the
  review flags it.
- Don't change `apps/smallstack/groups.py` downstream: declare your own group
  in your app's `groups.py`, or add members to the shipped ones.
- Don't write `AccessEvent` rows yourself; change the Django model and the
  signal records it.
- Don't set `user.groups` from a sign-in backend yourself, and don't match a
  directory user by email: call `apps.access.directory.sign_in` (subject-keyed,
  recorded, refuses nothing it shouldn't). See `directory-sso.md`.
