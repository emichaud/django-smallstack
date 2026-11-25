---
title: Access Control
description: Who may do what, every change to it, the least-privilege findings, periodic access reviews and the audit evidence pack at /smallstack/access/
---

# Access Control

SmallStack uses Django's own access model: the **staff** flag opens the
`/smallstack/` area, a **superuser** passes every check, and **groups** bundle
the **permissions** that pages, API routes and AI tools ask for. The Access
pages at **Admin → Access** (`/smallstack/access/`) let you see all of it,
change memberships, review it against least privilege, and export the result
when an auditor asks.

## The Overview

Counts of accounts, staff, superusers and groups; how many times access was
widened in the last 7 days; and the **least-privilege findings**, a list of
findings with a number, a sentence, and advice:

| Finding | Why it matters |
|---|---|
| Superusers | A superuser bypasses every permission check. Keep it for break-glass use. |
| Dormant privileged accounts | Staff or superusers with no sign-in for 90 days (`SMALLSTACK_ACCESS_DORMANT_DAYS`). |
| Permissions granted directly | Access outside any group can't be reviewed or removed as one thing. |
| Deactivated accounts with live API tokens | A deactivated account must not keep working through a token. |
| Dormant accounts | Accounts nobody uses. |
| Staff with no group | The staff flag opens the admin area; a group says what they do there. |
| Groups that differ from their declaration | A group an app ships in code has been changed by hand. |
| Groups with no members or no permissions | Clutter a reviewer has to read past. |
| Auth-level API tokens | Active auth-level tokens, and how many of them can manage accounts over the API (their owner is staff holding `accounts.change_user`). |

**Show N** opens the accounts or groups behind a finding. A project can add
findings of its own (see the skill below).

## A user

Open an account to see:

- its flags, when it joined and last signed in;
- **Check a permission**: type `app_label.codename` and get the answer the
  software itself gives (`user.has_perm`), with the reason: which group grants
  it, whether it's granted directly, whether the account is a superuser or
  deactivated;
- its **groups**, each with when it was added and by whom, and controls to
  add or remove (needs the `change_user` permission; to add someone to a group
  you must also hold every permission that group grants, unless you're a
  superuser);
- its **API tokens**, with a **Revoke tokens & sign out** button. A *User
  manager* (the `change_user` permission) or anyone holding `change_apitoken`
  sees it; only a superuser can use it on a superuser, and nobody on their own
  account. A *Token manager*, who can't open this page, revokes tokens from the
  Token Manager instead;
- **everything the account can do**, grouped by app, each permission marked
  `via group:Name`, `via direct` or `via superuser`;
- every access change involving the account.

## Groups

**Groups** lists every group: where it's defined (*here*, or the app that
declares it in code), whether its members come from your directory, and its
member and permission counts.

**Create a group** with **New group** at the top of the list (needs
`auth.add_group`): a dialog asks for its name, and you land on the new
group's page. On its page:

