---
title: Single Sign-On
description: Groups whose members come from Entra, Okta, Google or an auth proxy — setting one up on the Access pages, Entra step by step, the other providers, break-glass accounts and the limits
---

# Single Sign-On and Directory-Managed Groups

With single sign-on, people sign in through your organisation's directory
(Microsoft Entra ID, Okta, Google Workspace, an auth proxy such as Cloudflare
Access) instead of a password kept here. SmallStack can also take **group
membership** from the directory, so IT adds and removes people in one place.

The rule behind all of it:

> **The app decides what a group grants. The directory decides who is in it.**

The app never creates groups from what a directory sends, and never asks the
directory for write access.

## How it works

1. A group exists in the app, with its permissions. It's either made on the
   Access pages or declared in code.
2. The group is marked **directory-managed** with a **role key**: the value
   the directory will send for it, such as `Blog.Editors`.
3. In the directory, people (or a directory group of them) are assigned that
   role.
4. **At each sign-in** the directory sends the person's role keys. SmallStack
   sets their directory-managed groups to exactly those roles: it adds the ones
   that match and removes the rest. Local groups (without a role key) are never
   touched. Every change is recorded as made by `directory:<provider>`.

Who is in a group therefore changes **when people sign in**, not the moment
the directory changes. See [Limits](#limits).

## Walkthrough: a *Blog editors* group

**In the app** (Admin → Access → Groups):

1. Choose **New group** and name it **Blog editors**.
2. On its page, **Add permissions**: filter by `blog`, tick what editors need,
   add them.
3. Optionally **Add people** now, while you set the directory up. They're a
   starting list: once the group is directory-managed, each keeps it only if
   the directory assigns them the role.
4. Under **Membership**, choose **Make directory-managed…**. Accept the
   suggested role key `Blog.Editors` (or type the one your directory
   administrator wants; letters, digits, `.`, `_`, `-`, no spaces), tick
   *Members are staff* if editors need the admin area, and save.

The page now shows *directory-managed* and lists the current members' emails
for the directory administrator. Adding and removing members here is off.

**In the directory**, the administrator creates the role `Blog.Editors` for
this app and assigns the editors to it. The Entra version is below.

**From then on:** someone who signs in holding `Blog.Editors` is added to
*Blog editors* and has its permissions straight away. Someone who no longer
holds it is removed at their next sign-in. To stop managing it from the
directory, choose **Make local**: the group keeps its current members and you
manage them here again. Both changes are recorded.

The same steps from a script: `PATCH /smallstack/api/access/groups/Blog
editors/` with `{"directory_role": "Blog.Editors", "staff": false}` (an
auth-level token), or `manage.py access group role "Blog editors"
Blog.Editors`. In code: `register_group("Blog editors", permissions=[…],
directory_role="Blog.Editors")` in the app's `groups.py`. A group declared in
code shows its role read-only on the page.

## Microsoft Entra ID

What SmallStack expects, and what Microsoft's platform does.

**What to use: app roles, not the groups claim.** Define an **app role** on
the app registration for each directory-managed group, with **Value** set to
the role key (`Blog.Editors`). Assign users, or Entra security groups, to the
role under *Enterprise applications → the app → Users and groups*. Entra then
puts the values in the token's **`roles` claim**. Avoid the `groups` claim:
- it carries group **object IDs** (GUIDs), not names;
- above **200 groups** in a JWT, Entra leaves the claim out altogether (the
  "overage"), which looks like "no groups" and would lock people out.

**Generate the app roles from the app:**
`manage.py access directory-manifest --provider entra --json` lists an
`appRoles` entry for every directory-managed group (from code and from the
Access pages) and a suggested security-group name for each
(`APP - <your brand> - <group>`, set with `SMALLSTACK_DIRECTORY_GROUP_PREFIX`).
Role ids are derived from the role key, so running it again updates the roles
rather than duplicating them. A directory administrator applies it; the
deployed app holds no permission to change your tenant.

**Things that trip people up in Entra:**
- **Assigning a *group* to an app role needs Entra ID P1 or P2.** On the free
  tier, assign users one by one.
- **Nested groups aren't honoured for app-role assignment.** Only direct
  members of the assigned group get the role, so use flat groups or dynamic
  groups.
- The person is identified by the **`oid`** claim (their object id, stable
  within your tenant), never by email: a mailbox can be renamed or reissued.
  On first sign-in SmallStack links to an existing account with the same email
  (so people who had accounts before single sign-on keep their history), then
  remembers the `oid`. `SMALLSTACK_DIRECTORY_LINK_BY_EMAIL=False` turns that
  off.
- v1 tokens carry roles under the long claim name
  `http://schemas.microsoft.com/ws/2008/06/identity/claims/role` instead of
  `roles`; the sign-in code reads both.
- **Behind App Service Authentication ("Easy Auth")** the claims arrive in the
  `X-MS-CLIENT-PRINCIPAL` header (base64 JSON) and the `oid` in
  `X-MS-CLIENT-PRINCIPAL-ID`. `docs/skills/directory-sso.md` has the ten lines
  that read them.
- Removing a role takes effect at the person's next sign-in, and a session can
  outlive the change. To cut access at once, disable the user in Entra *and*
  deactivate the account here.

**What SmallStack has and hasn't verified.** The sign-in handling (roles to
groups, a missing claim changing nothing, an empty claim removing, never
granting superuser, the `oid` link, recording) is covered by SmallStack's
tests with Entra-shaped claims. Connecting to a real tenant (the app
registration, Easy Auth or an OIDC library, conditional access) is your
deployment's, and isn't exercised by those tests: try it with one test user
and one role first.

