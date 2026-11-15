---
title: Access Control
description: Who may do what, every change to it, and the least-privilege review at /smallstack/access/
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
widened in the last 7 days; and the **least-privilege review**, a list of
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

Each group with who declared it (an app, in code, or an administrator by
hand), its members and permission counts, and its state. A group's page lists
members with who added them, permissions by app (ones added by hand marked),
and the group's changes. Groups declared in code are created after each
`migrate` and kept in step with the declaration; an administrator's additions
are kept and shown as drift.

SmallStack ships five: **Access reviewer**, **User manager**, **Log reader**,
**Approver** and **Token manager**. Add people to them here or in Django admin.

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

## From a script or an AI client

The same answers are available over the REST API (`/smallstack/api/access/`,
listed under *Access* in the API docs) and as MCP tools
(`access_explain_user`, `access_check_permission`, `access_findings`), and a
script can add or remove a membership with an auth-level token that holds the
change-user permission. An AI client cannot change membership directly: its
`access_request_membership` tool files an approval request, and the change is
made only when someone who could make it by hand approves it in the approvals
console, in their name. From a shell, `manage.py access explain|check|grant|
revoke|groups|findings` does the same, recorded like every other change.

## For developers

`docs/skills/access-control.md` covers declaring a group in your app
(`register_group`), adding a finding (`register_check`), attributing changes
made outside a request (`acting_as`), and how a single sign-on directory
plugs in.
