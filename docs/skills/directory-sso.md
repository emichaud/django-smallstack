# Skill: Directory SSO — groups whose membership comes from the identity provider

How to put an app behind Entra, Okta, Google or an auth proxy so that **IT
assigns people to groups in the directory and the app picks membership up at
sign-in**. Read before writing any sign-in backend, middleware or claims hook,
and before deciding what a directory should be allowed to grant. The access
model it builds on is `access-control.md`.

## The one rule

**The directory decides who. The app decides what.** A group's permissions are
set in the app (declared in `groups.py`, or on the Access pages); its members
are whoever the directory says, at each sign-in. Nobody manages a
directory-managed group's membership inside the app, and the app never asks
the directory for write access. A group without a role key is an ordinary
local Django group and the sync never touches it.

## Why one design fits every provider

Whatever the protocol, a sign-in hands the app two things: *who this is* (a
stable subject) and *a list of role strings*:

| Provider | Subject | Roles arrive as |
|---|---|---|
| Entra app roles (recommended) | `oid` | `roles` claim (v2 tokens; `…/claims/role` URI on v1) |
| Entra, behind App Service Easy Auth | `X-MS-CLIENT-PRINCIPAL-ID` | the same claims, base64-JSON in `X-MS-CLIENT-PRINCIPAL` |
| Okta | `sub` | `groups` claim (filtered to the app's groups) |
| Keycloak | `sub` | `realm_access.roles` / `resource_access.<client>.roles` |
| Auth0 | `sub` | a namespaced custom claim |
| Google Workspace | `sub` | **no groups claim**: group emails via the Directory API, mapped with `SMALLSTACK_DIRECTORY_ROLE_MAP` |
| Cloudflare Access / oauth2-proxy / Pomerium | a header | a header (`Cf-Access-Jwt-Assertion` claims, `X-Forwarded-Groups`) |

Everything from "list of strings" downward is identical, and lives in
`apps/access/directory.py`. The only provider-specific code is reading the
claim: ten to thirty lines, kept in the project that signs in that way, never
upstream.

## The two calls

```python
from apps.access.directory import sign_in

identity, result = sign_in(
    "entra",                 # the <provider> in directory:<provider>
    claims["oid"],           # the provider's stable subject — never the email
    claims.get("roles"),     # the list as sent; None when the claim is absent
    email=claims.get("preferred_username", ""),
    name=claims.get("name", ""),
)
request.user = identity.user
if result.unknown:
    ...                      # roles no group carries; logged once, shown as a finding
```

`sign_in` is `resolve_identity` (find or create the account by `(provider,
subject)`) followed by `sync_roles` (set the directory-managed groups to
exactly the roles sent), and then stamps the account's `last_login` (at most
every 15 minutes), so a directory user isn't "never signed in" and the
dormancy findings see the sign-in. A backend that calls the two halves itself
gets no stamp; prefer `sign_in`. Call it on every authenticated request if your proxy
re-sends claims, or once per session on the sign-in callback; it's idempotent
and cheap (one query per directory-managed group plus the user's groups).

What `sync_roles` guarantees:

- Directory-managed groups (declared with `directory_role`) are set to
  **exactly** the matching roles. Groups without a role are **never touched**,
  so a locally granted group survives.
- **`roles=None` changes nothing.** A missing claim is a misconfiguration (the
  app registration was edited, the token version changed), not "this person
  holds nothing"; stripping everyone who signs in that morning is the wrong
  answer. It logs a warning and stamps `last_seen_at`. **`[]` strips**: the
  directory said they hold no roles.
- `is_staff` is set when any resulting group was declared `staff=True`. It is
  never unset by the sync (a local administrator may have set it); use a
  finding, not the sync, to review staff.
- `is_superuser` is never touched. The `directory_superuser` finding goes red
  if a backend does it anyway.
- Every change is recorded from `directory:<provider>` through the same
  signals as any other access change.

### Marking a group directory-managed: code, page, REST, CLI

Four equivalent ways; each one records a change and gives the same result
(the sync, the refusals, the manifest and the findings don't care which):

| Where | How | Notes |
|---|---|---|
| Code | `register_group("Blog editors", permissions=[…], directory_role="Blog.Editors", staff=False)` in the app's `groups.py`, or `map_directory_role("Blog editors", "Blog.Editors")` for a group declared elsewhere | Applied at the next `migrate`; the page shows it read-only. A declaration wins over a page mapping. |
| Page | Group page → *Membership* → *Make directory-managed…* (role key, *Members are staff*); *Make local* undoes it | Needs `auth.change_group`. Not offered for a group declared in code. |
| REST | `PATCH /smallstack/api/access/groups/{group}/` with `{"directory_role": "Blog.Editors", "staff": false}`; `""` makes it local | Auth-level token; 400 for a bad or taken key. |
| CLI | `manage.py access group role "Blog editors" Blog.Editors [--staff] [--user ACTOR]`; `""` makes it local | Without `--user`, a local command. |

The page, REST and CLI all call `services.set_directory_role(group, role,
staff=, actor=, source=)`. It stores a `ManagedGroup` with `source="page"`
(a declared group's row is `source="code"`), refuses a group declared in code,
a key with spaces, and a key another group already carries, and records a
`directory_role_set` event (`detail`: from, to, staff, member count).
**Current members keep the group until their next directory sign-in**; *make
local* keeps the members it has. A page group's name and permissions stay
editable on the page while it's directory-managed; only membership is the
directory's.

### Declaring the groups

```python
# apps/<app>/groups.py
from apps.access.registry import map_directory_role, register_group

register_group("Service administrators", permissions=[...], directory_role="Service.Admin", staff=True)
register_group("Event planner", permissions=["events.plan_event"], directory_role="Events.Planner")

# SmallStack's shipped groups, from your own groups.py — never edit theirs:
map_directory_role("Access reviewer", "Access.Reviewer")
map_directory_role("Log reader", "Logs.Reader")
```

`directory_role` is the one name everywhere: the Entra app-role `value`, the
Okta group name, the key in your Cloudflare policy. Keep to
`[A-Za-z0-9._-]` and treat it as permanent (renaming is a migration in both
places; display names can change freely).

### Failing closed without creating accounts

Use `sign_in_or_refuse`: it returns the identity to sign in, or `None` to
refuse. A subject seen before is **synced first** — so someone IT removed from
every role (`[]`) loses their directory groups at once, instead of keeping them
behind a 403 — and then refused if no recognised role remains. A subject never
seen is refused before any account is created. A missing claim (`None`)
changes nothing and is refused. (`recognised_roles(roles)` answers the role
question alone, without a write.)

```python
# apps/<app>/middleware.py — behind an auth proxy (Cloudflare Access,
# oauth2-proxy, Pomerium) that sets these headers and strips them from
# client requests. Add after AuthenticationMiddleware.
from django.http import HttpResponseForbidden

from apps.access.directory import sign_in_or_refuse

PUBLIC = ("/health/", "/static/")


class DirectoryHeaderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        subject = request.headers.get("X-Forwarded-User")
        if not subject or request.path.startswith(PUBLIC):
            return self.get_response(request)
        raw = request.headers.get("X-Forwarded-Groups")
        roles = [r for r in raw.split(",") if r.strip()] if raw is not None else None  # absent ≠ empty
        identity = sign_in_or_refuse(
            "proxy", subject, roles,
            email=request.headers.get("X-Forwarded-Email", ""),
            name=request.headers.get("X-Forwarded-Name", ""),
        )
        if identity is None:
            return HttpResponseForbidden("No role for this application.")
        request.user = identity.user
        return self.get_response(request)
```

A refused person's API tokens keep working until revoked (the sign-in can't
reach them): the *accounts the directory hasn't seen, with live tokens* finding
is the safety net, and deactivating the account revokes them.

Trust these headers only from the proxy (bind the app to it, or check a
shared secret header): anyone who can reach the app directly could send them.

## Entra, step by step

1. **Declare** the groups with `directory_role` and deploy.
2. **Emit the manifest** on the server:
   `manage.py access directory-manifest --provider entra --json`. It lists the
   `appRoles` to PATCH onto the app registration (ids are `uuid5` of the role,
   so reruns update rather than duplicate) and, per role, the security group
   to create (`APP - <brand> - <group>`) and assign to it.
3. **An Entra administrator** runs that against the tenant (Graph:
   `Application.ReadWrite.OwnedBy`, `Group.Create`,
   `AppRoleAssignment.ReadWrite.All`). The deployed app holds none of these.
   Group-to-role assignment needs Entra ID P1. Only *direct* members of the
   assigned group get the role: nested groups aren't honoured, so use flat or
   dynamic groups.
4. **Read the claim.** Behind Easy Auth:

   ```python
   import base64, json

   def principal(request):
       raw = request.headers.get("X-MS-CLIENT-PRINCIPAL")
       if not raw:
           return None
       data = json.loads(base64.b64decode(raw))
       claims = {}
       for c in data.get("claims", []):
           claims.setdefault(c["typ"], []).append(c["val"])
       roles = claims.get("roles") or claims.get("http://schemas.microsoft.com/ws/2008/06/identity/claims/role")
       return {
           "subject": request.headers["X-MS-CLIENT-PRINCIPAL-ID"],
           "roles": roles,            # None when neither claim is present
           "email": (claims.get("preferred_username") or [""])[0],
           "name": (claims.get("name") or [""])[0],
       }
   ```

   Then `sign_in("entra", p["subject"], p["roles"], email=…, name=…)` in a
   middleware that sits after `AuthenticationMiddleware`, and fail closed:
   no recognised role → 403, unless the page is public.
5. **Switch the token off the groups claim** once the roles path is live
   (`groupMembershipClaims: None`): the groups claim lists every group the user
   is in, and above 200 Entra drops it entirely (the "overage"), which reads as
   "no groups" and locks everyone out.

## Okta / Keycloak / Auth0 (native OIDC)

Use `mozilla-django-oidc` or `django-allauth`; don't write the redirect and
code exchange yourself. In its claims hook (`OIDCAuthenticationBackend.
create_user` / `update_user`, or allauth's `pre_social_login` /
`populate_user`) call `sign_in(provider, claims["sub"], claims.get("groups"),
…)` and return `identity.user`. Filter the groups claim at the provider to the
app's own groups so the list stays short and the names stay stable.

## Google Workspace

Google's OIDC token has no groups claim. After sign-in, fetch the user's groups
with the Admin SDK Directory API (a service account with domain-wide
delegation, `admin.directory.group.readonly`) and pass the group emails as
roles, with `SMALLSTACK_DIRECTORY_ROLE_MAP = {"service-admins@example.com":
"Service.Admin"}`.

## The migration from "we already set groups ourselves"

1. Declare the existing groups with their `directory_role`, **keeping the
   Django group names** so every `has_perm` and mixin keeps working.
2. Dual-read: keep the old mapping (GUIDs, a settings list) as a fallback
   while the new roles are rolled out, so nobody is locked out between the
   directory change and the deploy. Replace `user.groups.set(...)` with
   `sign_in(...)`.
3. Stop granting `is_superuser` from the directory. Administrators get a group
   with explicit permissions; one local break-glass superuser (password in
   the vault) stays outside the directory. Replace `is_superuser` checks with
   named permissions app by app, last.
4. Remove the fallback and the settings lists; the Access pages now show the
   groups as directory-managed and refuse local edits.

## What the Access pages show

- A directory-managed group's page: *directory-managed* under Membership,
  the role, no *Add people* or remove controls, and the current members'
  emails to hand the directory administrator. Local membership changes are refused on
  REST, the CLI and approvals too, with the reason
  (`SMALLSTACK_DIRECTORY_LOCAL_OVERRIDE` lifts it).
- A user's page: each provider that has seen them, when, and the roles it
  sent; the *directory* badge on their directory-managed groups; `added by
  directory:entra` on the membership row.
- Findings: `directory_local_changes`, `directory_superuser`,
  `directory_unknown_roles`, `directory_undeclared_groups`,
  `directory_unseen_with_tokens`.

## Questions

The help page `apps/smallstack/docs/single-sign-on.md` (Help → Single
Sign-On) is the operator's version of this skill, with the Entra steps; the
*Questions people ask* section of `apps/smallstack/docs/access-control.md`
answers the common ones (does a group have to exist first, when does a
removal take effect, how break-glass accounts work, what Django checks on its
own). Keep the three in step when the behaviour changes.

## Limits

- **Changes land at the next sign-in.** Removing someone from an Entra group
  takes effect when their session renews; check the proxy's cookie and token
  lifetime. Disabling the user in the directory blocks sign-in at once.
- **Nobody is deprovisioned.** An account whose owner left can't sign in but
  keeps its row and its API tokens until revoked; `directory_unseen_with_tokens`
  is the safety net. SCIM (the directory pushing users and groups) would fix
  both and is a later, separate feature.
- **Accounts appear on first sign-in**, not before.

## Don't

- Don't match a directory user by email. The subject is stable; a mailbox
  can be renamed or reissued to someone else.
- Don't call `user.groups.set(...)` or `add(...)` from a sign-in backend; call
  `sign_in` so the rules above hold and the change is recorded.
- Don't treat a missing roles claim as "no roles". `sync_roles` won't; don't
  convert `None` to `[]` before passing it.
- Don't grant `is_superuser` from a claim, ever.
- Don't give the deployed app directory write permissions to create its own
  roles and groups. That's one script run by a directory administrator.