## Other providers

The app side is the same for every provider: a stable subject and a list of
role keys. Only where the list comes from differs.

| Provider | Who | Roles come from | Notes |
|---|---|---|---|
| **Okta** | `sub` | the `groups` claim | Add a groups claim to the app's authorization server, **filtered to the app's own groups** so the list stays short. The role key is the Okta group name; if you can't rename groups to match, map them with `SMALLSTACK_DIRECTORY_ROLE_MAP`. |
| **Keycloak** | `sub` | `realm_access.roles` or `resource_access.<client>.roles` | Client roles keep the app's roles apart from the realm's. |
| **Auth0** | `sub` | a namespaced custom claim, added by an Action | Auth0 only puts custom claims in tokens under a namespace you choose. |
| **Google Workspace** | `sub` | **no groups claim** | Google's sign-in token carries no group membership. The app must look groups up with the Admin SDK Directory API (a service account with domain-wide delegation and read-only group scope) and pass the group **emails**; map each to a role key with `SMALLSTACK_DIRECTORY_ROLE_MAP = {"blog-editors@example.com": "Blog.Editors"}`. This is the most work of the providers. |
| **Cloudflare Access, oauth2-proxy, Pomerium** | a header | a header | The proxy signs people in and forwards who they are and their groups; your middleware reads the headers and calls the same sign-in function. |

For Okta, Keycloak and Auth0, use an OIDC library (`mozilla-django-oidc` or
`django-allauth`) rather than writing the sign-in flow yourself, and call
SmallStack's sign-in from its claims hook. `docs/skills/directory-sso.md` has
the code for each.

## Break-glass accounts

Keep one or two **local superusers** that sign in with a password (and MFA if
you have it), not through the directory, so a directory outage or a bad role
assignment can't lock everyone out. Keep the credentials in your vault and
use them rarely.

- The sign-in sync **never grants or removes superuser**, and an account that
  has never signed in through the directory is never synced.
- Give everyday administrators a directory-managed group with the permissions
  they need (for example *User manager*, marked staff), so their rights leave
  with them. Keep superuser for break-glass.
- The *superusers* finding lists everyone holding it; the *directory
  superuser* finding flags a directory account that is also a superuser; the
  Authentication evidence sheet flags a directory user who also has a usable
  password, which would let them bypass single sign-on.

## Limits

- **Membership changes at sign-in, not in between.** SmallStack doesn't ask
  the directory for changes on its own (there's no SCIM or polling). Someone
  removed from a role keeps the group until their session ends and they sign
  in again.
- **Accounts appear on first sign-in.** You can't pick someone for a local
  group before they've signed in once (or been created in the User Manager).
- **Leavers keep their account row and API tokens** until deactivated or
  revoked; they can't sign in once the directory blocks them. The *directory
  unseen with tokens* finding and the Leavers evidence sheet catch them.
- `SMALLSTACK_DIRECTORY_LOCAL_OVERRIDE=True` allows local membership edits on
  directory-managed groups for a repair, but the next sign-in undoes them.

More answers are under *Questions people ask* on the
[Access Control](/smallstack/help/smallstack/access-control/#questions-people-ask)
page.