- **Permissions**: *Add permissions* opens a list grouped by app with a filter
  (type `blog post` to narrow to the blog's post permissions); tick several and
  add them at once. Only permissions you hold yourself are listed, so nobody
  hands a group more than they have. Tick rows in the list to remove several.
  Needs `auth.change_group`.
- **Members**: *Add people* works the same way, filtering by username, name or
  email. Tick members to remove several. Needs `accounts.change_user`, and to
  add someone you must hold every permission the group grants (a superuser
  holds them all).
- **Rename** or **Delete** the group (`auth.change_group`,
  `auth.delete_group`). Deleting takes what it granted from its members; their
  accounts stay.

A group **declared in code** (an app's `groups.py`, including the six
SmallStack ships: **Access reviewer**, **Access attester**, **User manager**,
**Log reader**, **Approver** and **Token manager**) is created after each
`migrate` and kept in step with its declaration. You can still add and remove
its members and permissions here; a permission changed by hand shows as
*drift* until the code says the same. It can't be renamed or deleted here,
because the next `migrate` would make it again.

A user's page has the same picker for the other direction: **Add to groups**
puts one account in several groups at once.

### Local or directory-managed

Every group is one of two kinds, shown on its page under **Membership**:

- **Local** (the default): it behaves exactly like a plain Django group. You
  add permissions and people here, and the app's code checks
  `user.has_perm("app.codename")`; the answer is yes if any of the person's
  groups grants it.
- **Directory-managed**: the group still grants its permissions the same way,
  but **who is in it** comes from your single sign-on directory (Entra, Okta,
  Google, an auth proxy), set at each sign-in. *Make directory-managed…* asks
  for the **role key** the directory sends for this group (for *Blog editors*
  it suggests `Blog.Editors`; no spaces) and whether members should be staff.
  From then on *Add people* and *Remove* are gone and every other surface
  refuses a local membership change with the reason. Its name and permissions
  stay yours to change.

Making a group directory-managed doesn't empty it: **current members keep it
until their next directory sign-in**, and then the directory decides. The page
lists their emails for the directory administrator, so they can be assigned
the role and stay in. **Make local** turns it back into a local group with the
members it has; both changes are recorded. A group declared in code takes its
role from `groups.py` and shows it read-only.

See [Single sign-on](/smallstack/help/smallstack/single-sign-on/) for setting up the
directory side, Entra step by step, and the other providers.

**Who can read these pages:** a staff account holding `accounts.view_user`,
the permission Django admin and Explorer ask to list accounts. The shipped
*Access reviewer* and *User manager* groups grant it; superusers always read.
Staff without it don't see Access in the sidebar or on the dashboard.

## Changes

Every change to access, from whatever surface made it: Django admin, these
pages, the User Manager, a shell, an import, a directory sync. Each row says
what changed, for whom, by whom, and from where (the page, with the request
id). Filter by account, group or permission, or to grants only, and export
the result.

The same changes go to the log at `/smallstack/logs/` (a grant is a WARNING)
and to the account's History page.

**Deactivating an account** (in the User Manager, Django admin or anywhere
else) revokes its API tokens and ends its sessions at once; both are recorded.

## Exports

- **Export access (CSV)**: one row per account × permission × source, every
  account included, the evidence for "who can do what".
- **Snapshot (JSON)**: accounts, groups and findings, dated.
- **Changes → Export (CSV)**: the change log.
- From a shell or a scheduled job: `manage.py access_report`, which exits
  non-zero when a finding needs attention; `--json` writes the snapshot.

## Access reviews

The findings above are continuous; an **access review** is the periodic
control an auditor asks for (SOC 2, PCI DSS, ISO 27001). On **Reviews**, an
*Access attester* opens a review for a period. Opening **freezes the roster**
of accounts holding access at that moment (*privileged*: superusers, staff and
holders of a permission that changes access or credentials; or *all* active
accounts). The attester then decides each account:

- **Confirm**: the access is right.
- **Flag**, with a note: someone needs to look.
- **Remove**: files an approval. Someone holding `change_user` approves it in
  the approvals console and the account is deactivated in their name (tokens
  revoked, sessions ended). Only the attester who filed it, or someone who
  could approve it, can withdraw it; the account being removed can't. If the
  approval is rejected, withdrawn or expires, the account stays listed under
  *Review decisions not yet acted on* until it is deactivated, and deciding
  *remove* again on an open review files a new approval.

Nobody confirms or removes their own row, and a superuser can open a review
but not decide or sign one. When every row is decided, the attester types
their name and **signs**: the review is then read-only evidence, with the
signer, time, address and request id. Nothing in a review changes access by
itself. Each review exports as CSV, JSON and a print view.

## The evidence pack

**Evidence** builds, for a period and a scope, the sheets an auditor asks for:
privileged roster, access matrix, access changes, joiners, leavers,
authentication, API credentials, findings and the signed reviews, each with
the controls it supports. Preview a sheet, then download it as CSV, the whole
pack as a ZIP (a cover page, one CSV per sheet and JSON), the JSON alone or a
print view. A period or scope that can't be used is refused with the reason
rather than replaced by another.

**Store this pack** (an attester or a superuser) keeps the pack on the server
with its SHA-256, so a copy handed to an auditor can be checked against what
the system produced; the download carries the digest in `X-Content-SHA256`.
The newest packs are kept for each reason (`SMALLSTACK_ACCESS_EVIDENCE_KEEP`,
24): packs stored on request never push out the one kept when a review was
signed or a quarter closed.

## On a schedule (optional)

By default reviews are opened by hand and nothing is scheduled. Set
`SMALLSTACK_ACCESS_REVIEW_CADENCE=quarterly` and a daily job opens the review
when a quarter closes, stores that quarter's pack, tells the attesters in the
app and by email, reminds them while it stays open, and escalates once it is
overdue. The dashboard then shows an **Access review** card. Signing stays a
person's act; it stores the attested pack and sends the
`access.review.signed` webhook event.

## From a script or an AI client

The same answers are available over the REST API (`/smallstack/api/access/`,
listed under *Access* in the API docs) and as MCP tools
(`access_explain_user`, `access_check_permission`, `access_findings`), and a
script can add or remove a membership with an auth-level token that holds the
change-user permission. An AI client cannot change membership directly: its
`access_request_membership` tool files an approval request, and the change is
made only when someone who could make it by hand approves it in the approvals
console, in their name. From a shell, `manage.py access explain|check|grant|
revoke|groups|findings` does the same, recorded like every other change, and
`access review|evidence|packs|cadence` opens and lists reviews and builds,
stores and lists evidence packs. Reviews and packs are readable over REST;
deciding and signing exist on the Reviews page only.

## Questions people ask

**Does a group have to exist in the app before the directory can fill it?**
Yes. The app never creates groups from what a directory sends: you decide what
a group *grants* (here or in code), the directory decides *who* is in it. A
role the directory sends that no group carries is ignored and listed under the
*unknown directory roles* finding.

**If I create *Blog editors* here, what does the directory administrator do?**
Make the group directory-managed with a role key (say `Blog.Editors`), then
ask them to create that role in the directory and assign the right people, or
a directory group of them, to it. The group page lists its current members'
emails to hand over. [Single sign-on](/smallstack/help/smallstack/single-sign-on/) has the
Entra steps.

**Someone new signs in and the directory says they hold `Blog.Editors`. Are
they in the group?** Yes, during that sign-in: the account is created if it's
their first, they're added to *Blog editors*, and they have its permissions
straight away. The change is recorded as made by `directory:entra`.

**The directory removes them later. When do they lose access?** At their
**next sign-in**. Until then they keep the group for as long as their session
lasts, because the app learns about membership only when someone signs in;
it doesn't ask the directory in between. If it has to be immediate, deactivate
the account here (that ends its sessions and revokes its API tokens) or block
sign-in in the directory and keep session lifetimes short.

**What if the directory sends no roles at all?** If the roles claim is
*missing*, nothing changes: that's a configuration problem, not "this person
holds nothing", and removing everyone who signs in that morning would be the
wrong answer. If it's present and *empty*, the person is removed from every
directory-managed group.

**Can I add someone to a directory-managed group by hand, just for a while?**
Not on the group itself: the next sign-in would undo it, so it's refused.
Grant the access through a separate local group instead, with the same
permissions. The sync never touches local groups, so one person can be in a
directory-managed *Blog editors* and a local *Temporary editors* at once, and
the reason is visible in the change log.

**How do administrators stay in control if the directory is down or wrong?**
Keep one or two **break-glass** accounts: local superusers who sign in with a
password (and MFA if you have it), not through the directory, with the
credentials in your vault, used rarely. The directory sync never grants or
removes superuser, and an account with no directory identity is never synced.
Everyday administrators should still come from the directory, so their rights
leave when they do; the *superusers* finding lists everyone who holds it.

**Does Django stop someone automatically if they lack a permission?** Only
where something checks. Django admin checks model permissions on its own;
everywhere else your code does, with `user.has_perm(...)`,
`@permission_required` or `PermissionRequiredMixin`. A view with no check
admits anyone who gets past its sign-in or staff check. SmallStack's CRUD pages
check model permissions only when the view sets `model_permissions = True`, and
Explorer only with `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS`. A misspelt
permission (`blog.chnage_post`) isn't an error; it's simply never held, so
everyone is refused. **Check a permission** on a user's page, or
`manage.py access check <user> <perm>`, tells you whether it exists.

**Can a script or AI client do what these pages do?** A script can, with an
auth-level API token: create, rename and delete groups, change their
permissions and members, and make them directory-managed
(`PATCH /smallstack/api/access/groups/{group}/` with `directory_role`), or
from a shell with `manage.py access group new|rename|rm|grant|revoke|role`.
An AI client can only *propose* a membership change, which a person approves.

## For developers

**Start from the three tiers every app already has:** a signed-in **user**
sees their own things, **staff** reach the management pages, and a
**superuser** (admin) passes every check and is kept for break-glass use.
Declare a group only where staff is too coarse, when two kinds of staff need
different rights. Name it for the job, give it only what that job needs, and
check the permission in code. Most small apps need few groups, or none.

`docs/skills/access-control.md` covers declaring a group in your app
(`register_group`), adding a finding (`register_check`), adding an evidence
sheet (`register_sheet`), attributing changes made outside a request
(`acting_as`), reviews and the cadence. `docs/skills/directory-sso.md` covers
directory-managed groups and the sign-in call.
