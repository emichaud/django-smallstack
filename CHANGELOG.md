# Changelog

All notable changes to SmallStack are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Breaking-change migration recipes live in [`UPGRADING.md`](UPGRADING.md).

## [Unreleased]

## [0.32.2] - 2026-11-15

### Fixed
- **A wide table on a help page ran under the "On this page" sidebar.** A markdown table is as wide as its widest unbreakable cell (a setting name in `code`), and the article is 800px, with nothing to scroll a wider table: on the settings page three tables painted over the TOC, their row tints showing through its text. Both markdown renderers (the help app's, and `apps.smallstack.transforms.render_markdown` behind runbook documents, slides and steps, blog posts and newsletters, and the markdown dashboard card) now wrap every table in `<div class="md-table">`, which scrolls sideways inside its column (`components.css`, loaded by every themed page and the public blog); the table itself is unchanged, and a `<table>` typed as raw HTML into untrusted markdown stays escaped text. A runbook's `.runbook-content table` had the same overflow. A downstream page that renders either output under its own stylesheet should give `.md-table` `overflow-x: auto`.

## [0.32.1] - 2026-11-15

### Added
- **`wrap_fields` on a CRUDView:** `wrap_fields = ["title"]` makes those table columns wrap onto more lines instead of clipping with an ellipsis, while the rest stay on one line; the table's "Wrap text" tool still wraps every column. Pair it with a `column_widths` entry so the column has room to wrap in.

### Fixed
- **Every table cell showed a tooltip on hover,** clipped or not, because each carried its full text as `title`. The script now keeps the title only while the cell is actually clipped (and restores it when a resize clips it again); a wrapped column, whose whole text is visible, gets none. Without the script every cell keeps its title as before.
- **The sidebar starts where you left it.** Every sidebar link is a full page load, so the sidebar scrolled back to the top each time and the links low in the list (the Admin section) had to be scrolled to again. Its scroll offset is kept per tab (`sessionStorage`) and put back on the next page; in a new tab, the active link is brought into view by scrolling the sidebar alone, not the page.

## [0.32.0] - 2026-11-15

### Upgrading from 0.31.0
- **Explorer now asks a ModelAdmin's per-object `has_change_permission(request, obj)` and `has_delete_permission(request, obj)`** (as Django admin does) for each row's edit and delete, on the pages, bulk actions, REST and MCP, whatever `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` says. A downstream ModelAdmin that overrides either one with a rule on `obj`, or that calls `super()` (Django's default checks the model permission), now has that rule enforced in Explorer, where staff could edit or delete those rows before. See `UPGRADING.md` (G3-2, E-dec 5).
- **New app `apps.access` and middleware.** Add `"apps.access"` to `INSTALLED_APPS` (after `apps.usermanager`) and `"apps.access.context.ActorMiddleware"` to `MIDDLEWARE` right after `AuthenticationMiddleware`, mount `path("access/", include("apps.access.urls"))` in `apps/smallstack/site_urls.py` if your copy diverged, then `make migrate`: it creates the `access_accessevent` and `access_managedgroup` tables and SmallStack's five shipped groups. New settings `SMALLSTACK_ACCESS_DORMANT_DAYS` (90) and `SMALLSTACK_ACCESS_GROUPS_SYNC` (on). See `UPGRADING.md`.

### Added
- **Access control (`apps/access`, Admin → Access).** Django's groups and permissions stay the one model; this adds what they lack. **Groups declared in code:** `register_group()` in an app's `groups.py` ships a group with its permissions, created after each `migrate` and kept in step (a permission the code drops is removed, one an administrator added is kept and shown as drift). SmallStack ships Access reviewer, User manager, Log reader, Approver and Token manager. **Every change to access is recorded** from model signals, whichever surface made it (Django admin, the Access pages, the User Manager, a shell, a sync): group membership, direct and group permissions, the staff / superuser / active flags, accounts and groups created or deleted. Each goes to an `AccessEvent` row (kind, actor, subject, source, request id; names kept as text so it outlives a deleted user), to the log under `apps.access.record` (a grant at WARNING, so it reaches `/smallstack/logs/`), and to the account's History when a person made it. **Deactivating an account revokes its API tokens and ends its sessions.** **The Access pages:** an overview with least-privilege findings (superusers, dormant privileged accounts, direct permissions, deactivated accounts with live tokens, dormant accounts, staff with no group, group drift, empty groups, auth-level tokens) and drill-downs; a user page with everything the account can do and why (`via group:X` / `direct` / `superuser`), a **Check a permission** box answering as `has_perm` does with the reason, membership controls and token revocation; group pages with members, who added them, and drift; a filterable, exportable change log; **Export access (CSV)** (account × permission × source) and a dated **JSON snapshot**. `register_check()` adds a finding from any app; `acting_as(actor, source)` attributes changes made outside a request (a directory sync). `manage.py access_report [--rows|--json]` prints the findings and exits 1 on a warning, 2 on a danger, for a scheduled run. New skill `docs/skills/access-control.md` and help page.

- **The Access user page is compact:** one strip for the account (flags, facts, actions), the permission check beside it, groups and tokens side by side, and every long list in a scrolling frame. The permission list has a filter box (app, codename, label or group) and sticky app headings; the change log opens in full with one click.
- **Access has an API, MCP tools and a CLI, all on one service.** Every surface that changes membership (the Access pages, REST, an approved MCP request, the shell) calls `services.set_membership()`, which checks `accounts.change_user`, refuses nothing silently and records the change with the surface as its source (`web:/…`, `rest`, `mcp:approval:<id>`, `cli`). **REST** at `/smallstack/api/access/` (in the OpenAPI schema under *Access*): accounts with groups and counts, one account with every permission and its sources, `…/check/?perm=` answering as `has_perm` does with the reasons, groups with drift, the findings, the change log; `PUT`/`DELETE …/users/{user}/groups/{group}/` adds or removes membership, for an auth-level token holding `accounts.change_user`. **MCP:** `access_explain_user`, `access_check_permission`, `access_findings` (staff tier) and `access_request_membership`, which **does not change anything itself**: it files an `access.membership` approval that a person holding `accounts.change_user` decides in the approvals console (a card shows the change, the reason and the agent that asked); approving makes the change in the approver's name with the request's id in the record, rejecting changes nothing, and the agent learns the outcome by polling `get_approval`. New setting `SMALLSTACK_ACCESS_MCP_WRITES` (on) removes that tool when off. **CLI:** `manage.py access explain|check|grant|revoke|groups|findings` (`sc access …`), with `--user` naming the person a change is attributed to and `check` exiting 1 when the permission is not held.
- **An Access tab on the User Manager's edit page:** groups (with when and by whom), permissions held, direct grants, live tokens and the account's recent access changes, with a link to the full Access page. The Activity user page links there too.

### Fixed
- **An API token can no longer be moved to another account.** In Explorer and Django admin a token's `user` was editable, so a staff account could mint a token, set its owner to a superuser and keep the key, which then authenticated as that superuser (with `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` on, a *Token manager* still could). The owner is now chosen when the token is made and read-only afterwards on both forms.
- **Explorer always checks Django model permissions on the models that hold access itself:** accounts, groups, permissions, API tokens, the change history (`LogEntry`) and the Access app's events and managed groups, whatever `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` or a ModelAdmin's `explorer_model_permissions` says. With the setting off (the default) any staff account could edit or delete accounts there (deactivate the superuser, make members staff) and reassign tokens. The list is `ALWAYS_CHECKED_MODELS` in `apps/smallstack/model_permissions.py`.
- **Explorer no longer deletes rows its ModelAdmin forbids deleting.** A read-only Explorer model (one whose ModelAdmin refuses add/change) still offered bulk delete, and the bulk route deleted, so any staff account could erase `AccessEvent` and `LogEntry` rows. Read-only models now get no bulk actions; a CRUDView's bulk delete/update also needs `Action.DELETE`/`Action.UPDATE` in its `actions`; and Explorer asks the ModelAdmin's own `has_view/add/change/delete_permission` overrides on every surface, as Django admin does.
- **Explorer's example pages and widgets follow model permissions.** `/smallstack/explorer/examples/model/…` answered 200 with every row (usernames and emails, token owners, change messages) to a staff account the model's own Explorer list refuses; it now answers 403. The example group and app pages, and the Explorer index's widgets view, leave out models the viewer may not view, as the index already did. `get_group_context()` / `get_app_context()` / `get_dashboard_widgets()` / `get_widget_contexts()` take an optional `user` to filter the same way, and the `/smallstack/` dashboard passes it (so a staff account without `view_user` no longer sees the Users widget).
- **Search honours a CRUDView's `model_permissions`.** A staff account the view's list page refuses (no `view` permission) still got its rows from the topbar search, `/search/`, the indexed-sources preview, the `search_*` MCP tools and `sc search --user`. Those now leave the view's hits out for a user without `view`, staff included; trusted internal calls (`user=None`) are unchanged.
- **Datasets over accounts and API tokens need the model's view permission.** `smallstack_users` and `smallstack_api_tokens` (34 accounts with their flags, 50 tokens with owners and levels in the report) were readable by any staff account on the browse page, `/smallstack/datasets/<key>/`, MCP and in metrics and dashboards, after Explorer had refused those models. A dataset over a model that checks Django model permissions (the access models always; otherwise when its CRUDView sets `model_permissions`) now needs that model's `view` on every dataset surface; REST answers 404 without it.
- **A REST delete refused because it would cascade into rows the caller can't delete answered with Django's HTML 403 page.** It now returns the JSON error envelope every other API refusal uses (`{"errors": {"__all__": [...]}}`), as does a `check_object_permission` refusal on the detail route.
- **`sc --user` refuses a deactivated account.** With model permissions off it acted as an inactive staff account (a delete went through and its audit entry carried that name); every other surface already refused one.
- **More pages fit a 320px phone.** The page body (`.main-content`) took its widest child's one-line width as its minimum, so a wide table in its own scroller or a row of tabs pushed the whole page sideways: the Access users, change-log and group pages (334px), the User Manager's edit page (349px, its tabs now tighten and wrap) and `/smallstack/status/public/` (343px) now measure 320. The public status page's staff-only "← Status overview" link wraps below the brand instead of widening the page to 449px at 320–390px.
- **`docs/skills/django-apps.md` no longer prescribes django-tables2** (removed in 0.12.0: `tables.py`, `apps.smallstack.tables`, `table_class` and `{% load django_tables2 %}` all raised ImportErrors for an agent following it). It now builds the list with `list_fields` / `link_field` and the generic CRUD templates, and points at `crud-views.md`; its title-bar recipe uses `.page-header-bleed` instead of an inline `color-mix()`. Same stale rows fixed in `components.md` and `from-zero-to-running.md`. AGENTS.md's strict-typing list now matches `pyproject.toml`.
- **The status area has one set of sections** (Overview · Site timeline · SLA · Public page) in every page header, instead of a different pair of buttons on each page. **Public page** is a new staff section at `/smallstack/status/public/`: whether the page is published, its addresses (board, maintenance, calendar, JSON), every monitor with its public flag and what visitors see it as, and the branding the page carries with the `BRAND_*` settings that drive it. The overview no longer links straight out to the public page; it opens from the section.
- **The public status page shows the brand lockup** (the stock SmallStack mark drawn in the palette's colours, or a project's `BRAND_LOGO` / `BRAND_LOGO_DARK` swapped with the visitor's theme), the same as the sign-in page, instead of the square icon beside plain text. A project that has set those two settings gets its logo there with no other change.
- **The status pages fit a phone:** a long monitor diagnostic shortens with an ellipsis (full text on hover) and rows wrap instead of pushing the overview to 1484px; the hour spark and the uptime timelines no longer size the page; the SLA page's grids stack and its tables scroll inside their cards.
- **Status tables have preset column widths:** the SLA page's daily summaries (fixed, right-aligned numeric columns) and maintenance windows, the heartbeat log (time, status, response fixed; the note takes the rest), and the Monitored endpoints and Site monitors lists.
- **Activity's Resources table has preset, even column widths:** the numbers take fixed columns, the URL pattern takes the rest, and the table scrolls before the pattern column collapses. The Last column shows a short relative time (`9h ago`, with the exact time on hover) instead of "9 hours, 24 minutes ago". The `ago` template filter is new in `theme_tags` for any table that needs the same.
- **The User Manager's Top Pages cut long paths off with no way to see the rest.** Each path now shows in full on hover and links to the requests behind the number.
- **Security: an `access.membership` approval could be forged.** Any signed-in account (no staff flag, any API token) could file the kind through the generic `POST /smallstack/api/approvals/requests/create/` or the MCP `request_approval` tool with itself as the target and a card naming someone else; approving added the *caller* to the group, and the `SMALLSTACK_ACCESS_MCP_WRITES` switch didn't close it. Approval kinds now take `remote_filing=False` ("only my own code files this"), which those two routes refuse with 403 / `not_permitted`; `access.membership` sets it, so only `access_request_membership` files it. The card now shows the account the approval will change (the request's target) and the group's live permission count, and the callback refuses a request whose context names a different account than its target.
- **Security: holding `accounts.change_user` let a User manager grant any group,** including one carrying every permission, and including to themselves. `services.set_membership()`, which every surface calls (the Access pages, REST, an approved MCP request, the CLI), now refuses to **add** a member to a group that grants any permission the actor doesn't hold, naming the missing ones; superusers may add to any group, and removal is unchanged. An approval applies the approver's limits (a refused change shows as the request's `callback_error`). The CLI's `access grant|revoke --user` now also requires the named actor to be staff, as the other surfaces already did.
- **Security: the User Manager's writes checked only the staff flag,** so any staff account (an *Access reviewer*, an *Approver*, staff with no permissions at all) could make a member staff, deactivate anyone (ending their tokens and sessions) or create and delete accounts. `/smallstack/manage/users/` now sets `model_permissions`: creating needs `accounts.add_user`, editing (fields, the staff and active flags, a reset link, an unlock) needs `accounts.change_user`, deleting needs `accounts.delete_user`; superusers hold all three. Only a superuser may change a superuser's account. Reading stays open to staff: without `change_user` the edit page is read-only, and buttons a user can't use are hidden. See `UPGRADING.md`.
- **Security: in Django admin, anyone holding `accounts.change_user` could make themselves a superuser** (or give themselves any group or permission) from their own user form. `Superuser status`, `Groups` and `User permissions` are now read-only there for everyone but a superuser. The `User`, `AccessEvent` and `ManagedGroup` admins also set `explorer_model_permissions = True`, so Explorer checks Django model permissions on them whatever `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` says.
- **The first `migrate` left declared groups without most of their permissions** (on a fresh install, Approver had 0 of 2, User manager 3 of 5), because the sync ran before later apps' permissions existed, and the names it couldn't find were dropped from the stored declaration, so drift and the review said all was well. The sync now creates every app's content types and permissions first, and a declared permission that doesn't exist is kept in the declaration, so it shows as *missing* drift on the group and in the review. A project that already ran a second `migrate` is unaffected.
- **Access: three small holes in the pages and API.** A user or group id written with a non-ASCII digit (`²`) on REST, or a non-numeric one posted to the membership forms, was a 500; both are now 404. The group-members form followed any `next=` (an open redirect, and a 500 for `javascript:` after the change had been saved); it now accepts only a same-site path and settles it before changing anything. The CSV exports (`access.csv`, `events.csv`) now prefix `'` to a cell starting with `= + - @`, a tab or a return, so a username like `+1+x` or a group named `=HYPERLINK(…)` can't run as a formula in a spreadsheet.
- **Access: changes the record missed.** A deleted account or group is now recorded with its name in the event's account / group column, so the change log's filter, search and CSV find "when was X removed". Granting from the permission's side (`perm.user_set.add(user)`, `perm.group_set.add(group)`), renaming a group (a new `group_renamed` event, migration `access.0002`) and the members a group loses when it is deleted are now recorded too. An audit row that fails to write is rolled back on its own savepoint instead of breaking the caller's transaction.
- **The Access review overstated two things.** *Auth-level API tokens* said every such token "can manage accounts over the API"; it now counts the ones that can (the owner is active staff holding `accounts.change_user`) and marks them in the list. The dormancy all-clears said "every account has signed in within 90 days" while accounts had never signed in; they now say no account has gone that long without signing in and count the ones that never have.
- **The MCP `request_approval` tool told agents to poll `get_approval` until `terminal` is true,** a field `get_approval` doesn't return, so an agent following it polled until its own cap. It now says to poll until `status` is no longer `pending` (the approvals skill said the same and is corrected too).
- **Security: any staff account could mint an API token owned by someone else, a superuser included,** at `/smallstack/tokens/create/` and read its key on the reveal page (the key then worked on REST and MCP as that account, which also undid the token-owner lock above). A token's owner may now be someone other than the minter only for a superuser, or for active staff holding `smallstack.add_apitoken` (the *Token manager* group), and then only an active non-superuser holding no permission the minter lacks (the subset rule membership uses). The picker lists only those accounts, the form re-checks the choice server-side, and only a superuser may choose the `auth` level.
- **Security: `/api/auth/users/*` and `/api/auth/register/` checked only that the token was auth-level,** so a non-staff member holding one could deactivate a superuser and make herself staff, and the changes were recorded with no actor. The token's owner must now be active staff and hold `accounts.add_user` (register) or `accounts.change_user` (update, the staff and active flags, deactivate, password); only a superuser's token may change a superuser's account. A token's `access_level`, like its owner, is now read-only after it is made in Explorer and Django admin, so a *Token manager* can't raise their own token to `auth`. Access changes made in a request authenticated by an API token are attributed to the token's owner (source `rest:<path>`); `ActorMiddleware` now reads `request.user` when the change is made.
- **An approval read "approved" when nothing changed.** A User manager approving an `access.membership` request for a group granting permissions they lack got `status: approved`, membership unchanged, and a full Python traceback with server paths in `callback_error`, on the request page and in MCP `get_approval`, while agents are told to poll on `status`. Approval kinds take a new `check_approve(actor, req)` hook asked before the decision is recorded; a reason refuses the approval (`ApprovalRefused`, 403 / `not_eligible`, a message on the console) and the request stays pending. `access.membership` uses it for the approver's permissions, a vanished user or group, and a mismatched context. `callback_error` now stores one line (`ExcType: message`); the traceback goes only to the log, and migration `smallstack_approvals/0002` shortens existing rows to their last line.
- **Security: the invite page let any staff account create an active staff account.** `/smallstack/accounts/invite/` checked only the staff flag, so a staff account holding no permissions could post `is_staff=on` and get a new active staff account whose set-password link went to an address it chose. Inviting now needs `accounts.add_user`, the same as the User Manager's *Add User* page; the *Grant staff access* box is offered only with `accounts.change_user` as well (a posted `is_staff` is ignored without it), and the *Invite User* button is hidden from staff who can't use it. An invite never creates a superuser (G2-1).
- **Security: any staff account could revoke anyone's API token, the superuser's included, and nothing recorded it.** `/smallstack/tokens/<pk>/revoke/` asked only for the staff flag. Revoking your own token is unchanged; revoking another account's now needs `smallstack.change_apitoken` (the *Token manager* group), and only a superuser revokes a superuser's token, on the Token Manager, the Access page's *revoke all access*, Django admin's *Revoke selected tokens* action (which also now needs the change permission) and the active flag in Explorer and Django admin. Revoke buttons show only where they would work. Every revoke (those surfaces, REST logout, OAuth `/revoke`, `sc token revoke`, deactivation) is now recorded once as a `token_revoked` access event with its actor (G2-2).
- **Security: a User manager could take over any account short of a superuser.** Holding `accounts.change_user`, they could set the password of an account holding every permission (`POST /api/auth/users/<id>/password/`), or point its email at their own address and send it a reset link, then sign in as it. Changing another account's password, email or username, or sending it a password-reset or set-password link, now also needs the actor to hold **every permission the account holds** (the subset rule group membership and minting use; an inactive account counts with what its groups would give back), on the User Manager (edit and *Send link*), `/api/auth/users/<id>/password/` and `PATCH /api/auth/users/<id>/` (`email`), Django admin (the password form; *Username* and *Email address* read-only) and Explorer's user form. A superuser's account stays superuser-only and your own is unaffected. Refusals give the reason and the missing permissions; the locked fields say why on the page. `apps.access.services.sign_in_refusal(actor, target)` is the rule (G2-3).
- **The User Manager's create page let an `add_user` holder make a new staff account,** which the invite page (G2-1) already refused. Ticking *Staff* on `/smallstack/manage/users/new/` (and on Explorer's user create form) now needs `accounts.change_user` too; without it the box isn't offered and a posted `is_staff` is ignored. The rule lives in `apps.accounts.forms.AccountFormRulesMixin`, with the G2-3 username/email lock (D-1).
- **`sc new` / `sc set` now build the form with `--user`** (through `form_bridge.build_form`, as REST and MCP do), so a form that scopes its choices or applies account rules per user sees who is acting. Without it the account forms above failed closed for everyone on the CLI, a superuser included.
- **Security: the activity log kept password-reset and invite links, token included, for every staff account to read.** `RequestLog.path` stored `/accounts/reset/<uidb64>/<token>/` verbatim, so a staff account with no permissions could open `/smallstack/activity/requests/`, replay a link someone had opened but not finished, and set that account's password (a superuser's included). The middleware now replaces a one-time token with `***` before the row is written, keeping the route shape (`/smallstack/accounts/reset/MQ/***/`): any path segment captured by a URL parameter named `token` (reset, invite, newsletter confirm and unsubscribe), plus those shapes by pattern for paths that matched no route. Log capture gets the same treatment: `LogRecord` messages, tracebacks and `extra`, and the JSON and text formatters, redact token paths and credential query parameters (`?token=`, `code=`, `secret=` …), as does an `AccessEvent`'s `web:` source. Migrations `activity.0005` and `telemetry.0002` redact rows stored before the upgrade. Helpers in `apps/smallstack/redaction.py`. See `UPGRADING.md`.
- **No shipped group could use the Access user page's *Revoke tokens & sign out*:** it needed `smallstack.change_apitoken`, and the page needs `accounts.view_user`, which only User manager holds, and User manager lacked the token permission. `accounts.change_user` now opens it too, with deactivation's rules (a User manager could deactivate the account, which revokes the same tokens and ends the same sessions): only a superuser acts on a superuser, and nobody acts on their own account, on either permission. The button and the POST ask one function, `apps.access.services.revoke_all_refusal`, so the button shows only where the POST succeeds, and every revoke is still a `token_revoked` event (E-dec 1).
- **Security: the production access log printed password-reset and invite links, token included.** G3-1 redacted them from the activity log and the captured logs, but the shipped `gunicorn.conf` still logged the path (`GET /accounts/reset/MQ/<token>/`) and the referer to stdout, where `kamal app logs` and any log shipper read it. `gunicorn.conf` now sets `logger_class = "apps.smallstack.gunicorn_logging.RedactingLogger"`, which runs every access-log atom (path, request line, referer, query, header and environ atoms) through `apps.smallstack.redaction`, so the line reads `/accounts/reset/MQ/***/`. `runserver` and a proxy in front (kamal-proxy, nginx …) keep their own full-path logs: `logging-audit` and `kamal-deployment` say how to treat them (E-dec 6).
- **Django admin and Explorer let a User manager deactivate a superuser or remove its staff flag,** which the User Manager and REST refuse; admin also let anyone deactivate or demote the last active superuser (themselves included), and a non-superuser holding every permission could delete a superuser in admin or Explorer. Both now follow the User Manager's rules, through `apps.access.services.account_flags_refusal`: only a superuser changes or deletes a superuser's account (admin opens it read-only for anyone else; `UserAdmin.has_change_permission(request, obj)` / `has_delete_permission(request, obj)`, which Explorer now asks per object), nobody deactivates, un-staffs or deletes their own account, and nobody deactivates, demotes or deletes the last active superuser (bulk *Delete selected* included). A wider non-superuser's flags stay editable with `change_user`, as on the User Manager.

- **The MCP `access_request_membership` tool was a membership oracle** for a staff caller refused the read tools: it answered `unchanged: alice is already in Readers` for a member and filed a request for a non-member, listed every group on a miss, and looked an account up by email (the reply's title then named it). Without `accounts.view_user` the tool now files the request either way, doesn't list groups, resolves usernames and ids only, and stores no group permission count in the request; a request that would change nothing is refused when an approver decides it ("approving would change nothing"), so it stays pending until rejected. Callers holding `view_user` keep the precise `unchanged` answer (E-dec 2).

### Changed
- **Reading accounts, access and other accounts' API tokens needs the `view` permission, not just the staff flag.** A staff account holding no permissions read the whole Access area (every account's permissions, the change log, the review, the exports), the User Manager's list, pages and stat modals, `GET /api/auth/users/`, user search hits and every account's tokens, while Explorer and the datasets refused the same rows. The Access pages, `/smallstack/api/access/` reads and the `access_explain_user` / `access_check_permission` / `access_findings` MCP tools (now also hidden from `tools/list`) need `accounts.view_user`, as do the User Manager's reads and `GET /api/auth/users/` (the token's owner); the Access and Users sidebar links and the dashboard's Access widget are hidden without it. Other accounts' tokens on the Token Manager (list, detail, stat modals, counts, search hits) need `smallstack.view_apitoken`; your own are always visible. Superusers read everything. The shipped *Access reviewer* and *User manager* groups grant `view_user` and *Token manager* grants `view_apitoken`, so those roles keep working. New: `DashboardWidget.visible_to(user)`, and a CRUDView's `search_visibility_applies_to_staff = True` applies its `search_visibility` to staff too. See `UPGRADING.md` (S2-1). The User Manager's **Timezones dashboard** stays open to every active staff account (a team scheduling tool; it now has its own *Timezones* sidebar link): without `view_user` it shows names, avatars and time zones only, with no staff badge, *Staff only* filter, edit link or email match in its search (E-dec 3). The dashboard's **API Tokens** card also stays visible to all staff: it carries system-wide counts only (no token name, owner or label, on the card or in `/api/dashboard/widgets/`), now pinned by a test (E-dec 4).
- **`staff_required` keeps the decorated view's own type** (it accepted only `Callable[..., HttpResponse]`; a streaming export is an `HttpResponseBase`).

## [0.31.0] - 2026-11-14

### Upgrading from 0.30.3
- **A CRUDView's create, edit and delete pages now write the audit `LogEntry` themselves.** A view that added `AuditMixin` through `view_mixins`, or called `log_action()` from `on_form_valid` / `on_delete`, now records each web write twice: remove your own call. See `UPGRADING.md`.
- **New setting `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS`** (default off: Explorer behaves as before). Turned on, staff accounts without Django model permissions lose access to Explorer models until granted them; grant permissions first.

### Added
- **A FAQ at `/faq/`** in the showcase pages (and the public site's top bar): what SmallStack can build, answered plainly, including where it isn't the right tool. Four groups: **system builders** (a blog, a website, an internal tool, a CRM, an API server, a headless backend for React/Vue/Next.js/Svelte, a mobile backend, a customer-facing app, dashboards, payments, what it's not for, adding it to an existing project), **components** (CRUD pages, Explorer, the embeddable template tags, using them on your own theme, styling, datasets and calendars, card types, approvals/notifications/scheduled jobs, versioned documents, permissions), **integrators** (API tokens, MCP and Claude, search, webhooks in and out, feeds, spreadsheets/BI/calendar apps, the `sc` CLI, logs from outside, coding agents) and **running it** (hosting, SQLite or PostgreSQL, updates, licence). Each answer is a `<details>` that works without JavaScript; a link to one question (`/faq/#crm`) opens it. It links the help FAQ for how-to questions. Answers are set for reading (about 17px, against the interface's 14px).
- **Django model permissions on CRUDView, opt-in: `model_permissions = True`.** Every surface then also requires the user's `view` / `add` / `change` / `delete` permission on the model, the check Django admin makes: the generated pages, bulk actions, REST (by method), the MCP tools and `sc --user`. Buttons, row actions, bulk actions and related tabs follow the same answers, and a delete that would cascade into rows of an admin-registered model the user may not delete is refused, as in Django admin. `change` implies `view`; superusers hold all four. It adds to `mixins` and the per-row hooks, it doesn't replace them. `has_model_permission(request, action)` is the hook to override.
- **Explorer can honour Django permissions: `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS`** (off by default, so any staff account keeps full access). On, Explorer's pages, REST and index follow each staff account's model permissions, granted with groups as for Django admin; a ModelAdmin's `explorer_model_permissions` overrides it per model. Until now every staff account could create, edit and delete every Explorer model whatever its permissions.
- **A History page per row: `enable_history = True`** on a CRUDView (on for every Explorer model) adds `<pk>/history/` and a History button on the detail page, listing the row's `LogEntry` trail from every surface (these pages, bulk actions, REST, MCP, `sc` and Django admin) with who, when and what changed.
- **Explorer reads more of a ModelAdmin, and means what Django admin means by it.** `list_display` methods, model methods and properties, plain callables and `"__str__"` are columns now, with Django admin's own header (`@admin.display(description=…)`) and value (✓ / — for `boolean=True`); they were dropped without a word. `readonly_fields` and `exclude` keep a field off the create and edit forms. `ordering` is the list's default order. `list_select_related` joins as in Django admin, and by default the foreign keys shown in the list are joined, one query instead of one per row. A ModelAdmin's own `list_per_page` sets the page size when `explorer_paginate_by` doesn't (it was always 10). `SimpleListFilter` classes in `list_filter` filter the list, REST and MCP with their own `lookups()` and `queryset()`; they were skipped.
- **`search_fields` takes Django admin's prefixes on every CRUDView:** `^name` starts with, `=email` exact (case-insensitive), `@body` a substring match. A prefixed entry used to raise `FieldError` (a 500) on the list's search box, REST `?q=` and the MCP `q`. The search index takes the bare field path.
- **`explorer_enable_mcp`, `explorer_enable_search`, `explorer_enable_webhooks`** turn those surfaces on for an Explorer model. Explorer registers the MCP tools (named from the verbose names, staff-only) and the search entry itself, since it builds its views after the MCP and search apps have looked. A model another CRUDView already serves keeps that view's surfaces; Explorer logs a warning instead of registering a second set.
- **The delete confirmation says what goes with the row.** The delete page and the modal the list and detail pages open list what Django's deletion collector would cascade, per model with a count and, for staff, the first few rows by name. A row protected by a `PROTECT` / `RESTRICT` foreign key gets no Delete button and a list of what protects it. Before, both asked "Are you sure?" with no word of the cascade, and a protected row was found out only on submit.

### Fixed
- **Creates, edits and deletes made on a CRUDView's own pages left no audit record.** REST, MCP, `sc` and the bulk views wrote a `LogEntry`; the commonest way to change a row didn't. The pages now write one too, in Django admin's change-message format (create and edit name the fields that changed), and a delete's entry is written in the delete's transaction, so a refused delete leaves none.
- **A delete page refused by `check_object_permission` answered "Delete failed — an unexpected error occurred."** It now answers 403 with the reason.
- **Activity's resource page is laid out for a URL pattern.** The pattern now has the header's full width and wraps after a slash rather than mid-word, with its converters (`<slug:slug>`) highlighted. The stats, window picker and a new **Open page** button sit on a row below it; the button opens the most-used real path behind the pattern. "Most-used paths" lists each path with its hits and an ↗ link, keeping the end of a long path (where paths of one pattern differ) instead of cutting it off. A link is offered only for a path that answered a GET without an error and is on this site. The breadcrumb no longer repeats the URL truncated.
- **Activity's pages scrolled sideways on a phone.** Three causes, each fixed where it lives, so other pages using the same pieces benefit too:
  - **Tab bars (`.tab-bar`) widened the page** when their tabs didn't fit (five on Requests and Users). They now scroll sideways inside their own box; the active-tab underline is unchanged.
  - **Tables in a `.crud-table-wrap` widened the page.** A cell's screen-reader-only text was positioned against the page instead of the table's scroll box (688px of content on a 420px screen on the resource page). The wrapper is now `position: relative`.
  - **Fixed-width tables in Activity cards** ("Top resources", "Who uses it") scroll inside their card.
  - **Logs** (520px on a 420px phone): the level selector scrolls inside the filter bar, which now takes its width from the card, and the log table's scroll box is contained so its width no longer sizes the page.
  - **API Health and MCP Health** (558px): the diagnostics table scrolls inside its card instead of stretching the page for its longest route name.
  - **The showcase pages' full-bleed wrapper (`.pf`)** overhung each side by 4px (24px against the page's 20px padding).
  - **The public site's Login and Sign Up** ran off a 375px screen beside the wordmark ("Sign Up" wrapped). On a phone they're tighter and don't wrap, and the wordmark drops the margin that spaces it from a sidebar toggle the public site doesn't have.
  - **Code blocks set the page width** on the home page (828px of content), the platform pages (608px, 554px), Search (667px) and About (512px). Code samples (`.pf-code`, the home page's pipeline card, the help pages' `.markdown-body pre`, the Starter page's setup steps) and the showcase wrappers (`.pf`, `.search-stage`) take their width from the page and scroll inside; Search's grids use `minmax(0, 1fr)` and its source rows wrap.
  - **Forms on a 320px phone:** a file picker's built-in width pushed `.form-row-2col` off the screen; the picker now shrinks and the grid columns are `minmax(0, 1fr)`.
  - **The public header on a 320px phone** shrinks the wordmark and the sign-in buttons a little more, so Sign Up stays on screen.
  Every Activity page, Logs, API Health, MCP Health and every public page (home, About, Getting started, both platform pages, Prompts, FAQ, Search, the three Starter pages, the blog and the status page) now fit a 320px, 375px and 420px screen exactly; desktop layouts are unchanged.
- **`adopting-smallstack.md` recommended laying SmallStack over an existing project,** which collides with that project's own choices for the same things, all at once: settings tuned for the platform (the user model, axes-first authentication, a CSP with no inline JavaScript, tasks, logging into the log viewer, ~90 `SMALLSTACK_*` switches), the database configuration (SQLite's WAL and `IMMEDIATE` tuning, the search index built after each migrate, the median function on each connection) and eighteen middleware classes in a deliberate order. It also cut the project off from upstream updates, and every setting bent to fit conflicted again on each merge. It's rewritten around the path that works: a fresh clone kept as `upstream`, your apps moved in one at a time (keeping each app's label so tables, content types and permissions don't change), a fresh migration history, sign-in and the CSP's inline-script rule, users and data moved with natural keys (tested end to end, including the blank-email collision `accounts.User`'s unique email causes), then a table of which SmallStack tools replace what. The FAQ's "add SmallStack to my project" answer says the same.
- **The Starter page told readers to edit SmallStack's own `sidebar.html`** to add a link; step 3 now registers it with `nav.register()` from the app's `apps.py`. Its two-column demo, and the grid layout help page, use `repeat(auto-fit, minmax(240px, 1fr))`, which stacks on a phone; a plain `1fr 1fr` grid never does.
- **The Explorer docs described an Explorer that no longer exists.** They said search and filters were detected from a model's fields (they come from `search_fields` and `list_filter`; a model with neither has none), showed `Table2Display` as the default display (it went with django-tables2 in v0.12; examples using it raised `ImportError`), named a `table_class`, an `ExplorerSite.discover()` and an `app_label` URL base that don't exist, and said to leave Explorer for a `CRUDView` to get an API. `docs/skills/explorer.md` and the help pages (`explorer.md`, `explorer-admin-api.md`, `explorer-composability.md`) now describe what the code does, and list what Explorer doesn't read (`inlines`, `actions`, `date_hierarchy`, …). `apps/explorer/content/`, an older copy of those help pages that nothing served, is removed.

### Changed
- **Explorer lists can look different after the upgrade,** because Explorer now honours more of each ModelAdmin: method columns appear, `ordering` changes the default order, a declared `list_per_page` changes the page size, and `readonly_fields` / `exclude` leave the form. Set `explorer_list_fields`, `explorer_paginate_by` or `explorer_fields` on the ModelAdmin to keep the old behaviour for a model.

## [0.30.3] - 2026-11-14

### Upgrading from 0.30.2
- **The design tokens moved from `theme.css` to a new `core.css`,** which `theme.css` imports first, so every page loads the same CSS. A fork that edited token values in `theme.css` gets a merge conflict there: move those edits to `core.css`. The drill-down modal, help-bubble and stat-list rules moved from `theme.css` to the end of `components.css`.
- **SmallStack's loggers are named by module now** (`apps.webhooks.services`, `apps.mcp.views`, …) instead of `smallstack.<app>`. Logging config, alerts or log searches keyed on `smallstack.*` names need the new ones; MCP's dedicated entry is now `apps.mcp`. A `smallstack` logger stays configured for code of your own on the old names. See `UPGRADING.md`.
- **Using SmallStack's embeds on a base template of your own?** Add `{% smallstack_assets %}` to its `<head>` and `{% smallstack_modal %}` before `</body>`. See `UPGRADING.md`.

### Added
- **REST search: `GET /smallstack/search/api/?q=`.** The ranked, cross-model full-text search the omnibar and the `search_all` MCP tool run, now for REST clients with an API token, and in OpenAPI. It searches as the token's user, so `search_access` and `search_visibility` apply as everywhere else. `limit` (1–50), `model=app_label.Model`, and no `q` lists the searchable sources. Until now REST had only each list's `?q=`, a substring match over one model's `search_fields`.
- **Account events are logged** (`apps.accounts`): sign-in, sign-out and failed sign-in for every route in, sign-ups, invites sent and accepted, sign-in codes issued and rejected, the hourly code cap (WARNING), and password resets requested and completed. Usernames and pks only; never a password, code or token. Password reset now runs through `LoggedPasswordResetView` / `LoggedPasswordResetConfirmView`, Django's views plus a log line.
- **SmallStack's embeds work on a project's own theme.** `{% smallstack_assets %}` (in `theme_tags`) links `smallstack/css/embed.css`: the design tokens, palettes and components that `{% dashboard %}`, `{% metric_card %}`, `{% goal_list %}`, `{% card %}`, `{% report %}`, `{% calendar_card %}`, `{% stat_card %}` and `{% help_bubble %}` draw with, in a `smallstack` cascade layer. The host theme's own rules win wherever both style a class (Bootstrap's `.card`, `.btn-primary`), and `embed.css` sets no element styles, so it never restyles the host page. `{% smallstack_modal %}` renders the drill-down modal once per request; `smallstack/base.html` uses it too. Before this, an embed on a page that didn't extend `smallstack/base.html` drew without SmallStack's tokens (`--error-fg`, `--series-*`, radii) or `.sr-only`, and its drill-downs had no modal to open into. The theming guide's base template carries both tags and a section on embeds, and the dashboards and calendar skills say what a custom base needs.
- **Plain Django on SmallStack** (`apps/smallstack/docs/plain-django.md`, linked from the README and `/smallstack/help/`): an app written the way you would in any Django project, a function view, a `ModelForm`, a template extending `smallstack/base.html`, a `nav.register()` and pytest tests, with nothing SmallStack-specific to learn first, then a table of when `CRUDView`, the API and MCP flags, search, datasets and the scheduler earn their place. Every snippet was run as a real app before it went on the page.
- **`/starter/own-theme/`** in the showcase app: metric cards, a dashboard, a calendar and a help bubble on a stand-in theme that styles `body`, `.card` and `.btn-primary` itself.
- **`apps/smallstack/tests/test_embeds_on_own_theme.py`** renders the embeds on a base that isn't SmallStack's, follows the fragments htmx loads, and fails if a class they use is styled only by `theme.css`, a token their stylesheets read is defined only there, the modal is missing or doubled, or `embed.css` leaves its layer or styles a bare element.

- **Metrics can be a median.** `agg="median"` on a metric or a card over a dataset, computed in the database as datasets already did (`percentile_cont` on Postgres, a registered aggregate on SQLite). It works everywhere a metric does: cards, trends, goals, reports, snapshots, `metric_preview` and the agent tools. For skewed numbers (response times, deal sizes) it's the typical value where the average is pulled up by a few large ones. It needs a numeric column, and a database with no median (MySQL, MariaDB) doesn't offer it: the metric form, the card builder, card validation and the MCP schema all read `aggs_available()`. Migration `smallstack_dashboards.0015_median_aggregate` only adds the choice.

### Changed
- **SmallStack's own tests live in each app's `tests/` package,** as AGENTS.md always said: 59 modules moved from app roots (`apps/smallstack/test_*.py`, the `tests.py` files of help, smallstack, tasks, website, explorer, profile and usermanager) with `git mv`. `test_layout.py` keeps SmallStack's apps that way; a project's own apps may keep `startapp`'s layout.
- **Comments say why, not which audit.** About 180 comments in application code cited internal audit and ticket codes (`F-026`, `OPS30`, `(Audit 2026-09-13, C6.)`) that mean nothing outside this repository. The codes are gone; the reasons they sat beside stay, rewritten in plain words where a comment leaned on one.

### Fixed
- **`{% approval_card %}` showed a request to anyone the page handed it to.** It checked who could decide, not who could see, so a page that rendered the card for the wrong person showed that person the request's title and description. It now checks `can_view` (staff, the requester, an assignee) and renders nothing otherwise.
- **The User Manager's account actions left no trace.** Sending a set-password link and clearing a login lockout now write an audit entry (`LogEntry`: who, for whom) and a log line; a failed unlock logs its traceback instead of only flashing an error.
- **`apps/help/tests_llms.py` never ran.** Its name matched none of pytest's `python_files` patterns, so its five tests were never collected. As `tests/test_llms.py` they run, and pass.
- **Docs told readers to edit SmallStack's own templates and stylesheets.** The sidebar recipes in `theming.md`, `theming-system.md` and the FAQ pasted an `<li>` into `sidebar.html`, and the CRUD checklist said the same; they now use `nav.register()`. The customization guide listed `base.html` and `topbar.html` as the place for a logo and title (they're `BRAND_*` settings) and `static/css/project.css` as a project-wide override that nothing loads; `branding.md` put the `BRAND_*` settings in `base.py` (they're in `smallstack.py`); the adoption guide said to fix `topbar.html`. Each now points at the supported setting or API.
- **The framework apps' INFO logs were dropped in production.** Most of them logged as `smallstack.<app>`, a name production's `LOGGING` didn't configure, so those records fell through to root at WARNING: a dashboard defaults sync, a scheduler run, a feed fetch never reached the console or `/smallstack/logs/` unless a capture window was open. All 70 now use Django's convention, `logging.getLogger(__name__)`, so the configured `apps` logger covers them. `test_every_app_logger_reaches_a_configured_logger_at_info` checks every logger name in `apps/` against both settings files, and `logging-audit.md` documents the rule.
- **Five failures were swallowed without a trace.** A REST bulk delete that failed unexpectedly answered "Delete failed" and logged nothing; a broken approval-kind `can_decide` hook refused an approver silently; runbook sent subscriber mail and pruned versions inline, unannounced, when it couldn't queue them; a webhook challenge hook that raised was dropped before normal dispatch; a heartbeat that couldn't be saved showed "fail" with no traceback anywhere. Each now logs (error with the traceback, or a warning for the inline fallbacks), with a test. Expected misses in search previews, the help search index counts, dataset labels, links and value probes, the newsletter's SMTP close and token stats now log at DEBUG, so a capture window can see them. `logging-audit.md` has a section on choosing the level.
- **Runbook pages carried two drill-down modals**, its own copy and the base template's, both `id="stat-modal"`, and its script replaced `theme.js`'s `openStatModal`, dropping the narrow and reading sizes. It now uses `{% smallstack_modal %}` and keeps only its table sorting.
- **Four docs told readers to include `stat_modal.html` by hand** (`building-crud-pages.md`, `django-apps.md`, `components.md`, `dashboard-cards.md`), which doubles the modal on `smallstack/base.html`. They now say it's already there, and to use `{% smallstack_modal %}` on a base of your own.

## [0.30.2] - 2026-11-14

### Upgrading from 0.30.1
- **Built your own base template from the theming guide?** Check its `config.js` tag for `data-theme-url` and `data-palette-url`. Without them the light/dark toggle never saves, and the choice flips back on the next page load. See `UPGRADING.md`.

### Fixed
- **The theming guide's base template couldn't save the light/dark choice.** Its `window.SMALLSTACK` config left out the save URLs, so on a theme built from it the toggle changed only the browser's copy, and on the next page load the profile's older choice won and the toggle flipped back. Its setup was also inline `<script>` blocks, which the CSP has refused since 0.30.0. `adding-your-own-theme.md` (both copies), `theme-scenarios.md`, `from-zero-to-running.md`, `templates.md` and the "public, no login" help page now show what `smallstack/base.html` does: `theme-init.js`, then `config.js` with both save URLs, htmx and `theme.js`, plus a check that the choice survives a fresh browser. SmallStack's own pages were not affected.
- **A new browser could open dark for a user who saved light.** `theme-init.js` read only the browser's stored theme, so on a shell that loads `theme.js` late the page painted dark first. It now takes `data-user-theme` / `data-user-palette` and paints in theme.js's order: the profile's choice, then this browser's, then dark. `smallstack/base.html` passes them.
- `apps/smallstack/test_theme_wiring.py` holds the shipped shell, every template loading `config.js` and every base template in the docs to the saving setup, and runs `theme-init.js` under node (skipped without node).

## [0.30.1] - 2026-11-09

### Upgrading from 0.30
- **A dataset filter value that won't parse is now refused** (a ValueError, a 400 over REST) instead of ignored. That covers `<col>__gte=2026-13-45`, an unknown `__period`, or a non-number on a numeric column. It used to return every row.
- **The entrypoint's worker restart loop is fixed.** Take the change if your project carries its own `docker-entrypoint.sh`.
- **SmallStack's demo pages moved to a deletable `apps/showcase`,** the error pages became app defaults in `apps/smallstack/templates/`, and `README.md` became a short page that SmallStack rarely changes. Expect one round of conflicts on the files you rewrote, and keep yours. See `UPGRADING.md`.
- **Carrying call_stats' extensions to `apps/datasets/core.py`?** `cells()`, `series(sort=)`, `median`, `@dataset(units=)` and the extra flat lookups are upstream now, so drop your copies. For `day_entries()`/`day_counts()`, see "Calendar datasets" in `docs/skills/datasets.md`. `has_detail`, `_fk_label_map` and the `previous` period key still answer, with a `DeprecationWarning` on the first two.

### Added
- **Datasets: two dimensions, ranked series, medians, units and more filter spellings** (from call_stats). `Dataset.cells(x, y)` (REST `<key>/cells/`, MCP `group_by2`) returns a complete x × y grid for a heatmap, with 0 or None where a combination has no rows. It refuses an axis of more than 30 values rather than cutting it. `series(sort={"by": "value", "dir": "desc"})` (REST/MCP `sort=-value`) ranks before `limit` applies, so it's a top N; a time grain keeps its most recent periods. `agg="median"` is computed in the database, grouped or not: `percentile_cont` on Postgres, an aggregate registered on SQLite connections. `@dataset(units={...})` puts a `unit` on each schema column (else a guess from `*_seconds` / `*_minutes`). Flat filters gain `__gt`/`__lte` and numeric comparisons, `__ne`, `__icontains` and `__period=<key>`. Each schema filter lists its `lookups`, and `filter_problems()` reports bad values without querying. See `docs/skills/datasets.md`.
- **Keys and names from before the call_stats port still answer:** the `previous` period (now `yesterday`), `Dataset.has_detail` (now `has_links()`) and `_fk_label_map` (now `value_labels()`), the last two with a `DeprecationWarning`. `dateranges.py` lists how each period's meaning changed in the port.
- **`manage.py template_hygiene`** lists the inline `<script>` blocks, `on…=` handlers and `<style>` blocks in your templates, by file and line (`--summary`, `--framework`, `--check`). Use it to size the move off inline scripts. See `docs/skills/templates.md`, which now also covers the nonce route (django-csp's `NONCE` plus `nonce="{{ request.csp_nonce }}"`) as a step between the stopgap and static files.

### Changed
- **SmallStack's demo pages are their own app, `apps/showcase`, so a project deletes them once instead of merging them every release.** That's about, getting started, prompts, both platform pages, the starter pages, `/components/` and the public search. Their URLs are unchanged, and their names are now `showcase:…`. `apps/website/` keeps the home page, the public `base.html` and the chart card types. The public topbar and the home page reverse showcase URLs quietly (`{% url … as x %}`), so they work with the app deleted. The starter pages' "Starter" breadcrumb now links (it named a route that never existed).
- **The 400/403/404/500 pages are defaults in `apps/smallstack/templates/`.** A project's own `templates/404.html` overrides one, and upstream no longer ships files at those paths.
- **`README.md` is short and carries nothing that changes per release.** SmallStack's full description, with the version badge, is `docs/smallstack.md`.

### Fixed
- **The inline worker came back after a crash only if it exited cleanly.** `docker-entrypoint.sh` runs under `set -e`, so a `db_worker` that exited non-zero (a database restart, say) ended the restart loop, and the container kept serving with no worker. The loop now catches the exit code and restarts. *Upgrade note:* if your project carries its own entrypoint, take this change.
- **The `'unsafe-inline'` stopgap from 0.30.0 failed four framework tests.** The template sweeps now follow the policy in force. With `'unsafe-inline'` in `script-src`, only SmallStack's own templates are checked for inline scripts and handlers, and `test_csp_script_src_allows_no_inline_script` skips, naming how many of yours remain. The `<style>` sweep checks SmallStack's own templates only, since `style-src` allows inline styles. The rules moved to `apps/smallstack/template_hygiene.py`.
- **Framework tests assumed where a project mounts datasets and dashboards.** The datasets tests and the case-insensitive ordering test reverse their URLs instead of using literal `/smallstack/datasets/…` paths, and the Datasets nav entry's highlight follows the mount.
- **Tests that failed on Postgres or behind a downstream's first-request hook.** Two dashboards tests compared a filter tree as a JSON string (jsonb reorders keys), the case-insensitive ordering test expected SQLite's tie order for "Alpha" and "alpha", and the dashboards query-count test counted the first request after setup. The components-list sort test asserted on a three-way tie, which Postgres broke either way.
- **A dataset bound that didn't parse was dropped, returning more rows than the filters said.** `?created_at__gte=2026-13-45` used to filter nothing. It's now a 400, and the dataset browser shows "These filters can't be applied" with no rows.
- **`UPGRADING.md` had no section for 0.30.0's CSP change or the new dashboards app,** and two 0.30.0 settings (`HEARTBEAT_MAX_CONCURRENT_CHECKS`, `HEARTBEAT_RUN_DEADLINE_SECONDS`) were in no release note. Each release entry now opens with an "Upgrading from" block, and `downstream-release-migration.md` no longer describes v0.11 as the current release.

## [0.30.0] - 2026-11-08

### Upgrading from 0.29
- **The CSP blocks inline scripts.** `script-src` drops `'unsafe-inline'`, so inline `<script>` blocks and `on…=` handlers in your own templates stop running.
- **`apps.dashboards` is a new app in `INSTALLED_APPS`:** a nav item, MCP tools, 14 migrations, and shipped defaults synced after migrate (`SMALLSTACK_DASHBOARDS_ENABLED`, `SMALLSTACK_DASHBOARD_DEFAULTS_SYNC`).
- **Webhooks get their own queue and worker** (`webhooks` in `TASKS`, `WORKER_WEBHOOKS`, `SMALLSTACK_WEBHOOK_QUEUE`).
- **Invite and sign-in-code emails are queued** (`SMALLSTACK_ACCOUNTS_EMAILS_INLINE`), and `EMAIL_TIMEOUT` defaults to 10 seconds.
- **New tuning settings:** `HEARTBEAT_MAX_CONCURRENT_CHECKS`, `HEARTBEAT_RUN_DEADLINE_SECONDS`, `SMALLSTACK_FEEDS_MAX_CONCURRENT_FETCHES`.
- Each has a section in `UPGRADING.md` under v0.30.0, starting with "at a glance".

### Added
- **Every Dashboards and Goals piece on your own pages.** New template tags beside `{% dashboard %}`, `{% metric_card %}` and `{% playlist %}`: `{% goal_list %}` (a goal list judged), `{% card %}` (one saved card) and `{% report %}` (a report's table). Data tags hand a page the engine's results to draw its own way: `{% metric_value %}`, `{% metric_series %}`, `{% goal_values %}`, `{% report_values %}` and `{% dashboard_values %}`, with `{% dashboards_assets %}` for the stylesheet and scripts. All check access as the pages do. The starter page (`/starter/dashboard/`) shows each. The report page's table is now a shared include (`dashboards/includes/report_table.html`).
- **Apps ship their own dashboard defaults.** An app declares metrics, saved cards, dashboards, reports, goal lists and playlists in a `dashboard_defaults.py` (`register_defaults(Defaults(...))`). They're created after every migrate, shared and marked **From <app>**. People edit them in place: the app updates a default only while nobody has changed it, a changed one offers **Reset to default**, a deleted one stays deleted, and an app's defaults are archived while it's turned off. `manage.py dashboard_defaults` (`--dry-run`, `--app`, `--restore`, `--adopt`) runs the same sync. `seed_dashboards` is now the framework's own bundle and no longer overwrites edits to the demo. Migration `smallstack_dashboards.0014_app_defaults` adds the provenance fields (additive). See `docs/skills/app-defaults.md`.
- **Start from a saved metric on the dataset browser.** Above a dataset's filters, **Start from a metric** lists the metrics already made on it. Picking one loads its conditions and roll-up; change them or not, then **Make a metric** saves a copy ("Server errors (copy)", with its period column, format, thresholds, unit, description and tags) and leaves the original as it was.
- **Archive, Delete and Duplicate ask first, and say what they mean.** Each opens a confirmation in the page's modal. **Archive** says it isn't a delete, what still uses the item and keeps working, and how to restore it. **Delete** says what goes and what stays: cards, playlists and goal lists now have their own confirmations (a deleted card stays on each dashboard as that dashboard's own; a goal list's week-by-week history goes with it), each suggesting Archive instead. **Duplicate** says what the copy will be ("Site health (copy)", personal, nothing saved until you save; for a dashboard, that its cards still share their metrics) before the form opens. Restore stays one click.
- **Finding what's been archived.** Each list (metrics, goal lists, reports, dashboards, playlists, cards) shows **Show archived (N)** when it has archived rows, and **Back to the list** while showing them. The overviews' note names each kind with a count and links only those (“Archived: 2 metrics, 1 report”), not all three lists.
- **What a metric means, on hover.** On the metric library, the Goals overview, a goal list and its weeks, hovering (or tabbing to) a metric or goal name shows its description in a hover box. A goal made from a saved card shows the card's description first. Any element with `data-about` gets the same box (`dashboards/js/about-info.js`).
- **The demo has a rate.** `seed_dashboards` adds **Server error rate** (server errors ÷ requests, as a percent) and puts it in the Monthly KPIs report.
- **Help beside every Dashboards and Goals page.** A "?" next to a page's title opens a short explainer in the modal without leaving the page: what the thing is, what it represents, how it's set up, how to use it. Nine new "In short" help pages (how it all fits together, dataset, metric, component, dashboard, goal list, report, playlist, weeks and history), each a page to a page and a half, with chips to the related ones and a link to the full guide. The piece is reusable: `{% help_bubble "section" "slug" %}` (`help_tags`) opens any help page this way (`help:section_bubble`; `related` and `guide` frontmatter fill the footer; the stat modal gains a `reading` size).
- **Edit a card where it sits.** Every card on a dashboard has a ⋯ menu. **Edit card** opens the component builder for that one card in a dialog over the dashboard (`d/<slug>/cards/<id>/edit/`): a saved card is edited for every dashboard showing it, a card of this dashboard only is written back into its layout. Also **Move or resize**, **Open the metric**, **Edit the metric**, **Refresh this card** and **Remove from dashboard** (asks first). Viewers get Open the metric and Refresh.
- **Make a unique copy.** A saved card that other dashboards show too is marked with a small link tab and a count. Its menu's **Make a unique copy** makes that placement the dashboard's own, where it sits, and can copy its metric as well ("Requests (Ops EU)") so its filter can change there alone; **Give it its own metric** does the same for a card that was never a saved one. Together with Duplicate they turn a copy of a dashboard into one with numbers of its own (`d/<slug>/cards/<id>/copy/`, `boards.make_card_unique`).
- **Find things by tag, on every page.** Both overviews, all six lists and My dashboards have a **Tags** bar: every tag in use with how many rows carry it, and **Show everything**. The lists narrow to a tag (`?tag=`, REST too), show each row's tags, and keep the tag from page to page; an overview's "All N …" link carries it along. With nothing tagged yet, the bar says how to add the first one.
- **The logo follows the palette.** The stock SmallStack logo (the four-square mark and the wordmark) is drawn from the theme in the top bar and on the sign-in pages, so it matches every palette in dark and light. A project with its own `BRAND_LOGO_TEXT` / `BRAND_LOGO` keeps its image. `manage.py brand_logos` writes the same logo as SVG files for every palette (`static/smallstack/brand/palettes/`: logo and icon, for dark and light backgrounds), and the Theming help page shows them.
- **Number fields get − and + buttons.** Every `<input type="number">` is wrapped with theme-drawn buttons in place of the browser's few-pixel spin buttons: side by side on a wide field, a slim stacked pair on a narrow one. They step by the field's own `step`, `min` and `max` and disable at the limits; `data-no-stepper` opts a field out (`SmallStack.numberStepper`).
- **A drill-down designer.** In the component builder, **Choose the columns** opens a dialog with every column of the metric's data in one list (tick, drag into order, set a heading and a format) beside the rows that design opens, redrawn as it changes. `GET dashboards/api/metrics/<key>/rows/` takes `?drill=<json>`.
- **Pick calendars, don't type their keys.** The Calendar card's calendars are a tick-list of the ones you may see, in the builder and in a dashboard's Add card dialog. Card types can declare any option this way (`"type": "multichoice"`, with `choices` or `choices(user)`).
- **Rates.** A metric's source can be *a rate*: one metric divided by another, read for the same period on both sides, in cards, goals, reports, weeks and trends. Each week or bucket divides its own two numbers. A zero or missing bottom shows no value, and parts that can't be compared show an error rather than a number.
- **Metrics entered by hand.** A metric's source can be *entered by hand*: one value per date, typed on its page or set over REST (`dashboards/api/metrics/<key>/entries/`) or MCP (`metric_record_value`, `metric_delete_value`), rolled up by latest, sum, average, minimum or maximum. Nothing entered reads as no value, never 0. A value entered after a period was captured adds a new capture, keeping the targets it was saved with. The rows are scoped to people who can see the metric, so a shared one shows to non-staff.
- **Printing.** Goal lists, single weeks and reports have a **Print** button that opens a clean document (`g/<slug>/print/`, `r/<slug>/print/`): dark on white whatever the palette, status in words, wide reports sideways.
- **Repeating events.** An event can repeat every day, weekday, week, 2 weeks, month (same date or same weekday) or year, with an optional last date. Each date appears on the calendar and in the `.ics` feed. One date can be skipped and put back (`event_skip_date` over MCP).

- **Snapshots at any cadence.** A goal list can be captured hourly, daily, weekly, monthly or quarterly, any combination, from its new History page, REST (`goals/<slug>/tracking/`, `goals/<slug>/snapshots/`) or MCP (`goal_list_tracking`, `goal_list_capture`, `goal_list_history`). Each tracked period is captured once it ends. A period keeps every capture, the newest being what pages show, so saving again and late values add rather than overwrite. New lists track weekly (`SMALLSTACK_SNAPSHOT_DEFAULT_CADENCES`), and old hourly and daily captures are pruned (`SMALLSTACK_SNAPSHOT_KEEP_DAYS`). `register_subject` lets other models be captured.

- **Targets per cadence.** A goal can have its own target for any cadence, under **Targets by cadence** in the goal editor or as `targets` in its JSON. Without one, weekly and any number on the same scale at every length (an average, a rate, a latest reading) use the main target. A count or sum isn't judged, because a weekly target says nothing about one hour: it shows its value marked **No target**. Captures keep the target they were judged against.

- **A compact view of the designs.** The builder's **Pick a design** step has a **Full / Compact** switch: full shows each design with what it draws; compact shows one chip per design in a line per group, with the description (and, for a dimmed one, the reason) on hover. A new card opens full; an existing one, on its page or in the Edit card dialog, opens compact, where the page is long enough already. The switch remembers your choice.
- **Every card's settings, compact.** The builder's **What it shows** and **Style it** steps, the Edit card dialog and a dashboard's Add card now lay each setting out as wide as its control and flow them left to right: a stat's whole styling (format, unit, number size, number colour, title size and colour, alignment) is two short rows of pills and swatches instead of seven stacked selects; the colour rules pick their colour from swatches; a chart's kind, buckets, direction and order, a calendar's view, a menu's layout and a goals card's order are pills; the roll-up, its column and the period column share a row. Nothing stored changed.
- **A note has a look of its own.** The Note card's builder offers **Text size**, **Alignment**, **Text colour** (plain, quiet, accent, success, warning, danger) and a **Background** (off by default; an accent tint, a raised surface, or a success / warning / danger / info tint), all the theme's own colours, so a note reads right on every palette. They're drawn as one compact row — size and alignment as pills, the colours as swatches — in the builder, the Edit card dialog and a dashboard's Add card alike; the builder's whole "What it shows" step now lays small settings side by side. Agents set the same as `options.size` / `align` / `color` / `background`. For your own types, a `choice` option may ask for `"widget": "segmented"` or `"swatches"`.
- **Share a dashboard of your own.** **Share** on a personal dashboard lets everyone who can sign in open it, or people you pick by name (find them as you type; each gets a notification with the link). You still edit it; they read its cards as you do, including cards over your personal metrics, whose rows open by the card's place on the dashboard; data their own access doesn't reach stays restricted. Badges say who may open it (Shared with everyone, Shared with 3 people, Shared by alice), and My dashboards gains **Shared with you**. Agents: `dashboard_share`; REST reads `sharing`.
- **The card-type API, documented.** `docs/skills/card-types.md` is the contract for publishing a card design from a project or a reusable app: registration, every `ComponentType` field, what `build` receives and returns, the data helpers and rows links, option types and your own editors, what the shared validation already does, scripts and the `dashboards:card-drawn` event, what agents see, and how to test one.
- **Scripted cards draw everywhere, and bring their own editors.** A card type that draws with a script (a chart library in `media`) used to mount only on dashboards and embeds: the builder's preview, the Edit card dialog and the components gallery swapped HTML in without a word. `{% component_media %}` now writes `dashboards/js/cards.js` ahead of every type's files, and it fires `dashboards:card-drawn` on the element that holds a card's HTML on every surface, so one listener mounts a chart in all of them; the components page loads card files in its head. A type's `options_schema` entry can also be of a type of your own, drawn by an editor you register (`SmallStackDashboards.optionEditors[type]`) in the builder and the Add card dialog alike.
- **A Menu card.** Links in your order (words, where it goes, and whether it opens a new window), laid out across or down, or fitted to the card's shape: across when it's wide, down when it's tall, re-laid as the card is resized. A way around, on the dashboard. The builder has a row editor for the links (move, remove, add); a dashboard's **Add card** takes them one a line (`words | address | new`). A link is a page of this site, an http(s) address or mail, never anything that runs. For your own card types, `links` is a new option type.
- **Three more designs, no library: Bar chart, Gauge and Table.** *Bar chart* draws the filtered rows split by a column as columns (names under them) or horizontal bars, largest first or by name. *Gauge* puts one number on a half dial between a floor and a ceiling you set, with the card's (or the metric's) colour rules drawn as bands under the arc, so where the needle sits says how the number is doing; it takes a metric like a stat, so it's offered in a dashboard's Add card too. *Table* shows the filtered rows themselves, a page at a time (**Rows a page**), in the columns the builder's **Columns** step designs (the drill-down designer: tick, order, head and format them, pick the sort); its headers sort and its footer pages the card in place, columns resize, number columns can carry a **Totals** row of sums over every matching row, and **All rows** opens them in the rows window with a CSV. All three are in `apps/website/dashboard_cards.py`. For your own such type, `ComponentType(shows_rows=True)` turns the builder's Drill-down step into Columns, and `metrics.drill_rows` takes an `offset`.
- **Two more charts, no library.** *Pie chart* (a count or total, each group's share of the whole) and *Ranked bars* (any metric's groups, largest first) join the trend chart in the component builder. Both are server-drawn SVG and CSS, and each group opens its rows. They live in `apps/website/dashboard_cards.py` beside the trend chart.
- **The components page shows the components.** Hovering or focusing a row in the list shows the real card. The second view is now a gallery of live cards that load as they scroll into view, replacing the plain table.
- **Find a card by its dataset, its design or its dashboard.** The components page has three dropdowns beside the search: **Dashboard** (the saved cards a dashboard shows, with a line naming it and the way back; a dashboard's header gains **Cards**, which opens this), **Dataset** (cards over it, by their own filter or their metric's) and **Design**; each offers only what your cards use. The same `?dashboard=`, `?dataset=` and `?type=` narrow the REST list. With the tags bar, search, and pages of 15 (Rows per page), a library of hundreds stays a click or two from any card.
- **Try another design without losing this one's settings.** In the component builder, a trend's buckets and chart kind, a pie's group-by and limit, the styling and the drill-down are kept aside while another design is tried, and come back when the design does. Only the chosen design's settings are saved.
- **A trend over all time fits its buckets to the data.** With no period, the trend chart's *Fit* bucket size now reads the span of the rows it draws (a week of data by day, three years by quarter) instead of always by month, which drew one bar for a new install's few days.
- **More conditions on the dataset browser.** Under the quick filters, the same ALL/ANY condition editor the metric builder uses: any column, any operator, nested groups. It travels in the address as `?filter_tree=<json>` (what REST takes), narrows the rows, the roll-up and the CSV, and reads back in words. A condition that can't be applied shows its problem and no rows, never the unfiltered set.
- **Make a metric, keep the roll-up as a card.** The dataset browser's **Make a metric** opens a modal with the dataset, every condition on screen as one filter tree (the quick filters included) and the roll-up's aggregate, named and previewed, ready to save (see *The dataset browser filters as you go*). A grouped roll-up also offers **keep this roll-up as a card** (Grouped stat, Ranked bars, or Pie chart for a count or sum): save the metric, and the component builder opens on that card with the group-by set. A metric's page has **Make a card** for the same thing later. The metric form and the component builder take these as query parameters, so a link can open either filled in.

### Changed
- **Only administrators change an address.** A dashboard's, report's, playlist's or goal list's address (the URL) shows read-only in its settings to everyone but a superuser or a member of the `admin` group; plain staff no longer get **Change the address**, and the form refuses their change over every surface (`models.can_change_address`).
- **Webhooks get a queue and a worker of their own.** Outbound deliveries run on a `webhooks` task queue (`SMALLSTACK_WEBHOOK_QUEUE`, used when `TASKS` lists it, `default` otherwise), and the container starts a worker for it (`WORKER_WEBHOOKS`, default 1, `0` for none). A fan-out to slow or dead endpoints no longer holds up sign-in emails and scheduled jobs on the shared worker. See UPGRADING.
- **Feed collection fetches sources in parallel** (`SMALLSTACK_FEEDS_MAX_CONCURRENT_FETCHES`, default 6), so several slow feeds cost about one timeout. Writes stay on the calling thread; a fetch still going after 60 seconds is reported for that source and skipped.
- **Invite and sign-in-code emails no longer wait on the mail server inside the request.** They go out from the `email` task queue (inline under `DEBUG`, or with `SMALLSTACK_ACCOUNTS_EMAILS_INLINE=True`). The queued task holds only IDs: the worker mints the sign-in code (`LoginCode.rekey`) or invite token as it sends, so no credential is stored in the task table. Production needs a worker on `email`; see UPGRADING.
- **SMTP gives up after 10 seconds by default** (`EMAIL_TIMEOUT`, `0` for none). Unset used to mean no timeout, so a hung mail server held a web thread until gunicorn killed it, or held the task worker, and everything queued behind it, indefinitely.

### Migrations
- `smallstack_dashboards.0014_app_defaults` is additive: provenance fields (`provided_by`, `provided_key`, `provided_spec`, `provided_hash`, `provided_parked`) on the owned tables, and `RemovedDefault`.
- `smallstack_dashboards.0013_dashboard_sharing` is additive: `shared_with_everyone` and `shared_with` on `Dashboard`.
- `smallstack_dashboards.0012_card_sources` adds a card's own source (`dataset`, `filter_tree`, `agg`, `measure`, `period_field`) to `Component` and copies each metric's definition into every chart and grouped card bound to one, in saved cards and dashboard layouts.
- `smallstack_dashboards.0011_tags_archive` is additive: `tags` and `archived_at` on six tables.
- `smallstack_dashboards.0010_snapshot_engine` replaces `GoalSnapshot` with `Snapshot` and `SnapshotTracker`. Saved weeks carry over as weekly captures, and every existing list keeps a weekly tracker.
- `smallstack_dashboards.0009_metric_sources` and `smallstack_calendar.0003_event_repeat` are additive. Existing metrics become source `dataset` and existing events don't repeat.

### Fixed
- **`seed_dashboards` failed on a fresh database.** Its two grouped cards ("Requests by method/status") still pointed at a metric, which a grouped card no longer accepts, so saving the Site health dashboard raised. They filter the requests dataset themselves now.
- **A trend chart said "no period field" with nowhere to set one.** The period field is the metric's (the date column it is read over), not the card's, and nothing said so. The builder now dims the Trend chart for such a metric and says, under the metric picker, where to set it, with a link to the metric's form; saving the card is refused with the same reason, and an existing card says it too. A trend over a hand-entered or rate metric was refused on save as "needs a metric over a dataset" though the builder offered it; it saves now.
- **A dashboard's settings: one card for its name and picture.** The picture, with its screen-reader description, sits beside the name, address, description and tags instead of in a card of its own below.
- **The Edit card dialog could stand taller than the window**, its head cut off above with no way to scroll back to it. Its height was `100vh`, which in Safari counts the toolbar; a modal dialog is sized against the viewport itself now (the Add card and drill-down dialogs too), and scrolling inside it no longer chains to the page.
- **A note's colour held in the preview but not on the dashboard**, where a note is drawn flat and quiet and that rule outranked the chosen colour. The chosen colour wins now; a note that picked nothing stays quiet. The builder's Full / Compact design view is remembered per situation (choosing a new card, editing one), so picking Full once doesn't undo the compact default on edit pages.
- **A playlist's timings read as two settings fighting.** The settings page now puts **Playing (the defaults for the show)** first, and each slide below shows **Default · 30 s** as a pill until you click it to give that slide its own time, with full-size − and + and a ↺ back to the default; the period's default reads "Dashboard's own". Before, a slide's blank field with a greyed number sat under tiny stacked spin buttons, with no way back once typed in.
- **Linked cards: a click on one card narrows another.** Give a chart *Send clicks to* a channel and other cards *Listen to* it, in the builder's **What it shows** step (or `options.publish` / `options.listen` in a layout): clicking POST in a pie redraws the listening stat, bars and table to POST only, each with a "Showing POST ✕" chip that clears it. Cards chain (pie → bars → table reads *POST · 204*), cards over different data link through a column mapping, and it works on dashboards, `{% dashboard %}` embeds and playlist slides. A slice only ever narrows: it's checked against the listening card's own data and ANDed onto its filter, with its period and the viewer's access still applying; one it can't apply is refused with a reason, never quietly dropped. Rows links carry the slice, so a narrowed card's rows window opens narrowed too. A dashboard's **Add card** dialog has the fields too: *Send clicks to* on a calendar, *Listen to* on a card that draws data (a column mapping stays in the builder). A **calendar card** sends days: click one (or Tab to it and press Enter) and the listening cards show that day, read on their own period column unless they map the calendar's `date` to another; the calendar's events still open their own pages. For your own card types: `ctx.narrow`, `ComponentType(publishes=True)` for a card with no data that can still send clicks, and `dashboards.md` → *Linked cards*.
- **Table columns, sized for what they hold.** The generic CRUD table never crushes a column any more: it gets a minimum width (every unsized column at least 140px) and its wrapper scrolls sideways past it, where a crowded table used to squeeze a free column to nothing (the posts list's Blog column was 1px wide, the approvals' Requested by 0px). Its link column gets 240px of its own rather than an equal slice, a local date and time gets room for "Oct 28, 2026 8:00 PM EDT" (240px), and takes `CRUDView.column_labels` for headers shorter than a field's verbose name. The dashboards lists use both (Metrics, Dashboards, Playlists, Reports, Goal lists: "Updated", "Roll-up", "Opens with", "Seconds"), load their stylesheet on the table view too (the tags bar was unstyled there), the components table's Source column shows "(metric)" in full, and an owner badge on the Goals overview wraps under a long dataset name instead of being cut. Elsewhere, percentage widths that starved a neighbour became px: Users (the email gets 280px), Blog posts, Approvals, Scheduler runs, and the Explorer's request log, heartbeats, heartbeat epochs, log entries, access attempts and monitored endpoints. A % column out-bids the unsized ones for the slack in a fixed-layout table, so prefer px (`crud-views.md` says why).
- **A CRUD table drew Edit and Delete for rows the view refuses.** The generic table listed the two actions for every row; the edit and delete routes then answered 403 wherever `can_update` / `can_delete` said no (a staff member on someone else's personal playlist). The table now asks the same hooks before drawing an icon, as the library views already did.
- **Someone else's personal row said only "Personal".** A staff member sees every row but changes only their own personal ones, so a row with no Edit looked broken. Every list and overview now says whose it is ("Personal · admin"), with why on hover.
- **A card one row high made the layout unsaveable** ("'c1' and 'c2' overlap" with nothing overlapping on screen). The grid library's `save()` leaves out a width or height of 1 as "the default", the server then gave the card its design's default height, and that phantom row crossed the card below. The editor now reads each card's real place from the grid.
- **A card's ⋯ menu button covered its heading's right end**: the calendar's event count, a grouped stat's total, a goals card's "5 of 8 on target". Every card's top row now stops short of the corner the button sits in; a card type of your own can use `.dash-cell-toprow`.
- **A many-to-many field on a CRUDView's model returned 500 over REST**: the serializer handed the related manager to JSON. It now writes the related rows' primary keys.
- **A `filter_fields` entry that isn't a model column broke the REST list.** `CRUDView.apply_filter` lets a view serve a filter of its own (`?dashboard=` on the components list names no column), but the generated FilterSet was still handed the name and refused it. Such a name is now left to the hook on REST, as it already was on the page.
- **The saved-card gallery had no pager, and My dashboards had none at all**, so cards past the fifteenth couldn't be reached from the gallery and My dashboards loaded every dashboard you'd made. Both page like the other lists.
- **Edit and Delete slid out of line on the components list, and Delete off the edge of the metrics list**, where a row has three actions and the column was sized for two.
- **The tag a page was narrowed to was never highlighted**: the link colour rule outranked the "current" one.
- **The top-bar mark stayed green on every palette**, with the four fills written into the template.
- **A number field's spin buttons were a white block on a dark field**; number inputs now follow the dark colour scheme.
- **The playlist editor's seconds unit was cut off** ("…" where the "s" belongs).
- **Switching off dashboards or the calendar left their MCP tools working**, writes included, though the routes were gone and the docs say "no MCP tools". The tools now follow the switch, and the Monday snapshot does too.
- **Reversing `0010_snapshot_engine` said OK and emptied the history.** It now refuses while there are captures to lose.
- **A capture saved part-way through a period stopped the real one.** Click *Capture this week so far* on Wednesday and the job never saved that week when it ended, so Wednesday's numbers stood for the whole week. It now saves the finished period on top, and *Fill in* treats a part-way capture as missing too.
- **`goal_list_add_goal` dropped `targets` and answered `ok: true`.** They're now kept, and bad ones refused, as `create_goal_list` does.
- **An at-risk line pointing the wrong way was accepted**, so 3.4% against "under 1%, at risk above 0.5%" read as *At risk*. It must now point the same way as the target and be easier to meet.
- **Goal lists answered with Python reprs** (`"snapshots": "<…GenericRelatedObjectManager object at 0x…>"`) over REST and MCP. A relation manager is left out of any CRUD response.
- **History's CSV called every column "Week of …"**, hours and months included, and marked a value with no target as "No data".
- **Saving an old week stored today's value** for a number that doesn't depend on time, where filling the same week in refused. Both now give no value.
- **`goal_list_capture {fill: 0}` captured the current period.** It's refused, on REST too.
- **Printed goal lists lost a change's direction** ("20% vs the week before"). They now say Up or Down.
- **Skipping a date that's already skipped said it "isn't a date of this series", and restoring one that wasn't skipped reported success.** Each now says what's true, and `event_skip_date` takes the `<id>-<yyyymmdd>` that `calendar_events` gives.
- **Moving a series left skips on dates it no longer has**, listed with a *Put back* that did nothing. They're dropped on save. A weekday series can no longer start on a weekend.
- **`SMALLSTACK_BLOG_ENABLED=False` left the blog's MCP tools registered.** They follow the switch, like dashboards and the calendar.
- **A trend chart refused a rate or a hand-entered metric**, saying it needed "to split it into groups", though neither a trend nor `metric_trend` does. Both now draw. Pie, ranked and grouped cards still refuse them, for that reason.
- **A trend's points could be Decimals**, which `metric_trend` sent as strings and the chart didn't draw: any hand-entered metric, or a sum over a decimal column. They're numbers now.
- **A card option nothing reads was saved and did nothing**: `dashboard_add_card {"options": {"period": "pmtd"}}` answered `ok` and the card, titled "last month", showed the dashboard's period. It's refused, naming what the card takes.
- **`metric_delete_value` on a metric that isn't entered by hand answered `deleted: false`**; it's refused, like `metric_record_value`.
- **CSV exports could run as formulas.** A report label or row value such as `=cmd|calc` reached the spreadsheet of whoever opened the download, in report, weeks, drill-down and dataset CSVs. Such cells now start with `'`; plain numbers are untouched.
- **A weekly target scored against an all-time number.** A goal with its own period on a metric with no `period_field` was judged on the all-time value; it's now refused.
- **A value a choices column can't hold reads as a clean zero** (`status = "failure"` where the value is `failed`), so a metric stayed green for ever. Saving and previewing now refuse it and list the valid values.
- **Overlapping cards saved happily, and cards with no position all landed at 0,0.** A cell with no position now goes after the cards so far, and an overlap is refused.
- **A list tool's `count` looked like the total.** List tools now answer `total` too, and refuse a `limit` under 1.
- **Agents get the number they asked for.** Over MCP and REST a misnamed period (`this_week`) returned the metric's *all-time* value with no warning; a bad period, grain or week is now refused with the valid names. A metric with no `period_field` says so in `note` rather than quietly ignoring the period.
- **MCP: every successful `metric_value` and `metric_trend` was flagged `isError: true`**, because the dispatcher tested for an `error` key rather than a truthy one (those tools answer `"error": null`).
- **MCP: `list_datasets` returned nothing and `describe_dataset` refused every bundled dataset** on a default install, while `metric_preview` and `create_metric` accepted them, so an agent had to guess names. Both now cover every dataset the caller may read; `query_tool` says whether it also has a query tool.
- **MCP: unknown arguments were dropped and the call reported success**, so `update_goal_list {"id": 1, "goal": "g1", "target": …}` changed nothing and said it had. Tools now hold callers to their schema's `additionalProperties: false`. Schemas no longer list fields a model default fills as required.
- **An average, minimum or maximum over no rows read 0**, so a quiet week's "average response under 250 ms" counted as on target. It now has no value: the card shows "—" and the goal is *no data*. Counts and sums of nothing are still 0.
- **A metric's delete left its saved cards behind**, drawing a metric that no longer exists, along with any goals on them; they now go with it. The delete page said "Nothing uses this metric" for a metric used only by goals, and never listed goal lists; `delete_metric` now answers with `also_removed`.
- **Events with a `start_time` were saved as all-day over REST and MCP**, hiding the time. A start time now makes an event timed.
- **A repeated saved-calendar-view name was an uncaught `IntegrityError`** (measured over MCP; the page and REST use the same form). It's now a field error. `dashboard_add_card {w: "abc"}` and `goal_list_weeks {weeks: "abc"}` are refusals rather than Python exceptions.
- **A misspelt grouped-card column saved fine and only failed when drawn**; `card_preview` and every save now refuse it, and a note card needs its `markdown`.
- **Dashboard stat cards drew a double border with the comparison line across it**: their cell rules had stopped matching when `.card-style` was added. Goal-board trend and change text wraps instead of being cut off.
- **The bundled requests dataset can filter on `response_time_ms`** ("requests slower than 500 ms"), and generated labels read "IP address" and "API token".
- **Help links work again.** About 130 links and URLs in the bundled docs still pointed at `/help/...`, which has returned 404 since SmallStack's routes moved under `/smallstack/`. They now use `/smallstack/help/...`, and a test keeps old-prefix links out of the bundled docs.
- **A card of its own took any aggregate.** `agg: "median"` saved and drew the row count, and `count_distinct`, the spelling `dashboard_add_card` advertised, couldn't evaluate. An unknown aggregate is refused, and the description says `distinct`.
- **`PATCH {"layout": null}` answered 200 and removed every card**, and a `null` inside the list was dropped along with its card. Both are refused.
- **Linked-card options could be found only by sending bad values.** `list_dashboard_components` now names `publish`, `listen`, `style` and `thresholds` in `shared_options`, and `dashboard_add_card` says how to link cards.
- **Archive and Share returned 500 on a row that had stopped validating** (a metric it draws went personal). Writing only bookkeeping columns skips the full check.
- **A dashboard changing hands brought back the sharing a past owner chose.**
- **A gauge's ceiling or floor of 0 was read as unset.**
- **`this_month` / `this_year` were compared against all of last month without saying so.**
- **A link channel with only one end was accepted silently**, so a typo in its name broke the click with no sign. `dashboard_add_card`, `dashboard_snapshot` and the board's `values/` name it in `warnings`.
- **Groups of a choices column read their stored values** (`high`, `fail`); they read the labels (`High`, `Fail`), on charts and in `group_values`.
- **Duplicating a dashboard shared with you failed on save** when it drew the owner's personal metrics, though Duplicate was offered. In the copy, such a card filters that metric's dataset itself (same filter, roll-up, format and colour rules); one over a hand-entered or rate metric is left out, and the form says how many of each.
- **Another person's hand-entered metric read "—"** on a dashboard shared with you, as if nothing had been entered. It reads *restricted*, like other data you can't see.
- **A member's card over a staff-only dataset listed that dataset's columns** in the refusal, and with a valid column it saved, then drew "no access". It is refused like a dataset that doesn't exist, as the builder already did. A member's dashboard holding such a card must drop it at its next edit (it never showed a number).
- **A REST write dropped keys it doesn't take without a word** (`archived_at`, a misspelt field): the 200 read as "all applied". A create or update now lists them as `ignored`, only when there are some.
- **REST and MCP couldn't archive.** `archived_at` was read-only and silently ignored, and `DELETE` destroys; an agent asked to archive did one or the other. Every owned kind (metric, card, dashboard, report, playlist, goal list) now takes `"archived": true` / `false` on update.
- **The share dialog listed every account to any member** a letter at a time, staff included. Staff still search by any part of a name; anyone else finds a person by exact username. A person added, removed and added again is notified once.
- **An all-time trend drew only its last 12 buckets**, labelled all time: a fortnight by day lost its first two days, ten weeks of data showed 12 bars. All time fits its grain to the data's span, so it now gets the same 400-bucket cap as any period.
- **`dashboard_snapshot` gave a gauge no number**, though it is a one-number design; every single-value card now carries its `result`.
- **`dashboard_share` with a username that doesn't exist answered `ok: true`** with only an `unknown` list; it also says so in `warning` (usernames are case-sensitive).
- **The OpenAPI spec said nothing about a dashboard's `layout`** (`"layout": {}`). Every CRUD field's form help text is now its `description`, and the layout's names the cell keys, the three kinds of source, that a write replaces the whole list, and where the card types are listed.
- **Sharing a dashboard with someone who can't read its cards answered `ok: true`**, and the person saw only dashes (the data was staff-only, or a rate over it). `dashboard_share` now answers `cant_read` (`{username: [card titles]}`) and a `warning` for each person added.
- **A menu link to `/\host` drew as a page of this site.** A browser reads the backslash as a slash, so it went off-site with no external marker. It's refused.
- **An app that ships default dashboards turned the framework's tests red** (29 failures for one `dashboard_defaults.py`): the after-migrate sync seeded every app's defaults into the test database. Test settings turn the sync off, and `SMALLSTACK_DASHBOARD_DEFAULTS_SYNC` is declared in `config/settings/smallstack.py`, settable from the environment.
- **A heartbeat check the run's deadline reached before it started was written as a failure**, a false outage on a healthy endpoint, the same ones every run. It records nothing and reports `skipped`, and the order rotates. A feed source in the same spot says "not fetched" rather than "still running", and rotates too.
- **Webhook deliveries no worker takes sat pending with the monitor up** (a worker started with `default,email` only). Past the grace period they trip it down. The docs' dev worker command is `db_worker --queue-name "*"`; a bare one leaves `email` and `webhooks` queued.
- **`SMALLSTACK_ACCOUNTS_EMAILS_INLINE` was never read from the environment**, though UPGRADING's remedy for a deployment with no email worker is to set it, so sign-in codes stayed queued. An empty `EMAIL_TIMEOUT=` crashed settings import; it now takes the default, 10 seconds.
- **A phone-width page scrolled sideways.** At 390px the top bar ran to 581px on every page, the dashboard header's controls stayed in one row, and the calendar's action cards sat side by side. The dashboards lists size by content on a phone, and every `.crud-table-wrap` scrolls.
- **A dashboard's name broke over two lines beside empty space**, because the header's controls took as much room as they wanted. They keep to a column now, and Share and Edit layout match the buttons beside them.

### Added
- **Duplicate anything.** **Duplicate** on a metric's, dashboard's, report's, goal list's or playlist's page and in a card's builder opens the create form with the original's settings — the conditions, aggregate, period column, format, thresholds and tags of a metric; the type, metric, options and tags of a card; the layout, items, sections, periods and settings of the rest — named "(copy)", personal to you, and nothing is saved until you save. The copy gets its own key or a free slug from its name; the original is untouched. `?from=<key or slug>` on the create forms.
- **Tags and archiving on every owned row.** Metrics, dashboards, cards, playlists, reports and goal lists take comma-separated **tags** in their forms (REST and MCP too), shown as chips on the Goals and Dashboards overviews; a chip narrows the overview to that tag (`?tag=`). **Archive** on a metric's, dashboard's, report's, goal list's or playlist's page (editors only) takes it out of every list and picker — overviews, CRUD lists, REST and MCP lists, the board editor, goal-add and rate pickers — while anything that draws it keeps working; **Restore** brings it back, and a CRUD list with `?archived=1` shows what's put away. An archived board or report no longer counts as using its metrics. Migration `smallstack_dashboards.0011_tags_archive` (two nullable/blank columns on six tables).
- **Where each metric is used, and which aren't.** The Goals overview's metrics table has a **Used in** column ("2 boards, 1 report, 1 goal list"), sortable, with a **Not used** mark and a "N used nowhere" link (`?unused=1`) that shows only those, so the pile to clear is one click away. `usage_index(user)` works it out in one pass. Before a metric is saved from the dataset browser, the modal says when one already reads those rows that way, naming it, and lists the other metrics on the dataset (`same_metrics`).
- **The dataset browser filters as you go, and makes metrics in place.** Filters apply as they change, with the row count at the right edge of the filter bar; Apply remains for a browser without scripts. **Make a metric** beside the count opens a modal with the filtered rows fixed: name it, say how the rows become a number, pick the period column, the format and who sees it, watch the value as you choose, save, then open it, make a card, or make another from the same rows. The roll-up's keep-as-card links go through the same modal and end on the component builder. The full metric page is a link away, prefilled. `dashboards/metrics/quick/` (`MetricQuickView`).
- **One goal, week by week.** Every row of the week-over-week grid has a Trends button: a bar per week with its value over the 13 weeks up to the one shown, the last week's figure against the week before and the average before, the run it's on, and each week in a table. The same at `g/<slug>/goals/<goal id>/trends/?week=` as a page.

### Changed
- **A card filters a dataset of its own; a metric goes on a single stat.** The component builder's first step is where the numbers come from. *A dataset, filtered here* gives the card its own filter (the metric form's filter editor, the roll-up, the period column) and suits any design: one number, a split, a chart. *A saved metric* is a filtered result already rolled up to one number, for goals and thresholds, so it goes on the designs that show one number; a chart needs the rows, so it filters a dataset of its own. Picking a chart while on a metric switches to that metric's dataset with its filter copied in, and **Start from a metric's filter** does the same on request. Changing the dataset clears the column options and drill-down columns that aren't in the new one, and the builder says which. A dashboard's **Add card** offers a metric's number and the designs that draw nothing; splits and charts are built in the builder. REST and MCP take `dataset` + `filter_tree` + `agg`/`measure` + `period_field` on a card. Existing charts and grouped cards get a copy of their metric's definition (`0012_card_sources`) and no longer follow edits to the metric; a metric with no dataset (entered by hand, a rate) may still be charted as it is. See `UPGRADING.md`.
- **Addresses are made from the name.** New dashboards, reports, playlists and goal lists no longer ask for an address: *Site health* becomes `site-health`, a second one `site-health-2`. Renaming never changes it, so links, embeds and wall screens keep working; the settings page shows it, and an administrator can change it on purpose (see *Only administrators change an address*). REST and MCP may still send a `slug` on create, or leave it out.
- **A dashboard's controls are in its page header.** Updated / Refresh, Duplicate, Archive, Settings and Edit layout moved up beside the title (`includes/dashboard_controls.html`); only the period bar stays above the cards. `{% dashboard %}` is unaffected: it has always drawn cards without them.
- **The components page opens on the gallery**; the table is one click away (`?display=library`). Components, Playlists and Goal lists have their own headers and descriptions in place of "Component records".
- **"Past 7 days" is seven days.** The date preset on every filter bar and CRUD list now covers the 7 days ending today, as its name says; it used to reach back 8 and run into the future. Two periods join the vocabulary, `this_month` and `this_year` (the whole month or year, days to come included), so each quick preset on the dataset browser becomes the period that covers exactly the same days and a metric made from the browser counts what the browser showed.
- **The week-over-week grid is tighter.** Column headings read both ends of the week ("Sep 7–13", "Sep 28 – Oct 4") instead of the Monday alone, the saved mark and the on-target count share one line, and the week, its line and Open · Trends sit on the same left edge as the values beneath. Rows are shorter.
- **The pager is two rows.** Under every paged list, "Rows per page" sits at the left edge and "Showing x–y of n" at the right on one line, with the page controls centred beneath. On the dataset browser the **Save as metric** and keep-as-card links carry the accent so they stand out from the quiet row controls, and a long dataset description no longer pushes the CSV card under the text on a wide screen.
- **A delivery reads as a receipt.** The newsletter delivery page (`blog/deliveries/<pk>/`) says what happened in a sentence (accepted, waiting, sending, rejected outright, gave up, skipped), lays out queued → claimed → sent with their times, shows the last error in full, and links to the issue, the blog and (for staff) the subscriber record. The framework field table is gone from that page. `Delivery` gains `verbose_name_plural = "deliveries"` (migration `smallstack_blog.0002_delivery_plural`, options only), so the list and breadcrumbs no longer say "Deliverys".
- **One filter editor.** The ALL/ANY filter-tree editor moved out of the metric builder into a shared script, `datasets/js/filter-tree.js` (+ `filter-tree.css`), so any page that filters a dataset can mount it (`SmallStackFilterTree.create`). The metric form behaves as before.
- **Clearer words.** A metric's *Period field* is **Date to count by**, and its empty choice says the number won't change over time. A repeating event's *Last day* says it's how long each one lasts, and *Repeats* starts on **Doesn't repeat**. On History, a number that can't exist at that length shows **n/a** rather than a red mark, and filling nothing says so. `goal_list_capture` takes `replace` with `fill`, to judge saved periods again after fixing a target, as `snapshot_goals --fill --replace` could. MCP descriptions now cover per-cadence `targets`, percent targets, `fill`'s limits and what `dashboard_snapshot` leaves out.
- **The calendar opens on the Events calendar** when you've chosen nothing yet, so an entry you've just added is there. **None** still clears it, and a default saved view still wins.
- **The period bar has This week and Last week**, for a weekly meeting, and **Last week now compares with the week before**: dashboards and goal lists opening on last week had no change column at all.
- **The calendar's month and board chips show 24-hour times**, like its day panel, leaving room for the name.

### Added
- **Agent read-back and the last few UI-only actions.** `get_metric`, `get_dashboard`, `get_report`, `get_goal_list`, `get_playlist` and `get_component`, taking `key`/`slug` or `id` (as do their update and delete tools, via a new `mcp_lookup_field` on `CRUDView`); `goal_list_save_week` + `POST dashboards/api/goals/<slug>/weeks/<week>/save/`; `metric_rows` + `GET dashboards/api/metrics/<key>/rows/`; `metric_usage` (a look before a delete); `csv_url` on `report_values` and `?format=csv` on its REST route; `visibility` on read-backs; "did you mean" on an unknown tool. The evaluation routes are in the OpenAPI schema, the REST detail `GET` is advertised, and their 404s are JSON.
- **A calendar on any page — `{% calendar_card %}` and the `calendar` dashboard
  card.** The calendar counterpart of `{% metric_card %}` / `{% dashboard %}`:
  name the calendars (keys, a list or a `SavedCalendarView`) and pick `month`,
  `board` or the new `upcoming` list; the tag resolves access, loads
  `/smallstack/calendar/embed/` lazily (or renders it now with `lazy=False`) and
  navigates in place — the fragment's wrapper is `hx-boost`ed, so month arrows,
  day cells and the board's toolbar swap the fragment without touching the host
  page's URL. A viewer who may see none of the calendars gets nothing, as with
  `{% dashboard %}`. The calendar app registers a **`calendar` card type** with
  the dashboards registry from its `ready()` (the worked example of a downstream
  `register_component_type`), with `calendars` / `mode` / `days` / `limit`
  options; restricted viewers get the restricted card. Service:
  `apps.calendar.embed` (`calendar_embed`, `embed_context`, `build_upcoming`);
  fourth component `calendar/components/upcoming.html`. Skill: `calendar.md`.
- **Goals (`GoalList`, migration `0007`).** Key numbers against their targets, in
  titled sections, for reading down in an operations meeting. A goal is a metric or
  a single stat card plus a target rule and an optional at-risk line, judged on
  target, at risk or missed. Lists are shared or personal.
  - **Meeting view:** `/smallstack/dashboards/g/<slug>/` opens with a summary (the
    count, a bar, what needs attention), then each section's values, targets, distance
    from target and change. `?period=` switches the period; `?present=1` drops the
    site's chrome.
  - **Editor:** sections and goals, moved by drag or ↑/↓, including across sections.
  - **Add to goals:** a dialog on the metric page, form and list, and on single stat
    cards in the components list and builder. Targets are prefilled from colour rules.
  - **Elsewhere:** a `goals` dashboard card (up to 10 goals, optionally misses first),
    goal lists as playlist slides (`{"goals": slug}`), a Goals section on the index, and
    `ComponentType.single_value` so an app's own one-number card can be a goal.
  - **Agents:** CRUD tools and REST, `goal_list_values`, `goal_list_add_goal`, and
    `GET dashboards/api/goals/<slug>/values/`.
- **Goal lists week by week (`GoalSnapshot`, migration `0008`).** The spreadsheet with a tab per week.
  - **One week** (`g/<slug>/weeks/`): move with arrows or a picker; each goal shows its change from the week before.
  - **Week over week:** goals down, eight weeks across, with a CSV download.
    - **Sorting:** by goal, or by any week's value (`?order=goal`, `?order=-w2026-10-26`). Moving between weeks keeps the sort while that week is on screen, and "Back to the list's order" restores the sections. The CSV follows the sort.
    - **Resizing:** columns resize, and the widths hold as you move between weeks.
  - **Trends modal sorting:** sort by goal, this week's value, change against the week before, change against the average before, or run length (longest first). It sorts in place, offers "Back to the list's order", and its columns resize.
  - **Trends:** a button on any week shows the weeks around it per goal: bars, change against the week before and against the average before, streak, best and worst week.
  - **Saving:** every Monday the week just ended is saved with its values and targets as they were (`tasks.snapshot_goal_lists`; `manage.py snapshot_goals`). Editors can save the current week or fill in past weeks.
  - **Agents:** `goal_list_weeks` (MCP) and `GET dashboards/api/goals/<slug>/weeks/`.
  - **In playlists:** a goal-list slide can show its goals now, last week, or week over week (`{"goals": slug, "show": "week" | "weeks"}`).
- **The goal list meeting view and the one-week view sort and resize.**
  - **Sorting:** Goal (A to Z), Status (missed first) and Value sort each section's rows in place, so the sections stay in the order you set (`?order=`). The sort survives a period change, and "Back to the list's order" undoes it.
  - **Resizing:** every column resizes, and the sections' tables keep their columns aligned. A widened table scrolls inside its card.
  - **Unchanged:** slides and dashboard cards stay static.
- **Tables sharing a resize key stay in step.** `table-resize.js` applies a resize or reset to every table on the page with the same `data-table-key`.
- **Fixed:** on narrow screens the meeting view hid the Trend column instead of Change.
- **Trends on goal lists.** Each goal shows its last six periods (weeks, months or quarters, following the list's period), each judged against the target, with a streak such as "Missed 3 weeks running". The trend also appears in `goal_list_values`.
- **The component builder's drill-down columns are a sortable, resizable table.** Sorting by column, heading or format reorders the columns the drill-down and its CSV show, with a note, Undo and nothing changed until Save. Colour rules stay unsorted because the first match wins.
- **Fixed: the metric form's "See them" rows sort and resize.** The headers had no address for an unsaved metric, so clicking one loaded the form page into the modal. They now sort by posting the unsaved metric again with an `order`, and the columns resize. Filters and colour rules stay as they are: a filter is a nested tree, and colour rules are first-match, so their order is their meaning.
- **The dashboard form lists its cards.** A "Cards on this dashboard" table shows each card's name, design, metric, size and value, sortable and resizable. Values load as rows scroll into view; sorting by value works them all out. Sorting swaps only the table, so unsaved form edits are safe, and it never moves a card. A card whose metric is gone says so.
- **The report form's rows are a sortable, resizable table.** Each row now shows Metric (with its label), Target and At risk. Sorting reorders the report's rows, with a note, Undo and nothing changed until Save; moving, adding or removing a row clears the sort.
- **The goal list form's sections are sortable, resizable tables.** Each goal is now a row: Goal, Target, At risk, Period. Sorting reorders that section's goals, because the rows are the reading order; a note says so and offers Undo, nothing changes until Save, and moving, adding or removing a goal clears the sort. Resizing a column applies to every section.
- **The playlist form's slides are a sortable, resizable table.** Sorting by slide, seconds or period reorders the slides themselves, because the rows are the play order. A note says so and offers Undo, nothing changes until Save, and moving a row by hand clears the sort.
- **The Dashboards overview's sections are sortable, resizable tables.** The List view sorts dashboards by name, cards, opens on and updated (`?dash=`), and the Cards view has a Sort select. Playlists sort by name, round length and updated (`?playlists=`), and components by name, design, metric and updated (`?components=`). Each table sorts on its own. Sorting by anything other than name or updated loads that section's rows, only when asked.
- **Fixed:** the Dashboards overview's Cards button did nothing from the List view when no other options were in the URL.
- **The Goals overview's sections are sortable, resizable tables.** Goal lists sort by name, goals and updated (`?lists=`), metrics by name, source and value (`?metrics=`), and reports by name, movement and updated (`?reports=`). Each table sorts on its own, and the sorts and the period survive one another. A metric's value sorts the metrics shown (up to 24).
- **Fixed:** the metrics filter box stopped working after a period change swapped it in place.
- **Fixed:** at phone width, the Goals overview's header buttons and the weekly grid made the page scroll sideways.
- **The reports list sorts by movement.** The movement summary ("▲ 2 up, ▼ 5 down") has its own Movement column. `?ordering=movement` puts the most fallen reports first and `-movement` the most risen; reports with nothing to compare go last. Sorting by movement evaluates every report and then pages the result (`reports.sort_by_movement`). Otherwise each row still loads as it scrolls into view.
- **Targets on reports.** A report row can take a target and an at-risk line. Its values are then coloured on target, at risk or missed, a Target column appears, the CSV gains status columns, and REST/MCP values carry each status. The editor sets a target per row, or starts from the metric's colour rules.
- **The component builder asks for a card's required choice instead of reporting it as an error.** An info card with no widget picked says "Choose a widget to see the card." The validation message no longer lists every widget key.
- **Goals is its own area of the sidebar.**
  - **Goals:** Overview, Goal lists, Metrics, Reports. The overview at `/smallstack/goals/` shows goal lists with live summaries, metrics with live values, and reports.
  - **Dashboards:** Overview, My dashboards, Components, Playlists. Its overview now shows dashboards, playlists and saved cards.
  - URLs are unchanged. Breadcrumbs for metrics, reports and goal lists now read "Goals".
- **Nav items can match several paths.** `nav.register(active_prefix=...)` takes a tuple, for an area whose pages don't share one path.
- **The component builder shows what a card takes from its metric.** It shows the format, unit and colour rules, marks anything the card overrides, and offers "Use the metric's" to reset it. Settings left alone follow later edits to the metric.
- **My dashboards as a table.** A Cards/Table switch (`?view=table`); the table's
  headers sort and its columns resize.
- **Saved cards and a component builder (`Component`, migration `0006`).** A metric
  is *what* number; a component is *how it's drawn*: a card type, its metric and the
  type's options. The key is made from the name.
  - **Builder:** `/smallstack/dashboards/components/new/` (Dashboards → Components)
    lays out a palette of every registered card type, grouped. Designs the chosen
    metric's data can't support are dimmed, with the reason. Each type's form is
    drawn from its `options_schema`, with a live preview rendered by the same
    `render_cell` a dashboard uses.
  - **Placement:** dashboards place a card with `{"component": key}` (the editor's
    Add card → Saved card). Every placement follows the card's edits; deleting the
    card leaves the copies as ordinary cards.
  - **Agents:** `create_component`, `card_preview`,
    `dashboard_add_card {component}`, and `POST dashboards/api/card-preview/`.
  - **The extension seam for charts:** `ComponentType` gains `group` (palette
    section), `icon` and `media` (JS/CSS a card needs). `{% component_media %}`
    loads `media` once on every page that shows cards. `cell_title(cell)` is the
    title helper for card types.
  - **Thresholds and styling on cards.** Single stats, grouped stats, and any app type
    that sets `stylable=True` take:
    - `options.thresholds`: the card's own colour rules, replacing the metric's
      (`[]` = none);
    - `options.style`: number format, unit, number size and colour, title size and
      colour, and alignment, from a fixed vocabulary of theme tokens
      (`components.CARD_STYLE`, no literal colours).

    The builder's **Style it** step edits both, with a live preview. Helpers for
    app types: `card_style(cell)`, `styled_value(...)`, and the `cs-…` CSS hooks.
    `apps/website`'s Trend chart opts in as the reference:
    - each bucket is coloured by the card's rules (else the metric's), and line
      charts get a dot per bucket;
    - a chosen colour paints the series and the headline;
    - the format and unit apply to every bucket and the headline;
    - success and muted states now colour bars too.
  - **Info cards take colour rules and styling** (size, colour, title, alignment).
    - Rules compare the widget's numeric `value`, else the headline's first number,
      and replace the app's status colour.
    - A placement's title now shows on the card: `smallstack/widgets/card.html`
      reads an optional `ctx.title`.
  - **Drill-downs.**
    - **Design:** a `drillable` card (Single stat, Grouped stat, Trend chart) can
      choose what its rows modal shows: up to 12 columns, each with a heading and a
      format (number, compact, decimal, percent, currency, duration, date,
      datetime, yes/no), a sort, and how many rows. The builder's **Drill-down** step
      edits it; tap the number in the preview to try it.
    - **Export:** every rows modal has **Download CSV**, with the same columns, up
      to 10,000 rows.
    - **Sorting:** clicking a column header re-sorts the rows on the server
      (`?order=`; the modal shows only the first rows of all that match). A
      second click flips the direction, dates and numbers start newest or largest
      first, and the CSV follows the chosen order.
    - **Resizing:** columns can be dragged wider or narrower, resized from the
      keyboard, or double-clicked to fit, through the framework's
      `table-resize.js`, as CRUD and dataset tables use it. Widths are remembered
      per card.
- **The metric page's "Rows behind the number" table sorts and resizes.**
  - **Sorting:** the drill-down's header sorting (`?order=`, newest or largest
    first for dates and numbers, a second click flips it), swapping the page in
    place. Changing the period keeps the sort.
  - **Resizing:** columns resize through the framework's `table-resize.js`, with
    widths remembered per metric.
- **The metrics, dashboards and reports lists are sortable, resizable tables.**
  Their library views keep what they showed (a metric's filter in words, data
  source, use and live value; a dashboard's picture, cards and health; a report's
  columns and movement), as `crud-table`s.
  - **Sorting:** Name and Updated sort on all three, and metrics also by Data
    (`?ordering=`, `{% sortable_th %}`). The metrics period bar and the sort keep
    each other.
  - **Resizing:** every column resizes with `table-resize.js`.
  - The old row-list CSS is gone.
- **The components list is a sortable, resizable table.**
  - **Sorting:** Name, Design (type), Metric and Updated sort through the CRUD
    list's `?ordering=` (`metric` joins `ordering_fields`).
  - **Resizing:** every column resizes with `table-resize.js`.
  - **Placed on** shows how many dashboards use each card.
  - A card you can't edit shows its name as text, not a dead link.
- **The playlists list is a sortable, resizable table.** Its library view keeps the
  dashboard strip and Play, but as a `crud-table`.
  - **Sorting:** Name, Each (seconds per dashboard) and Updated sort through the
    CRUD list's `?ordering=` (`{% sortable_th %}`; `seconds` joins
    `ordering_fields`).
  - **Resizing:** every column resizes with `table-resize.js`.
- **The report table sorts and resizes.**
  - **Sorting:** clicking Metric sorts A–Z and clicking a period column sorts
    largest first; a second click flips it. Rows without a number (a deleted
    metric, restricted, an error) stay last.
  - **How:** server-side (`?order=metric` / `-c0` …;
    `reports.report_order` / `sort_report`), swapped in place, with a "Back to
    the report's order" link. Both CSV links follow the order.
  - **Resizing:** columns resize through the framework's `table-resize.js`, and
    the readings still wrap.
- **The dataset browser sorts in place.** A header click swaps just the rows
  card (with the address following), like its pager, instead of reloading the
  page. Its columns were already resizable.
    - **Carrying the design:** it travels on the rows URL (`?drill=`), validated
      against the dataset, so it follows the card onto any page.
    - **For app types:** set `drillable=True` and use `with_drill()` /
      `drill_params()`.
  - **Built-in labels:** Single stat, Grouped stat, Info card, Note.
    `apps/website`'s Trend chart is the downstream example, under Charts.
- **The dashboards overview stays fast as things grow.** Each section shows the most
  recently changed few (8 dashboards, 6 playlists, 8 reports, 24 live metrics),
  with an "All N" link to the paged list. Counts use `count()`, so the page runs
  the same queries at 10 dashboards or 10,000. Dashboards switch between Cards
  and a denser List (`?boards=list`), and the period links keep that choice.

### Changed
- **Playlist slides carry a `kind`** (`dashboard` or `goals`) in `playlist_slides` and
  the REST/MCP payloads. A goal slide's `dashboard` is `None`, so code reading
  `slide["dashboard"]` needs to check `kind`. Playlist lists now count "slides".
- **Name sorting is case-insensitive on every list.** Text columns now sort with
  lowercase and capitals together ("alpha" beside "Alpha", not after "Zeta" as
  a byte-order sort put it), with the raw value as a tie-break so the order stays
  stable.
  - **Where:** `crud._apply_ordering_fields`, the one place `?ordering=` becomes a
    query, so it covers the HTML CRUD lists, the REST API and MCP, the dataset
    browser, the drill-down modal and the metric page's rows.
  - **Which columns:** Char, Text, Slug, Email and URL fields count as text,
    including through foreign keys (`user__username`) and text-typed annotations.
    Numbers, dates and foreign-key ids sort as before.
- **The dashboards forms no longer ask people to write JSON or a key.**
  - **Metric key:** made from the name on create (`open_urgent_tickets`, then
    `_2` if taken) and shown read-only. It can't change afterwards: REST/MCP
    explain with a 400 instead of quietly breaking the dashboards, reports and
    templates that use it. Agents can still choose a key on create.
  - **The "edit as JSON" boxes are gone** from the metric, report and playlist
    forms; their visual editors write hidden fields. A filter an agent wrote
    with conditions the builder can't show (NOT) is kept as-is, with a "Start
    over" option.
  - **Dashboard settings** no longer show or post the layout (cards are
    arranged on the dashboard), so a save can't overwrite a layout changed
    meanwhile.
  - REST and MCP still read and write all of it.
- **The dataset browser and the datasets index page in place** with the
  framework pager. `{% render_paginator %}` gains:
  - `hx_select` and `push_url`, for pages that answer with full HTML;
  - `page_param`, `reset` and `label`, so one page can carry several lists,
    each paging under its own parameter (the index's `fpage` / `ppage`), with
    one "Rows per page" that starts them all again at page 1.

  The tag now builds its links in Python, and the datasets app's hand-built
  pager (`_index_pager.html`, `views._pager`) is gone.

### Added
- **Dashboard playlists.** A `Playlist` (migration `0005`) shows dashboards in
  sequence: paged by hand like slides, or rotated on a timer for a wall screen.
  - **Items** are JSON an agent writes in one call:
    `[{"dashboard": slug, "seconds"?, "period"?}]`. A shared playlist holds only
    shared dashboards.
  - **Viewers** see only the dashboards they may open. A renamed or deleted
    dashboard is followed.
  - **The player** has previous, play/pause and next, one step per dashboard
    (which fills as its time runs), full screen, and keyboard shortcuts. It pauses
    on its own when the tab is hidden or someone clicks into a card. It fetches
    the next slide ahead, and works without JavaScript.
  - **Links control it:** `?slide=N&play=1|0&seconds=N&loop=1|0&kiosk=1`, and
    the address follows the current slide.
  - **Components** for downstream apps: `playlists.py` (`playlist_slides`,
    `player_options`, `player_context`, `playlist_payload`), the player include
    plus `playlist.js`, and `{% playlist "slug" play=True %}`.
  - **SmallStack pages** built on them: `/smallstack/dashboards/playlists/`
    (list, and a form with an ordered dashboard editor) and
    `/smallstack/dashboards/p/<slug>/`.
  - **Agents:** CRUD over REST/MCP, `GET dashboards/api/playlists/<slug>/slides/`
    and the `playlist_slides` tool.
- **Dashboards has a submenu** in the sidebar and topbar: Overview, My dashboards,
  Metrics, Playlists. The dashboards index has a Playlists section (each one's
  dashboards, how long a round takes, Play).
- **`CRUDView.page_sizes` — a "Rows per page" choice for any CRUD list.** Set
  `page_sizes = PAGE_SIZE_CHOICES` (`apps.smallstack.pagination`: 15, 25, 50, 100)
  and `?per_page=` picks one, defaulting to the first. The framework pager
  (`{% render_paginator %}`) shows the control, swapping the list in place and
  keeping the choice in the address; it stays visible even when everything
  fits on one page. Custom displays paginate with
  `crud_config.page_size_for(request)` (the built-in, dashboards and calendar
  displays already do); unset, a list pages at `paginate_by` as before. Every
  dashboards-app list uses it: dashboards, playlists, metrics and reports.
- **The dataset browser and the datasets index show 15 rows a page by default**,
  with a "Rows per page" choice (15 / 25 / 50 / 100, `?per_page=`) in the pager
  that keeps the filters and starts again at page 1. On the index, it sits in
  each section's pager (it was a "Per page" control above the sections,
  defaulting to 10) and sets both sections.
- **The dashboard page header shows its cover** (the photo or the generated one)
  at 16:9 beside the title.
- **The `/smallstack/` page is now an editable dashboard.** With `apps.dashboards`
  installed, it is the shared, staff-only system dashboard
  (`Dashboard.system_key="smallstack"`, migration `0003`). Staff can drag, resize
  and remove the cards, and add metric, trend and note cards next to them.
  Publishing cards is unchanged: `dashboard.register(...)` and
  `explorer_dashboard_widgets` still feed it.
  - `boards.sync_widgets` places each newly published widget once, sized by its
    `span`, and records it in `offered_widgets`, so a card someone removes stays
    removed.
  - A widget whose app is disabled leaves the page and returns with the app.
  - The system dashboard can't be deleted or made personal.
  - The core seam is `apps.smallstack.dashboard.set_dashboard_page(view)`. Without
    `apps.dashboards`, the page is the old fixed widget grid.
  - `boards.system_dashboard(key, …)` lets a downstream page pin its own dashboard
    the same way.
  - A dashboard's period bar now shows only when one of its cards reads a period.
  - The `widget` card type is labelled "App card".
- **A dashboard can have a picture, and there's a My dashboards page.**
  `Dashboard.cover_image` / `cover_alt` (migration `0002`) are set on the settings
  page (thumbnail with Replace / Remove, previewed before upload) and show on the
  index, the dashboards list and beside the dashboard's title. A dashboard without
  one gets a generated cover instead of the old layout miniature: its initials
  over a chart motif (bars, line, ring or tiles; `{% board_cover %}`, stable per
  slug), drawn in theme colours so it fits every palette. Uploads get a server-chosen name under
  `dashboards/covers/`, are checked as images (≤ 5MB), and a replaced, cleared or
  deleted dashboard's file is removed after the commit. Agents set it through
  `POST /smallstack/dashboards/api/boards/<slug>/picture/` (multipart; CSRF-checked
  for a session caller) or the `dashboard_set_picture` MCP tool (base64).
  **My dashboards** (`/smallstack/dashboards/mine/`, in the sidebar and the user
  menu) lists your
  dashboards, newest change first, each with its "needs attention" line: the
  personal ones you own and the shared ones you made. Metrics, dashboards and
  reports now record `created_by` (migration `0004`; personal rows are backfilled
  from their owner), set on every surface that creates one and returned by REST
  and MCP. Unlike `owner` it survives sharing. `OwnedQuerySet.mine(user)` is the
  query behind the page; `owned_by(user)` is personal rows only.
- **Dashboards — metrics, grid dashboards and KPI reports (`apps/dashboards/`, label
  `smallstack_dashboards`).** A framework layer over `@dataset` for numbers that
  matter, built by hand or by an AI agent. A **Metric** is a stored filter tree
  over a dataset plus an aggregate (count / distinct / sum / avg / min / max), a
  format, thresholds (→ the stat-card states) and an optional `period_field` a
  dashboard or report period narrows. One evaluation seam
  (`apps.dashboards.metrics.evaluate`) feeds every surface. A **Dashboard** is a
  12-column grid (gridstack.js 13, vendored, MIT) of lazily loaded htmx cells with a
  period bar, optional auto-refresh and an edit mode (drag, resize, Add card, Remove,
  Save). A **Report** is metrics × periods on screen and as CSV. Four card types ship:
  `metric` (the exact `{% stat_card %}` markup), `metric_group` (top-N groups + Other,
  each drilling into its rows), `widget` (any existing `/smallstack/` DashboardWidget)
  and `text` (hardened markdown). `register_component_type()` is the seam for an app
  on top (charts and so on); SmallStack itself ships no chart library. The **metric
  builder** edits the AND/OR filter tree visually from the dataset schema, with a live
  preview. `{% metric_card "key" %}` puts a saved metric on any page. All three models
  are CRUDViews (HTML + REST + MCP). The custom MCP tools are `metric_preview` (dry run:
  value, row count, every problem), `metric_value`, `list_dashboard_components`,
  `dashboard_add_card`, `dashboard_remove_card`, `dashboard_snapshot` and
  `report_values`, with matching JSON routes under `/smallstack/dashboards/api/`.
  Ownership is personal or shared, and only staff share. A card shows its number only
  to users the metric's dataset admits. `manage.py seed_dashboards` builds a demo.
  Master switch `SMALLSTACK_DASHBOARDS_ENABLED` (default on). Skill:
  `docs/skills/dashboards.md`.
- **Dataset filter trees — nested AND/OR, stored, strict.** Every dataset read path
  (`rows` / `count` / `series` / `scalar` / `queryset`) takes `filter_tree=`, REST takes
  `?filter_tree=<json>`, and the `query_dataset_<key>` MCP tools take a `filter_tree`
  object. Ops: `= != > >= < <= between in contains isnull period`, plus word aliases.
  Unlike the tolerant flat filters, a tree **raises** `FilterTreeError` (REST 400),
  listing every path-addressed problem, rather than dropping a condition. A dropped
  condition on a stored KPI silently widens the number, the fail-open shape v0.21.11
  fixed for computed columns. Ported from call_stats with that one deliberate change.
  Also added: `ds.validate_filter_tree()`, `describe_filter_tree()` (the one-line
  reading) and `and_trees()`.
- **Relative periods** (`apps/datasets/dateranges.py`): `today`, `yesterday`, `wtd`,
  `pwtd`, `mtd`, `pmtd`, `qtd`, `pqtr`, `ytd`, `prev_year`, `last_<N>`, `next_<N>`. They
  resolve at query time, so a saved "Month to date" stays current, and date filters
  advertise them in `schema()`.
- **Dataset `schema()` additions**: each filter's `ops` and `column_type`, a date
  filter's `periods`, the dataset's `aggs` and `capabilities` (`measure`, `dimension`,
  `dimension2`, `date`; `apps/datasets/capabilities.py`). A `distinct` aggregation.
- **`@dataset(access="staff"|"auth")`** (default `staff`) declares who may read a
  dataset through in-app surfaces that evaluate it for a user (metrics, dashboards,
  reports). `apps.datasets.registry.user_may_read()` checks it.
- **Dashboards UI round**:
  - **Every page redesigned** on the theme tokens: index, dashboard, metric, report, the three
    forms, the three lists, the delete pages and modals, and the rows modal.
  - **One shared previous-period comparison** (`compare_with_previous`, "vs all of last month"
    for a still-running period) on metric pages, dashboard cards, period-aware lists, the rows
    modal, and `metric_value`/REST.
  - **Lazy digests:** a report's up/down movement, and a dashboard's cards needing attention.
  - **Every value drills into its rows**, including an unsaved metric's
    (`POST dashboards/preview-rows/`).
  - **Live report preview** (`POST dashboards/api/report-preview/`).
  - **Metric delete impact** with same-transaction cleanup of cards and report rows.
- **Changing the period no longer reloads the page.** On the dashboards index, the metrics list,
  a metric's page and a dashboard, choosing a period used to reload everything: the page blanked,
  scrolled (the index jumped to an anchor), and a dashboard's cards all collapsed to "Loading…"
  and regrew.
  - Now only what depends on the period refreshes, via htmx with `hx-push-url`, so the URL updates
    and Back works.
  - On a dashboard, each card keeps its current value until the new one arrives, and auto-refresh
    continues on the new period.
  - Focus returns to the newly selected period. The links keep real `href`s as the no-JS fallback.
  - Measured in a browser: the period bar doesn't move during the switch on any of the four pages.
- **Template `<style>` blocks moved into stylesheets.** 53 blocks (about 7,200 lines across 52
  templates) are now `<app>/css/templates/<template>.css`, linked where each block was so the
  cascade order is unchanged.
  - Identical blocks share a file. The 400/403/404 pages share `errors.css`.
  - `500.html` keeps its CSS inline on purpose (it must render without static files), and so
    does the Swagger page's brand-logo rule.
  - Verified by pixel-diffing all 191 pages before and after: no visual change. The only
    differences were live data, confirmed by a second identical run.
  - New tests fail on a new inline `<style>` block, and on any `{% static %}` path a template
    references that doesn't exist.
  - `style="…"` attributes are unchanged, and `style-src` still allows them.
- **The CSP's `script-src` drops `'unsafe-inline'`** (in settings, on the API docs pages and on
  the MCP consent page). An injected `<script>` or `onerror=` no longer runs.
  - All 65 inline `<script>` blocks moved into static files that mirror the template tree
    (`<app>/js/templates/<template>.js`), loaded where each block was so timing is unchanged.
  - Server values reach those scripts as `data-` attributes on their own tag
    (`document.currentScript.dataset`); lists use JSON data blocks.
  - The pre-paint theme snippet, copied into ten page shells, is now one
    `smallstack/js/theme-init.js`. `window.SMALLSTACK` comes from `smallstack/js/config.js`.
  - The bulk-update fragment's Python-built `<script>` became a delegated listener.
  - Verified in a real browser with the policy enforced: 191 pages showed no CSP violations or
    script errors, and an injected inline handler and inline script were blocked and reported.
  - New tests fail on an inline executable `<script>` in any template, and on `'unsafe-inline'` or
    `'unsafe-eval'` in `script-src`.
  - Fixed along the way:
    - **The bulk-update dialog's field checkboxes never revealed their inputs.** The fragment's
      `<script>` was inserted with `innerHTML`, which doesn't execute scripts.
    - **A deleted CRUD row faded out but was never removed,** and an error was logged, because the
      modal cleared its row reference before the fade finished.
  - *Upgrade note:* the browser now blocks inline `<script>` blocks and `on…=` handlers in your
    own templates. Move them as described in `docs/skills/templates.md`. As a stopgap, add
    `"'unsafe-inline'"` back to `CONTENT_SECURITY_POLICY["DIRECTIVES"]["script-src"]` in your
    settings.
- **No inline event handlers anywhere in the templates.** About 150 `onclick` / `onsubmit` /
  `onchange` / `onkeydown` / `onmouseover` handlers in 55 templates are gone, covering CRUD
  tables, delete and bulk modals, backups, heartbeat, runbook, help, telemetry, tokens, webhooks,
  search, activity, calendar, blog and the starter pages. Behaviour is declared with data-
  attributes and carried out by delegated listeners in `theme.js`:
  - Generic behaviours: `data-confirm` (forms, links, buttons; checked in the capture phase so a
    "no" stops htmx too), `data-autosubmit`, `data-copy` / `data-copy-text`, `data-scroll-to`,
    `data-toggle-class`, `data-activate-in` and `data-keyclick`.
  - Page functions: `data-ss-action="name"` plus `data-ss-args` (JSON, with `"$this"` and
    `"$event"`). It calls only functions a script registered on `SmallStack.actions`, so markup
    can't reach arbitrary globals. The `data-ss-` prefix avoids colliding with Stimulus-style
    `data-action`.
  - The focus button's hover moved from JavaScript into CSS. `event.stopPropagation()` handlers
    that guarded nothing were removed; the bulk-select code listens for `change`, and links inside
    `<summary>` navigate either way.
  - `dashboard.js` dropped its own copy and auto-submit handlers in favour of these.
  - New tests in `test_template_hygiene.py` fail on any inline handler, on a `data-ss-action` no
    script registers, and on a template value in `data-ss-args` without `|escapejs`.
  - Documented in `docs/skills/templates.md`.
  - Fixed along the way: the starter page's demo "action card" called a `doAction()` that never
    existed.
- **`{% dashboard "slug" %}`** shows a saved dashboard on any page (`period=`, `title=False`,
  `lazy=False`):
  - The cards, cell endpoint, access checks and drill-down modal are the dashboard page's own.
  - The layout is plain CSS grid, and the cards stack in reading order on a phone.
  - It renders nothing for a viewer who may not open the dashboard.
  - `boards.board_embed()` gives the same structure to a page that wants its own markup.
  - `/starter/dashboard/` is a working example.
- **`trends.metric_trend`**: a metric per day, week, month, quarter or year across a period, as
  the series any chart reads. It's also available at `GET dashboards/api/metrics/<key>/trend/` and
  as the `metric_trend` MCP tool.
  - Every bucket is present: empty ones read 0 for count/sum and are gaps for averages.
  - The running bucket is flagged `partial`.
  - Each point carries the `[lo, hi)` filter for its rows.
- **`Dataset.series(..., grain=)`** is call_stats' time-grain grammar, lifted into SmallStack's
  datasets: calendar buckets with Monday weeks and `lo`/`hi` bounds.
- **A reference chart card, registered by the project, not by SmallStack.** `apps/website/dashboard_cards.py`
  adds a "Trend chart" card through `register_component_type`.
  - It draws bars or a line in theme tokens; each bucket is a labelled button that opens its rows,
    and screen readers get a table.
  - SmallStack's built-in card types stay stat and roll-up cards. Delete the line in
    `WebsiteConfig.ready()` to ship without the chart card.
- **The "Add card" dialog renders any registered type's `options_schema`** (choice, integer/number,
  text, boolean). Before this, a downstream type could be placed over MCP or REST but not from the
  dialog.
- **Filter descriptions read ISO datetimes as local dates or times** ("Timestamp ≥ 2026-10-19").
- **Declarative stat modal**:
  - Opening the global drill-down modal no longer needs inline JavaScript. `data-stat-modal="Title"`
    on any element opens it with that title (an `<a>` doesn't navigate), and `data-stat-modal-close`
    or the backdrop closes it. One delegated listener in `theme.js` handles both.
  - `{% stat_card %}`, the modal's own close button and backdrop, and the CRUD table's
    `confirm_modal` delete now use it. `openStatModal` / `closeStatModal` stay on `window`, so
    existing inline callers keep working.
  - This is a step toward dropping `'unsafe-inline'` from the CSP's `script-src`. The remaining
    inline handlers are in runbook, the backups page, the explorer example and the generic CRUD
    delete confirmation.
- **Dashboards templates carry no inline JavaScript and no hand-numbered `?v=` cache busting.**
  `{% static %}` already emits content-hashed names in production
  (`CompressedManifestStaticFilesStorage`). The metrics list's period-carry script moved into
  `dashboards/js/dashboard.js`, which now attaches its document listeners once even when htmx
  re-executes it. `tests/test_layering.py` checks every dashboards template for both.
- **`CRUDView.view_mixins = {Action.DELETE: [MyMixin], …}`** is the supported way to customise one
  generated HTML view. The mixins are ordinary Django mixins placed between the auth mixins and the
  generated base, so they use `super()`. It replaces overriding `_make_view` and assigning functions
  onto the class it returns. Dashboards and calendar have moved over; usermanager and tokenmgr still
  use the old pattern, which keeps working.
- **HTML create/edit forms get `user=`** whenever their `__init__` accepts it, the same rule REST,
  MCP and `sc` already followed (`form_bridge.build_form`). Blog and calendar dropped their copies
  of that injection.
  *Upgrade note:* a downstream form that takes `user` now receives it on the HTML views without a
  `_make_view` patch. An existing patch still works; it just becomes redundant.
- **`apps.smallstack.api.authenticate_api_request`** is the public name for the Bearer-or-session
  check that custom JSON views use. `_authenticate_api_request` remains as an alias.
- **Dashboards service layer**:
  - The logic behind the pages has moved out of `views.py` into building-block modules: `periods`,
    `comparison`, `reports`, `boards` and `previews`, with metric wording added to `metrics`.
  - Pages, REST, MCP, template tags and list displays now all call those modules, and none of them
    imports another. Before this, MCP imported its logic from the REST module, and REST, the
    template tags and the displays imported from the views.
  - `tests/test_layering.py` enforces the import direction.
  - The unsaved-metric rows route moved from the CSRF-exempt API to a session route that requires
    a CSRF token: it is now `POST dashboards/preview-rows/`.
- **`Dataset` public helpers** for apps that group a dataset's queryset themselves:
  `aggregate_expression(agg, measure)`, `column_label(name)`, `column_labels()`,
  `value_labels(dimension, rows)` (previously the private `_fk_label_map`), and the module-level
  `round_value`. `apps.smallstack.dashboard.widget_url` is the public name for `_resolve_url`.
- **`CRUDView.on_delete(request, obj)`** is a hook called just before `obj.delete()` on every delete
  surface: the HTML delete view, HTML bulk, REST, REST bulk and MCP `delete_*`. It runs inside the
  delete's transaction, so a failed delete rolls back its side effects. The dashboards metrics CRUD
  uses it to remove a deleted metric's cards and report rows, which means REST and MCP deletes no
  longer leave "metric no longer exists" cards behind.
- **Grouped dashboard cards** show each group's change from the previous period, and their groups'
  threshold states count in the "needs attention" digests.
- **`confirm_modal` on a CRUD delete action** (set from `row_actions`): TableDisplay loads the view's own
  delete confirmation into the global stat modal over htmx instead of the generic "Are you sure?" box. The view
  answers an `HX-Request` GET with a fragment. It's opt-in, so other tables are unchanged. The dashboards metrics
  table uses it to show which dashboards and reports a delete would break.
- **`describe_dataset` MCP tool**: a dataset's `schema()` for an agent, gated by that
  dataset's own `mcp_access`.

### Fixed
- **Tests no longer leak CRUDView registrations into each other.**
  - A CRUDView subclass registers itself for its model when defined. A
    throwaway one a test made for `BackupRecord`, which has no real CRUDView,
    stayed registered for the rest of the run.
  - The backups dataset then linked rows through routes that don't exist, so
    `apps/calendar`'s point-events test failed depending on which files ran
    first.
  - The root `conftest.py` now restores `CRUDView._registry` after every test,
    after loading the URLconf once so real CRUDViews are never rolled back.
    `test_crud_registry_isolation.py` pins it.
- **MCP create/update tools no longer advertise file fields.** A JSON-RPC argument
  can't carry a file and the form reads uploads only from `request.FILES`, so a
  string sent for an `ImageField` was silently dropped. File fields are now left
  out of the generated write schema; reads still return the file's URL.
- Report columns now keep the order you chose. The grouped period chips submitted in group order,
  which made "this month vs last month vs YTD" compare this month with the year.
- The metric builder broke on a metric whose stored filter is a single condition, not a group.
- `test_widget_reports_endpoint_count` asserted `"0" not in headline` and so failed
  on any two-digit count ("20 endpoints"); it now checks the count is positive.
- **Dataset browser: Apply and Roll up no longer undo each other.** The filter
  bar and the roll-up controls were two forms, each carrying a hidden snapshot of
  the other's state, so picking a new group-by and clicking Apply reverted the
  roll-up, and editing a filter then clicking Roll up reverted the filter. They
  are now one form (the roll-up controls attach with `form="ds-form"`), either
  button submits the whole page state, the current sort survives a re-submit,
  and Clear drops the filters but keeps the roll-up.
- **A timed calendar entry ending on a date (no end time) crashed the day column.**
  `date` cannot be formatted with `H:i`; the page 500'd with that day selected.
  `CalendarEvent.timed_end` now guards the end time in the day column and the
  upcoming list.
- **`/smallstack/blog/` 404'd.** The blog console is a set of CRUDViews under that
  prefix with no route for the prefix itself, yet every doc named it as the console
  path. It now redirects to the posts list, the way the webhooks and scheduler
  consoles land on theirs.
- **Native date pickers were invisible on the dark theme.** The calendar glyph in
  `<input type="date">` rendered near-black on the dark field and the popup it
  opened was white. `components.css` now sets `color-scheme: dark` on date /
  datetime-local / time / month / week inputs under `[data-theme="dark"]`, next to
  the existing rule for `<select>`. The SLA and maintenance pages, which each
  patched this locally, use the shared rule.

## [0.29.0] - 2026-10-31

### Fixed
- **Subscribing to the `.ics` feed from a calendar app could not work.** The
  help page said to mint a token and give it to the app as a password, but
  the API accepted a token only as a `Bearer` header, which Apple Calendar,
  Google Calendar and Outlook cannot send — a real subscription got 401 and
  only the signed-in browser download worked. `_authenticate_api_request` now
  also reads **HTTP Basic** credentials, taking the API token as the password
  (any username; a user's account password is still never accepted), so
  `curl -u anything:<token>` and every API route work the same way. The
  `.ics` route alone answers an unauthenticated request with a
  `WWW-Authenticate: Basic` challenge so the app prompts; JSON routes do not,
  which would make browsers pop a native login dialog. The help page now
  gives the three steps.
- **The calendar's delete pages crashed.** Both calendar CRUDViews handed the
  signed-in user to every generated view's form, and Django's `DeleteView` is
  a `FormMixin` with a bare `Form` that takes no `user`, so
  `/smallstack/calendar/events/<pk>/delete/` and the saved-view equivalent
  raised `TypeError`. The form kwarg now goes to the create and edit views
  only; a test opens and submits both delete pages.

### Changed
- **The calendar's entry and view pages have their own design.** Like Runbook
  and My blogs, the Events and Saved views pages no longer use the generic
  explorer table and form. The Events list is an **agenda** (`AgendaDisplay`,
  beside the Calendar and Board displays): rows grouped by month, each led by a
  tear-off *leaf* (month over a large day number, the end of a span under it),
  with the time, category and location on one line and Cancelled / private
  tags on the right; search, filters, sort and the delete modal are the list
  page's own and still work. The entry form is narrow, labels above fields,
  grouped **What / When / Details**, with first and last day side by side and
  a time row that switches off while All day is ticked. The entry page leads
  with the leaf and the long-form date, shows only the facts that are filled
  in, and offers **Show on calendar**. Delete is a real page with the leaf and
  a sentence on what deleting means (and when to mark cancelled instead).
  Saved views list as rows with their calendars as chips in the same series
  colours the calendar page uses (`SavedViewsDisplay`), and the view form
  picks calendars from colour-swatched tiles. Templates live under
  `apps/calendar/templates/smallstack_calendar/crud/` — the per-app CRUD
  template seam — so a project can override any one of them.
- **Selecting a day no longer scrolls the calendar back to the top.** A grid
  cell, a board day heading and the day column's × were full page loads, so a
  click after scrolling down landed you at the top of the page again. A small
  script (`calendar/js/calendar.js`) now fetches the same URL and swaps in only
  the grid/board and the day column (`data-cal-region="main"` / `"day"`), so
  the scroll position stays put; the address bar follows, and the links still
  work as plain navigation without script, with a modifier key, or if the
  fetch fails. Applies to the shared page and to every `RangeBoardDisplay` /
  `{% calendar_board %}` page (the runbook's board included); the day column is
  `aria-live="polite"` so the change is announced.
- **Calendar page: the picker is as tall as the calendar.** The Calendars
  column now stretches to exactly the month grid's (or board's) height and the
  list scrolls inside the card instead of running past the grid; the
  Subscribe (.ics) / JSON links moved into the card as its footer so the two
  bottom edges line up. A sparse 30/60/90 board gets a height floor near the
  month grid's so Month ⇄ board no longer re-flows the page. Below 1280px the
  picker still folds into a chip row above the grid.

## [0.28.0] - 2026-10-28

### Security
- **Pillow floor raised to 13.0.** 13.0.0 (2026-10-16) closes fifteen CVEs
  filed against the 12.x image decoders (CVE-2026-96638, -96640, -96778,
  -112390/1/3/9, -112401/6, -112891/2/3/4, -112900, GHSA-78g4-xqwv-q3g8) —
  the path an `ImageField` upload reaches. `pillow>=13.0` in `pyproject.toml`
  so a downstream resolve can't land on a vulnerable version; the lockfile
  moves to 13.0.0. SmallStack uses Pillow only through `ImageField`, so none
  of 13.0's removed APIs apply. The lock refresh also takes the current
  tooling patches (ruff 0.17.3, mypy 2.4.1, pytest 9.2) and croniter's
  python-dateutil 3.0; the full suite passes on all of them.

### Fixed
- **ICS `UID`s were derived from the request host.** `/smallstack/calendar/api/events.ics`
  built each `UID` from `request.get_host()`, so one event had a different
  identity per host *or port* — the same row answered `…@localhost:8055` to one
  caller and `…@localhost` to another. A subscribed client keys on `UID` to
  recognise an event it already has (RFC 5545 §3.8.4.7), so the day the host
  changes — dev → prod, a new domain, a proxy forwarding a different `Host` —
  every event re-appears as new: duplicates accumulate and the originals stop
  updating. The domain now comes from `SITE_DOMAIN` (then a URL-shaped
  `SITE_URL`/`BASE_URL`, then the request as a last resort) with the port
  stripped, so it is stable across environments. `{calendar}-{pk}` on the left
  was always stable; only the right-hand side moved. (Found by the integration
  harness.)
- **`MultipleChoiceField` was advertised as a single string.** The REST
  OPTIONS metadata, the OpenAPI document and the generated MCP tool schemas
  described a multiple-choice form field as `choice` / `"type": "string"` with
  an enum, so a schema-strict client (Claude Desktop validates tool inputs)
  would send one value where the form requires a list. Such a field is now
  `multichoice` → `{"type": "array", "items": {"type": "string", "enum": […]}}`
  on all three surfaces. (Found via the calendar's saved views.)

### Changed
- **`check_object_permission` enforces `can_update` / `can_delete` by
  default.** Those hooks used to decide only which buttons render — REST, MCP
  and the bulk views consulted them, but the HTML edit and delete views did
  not, so a CRUDView that implemented `can_update` and stopped there still
  accepted a non-owner's POST to `…/edit/`. The default now refuses with 403
  on the edit/delete routes (any method) and on every non-GET unless the
  matching hook says yes; `enforce_write_hooks()` is the reusable body for
  overrides that want to keep it. A CRUDView whose `can_update` returns
  False purely to hide a button will now also block the write — which is
  what the hook's name always promised.

### Added
- **Agent discovery, three standards.** *(1)* `AGENTS.md` is now the
  tool-neutral project instruction file (https://agents.md/ — read by Codex,
  Cursor, Copilot, Gemini CLI and, since 2.1.277, Claude Code); `CLAUDE.md`
  imports it with `@AGENTS.md` and keeps only Claude-specific notes. *(2)*
  Every registered skill in `docs/skills/` is also generated as an **Agent
  Skill** (https://agentskills.io/specification): `.agents/skills/<name>/
  SKILL.md` with spec-valid frontmatter, long skills split into
  `references/`, and `.claude/skills/<name>` symlinks for Claude Code (which
  reads only that directory). `make skills-index` writes both; `--check` (and
  so `make lint`) fails on drift. Hand-made skills in either directory are
  left alone. The former loose `.claude/skills/branding.md` became a
  registered `docs/skills/branding.md`. *(3)* **`/llms.txt`** and
  **`/llms-full.txt`** (https://llmstxt.org) publish the help system as an
  agent-readable index and a single concatenation; every help page now has a
  Markdown alternate at `…/<slug>.md`, advertised with
  `<link rel="alternate" type="text/markdown">`. New setting
  `SMALLSTACK_LLMS_DESCRIPTION` for the one-line summary.
- **Three pages on the starter site.** `/platform/datasets-calendars/` and
  `/platform/blogs-newsletters/` explain, at a high level and with
  screenshots, how datasets, calendars, blogs and newsletters work for the
  bundled apps and are ready for a project's own apps (one code example each,
  the REST / `.ics` / MCP surfaces, links to the help pages). `/prompts/`
  carries the common task-oriented prompts for coding agents with a Copy
  button each. The topbar links all three; Getting Started's "Keep going"
  section links the two platform pages and its agent aside points at the
  prompts. Screenshots live under `static/website/img/`.
- **Help: "Prompting a coding agent."** A new Getting Started page
  (`/smallstack/help/smallstack/prompting-coding-agents/`) with copy-ready
  prompts for the common first tasks — a new app on SmallStack, the public
  site, an end-user app with tenancy, a model with pages + REST + MCP, a
  calendar, a dataset, a scheduled job, an approval gate, a status monitor, a
  webhook integration, a blog, a themed page, a deploy, an upstream update, a
  diagnosis — each naming the skill files to read first, the built-in seams
  to ask for by name, and the gate (`make lint`, `make test`, two-palette
  screenshots) that counts as done. Linked from "Extending with AI".
- **Calendar app** (`apps/calendar/`, label `smallstack_calendar`) — a user
  app beside Runbook and My blogs. A *calendar dataset* is an ordinary
  `@dataset` plus a small protocol: `start` (a date/datetime column), optional
  `end` for ranged events, per-row `title` / `subtitle` / `status` resolvers
  and an `access` level (`staff` default, or `authenticated`). Declare one with
  `@calendar_dataset(...)` (every `@dataset` keyword passes through) or attach
  the protocol to an existing dataset with `register_calendar(key, ...)`. The
  ladder is CRUDView → dataset → calendar dataset: nothing is copied, the
  calendar reads rows through `Dataset.queryset()` so per-user scoping and row
  links apply. `/smallstack/calendar/` merges any number of calendars onto one
  month grid — three columns: the additive picker (a stable colour per
  calendar from the new `--series-1…8` theme tokens, light + dark), the grid,
  and the selected day's events (today by default; click a day to switch;
  grouped by calendar with a monospace time gutter). A **Month | 30 | 60 | 90
  days** control swaps the grid for a day-range board — one column per week,
  an entry card per event — and a **Weekends** toggle hides Sat/Sun in both.
  Saved views open from an A–Z dropdown. **The renderers are reusable
  components**: partials under `calendar/components/` wrapped in the
  `{% calendar_month %}`, `{% calendar_board %}` and `{% calendar_day %}`
  template tags (driven by `CalendarEvent` rows from `collect_events` or the
  new `core.events_from_objects`), and `apps.calendar.displays.RangeBoardDisplay`
  — a `ListDisplay` sibling of `CalendarDisplay` that gives any CRUDView a
  Table ⇄ Calendar ⇄ Board toggle (adopted by the scheduler's jobs and run history,
  the maintenance-window explorer, and the blog's posts and newsletter issues;
  `backward=True` for history-shaped models). `core.RangeWindow` reads the
  board's URL state for hand-rolled pages — the runbook's documents page gained
  a Table | Board toggle this way. **Provider-backed calendars**:
  `@calendar_provider(key, …)` / `register_calendar(key, provider=fn)` make the
  function the source — `fn(lower, upper, request)` yields
  `CalendarEvent.make(...)` rows — for dates that are computed rather than
  stored (rule-generated holidays, milestones, folded rotas); no dataset
  needed, and every surface reads them the same way. `CalendarEvent` gained
  `cancelled` (struck through on the board, `STATUS:CANCELLED` in ICS) and
  `image` (a small face beside the row), both also resolvers on the column
  protocol; `color=N` pins a calendar to a `--series-N` token. Hiding weekends
  is now honest: entries on hidden days are counted and announced beside the
  toggle, and a week column with no visible day in range is dropped. New
  setting `SMALLSTACK_CALENDAR_WEEKENDS_DEFAULT` (default on) makes a
  work-week desk the site default (`?weekends=1` shows them on demand).
  **The Events calendar** — the one a person types into: an `Event` model
  (all-day by default, optional times, inclusive end date, category, location,
  url, cancelled flag, members/private visibility) with a login-scoped
  CRUDView at `/smallstack/calendar/events/` (HTML + REST + MCP, so an agent
  can file one), **Add event** on the calendar page, and registration under
  one key `smallstack_events` as both a bundled dataset and a provider-backed
  calendar open to every signed-in user. `CalendarEvent` gained `calendar_label`
  (also on the events API) and `series`. The shared page renders through the
  same partials,
  month navigation, every state a link. **Saved views** (`SavedCalendarView`:
  name + list of calendar keys, one default per owner) are a per-user CRUDView
  with REST (`/smallstack/api/calendar/views/`) and MCP; **Save this view**
  prefills one from the current selection. Events API: `/smallstack/calendar/
  api/` (calendars), `…/api/events/?ds=&start=&end=` (merged, normalised
  `{calendar, id, title, subtitle, start, end, all_day, status, url}`),
  `…/api/<key>/events/`, and `…/api/events.ics` — an iCalendar feed a desktop
  or phone calendar subscribes to. MCP tools `list_calendars` and
  `calendar_events`. Eleven **bundled calendars** are attached to the framework
  datasets: maintenance windows (ranged), daily uptime (SLA-tinted), upcoming
  scheduled jobs + job runs, API token expiry (amber ≤14 days, red past),
  backups, approval deadlines, blog posts, newsletter sends, log capture
  windows (ranged) and user sign-ups — all staff-only. Plus a
  `smallstack_calendar_views` dataset, a dashboard widget, help pages at
  `/smallstack/help/calendar/` and `docs/skills/calendar.md`. New settings:
  `SMALLSTACK_CALENDAR_ENABLED` (default on; off ⇒ no nav, routes, tools or
  widget) and `SMALLSTACK_CALENDAR_MAX_WINDOW_DAYS` (default 366 — the widest
  window one events/ICS/MCP request may ask for).

## [0.27.1] - 2026-10-26

### Changed
- **Dataset browser index is paged.** Each section (Project / Framework)
  pages independently (`ppage` / `fpage`) with a shared per-page selector
  (10, 25, 50, 100; default 10) that preserves the other query params.

## [0.27.0] - 2026-10-26

### Added
- **Bundled framework datasets.** Every module that creates data now ships a
  lightweight, read-only `@dataset` over it — 27 datasets keyed
  `smallstack_<thing>` (requests, log records, heartbeats + the daily rollup,
  task attempts, workers, scheduled jobs + runs, webhook endpoints /
  deliveries / receivers / receipts, notifications, approval requests,
  collected feed items, blog posts / subscriptions / issues / deliveries,
  runbook documents + versions, users, profiles, API tokens, backups). They
  are the browse/report seam downstream reporting tools build on:
  `get_dataset("smallstack_…")` in-process, `/smallstack/datasets/smallstack_…/`
  over REST (staff-gated, `?format=csv`). Declared through
  `apps.datasets.framework.framework_dataset`, which enforces the reserved
  prefix and an explicit column allow-list — credential hashes, secrets,
  OAuth codes, payloads, bodies and task kwargs are never columns. Newsletter
  issues declare `sent_pct` / `failed_pct` ratio measures (sum over sum, never
  an average of percentages). New settings:
  `SMALLSTACK_FRAMEWORK_DATASETS_ENABLED` (default on) and
  `SMALLSTACK_FRAMEWORK_DATASETS_MCP` (default off — set it to also publish
  each as a staff-tier `query_dataset_smallstack_<thing>` MCP tool). See the
  "Bundled framework datasets" section of `docs/skills/datasets.md`.
- **Dataset browser.** A staff page at `/smallstack/datasets/browse/`
  ("Datasets" in the admin nav) lists every registered dataset and opens each
  in a generic, schema-driven viewer: filter widgets from
  `schema()["filters"]` (dropdowns, text, date presets + from/before range),
  a sortable paged table from `schema()["columns"]`, a roll-up card (group by
  any column, optional measure + aggregate, declared ratios included) and a
  Download CSV card that deep-links the REST export with the active filters.
  Hard-codes no model, so a downstream `@dataset` shows up with no wiring.
- **Dataset row links.** Every dataset row now carries a `url` key — the
  page where that record can be viewed — on `rows()`, REST, MCP and as the
  CSV's last column; `schema()["links"]` advertises it and the browser
  renders the first column as the link. Resolved generically from the model's
  CRUDView page (detail, else edit) or `get_absolute_url()`; `@dataset(link=…)`
  takes a callable or a route name to override, `link=False` opts out. A link
  that can't be built is `null`, never an error.

## [0.26.0] - 2026-10-25

### Added
- **Resizable CRUD table columns.** Every `{% crud_table %}` header now has
  a drag handle (`table-resize.js`): drag to resize, double-click to fit the
  column to its content, and — the handle is a focusable `role="separator"` —
  ←/→ to nudge, Enter to fit, Home to collapse. Widths persist in
  `localStorage` per table, keyed by `url_base` + the field list so a
  changed `list_fields` never replays stale widths, and re-apply after every
  htmx swap. Widening a column grows the table (the wrapper scrolls) instead
  of squeezing its neighbours. Two tools render under the table: **Wrap
  text** (cells wrap instead of clipping; persisted) and **Reset columns**.
  Progressive enhancement — without the script the handles and tools are
  hidden. Handles are hidden below 768px.
- **Activity drilldowns by user and by resource.** `/smallstack/activity/`
  gained a per-user page (`users/<pk>/`: histogram, status mix, top
  resources, addresses, clients, API tokens, and the user's requests /
  resources / errors) and a Resources page (`resources/`, one row per URL
  pattern plus unmatched paths) with a per-resource page (`resources/detail/
  ?r=`: histogram, who uses it, status and method mix, sample paths, the
  slowest requests). Every request row now links to its resource, its user,
  its IP, and its telemetry log lines. `RequestLog.route` (new, backfilled by
  migration) stores the matched URL pattern so `/things/1/` and `/things/2/`
  roll up together.
- **Probing & noise warning area.** The Requests page classifies the
  window's traffic (`services.probe_report`): error responses to scanner
  paths (`.php`, `/wp-admin`, `/.env`, `/.git`, traversal, dumps, consoles),
  scanner user agents, and anonymous addresses that are mostly 404s across
  many paths, mostly denied, or locked out by django-axes. A warning band
  lists the addresses with their reasons and the most-probed paths; a Probes
  tab lists every flagged request; flagged rows carry a `!` glyph
  everywhere. A flagged address contributes only its error rows, never its
  whole traffic. `ACTIVITY_PROBE_PATTERNS_EXTRA`,
  `ACTIVITY_SCANNER_AGENTS_EXTRA` and `ACTIVITY_PROBE_IGNORE_PATHS` tune it.
- **A time window on every activity page** (`?window=1h|24h|7d|30d|all`,
  default `ACTIVITY_DEFAULT_WINDOW` = 7d), carried through tabs, filters,
  sort and paging, and a traffic histogram on each page. Request tables have
  a filter bar (status, method, path contains, IP, anonymous only, exact
  path) and are resizable `crud-table`s. `{% sortable_th %}` now emits
  `data-field` + the resize handle, so any hand-written `crud-table` with a
  `data-table-key` is column-resizable.
- Sidebar sub-items under Activity: Requests, Users, Resources.

### Changed
- **Type-derived default column widths.** `.crud-table` is
  `table-layout: fixed`, so every column the view did not size got an equal
  share — a ✓/— boolean was as wide as an email column, and the email
  clipped. `_build_sort_headers` now emits a pixel default for naturally
  compact fields (booleans 110px, datetimes 170px, dates 120px, times 100px,
  durations 110px, numbers 100px, `choices` CharFields 130px); free-text,
  relation and pk columns stay unset and share the freed space. An explicit
  `column_widths` entry always wins. Documented in `tables.md`.
- The Users page leads with the per-user roll-up (hits, errors, paths,
  latency, last seen, each linking to the user page); theme usage moved to a
  Preferences tab. "Inactive" now means no logged request *and* no login in
  the window, instead of no row ever (which the retention cap made
  meaningless). Signups follow the window.
- All activity tables use the standard `crud-table`; the page-local
  primary-tinted zebra styles and the hard-coded `orange` status fallback
  are gone. Status codes render as tinted pills.
- `apps.activity` joins the strict-typing ratchet.

### Fixed
- The Activity dashboard showed "1 tracked requests" and a Requests card of
  1: the theme-usage loop reused the name `total` and overwrote the request
  count. Every headline number now comes from one aggregate.

## [0.25.2] - 2026-10-16

### Changed
- **A typing ratchet.** The global mypy config stays lenient (legacy debt in
  `apps/smallstack`, `explorer` and `usermanager` would flood the gate), but
  the apps that are already fully annotated — approvals, blog, datasets,
  feeds, notifications, runbook, scheduler, webhooks — are now checked with
  `disallow_untyped_defs`, `disallow_incomplete_defs` and
  `check_untyped_defs` via `[[tool.mypy.overrides]]`, so an unannotated
  function in any of them fails `make lint` instead of passing silently. The
  remaining unannotated signatures in those apps were completed (feeds
  parser/collector, approvals MCP helpers, webhooks views, datasets core,
  notifications inbox, scheduler post-migrate hook, runbook command), as were
  the six found in the 0.25 work (`form_bridge.build_form`, the profile Blogs
  card, the blog dashboard widget) and every dashboard widget's `get_data` /
  `get_api_extras`, which now match the base-class signature. New
  `make typecheck-strict` shows what the lenient config hides and which app to
  add next. `CLAUDE.md` documents the ratchet and that a downstream must carry
  the mypy block and run it in lint — a clone from before v0.9 never had it.


## [0.25.1] - 2026-10-12

### Removed
- **`enable_rss` and the one-flag model feed.** `ModelFeed` built its items
  from `model.objects.all()` and never applied `get_list_queryset` or
  `search_visibility`, so a single flag could syndicate drafts and other
  tenants' rows to an anonymous URL — the one place in the framework where an
  opt-in could leak private rows. Nothing upstream used it; the blog and the
  status page were already curated feeds. `apps/feeds/model_feed.py`, the
  `enable_rss` / `rss_*` attributes and `rss_item_extra()` are gone, and
  setting any of them on a CRUDView raises `ImproperlyConfigured` at import so
  a stale copy fails at startup rather than serving an unscoped feed. The
  engine — `Feed`, `FeedItem`, `register_feed`, `render_feed`, access tiers,
  token auth, the collector — is unchanged. Migration recipe in `UPGRADING.md`.

### Changed
- **Feeds are a publishing surface, not an integration one.** The README, the
  shipped site (home page pipeline, roles, surface cards, seams; the
  getting-started reference grid; the features deck, where "Webhooks & feeds"
  became "Webhooks" and feeds joined the publishing slide), the help Welcome
  table, `CLAUDE.md` and the settings comments now present RSS/Atom/JSON feeds
  as how blogs, podcasts and changelogs reach readers and the tools that
  subscribe on their own terms, with the collector filed under integrations
  for sources that only speak RSS. Integrations you own are webhooks, the REST
  API and MCP. `docs/skills/rss.md` and the feeds reference were rewritten to
  lead with the curated pattern, per-runtime-object feeds via `render_feed`,
  and a podcast enclosure example.

## [0.25.0] - 2026-10-12

### Added
- **A worked `SearchBuilder` example on the public search page.** The blog's
  `PostCRUDView` now implements `get_search_variants` + `transform_hit`
  (`apps/blog/views.py:search_hit_for_post`): a hit carries the blog name,
  publish date, reading time, tags and cover with a `card: "article"`
  discriminator, and `/search/` renders those hits as an article card
  (`templates/website/includes/search_article_card.html`) while every other
  model keeps the default row. The `compact` variant is exposed as its own
  MCP tool, `search_blog_posts_compact`. The empty `/search/` page gains a
  "Shape a result" panel with the recipe and a rendered example, so the
  pattern is visible before any post exists. Documented in
  `docs/skills/search.md` and the search reference.
- **Blog + newsletter (`apps/blog/`, label `smallstack_blog`).** Per-user blog
  channels of markdown posts, with a three-tier visibility ladder
  (`private` / `members` / `public`) instead of a single public flag — the
  middle tier is an internal team blog readable by every signed-in colleague
  and invisible to the internet. A post has its own lifecycle (draft /
  scheduled / published / archived) and both gates apply, so a published post
  in a private blog stays private and a draft in a public blog stays a draft.
  Authoring console at `/smallstack/blog/` (login-gated and ownership-scoped,
  not staff-only); public reading surface at `/blog/`.
  New settings: `SMALLSTACK_BLOG_ENABLED` (master switch),
  `SMALLSTACK_BLOG_PUBLIC_ENABLED` (the anonymous reading surface, separately
  switchable because "drafting internally, nothing public yet" is a real
  state — off ⇒ every public route 404s rather than 403s),
  `SMALLSTACK_BLOG_PAGE_SIZE`, `SMALLSTACK_BLOG_FEED_LIMIT`.
- **Newsletter sending.** Email-identity subscribers (not tied to
  `AUTH_USER_MODEL`), double opt-in, and a durable batched sender whose
  per-recipient `Delivery` rows are the progress ledger — a worker killed
  mid-send resumes without re-sending anyone.
  New settings: `SMALLSTACK_BLOG_SEND_BATCH_SIZE`,
  `SMALLSTACK_BLOG_SEND_MAX_BATCHES` (defaults drain 2,000 recipients a minute
  while keeping each task inside the lost-task reaper window),
  `SMALLSTACK_BLOG_CLAIM_TIMEOUT_MINUTES`,
  `SMALLSTACK_BLOG_SEND_MAX_ATTEMPTS`,
  `SMALLSTACK_BLOG_SOFT_FAIL_LIMIT` (consecutive soft failures, counted across
  issues and reset on any success, before an address is suppressed — a single
  transient SMTP error must never permanently drop a good reader),
  `SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL` (refuse to queue a send whose
  unsubscribe links would point at localhost — a blast cannot be recalled), and
  `SMALLSTACK_BLOG_CONFIRM_MAX_AGE_DAYS`. The unsubscribe link deliberately has
  no expiry: an RFC 8058 one-click header in a two-year-old email must still
  work.

- **The runbook → blog bridge.** A runbook `Document` can be published into a
  blog from `/smallstack/blog/import-runbook/`, from REST, or from MCP. Reads
  go through `runbook.service` + `runbook.permissions`, so locking,
  authorization and the audit trail still apply and nothing can publish a
  document its caller could not read; runbook itself is untouched and unaware.
  Frontmatter is *parsed* (title/description become the post's title and
  excerpt) rather than merely stripped, and `sync="auto"` keeps a post
  following the runbook page via the `document_written` signal while
  `sync="manual"` leaves an author's adaptations alone.
- **The writing studio at `/my/blogs/`.** A person's own blogs, apart from the
  system manager: a list of posts with drafts first (or cards, remembered per viewer), a compact editor
  (borderless title, markdown body with live server-rendered preview, a side
  rail for publishing and details, ⌘S to save), and blog settings with the
  newsletter block split out. Publish, Schedule and Archive are buttons that
  save the editor first and then transition in the same request. Reached from
  "My blogs" beside Runbook in the nav, from the user dropdown, and from a
  Blogs card on the profile page.
- **`docs/skills/blog.md`** plus six in-app help pages at `/help/blog/`,
  including *Showing posts in your own pages*: the permission scopers for a
  same-project template, the anonymous JSON API's shapes and rules for a
  separate front end, and publishing from code via the service layer, REST
  or MCP.

### Changed
- **The shipped site now frames SmallStack as a platform to build apps on,
  not an app starter — and knows about every app added since 0.13.** The
  home page's hero, "what you can build on it" shapes (internal tools, API
  backends, MCP servers, integration hubs, workflow apps, publishing), the
  pipeline (now `enable_webhooks` + `enable_rss` + the `sc` CLI alongside
  HTML/REST/MCP/search), a 16-tile batteries grid (Runbook, Blog &
  newsletter, Approvals, Notifications, Scheduler, Webhooks, Search, Logs
  join the original eight; staff get live links, everyone else the help
  page, and a switched-off app falls back to its docs automatically), and a
  new "build on it" section listing the seams the built-in apps register
  through. The about page's lede and the `features` slide deck (new slides
  for surfaces, search, webhooks & feeds, approvals & notifications,
  runbook/blog/newsletter; stale 5-palette and "recurring schedules are on
  the way" copy fixed), the getting-started page (a sixth "platform apps"
  step with the `SMALLSTACK_*_ENABLED` flags, six surfaces, an expanded
  reference grid), the help "Welcome" page (full what's-included table with
  deep links, and its `/help/...` links — which 404'd — fixed to
  `/smallstack/help/...`), and the README ledes follow the same framing.
- **UI consistency pass across Runbook, Help and Blog.** The studio's list
  pages (My blogs, a blog, settings, new blog) now use the same header band
  with the breadcrumb inside it that Runbook, Help and the CRUD console use,
  and the dashboard shows the `{% stat_card %}` row instead of a sentence; the
  editor stays flat on purpose. Button and link copy in Runbook and Help is
  sentence case ("Edit content", "New runbook", "Table of contents"); the three
  upload buttons all say "Upload new version"; "Save Changes" is "Save". The
  "On this page" rail is headed identically on all three reading surfaces.
  Runbook's visibility badge says **Signed-in** rather than "Public", because
  one sidebar entry away a public *blog* means the internet.
- **The public blog post has an "On this page" rail** built from the TOC the
  renderer already stores, shown once a post has three or more headings.
- **One hardened markdown renderer for the whole framework.**
  `render_markdown()` moved from `apps/runbook/utils.py` into
  `apps/smallstack/transforms.py`, beside the `harden_markdown_renderer()` it
  already depended on, so runbook, blog and the CRUD field preview share a
  single renderer rather than three near-copies. Re-exported from
  `apps.runbook.utils`, so every existing import keeps working. It gained
  `extensions=` / `toc=` options, and refuses `attr_list`, `legacy_attrs` and
  `md_in_html` outright: hardening strips raw HTML and dangerous URL schemes
  but *cannot* strip authored attributes, so those three reopen a stored-XSS
  vector. A fork wanting richer markdown (`codehilite`, say) passes its own
  `extensions` and owns that choice.
- **`split_frontmatter()` / `parse_frontmatter()`** added to
  `apps/smallstack/transforms.py`; `runbook.models.strip_frontmatter()` now
  delegates to it. The YAML-mapping check that distinguishes real frontmatter
  from a `---` thematic break is now shared, and malformed frontmatter degrades
  to "no metadata" rather than costing the document body.
- **`send_branded_email()`** accepts `headers=`, `connection=`, `reply_to=` and
  `from_email=`, all optional and all defaulting to the previous behaviour.
  Without them bulk list mail was impossible: `List-Unsubscribe` /
  `List-Unsubscribe-Post` could not be set at all (so no RFC 8058 one-click
  unsubscribe), and every message opened its own SMTP connection — one TCP+TLS
  handshake and one AUTH per recipient.

### Fixed
- **Cross-tenant create on the generated REST and MCP write surfaces.** CRUDView
  hands `request.user` to its HTML forms (that is how a form scopes its own
  `ModelChoiceField` querysets), but the scripted surfaces built the form with
  no user, so the queryset stayed unscoped — and on a create the form is the
  only gate. Any authenticated account could POST a post into another user's
  private blog, or do the same through `create_blog_post`. `form_bridge.build_form()`
  now passes `user=` whenever the form declares it, walking the MRO so a
  subclass that overrides `__init__` and forwards `**kwargs` still counts.
  Wired into REST create/update/bulk-update/OPTIONS and MCP create/update.
- **`serialize()` crashed on `FileField`/`ImageField` and emitted non-JSON
  primitives.** A create wrote the row and *then* 500'd (three identical POSTs
  made three posts); GET detail broke; and because `apps/webhooks` stores the
  same dict in a `JSONField` with no encoder, a `UUIDField` in `detail_fields`
  raised on the webhook write. Files now serialise to their URL (or `None`),
  and UUID/Decimal/timedelta to strings — the REST wire format is unchanged.
- **A webhook fan-out failure silently discarded the caller's write.** `fan_out()`
  runs in a `post_save` receiver inside the caller's `atomic()`; a failed delivery
  INSERT marked the block for rollback, so `service.create_post` returned a pk
  and left no row. Each delivery INSERT now runs in its own savepoint.
- **`api_expand_fields` and `.only()` were mutually exclusive.** Expanded FKs
  were joined but deferred, so `/smallstack/api/blog/issues/` 500'd with no
  client input. Expanded fields now join the `only()` set.
- **`blog_send --dry-run` sent the newsletter for real** when `--issue` was
  omitted. The flag is now honoured before the drain, reaping is skipped too,
  and `service.pending_send_summary()` is read-only.
- **Queueing a second issue for one post answered 500.** `queue_issue` now
  raises a readable `AlreadySending` naming the live campaign; the database
  constraint remains the guarantee.
- **`SMALLSTACK_BLOG_ENABLED=False` did not take the public blog offline.** Only
  `ready()` honoured it: the public routes, JSON API, per-blog feeds and both
  scheduled ticks kept running, and a disabled blog published a scheduled post.
  `public_surface_enabled()` now requires both switches and the tick bodies
  check the flag themselves. `SMALLSTACK_BLOG_PUBLIC_ENABLED=False` also
  unregisters the site-wide `/feed/blog.rss` river.
- **Blog slugs were enumerable anonymously.** Members blogs redirected to
  login while unused slugs 404'd; the first fix moved the oracle onto private
  blogs. An anonymous visitor now gets the same login redirect for members,
  private and no-such-slug alike; a signed-in visitor still gets an honest 404.
- **An explicit `https://` in `SITE_URL` was downgraded** to `http://` in
  mailed unsubscribe and permalink links when `USE_HTTPS` was left at its
  default. The explicit scheme now wins when it names the same host.
- **Auto-synced runbook posts had no monitor.** `sync="auto"` enqueues a task,
  so with no worker the post silently kept old text; `AutoSyncMonitor` now
  reports it on the status page.
- **`p` (the shortlink prefix) was not a reserved blog slug**, and
  `canonical_url` reached an `href` unfiltered from trusted internal callers.
  Both closed; a test walks `public_urls.py` so the reserved set cannot drift.
- **MCP tool registry leaks between tests.** Several suites wipe
  `TOOL_REGISTRY` / `TOOL_HANDLERS` with `clear_registry_for_tests()` to
  test registration in isolation and left them empty for the rest of the
  process, so any later test asserting "my app's tools are registered"
  passed or failed on file order alone — green in the default alphabetical
  run, 24 failures when `apps/search apps/mcp apps/blog` ran together. The
  root `conftest.py` now snapshots both registries before every test and
  restores them after (`apps.mcp.server.isolated_tool_registry`), pinned by
  `apps/mcp/tests/test_registry_isolation.py`. The per-app conftests that
  re-registered their own tools to cope (runbook, webhooks, approvals,
  telemetry) still work and are now redundant.
- **Help's dark theme was hard-coded again.** `help.css` carried 26 legacy-grey
  literals (`#1e1e1e`, `#3a3a3a`, `#e0e0e0`, …) inside `[data-theme="dark"]`
  blocks — the exact anti-pattern `modern-dark-theme.md` cites that file as
  the fixed example of. It rendered correctly on the purple palette and muddy
  on orange and gold. Every value is now a theme variable, Runbook's one
  literal (the toggle thumb) is `--button-fg`, and a new test pins every app
  stylesheet literal-free so it cannot drift back quietly.
- **The search hub advertised MCP tool names that don't exist.** Two functions
  derive the name — `registry._mcp_tool_name_for` for the "what's indexed"
  panel and `mcp_tools._tool_name_for` for the actual registration — and they
  had drifted onto different attributes (`mcp_tool_name` vs the documented
  `mcp_tool_noun_plural`), despite a comment saying they were kept in sync.
  Runbook was the shipped instance: the panel said `search_documents` while the
  registered tool was `search_runbook_documents`, so an agent reading the panel
  to learn the tool name called something that did not exist. A test now pins
  the two derivations together for every registered view.
- **Scheduler tick tests were not isolated from code-declared jobs.**
  `services.run_due_jobs()` is global — it runs every job that is due — so a
  test asserting `enqueued == 0` was implicitly asserting that no app anywhere
  in the project has a `@scheduled` job due at that moment. That held only
  while every bundled cadence was 5 minutes or longer; adding a one-minute job
  broke eight unrelated tests intermittently, depending on how long the run had
  been going. `apps/scheduler/tests/conftest.py` now clears code-declared rows
  and suppresses the lazy sync per test, so a downstream project with a
  frequent job does not inherit the same puzzle.
- **CRUDView filter dropdowns ignored the view's tenancy scope.** `filter_fields`
  builds a `<select>` per field, and for a `ForeignKey` the options came from
  `related_model._default_manager.all()[:100]` — the whole related table,
  whoever was looking. On a tenancy-scoped CRUDView (the documented end-user
  pattern in `building-a-user-facing-site.md`) `get_list_queryset` correctly
  hid other people's rows from the table while the filter bar above it listed
  them by name. `/smallstack/tokens/` is the shipped instance: reachable by any
  signed-in user, scoped by `owner`, and declaring `user` among its
  `filter_fields`, so its filter bar enumerated up to 100 usernames from the
  installation. Choices now come from the tenancy-scoped list queryset, taken
  *before* the request's own filters are applied so the dropdowns stay
  switchable; the low-cardinality distinct-values branch is scoped the same
  way. Staff and `user=None` callers are unaffected.
- **The search hub's "what's indexed" preview ignored `search_visibility`.**
  `get_indexed_sources()` sampled five recent rows with
  `model._default_manager.all()` and rendered their display values and links,
  applying only the per-view *access tier*. For any view whose tier is broader
  than staff, that previewed other users' rows — including unpublished ones —
  to every caller the tier admitted. Now scoped exactly as `search_all()`
  scopes hits, with staff and trusted-internal callers bypassing as before and
  a raising callback failing safe to no preview. The row *count* stays
  table-wide by design: on Postgres it is a planner estimate, and a per-user
  `COUNT` would undo that on every render.

## [0.24.0] - 2026-10-11

### Added
- **The agent skill index is generated, and `make lint` checks it.**
  `docs/skills/README.md`'s tables are now the single source of truth;
  `docs/skills/index.json` is generated from them by `manage.py skills_index`
  (`make skills-index`). `--check` runs inside `make lint` and the pre-commit
  hook, failing on a skill file registered nowhere, a row pointing at a missing
  file, or a stale index. Hand-curated `name` / `keywords` / `use_when` fields
  carry forward across regeneration, and a `**(upstream repo only)**` or
  `**(forks / downstream)**` prefix on a row becomes a `scope` field agents can
  read. The checks assert self-consistency only — never that a particular skill
  exists — so a project built on SmallStack stays free to add, delete or rewrite
  skills. It no-ops where there's no `docs/skills/README.md`.
- **`docs/skills/local.md`** — a skill registry upstream never ships, so a
  project can register *its own* skill files (tagged `"origin": "fork-local"` in
  the generated index) without taking a merge conflict on every
  `git pull upstream main`.

### Fixed
- **The skill index agents consult was two-thirds empty.** It listed 29 of 76
  skill files: every read-first skill (`modern-dark-theme`, `cli-tools`,
  `accessibility`, `modify-palettes`) was missing, 19 of the 25 files `CLAUDE.md`
  names were absent, and it still carried an entry for `report-card.md`, deleted
  releases ago. Nothing read it and registering a skill meant hand-editing two
  files with no check, so it had rotted since 0.8.7. Now 76 of 76, with 11 files
  that had no README row given one (`crud-views.md` and `from-zero-to-running.md`
  among them) and 54 entries carrying keywords + `use_when`.
  (Downstream-reported: a fork's own skill file was referenced by `CLAUDE.md` but
  registered in neither index, so an agent looking for release guidance found
  upstream's `release-process.md` — exactly the wrong one for a fork.)
- **`release-process.md` now says it's upstream-only** and points a fork at
  `integration-workflow.md` / `downstream-release-migration.md` instead; its own
  "Version Locations" table named a file that no longer exists and omitted
  `CHANGELOG.md` and the post-bump `uv sync`.
- **Shipped docs no longer name the maintainer's own projects.** Deployment
  hostnames and project names from the author's workspace appeared in
  `integration-workflow.md`, `UPGRADING.md`, `kamal-deployment.md`,
  `screenshot-workflow.md` and others, which every clone inherited as if they
  were its own. The screenshot "port reference" became the rule it was hiding:
  8005 is the default here *and* in every clone, so two checkouts collide —
  override with `PORT=N`.

## [0.23.1] - 2026-10-11

### Changed
- **The shipped workers now run under a readable label.** Every `db_worker`
  launch site passed no `--worker-id`, so upstream's random 32-char default
  became the label and the heartbeat table read
  `oxp0RB1Z85F7X4yFX7IO8Vc1kAedLTER#a1b2c3…` — useless to an operator trying to
  tell one worker from another. The inline worker in `docker-entrypoint.sh` is
  now `web` (accurate: it runs inside the web container), `utils/dev_services.sh`
  is `dev`, and the commented-out separate worker container in
  `config/deploy.yml` is `worker` so it can't collide with the inline one if
  someone uncomments it. All three honour **`SMALLSTACK_WORKER_ID`** for
  deployments running several. Reusing a label across restarts is safe — the
  worker appends a per-process token (`web#a1b2c3…`), which is what v0.23.0's
  incarnation change made true — so this only needed the labels, no behaviour
  change. A guard test pins every shipped launch site, since these are shell and
  YAML that no unit test executes and a dropped flag would silently restore the
  unreadable default. (Downstream-reported from a production migration.)

## [0.23.0] - 2026-10-11

### Added
- **Lost tasks no longer stay `RUNNING` forever.** `django-tasks-db` never
  finished a task whose worker was SIGKILLed, OOM-killed or replaced mid-run.
  SmallStack now ships its own `db_worker`, which shadows the upstream command
  (same arguments; every existing entrypoint, compose, Kamal and dev-script
  invocation picks it up unchanged). Each worker writes a `WorkerHeartbeat` row
  (`apps.tasks`), refreshes it every `SMALLSTACK_TASKS_HEARTBEAT_SECONDS` (15),
  and runs a reaper at startup and then every 4 beats — about once a minute at
  the default interval, and proportionally less often if you raise it (the
  4-beat period is fixed, so `HEARTBEAT_SECONDS=300` means a reap every 20
  minutes). The reaper fails a
  `RUNNING` task as `apps.tasks.exceptions.WorkerLost` when its worker exited, or
  hasn't heartbeated for `SMALLSTACK_TASKS_LOST_AFTER_SECONDS` (90), or has no
  heartbeat row at all and the task started more than
  `SMALLSTACK_TASKS_ORPHAN_SECONDS` (86400) ago. The traceback's last line
  explains why — naming the host, pid and last-seen time when there is a
  heartbeat row to read them from, and how long the task has been `RUNNING` when
  there isn't — and the scheduler's run summary shows it.
  The update is conditional on `status=RUNNING`, so a late finish always wins
  and concurrent reapers are safe. Timestamps are written and compared on the
  **database** clock, so the thresholds don't measure NTP skew between hosts.
  `manage.py reap_tasks [--dry-run]` runs a
  pass by hand. `SMALLSTACK_TASKS_HEARTBEAT_ENABLED=False` turns the worker back
  into a plain pass-through — note that this also removes the only thing that
  *runs* the reaper, so if you disable it, schedule `manage.py reap_tasks`
  yourself or nothing will ever reap. New migration: `tasks.0001_initial`; run
  `migrate`.
- **Task retries with backoff** (`apps/tasks/reliability.py`). Put
  `@retry_policy(max_attempts=3, backoff=5, backoff_max=600, retry_on=(OSError,))`
  above `@task`. When an attempt fails, a fresh copy of the task is enqueued
  with `run_after` set by exponential backoff with jitter. It keeps the same
  args, queue, priority and backend. Every attempt is its own result row, so
  every traceback is kept. A `TaskAttempt` row links each retry to its chain.
  Its `parent_id` is unique, so the three paths that can retry (the worker's
  `task_finished` signal, the reaper for lost tasks, and a repair sweep for
  retries a crash skipped) never produce two retries. By default a lost or
  force-stopped attempt is retried too (`retry_lost=True`). **Retries are
  opt-in**: `SMALLSTACK_TASKS_DEFAULT_MAX_ATTEMPTS` defaults to 1 because
  execution is at-least-once. The built-in email tasks (`send_email_task`,
  `send_html_email_task`, `send_welcome_email`) now retry up to 3 attempts on
  `OSError` (SMTP and socket errors). `SMALLSTACK_TASKS_BACKOFF_SECONDS` (5) and
  `SMALLSTACK_TASKS_BACKOFF_MAX_SECONDS` (600) set the defaults. Retries only
  happen on the database backend; `ImmediateBackend` behaves as before.
- **Scheduled jobs retry: `ScheduledJob.max_retries` is live.** It was
  "Reserved" until now. It's editable in the scheduler form, REST and MCP, where
  a validator caps it at 10 (the cap is not a database constraint). When greater
  than 0, each run's first attempt is enqueued in the same transaction as a
  pinned budget of `max_retries + 1` attempts. This pins the **attempt count
  only** — which exceptions retry (`retry_on`), whether a worker death retries
  (`retry_lost`) and the backoff still come from the task's own `@retry_policy`,
  so `max_retries=5` on a task declaring `retry_on=(OSError,)` will not retry a
  `ValueError`. On a task with **no** `@retry_policy` the pinned budget uses a
  deliberately conservative fallback: any exception the task *raises* retries,
  but a run whose worker died mid-task is **not** re-run, because re-running a
  half-finished task is an at-least-once decision only an explicit
  `@retry_policy(retry_lost=True)` may make. 0 (the default) means
  the task's policy applies unchanged. The scheduler now reads a run's outcome
  from the **latest attempt** of its retry chain
  (`apps.tasks.reliability.chain_outcome`). A run stays `QUEUED` while a retry
  is pending, so the overlap guard keeps waiting for it. The run ends `SUCCESS`
  with an "(attempt N)" suffix if a retry succeeds. The failure email goes out
  once, after the last attempt, with an "after N attempts:" message. A failed
  attempt with budget left that no retry ever picks up is treated as final
  after an hour. Migration: `scheduler.0004_max_retries_live` (help text and
  validator only).
- **Explorer → System** now also lists **Worker heartbeats** (which workers are
  alive, when each was last seen or stopped) and **Task attempts** (retry
  chains). Both are read-only.
- **Scheduler failure emails include the error** ("Error: after 3 attempts:
  …"), not just the first attempt's result id.
- Docs: a Reliability section in `docs/skills/background-tasks.md` and in the
  help page. Also updated the scheduler skill and help pages (retries), the CLI
  reference (`db_worker`, `reap_tasks`), `cli-tools.md`, the settings
  reference, and `UPGRADING.md`.

### Compatibility
- **A failed attempt that is being retried no longer logs like a real failure.**
  Django's `log_task_finished` logs every `FAILED` result at `ERROR` with a
  traceback, including attempts this layer is in the middle of absorbing — so a
  task that fails twice and succeeds paged someone twice, and the feature's
  success became its own false-alarm source. SmallStack now owns that record
  (`apps/tasks/signals.py`): an attempt with a retry enqueued logs `WARNING`
  with `retrying_as=<id>` and no traceback, a final failure keeps `ERROR` with
  the traceback, and both use the same `django.tasks` logger and
  `Task id=… path=… state=…` prefix so existing alert rules and parsers still
  match. `SMALLSTACK_TASKS_SOFTEN_RETRYABLE_LOGS=False` restores Django's stock
  behaviour.
- **`django-tasks-db` is pinned to one minor** (`>=0.13,<0.14`). `apps/tasks`
  shadows that package's `db_worker`, subclasses it, and imports its
  `DatabaseBackend` and `DBTaskResult`, so a minor bump can stop the whole
  reliability layer importing — which is exactly what 0.12 → 0.13 did. A floor
  alone could not have caught it. The 0.12 compatibility shim is gone with it:
  unreachable under the pin, so untestable, and its failure mode was a double
  delivery that enqueues a retry and then cancels it.
- **Works with django-tasks-db 0.13** (shipped in v0.22.0) and still with 0.12.
  0.13 removed its bundled `django_tasks` package, so the reliability modules
  now import `TaskResultStatus` from `django.tasks`. Before this change the app
  failed to start at all on 0.13. 0.13's worker also sends Django's own
  `django.tasks.signals`, the same signals `ImmediateBackend` sends, where
  0.12 sent a private pair. The retry receiver therefore now acts only when
  `sender` is a `DatabaseBackend`. It accepts both the instance (upstream's
  success path) and the class (its failure path). It also stays subscribed to
  0.12's signal when that package is present. 0.13's new
  `db_worker --exclude-queues` passes through, and the heartbeat row records it
  ("* (excluding email)").
- **Every failed attempt now logs at ERROR, retried or not.** On 0.13 the worker
  sends Django's signals, and Django's own `log_task_finished` receiver logs
  each `FAILED` result to the `django.tasks` logger at ERROR, with the
  traceback. That includes attempts `@retry_policy` is about to retry. The
  retry itself still logs at INFO (`apps.tasks.reliability`: "retrying … as …").
  If you alert on ERROR, key the alert on the chain's final outcome (the
  scheduler's failure email, or `chain_outcome`), not on individual attempts.
- **`safe_reap()` no longer closes a caller's database connection.** It
  refreshed connections with `close_old_connections()`, which closes any
  connection inside an `atomic()` block. On Postgres that killed the caller's
  transaction ("the connection is closed"), while SQLite's in-memory test
  database ignored it. It now skips connections in an atomic block
  (`heartbeat.refresh_owned_connections`). The worker's own calls run in
  autocommit and were never affected. This predates 0.13. Three tests had been
  failing on Postgres only. The full suite now passes on SQLite and on
  Postgres 16.

## [0.22.0] - 2026-10-10

### Removed
- **The `mcp` SDK is no longer a dependency.** SmallStack implements the
  protocol itself — JSON-RPC envelope, `initialize`/`tools/list`/`tools/call`
  dispatch and OAuth are plain Django in `apps/mcp/views.py` — and the package
  was declared for one thing: a singleton `mcp.server.lowlevel.Server` that
  nothing ever read. Removing it drops **20 packages** from every install
  (`pydantic`, `starlette`, `uvicorn`, `sse-starlette`, `httpx2`, `jsonschema`,
  `pyjwt[crypto]`, `opentelemetry-api`, `anyio`, `cryptography` and others —
  several of them ASGI machinery SmallStack never runs). The MCP surface is
  unchanged: tools, `@tool`, `TOOL_REGISTRY`, `/mcp`, OAuth, Claude Desktop and
  `MCP_SERVER_NAME` all behave exactly as before. `mcp_doctor` loses its
  `"mcp package"` row, which only verified that its own dependency was
  importable; every check describing the live surface stays. **If your own code
  does `import mcp`, declare it in your own `pyproject.toml`** — see
  `UPGRADING.md`. A new test guards against the import creeping back, because
  it would keep working in any virtualenv that still has the package and fail
  only on a clean install.

### Security
- **Django floor raised to 6.1.2** (released 2026-10-06), which fixes four
  security issues. Two apply to any SmallStack install: **CVE-2026-77050**
  (denial of service in `get_supported_language_variant()`, i.e. Accept-Language
  parsing) and **CVE-2026-84429** (denial of service in HTTP header parsing).
  The other two are GeoDjango request forgery (**CVE-2026-87890**, not applicable
  — SmallStack doesn't use spatial lookups) and privilege abuse in model
  formsets with editable primary keys (**CVE-2026-87975**). The floor is raised
  rather than only re-locked, so a downstream resolve can't land on a
  vulnerable version.

### Changed
- **Dependencies refreshed across the board** (`uv lock --upgrade`): notably
  django-tasks-db 0.12→0.13, django-filter 25.2→26.2, gunicorn 25→26,
  mcp 1.27→2.3, psycopg 3.3.6, starlette 1.3→1.7, tzdata 2025.3→2026.5, plus
  dev tooling (ruff 0.15→0.17, mypy 2.3→2.4, django-stubs 6.0→6.1).
- **`apps/tasks/tracing.py` survives the django-tasks-db 0.13 restructure.**
  0.13 dropped the bundled `django_tasks` package for Django's own
  `django.tasks`, so the unguarded `from django_tasks.signals import …` at
  import time broke startup outright (`manage.py check` included). That import
  is now guarded exactly like the built-in one already was, so trace binding
  keeps working on **either** version rather than the one that happened to be
  installed. The tracing tests were asserting "both signal pairs exist" — true
  for one dependency generation only; they now assert the durable invariant:
  *every* pair available on this install is subscribed (and at least one is).
- Six `form_valid()` overrides carry a scoped `# type: ignore[override]`:
  django-stubs 6.1 flags narrowing the parameter to the view's own `form_class`
  as a Liskov violation. The narrower type is accurate at runtime (Django only
  passes `get_form()`'s result) and more useful to a reader; the formally-correct
  fix — parameterising `UpdateView[Model, Form]` — needs
  `django_stubs_ext.monkeypatch()` at runtime, and django-stubs is dev-only here.

Verified on **Python 3.13 and 3.14**, and on **SQLite and Postgres 16**:
2,684 / 2,685 tests green, ruff + mypy clean. `requires-python` stays at
`>=3.12` — Django 6.1 supports it and it's maintained until 2028, so raising
the floor would break downstreams for no gain. (Django 6.2 is **not** released;
6.1.2 is the current stable.)

### Added
- **`schema()["filters"]` now advertises a widget for computed (annotated)
  dataset columns.** v0.21.11 made those filters apply; this makes a builder UI
  able to *offer* them. The widget is typed from the annotation — booleans get
  All/Yes/No, date/datetime get the usual preset dropdown plus `range`, and
  anything else gets a dropdown of the values actually present (probed, capped
  at 30 distinct — the ceiling model fields already use). The pairing is the
  point: a **choice widget means an exact match** in this framework and
  computed columns compare exactly, so a dropdown is the only control whose
  semantics are honest. Two cases stay unadvertised on purpose — **aggregate**
  annotations (probing the domain would mean a GROUP BY over the table, and the
  filter is a `HAVING`) and computed strings with **>30 distinct values** (a
  text box would promise substring matching the exact comparison won't
  deliver). Not offered ≠ not supported: the filter still applies when the
  param is passed.

## [0.21.11] - 2026-10-10

### Fixed
- **Filters on computed (annotated) dataset columns are no longer silently
  ignored.** `_apply_list_filters` resolved every declared filter name with
  `model._meta.get_field()` and skipped the filter when that raised — so a
  plain filter on an annotation (`?hours_band=business`, `?route=on_call`,
  `?answered=1`) was dropped and the query returned **every row**. No error and
  no empty result, which is the dangerous shape for an analytical surface: a
  tile labelled "business hours" quietly showing all hours. It also broke two
  documented promises — "every operation works on a computed dataset" and the
  one-filter-contract-for-rows/series/scalar invariant. The pipeline now
  consults `qs.query.annotations` before giving up and types the comparison
  from the annotation's `output_field` (booleans take 1/0/true/false,
  date/datetime take the usual presets, everything else is an exact match —
  computed columns are categorical). Genuinely unknown keys are still
  tolerated-and-ignored, and only *declared* filter fields are considered, so
  nothing new is filterable by accident. Annotated CRUDView querysets get the
  same fix for free. (Downstream-reported; they patched their own copy.)

## [0.21.10] - 2026-09-28

### Fixed
- **`help_article_count()` no longer re-parses the whole markdown corpus on
  Postgres.** The last ENGINE-string check in `apps/help/search.py` (everything
  else had moved to `connection.vendor`) was written when only SQLite had a
  help FTS table, so **every non-SQLite engine — i.e. production** — counted
  articles by calling `build_search_index()`: a full re-read and re-render of
  every markdown doc, ~1.5s locally and seconds on a small box. `@lru_cache`
  bounded it, but `sync_help_index()` *clears* that cache, so after v0.21.9
  gave Postgres a real lazy index build, each build made the next count pay the
  parse again. Postgres has had `help_articles_search_idx` since v0.21.9, so it
  now takes the same cheap `COUNT(*)` as SQLite — and the number means the same
  thing on both engines (rows in the index, which is what "currently indexed"
  claims). Guarded by a test that fails if a count ever parses markdown.
  (Downstream-reported, with their own equivalent guard.)

### Changed
- **`test_transaction_safety.py` no longer fails a downstream that routes help
  search differently.** The v0.21.9 memo self-heal tests drove
  `search_help_articles()`, so they also asserted *which engines route to FTS* —
  a separate contract, and one a downstream may legitimately override. They now
  drive the engine's FTS query path directly (where the fix lives), and the
  routing contract gets **its own named test**, so a diverging project sees one
  honest failure instead of three misleading ones. `docs/skills/testing.md`
  gains the general rule with the three cases that taught it.

## [0.21.9] - 2026-09-28

### Fixed
- **`rebuild_search_index` can run inside an open transaction again, and
  `ensure_index` stops locking provisioned tables.** The Postgres backend
  guarded its GIN index with `_index_exists` but issued the column
  `ALTER TABLE … ADD COLUMN IF NOT EXISTS` unconditionally. Verified against
  PG 16, that costs two things even as a no-op: it takes an
  **AccessExclusiveLock** on the table (every `post_migrate`, every rebuild —
  briefly blocking every reader and writer on a live table), and Postgres
  refuses it outright when the transaction holds pending **deferred**
  constraint trigger events (`cannot ALTER TABLE "x" because it has pending
  trigger events`). A new `_column_exists` guard mirrors the existing index
  guard, so a provisioned model issues **no DDL at all**. Note the refined
  mechanism vs. the downstream report: plain writes aren't enough — a
  non-deferrable FK's after-row trigger fires at end of statement, so it takes
  `SET CONSTRAINTS ALL DEFERRED` (what `loaddata` does) or a deferrable
  constraint. (Downstream item #6.)
- **Help search no longer poisons the caller's transaction on Postgres.** Every
  raw query in `apps/help/search.py` sat inside a bare `except Exception` —
  including the "does my FTS table exist?" probe, which asks by running
  `SELECT COUNT(*)` and catching the failure. On Postgres that aborts the whole
  transaction, so the swallowed probe killed every later query in the request:
  help-search 500s, the activity middleware's log write, and (how it was found)
  two unrelated approvals *search* tests. All six such cursors now run in
  `transaction.atomic()`. Second layer: `_HELP_INDEX_BUILT` is a process-global
  memo of *database* state, so a dropped/restored index left help search empty
  until the process restarted — a failed query now clears the memo and the next
  call rebuilds. Found by running the full suite against a real Postgres 16;
  **both suites are now fully green on both backends** (2,664 PG / 2,663 SQLite).
- **`test_orphan_renders_muted_with_remove` no longer assumes `pk == 1`.**
  Postgres sequences are not transactional — `nextval()` survives the test
  rollback — so the hard-coded pk passed in isolation and failed whenever an
  earlier test in the session created a `MonitoredSurface`; SQLite's rowid
  counter rolls back, hiding it. The test now asserts the row's own pk. This
  was the downstream's one undiagnosed failure; diagnosed and reproduced here
  against a real Postgres 16.

### Documentation
- `sqlite-vs-postgres.md`: a dedicated section on **`except Exception` around a
  DB statement** — the bug hit four times in one week — including *"the visible
  error is not the culprit; read the Postgres server log"* and *"probe by
  failing is not free"*. Plus **sequences are not transactional** — never assert a
  literal primary key (plus the checklist item), and **existence-check DDL
  before issuing it** — `IF NOT EXISTS` is not free (AccessExclusiveLock +
  the deferred-trigger-events refusal, with the exact conditions).

## [0.21.8] - 2026-09-27

### Fixed
- **The test suite's throwaway MCP tables no longer break Postgres teardown.**
  The root `conftest.py` creates `mcp_server_widget`/`mcp_server_gadget`
  (managed=False, schema_editor) with real FK constraints to `accounts_user` —
  and since flush doesn't truncate unmanaged tables, Postgres refused to
  TRUNCATE `accounts_user` at every `transaction=True` teardown ("cannot
  truncate a table referenced in a foreign key constraint"), failing 46 tests
  and leaking rows that surfaced as duplicate-username collisions later. The
  FKs are now `db_constraint=False` (ORM joins/expansions unchanged), with an
  introspection test that fails on any backend if a real constraint returns.
  Fourth of the SQLite-forgives family, same downstream reporter.

### Documentation
- `sqlite-vs-postgres.md`: dots and emails tokenize **atomically with no
  part-lexemes** on Postgres (`file`/`email` parser tokens) on both the
  document AND query side — unlike hyphens, document-side splitting can't
  rescue them. Searching `probe` finds `unique.probe` on SQLite and misses it
  on Postgres.

## [0.21.7] - 2026-09-27

### Fixed
- **MCP async tool dispatch keeps ORM work on the request's connection.** Async
  tool handlers were dispatched with `asyncio.run(handler(...))`, which gives
  asgiref no executor context — so every `sync_to_async(thread_sensitive=True)`
  (the default; how every tool touches the ORM) ran on asgiref's process-global
  `single_thread_executor`: one shared background thread with its own
  long-lived connection. The tool's DB work therefore ran outside the request's
  transaction, serialized process-wide across all tools, was one nested
  thread-sensitive call from asgiref's "would deadlock" guard, and on Postgres
  killed `transaction=True` test teardowns ("cursor already closed" during the
  flush) — a downstream's 46 teardown failures. Dispatch now uses
  `async_to_sync(handler)`, whose `CurrentThreadExecutor` hops the ORM work
  back to the calling thread and its connection. Third instance of the
  SQLite-forgives-Postgres-doesn't family (same downstream reporter); the
  mechanism-pinning tests fail under the old dispatch on SQLite too
  ("database table is locked" — the cross-connection symptom in miniature).

## [0.21.6] - 2026-09-27

### Fixed
- **From-scratch `migrate` on Postgres can no longer be aborted by the search
  index.** Three facts compounded (downstream report, validated here): the
  search `post_save` receiver has no `sender` filter; `get_view()` resolves by
  label string, so the *historical* model `apps.get_model()` hands a RunPython
  migration matches the real model's registry entry; and the index is
  provisioned at `post_migrate` — after every migration. A downstream that
  creates a searchable row in a migration therefore wrote to the missing
  `search_vector` column inside the migration's transaction, poisoning it —
  the visible error was Django's own `INSERT INTO django_migrations`, and a
  fresh Postgres build (DR restore, new region, CI) was impossible. SQLite
  hid the category: its FTS index is a separate table and a failed statement
  doesn't poison the transaction. The handlers now require
  `view.model is sender` (historical models no-op) and wrap each index write
  in `transaction.atomic()` — a savepoint — so "a search index write should
  never break a model save" is finally true on Postgres, not just SQLite.
- **Telemetry's synchronous flush no longer manages a connection it doesn't
  own.** `_write()` unconditionally called `close_old_connections()` and, on
  error, `connection.close()` — correct on the worker thread (which owns its
  thread-local connection), wrong on the `flush()` path, which runs on the
  CALLER's thread: `start_worker=False` mode, tests, and `logging.shutdown()`
  at interpreter exit. On Postgres that closes a live request's (or test
  transaction's) connection; SQLite's shared in-memory connection made both
  calls no-ops, hiding it. Connection management is now gated to the worker
  path, and the batch insert runs in `transaction.atomic()` so a failed write
  can't poison a caller's transaction either. (Same downstream report — two
  independent instances of code silently depending on SQLite's forgiving
  semantics.)
- The `config/settings/test.py` comment claiming "CI runs both backends" is
  corrected (this repo deliberately ships no CI); it now recommends the cheap
  gate for downstreams that add CI — a from-scratch `migrate` against an empty
  Postgres — and the sqlite-vs-postgres skill checklist gained the same item.

## [0.21.5] - 2026-09-27

### Fixed
- **The 90-day timeline no longer shows a permanent false red square on the day
  currently crossing the retention boundary.** The pruner advances one minute at
  a time, so a day takes ~24 hours to fold into its summary — throughout, the
  summary holds the already-pruned prefix and raw beats hold the remainder.
  `_daily_uptime_map` *chose* the summary outright, scoring a flawless mid-fold
  day at `prefix/1440` (live downstream evidence: 563/1440 ⇒ 39.097% "down"),
  while `_uptime_over_window` handled the same day correctly — the two public
  surfaces contradicted each other, and exactly one day per monitor is always
  mid-fold. The map now **sums** the two halves (disjoint by construction), with
  the raw half SLA-scoped on *both* terms so excluded-maintenance beats can't
  re-enter the `max(observed, expected)` denominator through the raw side.
  Four regression tests, three of which fail against the previous code.
  (Downstream report; validated live.)

## [0.21.4] - 2026-09-27

### Fixed
- **Heartbeat tests no longer hard-code the brand name or one theme's markup.**
  A rebranded downstream (`BRAND_NAME=Planner`) or one overriding the
  `detail_grid.html` display template inherited three false test failures. The
  public-status assertions now read `settings.BRAND_NAME`, and the boolean-
  rendering test asserts the actual regression invariant (False renders
  differently from True) via a template-agnostic extractor instead of pinning
  upstream's ✓/— glyphs. (Downstream report; verified non-vacuous — simulating
  the original all-booleans-truthy bug still fails the rewritten test.)
- **Daily uptime summaries prorate their expected-checks denominator.** Three
  spans nobody agreed to monitor were read as downtime by the flat
  `86400 // interval` denominator: the epoch's first partial day (~6% "down"
  even with every check green), a monitor added mid-day (same shape — its epoch
  is its first beat), and SLA-excluded maintenance (a 4h excluded window capped
  an honest day at 83%, defeating `exclude_from_sla=True`). The summary writer
  now computes `expected_intervals_for_day` (epoch row → day-in-progress →
  excluded windows) **and** moves beats recorded inside excluded windows out of
  `ok_count`/`fail_count` into `maintenance_count` — mirroring the raw span's
  `_uptime_over_window` semantics; shrinking the denominator alone would have
  left `max(recorded, expected)` resurrecting the excluded time. The 90-day
  timeline's raw branch uses the same math, so a day's uptime no longer changes
  when it crosses the retention boundary. Missing beats inside the monitored
  span still count as downtime (deliberately: for a self-pinged monitor, "cron
  didn't run" and "host was down" are the same event). A fully excluded day
  writes `expected_count=0` and renders "No data". New
  `manage.py heartbeat --reprorate` backfills existing summaries — expected
  depends only on the date, the epoch row, and the maintenance windows, so
  unlike `--repair-summaries` it fixes history (run repair first).
- **One host setting now satisfies both email links and webhooks.** Emails built
  outside a request (approval notifications, welcome mail) read `SITE_DOMAIN`,
  while webhooks read `SITE_URL` — so a deployment that configured its host the
  way `webhook_doctor` instructs still sent dead `localhost:8000` email links,
  and the Approvals status monitor stayed DOWN telling it to set a *second*
  variable. `site_base_url()` (in `apps/accounts/emails.py`) now resolves
  `SITE_DOMAIN`+`USE_HTTPS` → a URL-shaped `SITE_URL`/`SMALLSTACK_SITE_URL`/
  `BASE_URL` → the localhost default, and every consumer (branded emails, the
  welcome task, the `ApprovalsFanoutMonitor` link check) shares it. The monitor
  message now names both knobs, and `.env.example` finally documents
  `SITE_DOMAIN`/`USE_HTTPS`/`SITE_URL` (it mentioned none of them).

## [0.21.3] - 2026-09-26

### Fixed
- **Public status pages no longer paint all history "down" at 0.07% on long-running
  sites.** The heartbeat pruner runs every minute (the ping view calls it), so one
  calendar day is pruned across ~1440 tiny batches — but `_write_daily_summaries`
  *overwrote* the day's `HeartbeatDaily` row with only the current batch, so every
  fully-summarized day converged to its final single beat: 1/1440 ⇒ `uptime_pct =
  0.069%` ⇒ "down" (while the raw-retention window stayed green — the "only ~7 days
  survive" symptom). Summaries now **accumulate** across batches (counts merge,
  response times weighted-average), the aggregate-then-delete pair runs in one
  transaction, and the timeline/calendar/SLA maths are unchanged. Deployments that
  ran the buggy pruner: `manage.py heartbeat --repair-summaries` deletes the
  corrupted rows (recorded beats < 5% of expected — the bug's fingerprint; genuine
  full days and recorded outages are kept), after which those days honestly render
  "No data". The true counts are unrecoverable.

### Added
- **User-facing help pages for the scheduler** (`/smallstack/help/smallstack/scheduler/`)
  — the control console, `@scheduled` cadences, tick triggers, and the run lifecycle
  finally have a human-readable page (the skill doc existed; Help had nothing).
- **Webhooks help covers the v0.19 event picker** — the annotated checkbox event
  list, the Advanced custom-pattern disclosure, and every-surface pattern validation.
- **Background Tasks help no longer steers cron work to Celery** — the comparison
  table predated the `@scheduled` scheduler; it now says scheduling is built in and
  links to the scheduler page.

### Documentation
- **The palette count is corrected in the three files the v0.21.1 sweep missed.**
  `README.md` (four claims), `CLAUDE.md` and `apps/smallstack/docs/tldr.md` still said
  **five** palettes; there are **six** (`django`, `dark-blue`, `purple`, `orange`,
  `high-contrast`, `gold`). `CLAUDE.md` also named the palettes by label rather than id,
  omitted `gold`, and left the default unstated — it is `purple`
  (`SMALLSTACK_COLOR_PALETTE`). These are the read-first files for a new contributor and
  for an agent onboarding to the repo, so they were contradicting
  `docs/skills/modern-dark-theme.md`, which v0.21.1 had already fixed.

## [0.21.2] - 2026-09-26

### Removed
- **The approvals scenario test-harness apps no longer ship in the base template.**
  `apps/demo_purchasing`, `apps/demo_agentops` and `apps/demo_access` — plus
  `manage.py approval_scenario` and `manage.py seed_approval_scenarios` — were the QA
  workspace's test vehicle for the v0.21.x approvals work. They drove the findings but
  were never meant to land in the starter template: a fresh clone got three extra apps,
  six extra migrations, and 29 routes under `/demo/` without opting in. The apps, their
  conditional `INSTALLED_APPS` registration, and the `/demo/` URL mounting are all
  removed; the framework itself never referenced them, so no framework behavior changes.
  If you cloned at v0.21.0/v0.21.1 and migrated, see "Scenario demo apps" in
  `UPGRADING.md` for what the leftovers are (inert) and how to drop them.

## [0.21.1] - 2026-09-26

Fixes for findings from the 2026-09-26 test rounds. Each carries a regression test that
fails against the old code.

### Fixed
- **Turning the approval email channel off no longer holds the status page down.**
  `SMALLSTACK_APPROVALS_EMAILS_ENABLED=False` still enqueued a `notify_*` task per request —
  the gate lived only at *send* time — so with no worker those rows sat READY forever and
  `ApprovalsFanoutMonitor` counted exactly them. A **core-category** service card sat
  permanently DOWN telling the operator to start a mail worker they had deliberately chosen
  not to run, and `UPGRADING.md` recommended that very setting as the remedy for the
  symptom. Nothing to send now means nothing to queue, and the monitor ignores a backlog
  while the channel is off, so rows left from before the switch don't hold it down either.
- **The approvals monitor no longer reports "email queue drained" while mail is queued.** It
  now distinguishes *stale* from *queued-but-young* and says which it found — the note
  described the opposite of the situation on the one channel that fails silently.
- **The approvals monitor reports every fault in one check.** The `SITE_DOMAIN` branch
  returned before the backlog was looked at, so an install with both faults learned about
  the second only after fixing the first.
- **The notifications inbox has an `<h1>`** — its page heading was an `<h2>`, leaving the
  page with no `h1` at all and breaking the document outline and heading-jump navigation.
- **Unread notifications are announced to screen readers.** Unread state was carried only by
  an `aria-hidden` dot and bold weight, so the state the screen exists to convey was
  sighted-only (WCAG 1.3.1 / 1.4.1). A visually-hidden "Unread." marker now precedes the row.
- **The sidebar no longer claims you are on the Dashboard when you are not.** The dashboard
  lives at `/smallstack/`, which prefixes every admin route, so any page without its own nav
  entry — the notifications inbox, reached from the topbar bell — lit it up. Nav items gain
  `active_exact`, set on the dashboard root.

### Changed
- `nav.register(...)` accepts `active_exact=True`: the item goes active only on an exact path
  match, never on a prefix. For a section root that is the difference between "you are here"
  and "you are somewhere below here".

### Documentation
- **`docs/skills/modern-dark-theme.md` was wrong about the palettes it is the read-first
  authority for**: it claimed **five**, named a `dark-purple` that does not exist (the id is
  `purple`), omitted `gold`, and said the default was `django` when it is `purple`. Corrected,
  with a pointer to `UserProfile.color_palette.choices` + `palettes.css` as the authoritative
  list. The same claims are fixed in seven other docs.
- **`UPGRADING.md` under-counted the migrations**: it said "Four", which is what the
  approvals/notifications *review* added. Coming from v0.20.1 — the only previously released
  version — you apply **thirteen**. Now stated with the breakdown.
- **The bundled scenario demo apps are documented.** `apps/demo_purchasing`, `demo_agentops`
  and `demo_access` ship as of v0.21.0 and register themselves when present, so a fresh clone
  gets three extra apps, six extra migrations and 29 routes under `/demo/`. `UPGRADING.md`
  now says so and gives the one-line opt-out; `config/settings/base.py`'s comment no longer
  claims they are "deliberately not tracked".

## [0.21.0] - 2026-09-26

Fixes from the 2026-09-13 base-framework audit (v0.20.1). Each carries a
regression test that fails against the old code.

### Security
- **MCP now checks the *user's* staff flag, not just the token's label.** Any
  tool at `requires_access="staff"` (or `"auth"`) also requires
  `token.user.is_staff`, matching REST. Previously a staff-level token held by a
  non-staff user — flag cleared after minting, or minted for them by another
  staffer — kept full staff read/write over MCP (26 of 40 tools, incl.
  `create_webhook`). The token form also refuses to mint staff/auth-level
  tokens for non-staff users. (C1)
- **`/media/` no longer serves access-controlled files.** Runbook bodies were
  reachable anonymously at `/media/runbook/<key>.md`. The media route now 404s
  prefixes listed in the new `SMALLSTACK_PRIVATE_MEDIA_PREFIXES` (default
  `runbook/`, env-overridable, comma-separated); profile photos stay public.
  The gate compares the resolved file path the server would open — not URL
  strings — so `..` tricks (`/media/%2e%2e/media/runbook/x.md`) and symlinks
  can't slip past it. (C2)
- **API tokens no longer leak into logs.** An `HttpRequest` in a log record's
  `extra` (every `django.request` 4xx/5xx) is reduced to method + path, so a
  feed's `?token=` never reaches JSON log lines or `LogRecord.extra`. Gunicorn's
  access log format drops the query string too. (C3)
- **Webhook delivery can't be redirected into the private network.** 3xx
  responses are recorded as failures, never followed, and the connected
  socket's peer address is re-checked before any byte is sent — closing the
  DNS-rebinding window as well. (C4)
- **REST detail/update/delete and bulk endpoints honour `get_list_queryset`**,
  as REST list and all MCP verbs already did. A fork scoping rows per owner
  leaked other tenants' rows at `/api/<base>/<pk>/`. (C5)
- **Inbound webhook receiver hardened**: bodies over
  `SMALLSTACK_WEBHOOK_INBOUND_MAX_BYTES` (1 MB) get 413 before anything is
  stored; signature-rejected receipts keep a 1 KB excerpt + SHA-256 and stop
  being recorded past `SMALLSTACK_WEBHOOK_REJECTED_PER_MINUTE` (30); new
  `prune_webhook_receipts` command (in the shipped crontab). (C6)
- **Runbook images get server-generated names and a pinned content type.**
  Only png/jpg/gif/webp are accepted by the form; any other stored name
  (service/bundle paths, pre-fix uploads) is served as an
  `application/octet-stream` download, never rendered. (C7)
- **OAuth consent POST requires a CSRF token** (`AuthorizeView` is no longer
  `csrf_exempt`), and `SESSION_COOKIE_SAMESITE`/`CSRF_COOKIE_SAMESITE` are
  pinned to `"Lax"`. The consent page's CSP override regains `base-uri`,
  `object-src`, `font-src`, `connect-src`. (C8, H5)
- **Abandoned OAuth codes are scrubbed**: past their TTL the plaintext key is
  cleared and the never-delivered token deactivated. (C9b)
- **Passwordless login**: attempts are spent atomically before the code check
  (parallel guesses bypassed the 5-attempt limit) and codes per account are
  capped by `SMALLSTACK_LOGIN_CODES_PER_HOUR` (5). (H3)
- **`.dockerignore` excludes `backups/`, `data/`, `.secret_key`, `.kamal/` and
  nested `*.sqlite3`** — `COPY . .` was baking DB snapshots into images. (H1)
- `SMALLSTACK_PUBLIC_STATUS_ENABLED=False` now also closes the per-monitor
  detail page to anonymous visitors (C9a). New `SMALLSTACK_PUBLIC_PROFILES`
  flag (default on) lets a deployment require sign-in for `/profile/<username>/`,
  which otherwise answers "does this account exist" (C9d).

### Fixed
- **The telemetry `after_id` cursor skipped records.** It filtered by pk but
  ordered by ts, so batch-inserted records captured earlier than their pk
  suggests were never returned — with `has_more=False`. Cursor mode now pages
  in pk order. Affects `/api/logger/records/`, MCP `logs_search`, and
  `logs --follow`. (D1)
- **A scheduler fire that failed to enqueue was lost silently.** Any enqueue
  exception now records a FAILED run and `last_status="failed"`; an unknown
  `queue_name` is rejected by `ScheduledJob.clean()`. (D2)
- **The shipped crontab now drives the webhook retry tick** (`POST
  /webhooks/tick/` every minute) — failed deliveries were never retried or
  dead-lettered — **and nightly `run_retention`**, the only driver of runbook
  document TTL expiry. (D3, D4)
- `api_doctor` and the OpenAPI validity tests validate the spec actually
  served (custom endpoints included: 68 operations, not 42), via the new
  `build_served_spec()`. (D5)
- A log-capture window that would capture nothing extra (a typo, or a level at
  or above the baseline) is refused with a clear message on every channel
  instead of being audited and reported as active. (D6)
- Dynamic status monitors: a DB error is logged instead of silently dropping
  every endpoint/surface monitor from the tick; one bad row no longer drops
  the rest. (D7)
- Bulk deletes log at WARNING, so the v0.20.0 summary line actually reaches
  the log viewer at the default baseline. (D8)
- Smaller: heartbeat log uses `attach_display_helpers` (D9); the log viewer
  gains a CRITICAL filter and flags unknown levels (D10a); write give-ups count
  toward `dropped` (D10b); `reset_schedule` reports a failed re-sync (D10c);
  bulk-delete and help-search failures are logged (D10d); the api/mcp/webhook
  doctors report a missing schema instead of a traceback (D10f); CRUD lists
  fall back to pk order when the queryset is unordered — fixes
  `UnorderedObjectListWarning` on the user list (D10g).
- Dataset CSV export is capped by `SMALLSTACK_DATASET_CSV_MAX_ROWS` (50,000);
  over the cap is a 400 asking the caller to filter or page. (C9c)

### Added — approvals + notifications

The two primitives themselves, which had no changelog entry: ~19 *fixes* to them
were documented below before this section said they existed. (F-56 #10)

- **`apps/approvals` — a side-car human-in-the-loop approval gate.** An app (or
  an AI agent) files an `ApprovalRequest`, a human decides it in the staff queue
  and decision console at `/smallstack/approvals/requests/`, and the app reacts
  through a per-kind callback. What "approved" *means* stays app-owned:
  approvals never write your models. State machine
  `pending → approved | rejected | canceled | expired`, every transition
  race-safe (conditional UPDATE, single winner) and audited.
  - `@approval_kind` registry, autodiscovered from `<app>/approvals.py`, with
    `default_expires_in`, a `can_decide` eligibility hook that *narrows only*,
    `assignable` allowlisting, `notify` extra recipients, and a context card
    template per kind.
  - One eligibility implementation (`permissions.can_decide`) shared by web,
    REST and MCP: staff by default, self-approval blocked, assignees narrow.
  - Surfaces: the console, `{% approval_card %}` for non-staff assignees,
    `POST …/requests/create/` + `{id}/decide/` REST, `request_approval` /
    `decide_approval` MCP tools, `approval_requested` / `approval_decided`
    signals, `.created` / `.updated` webhooks carrying `data.status`, a
    dashboard widget, and a 5-minute expiry sweep plus lazy expiry so
    correctness never depends on the worker.
- **`apps/notifications` — an in-app notification primitive.** A never-raising
  `notify()` service, topbar bell with unread badge, a LoginRequired inbox at
  `/smallstack/notifications/` (deliberately *not* staff-only), per-user REST
  (`api/` + `api/mark-read/`), and a daily retention prune.
- **New public notifications API** beyond `notify()`: `services.resolve(subject_key,
  kind="")` retires every unread row about a subject, `notify(..., subject_key=…)`
  tags a row with a producer-owned handle, and `Notification.subject_key` (indexed)
  stores it. This is what lets a decision retire the other approvers' now-stale
  "Approval needed" bells instead of leaving a badge that means nothing. (F-56 #3)
- **New middleware** — `apps.notifications.middleware.NotificationReadOnArrivalMiddleware`
  is added to `MIDDLEWARE` in `config/settings/base.py`. It marks a notification
  read only on a 2xx arrival, so a click that dead-ends cannot silently consume
  the badge. **A fork that pins its own `MIDDLEWARE` list must add this entry**
  or it loses read-on-arrival. (F-56 #1)
- **Nine settings**: `SMALLSTACK_APPROVALS_ENABLED`,
  `SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE`, `SMALLSTACK_APPROVALS_STAFF_OVERRIDE`,
  `SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES`, `SMALLSTACK_APPROVALS_EMAILS_ENABLED`,
  `SMALLSTACK_APPROVALS_NOTIFY_EMAILS`, `SMALLSTACK_APPROVALS_SWEEP_ENABLED`,
  `SMALLSTACK_NOTIFICATIONS_ENABLED`, `SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS`
  — plus the five added by the review, listed under Changed.

### Changed — approvals/notifications review (2026-09-25)

Behaviour changes an operator or a fork will notice. Recipes for the ones with a
remedy are in [`UPGRADING.md`](UPGRADING.md).

- **API tokens held by deactivated accounts stop working.** `APIToken` now
  refuses a token whose user is `is_active=False` on *every* surface (REST, MCP,
  feeds, OAuth), and approvals eligibility requires an active user too.
  Previously an offboarded account's un-revoked token kept reading the queue and
  **approving/rejecting**, recorded under their name. This changes behaviour at
  every offboarding: deactivating a user is now sufficient to cut their tokens,
  where before revocation was also required. (F-10, F-56 #4)
- **The master switches now un-mount their app's URLs**, following the
  `SMALLSTACK_MCP_ENABLED` precedent. With `SMALLSTACK_APPROVALS_ENABLED=False`
  or `SMALLSTACK_NOTIFICATIONS_ENABLED=False`, the routes cease to exist rather
  than staying live while only the fan-out died. **Consequence:** a template or
  `reverse()` referencing e.g. `notifications:inbox` under a disabled switch now
  raises `NoReverseMatch` (a 500) instead of rendering a dead link — guard such
  references with the switch. (F-11, F-56 #2)
- **New `WebhookReceiver.signature_header` default:** `"X-Signature"` →
  `"X-SmallStack-Signature"`, matching what outbound signs, with migration
  `webhooks/0004`. Existing receivers keep their stored value; **receivers
  created after the upgrade expect the new spelling**, so a third-party sender
  configured for `X-Signature` will 401 unless the field is set explicitly.
  (F-06, F-56 #8)
- **System-initiated audit entries create one inactive `User` row.** The first
  write with no human actor (expiry sweep, scheduler retirement) creates an
  `is_active=False`, non-staff account named by the new
  `SMALLSTACK_AUDIT_SYSTEM_USERNAME` (default `"system"`), so those entries have
  an author instead of being invisible. Expect one unfamiliar row in the user
  list; it cannot log in. (F-15, F-56 #7)
- **Filing an approval can now return 429.** `SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER`
  (default 50) caps one requester's open requests **per kind**; over it, REST and MCP return
  `too_many_pending`. An agent in a retry loop could previously fill the queue
  unbounded. (F-18, F-56 #5)
- **Four more new settings** (F-56 #6):
  - `SMALLSTACK_APPROVALS_EMAILS_INLINE` — defaults to `DEBUG`. Sending falls
    back to inline only when set; **in production this means approval email
    requires a `db_worker` draining the `email` queue.** The new
    `approvals-fanout` monitor goes DOWN when it isn't.
  - `SMALLSTACK_APPROVALS_EMAIL_BACKLOG_MINUTES` (15) — how stale the email
    queue may get before that monitor complains.
  - `SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT` (25) — rows lazily expired per
    request, bounding what had been an unbounded synchronous sweep inside a GET.
  - `SMALLSTACK_AUDIT_SYSTEM_USERNAME` (`"system"`) — see above.
- **Generated MCP tool refusals carry a machine-readable `code`** —
  `invalid_argument` · `not_found` · `not_permitted` · `validation_error` ·
  `unsupported` — where they previously returned a bare English sentence. A
  rejected create also now sets the protocol-level `isError` flag (it returned
  `{"errors": …}` with no top-level `error` key, so a model reading the flag saw
  success). Clients string-matching the old prose must switch to `error.code`.
  (F-53)
- **REST exposes `target_ref` and `assignee_usernames` on approval requests**,
  so the API shows the target it accepts (`"app_label.model:pk"`) instead of
  serializing it to `null`. (F-35)
- **Four new framework migrations**: `notifications/0002` (+`subject_key` and its
  index), `notifications/0003` (backfill — see `UPGRADING.md`), `scheduler/0003`
  (+`auto_retired`), `webhooks/0004` (the header default above).

### Security — approvals/notifications review (2026-09-25)

- **Per-object authorization now covers every single-object CRUD surface.** New
  `CRUDView.check_object_permission(obj, request)` hook, applied by the base to
  detail, edit, delete, field-preview, related-tab, the REST detail/update/delete
  handlers, the bulk-action view and the generated MCP `get_*`/`update_*`/`delete_*`
  tools. Previously a view that expressed ownership by overriding one generated
  base's `get_object` protected only that base: `/smallstack/tokens/<pk>/related/request_logs/`
  returned **200** with another user's API-token request log — which endpoints
  that token calls and when — to any logged-in non-staff account, while the
  detail page beside it correctly answered 403. `tokenmgr` now uses the hook.
  (F-27)
- **Deactivating an account no longer widens an approval's audience.** A request
  routed to one named assignee used to become a broadcast to every active staff
  user the moment that assignee was offboarded (1 recipient → 6 recipients, 1
  bell → 10), silently. The fallback remains — the request must not go unseen —
  but it logs a warning naming the deactivated assignees and both the email
  subject and the bell title carry `(assignee deactivated)`. (F-32)
- **The MCP tier ladder is no longer inverted.** It ranked
  `readonly < staff < auth`, so `requires_access="auth"` — documented as "gate to
  any authenticated caller" — could be satisfied by *no* login token, and staff
  were strictly less capable than non-staff on that tier. The ladder is now
  `readonly < auth < staff`, and only the `staff` tier implies the staff flag.
  Latent before this (nothing shipped declares `"auth"`, though a dataset author's
  `mcp_access="auth"` reaches it). (F-26)
- **An inbound webhook verifier that raises is logged.** The bare
  `except Exception` around the verifier swallowed everything, so a verifier
  raising on a *correct* signature was indistinguishable from a forged one with
  nothing in the log. Still fails closed. (F-37)

### Fixed — approvals/notifications review (2026-09-25)

- **Multi-line `{# … #}` comments no longer render as page text.** Django's `{# #}`
  is single-line only; three multi-line ones were being emitted verbatim — on the
  approvals decision console and in *every* CRUDView's no-match empty state. Swept
  tree-wide (12 more in `smallstack/starter.html`, which ships as "copy this
  file"). Guarded by `apps/smallstack/test_template_hygiene.py`, which reads every
  template in the tree and also asserts that rendered CRUD pages contain no `{#`,
  `{%` or `{{`. (F-45)
- **The empty state branches on filters, not on "any query param".** It tested
  `request.GET.urlencode`, which is truthy for pagination, ordering, the display
  toggle and the `?_notification=` marker the notification bell appends — so a
  user who sorted an empty list or arrived from a bell row was told to "clear
  their filters" and lost the create-the-first-one link. New
  `has_active_filters` context flag; the four divergent copies of the empty state
  converge on one include. (F-44)
- **`?status=pending` on the approvals queue now agrees with its own Pending stat
  card.** Expiry is lazy, so an overdue row's stored `status` still reads
  `pending`; the filter matched the column while the card counted `actionable()`,
  and the page contradicted itself by 900 rows. Both now evaluate
  `ApprovalRequestQuerySet.for_effective_status`, on HTML, REST and MCP, and
  `?status=expired` includes overdue-but-unswept rows. New generic
  `CRUDView.apply_filter(qs, field_name, value, request)` hook. (F-29)
- **`SMALLSTACK_APPROVALS_SWEEP_ENABLED` is a two-way switch again.** Retiring a
  code-declared scheduled job whose spec disappeared had no reverse, so turning
  the flag back on never restored the job. New `ScheduledJob.auto_retired` marks
  automatic retirements and they are undone when the spec returns; a job an
  operator disabled by hand stays off (and now says so in the log). A relative
  safety valve also refuses to retire more than half the known code jobs in one
  sync, which is the signature of a *partial* autodiscovery failure. (F-30)
- **A verifier that mutates its headers dict works again.** The case-insensitivity
  fix had narrowed the argument from `dict[str, str]` to Django's immutable
  `CaseInsensitiveMapping`, so a third-party verifier doing
  `headers.pop("X-Smallstack-Signature", "")` began returning 401 on correct
  credentials. The argument is now `webhooks.hooks.CaseInsensitiveDict` — a real
  mutable `dict` subclass with case-insensitive lookups. (F-37)
- **A failing status monitor no longer renders as a green tick.** The core tier of
  `/smallstack/status/overview/` built each service row from `Monitor.inventory()`,
  whose base implementation returns `{"ok": True}`, so `approvals-fanout` ("191
  approval email tasks queued and unrun") and `scheduler-tick` ("2 jobs overdue")
  both showed "on" while recorded as FAILING. The row now needs `inventory()` **and**
  the recorded state to be good, and carries the monitor's actionable note.
  Not-yet-recorded still reads as fine. (F-28, F-07)
- **Generated MCP `get_*`/`update_*`/`delete_*` tools accept `id`.** `serialize()`
  emits the row identity as `id` and three hand-written tools accept `id`, but the
  generated ones required `pk` — so an agent passing the id it had just been
  handed got `{"error": "pk is required"}` on its first call, which is exactly
  what `request_approval`'s own description told it to do. `pk` remains a
  permanent alias; schemas declare both with `anyOf`; descriptions name the
  parameter. (F-25)
- **A feature's master switch degrades to 503, not 500.** New
  `apps.smallstack.exceptions.FeatureDisabled`, translated by `api_view` for every
  endpoint in the project. `ApprovalsDisabled` is one, so a *downstream* app's
  endpoint that files an approval with approvals switched off returns a 503
  envelope naming the setting instead of an unhandled 500. Approvals' own dead 503
  handlers and OpenAPI entries are removed — those routes are unmounted whenever
  the exception can be raised. `PermissionDenied` gets the same treatment (403).
  (F-31)
- **Approval emails warn when they would link to `localhost`.** Approvals mail is
  sent without a request, so its absolute console link comes from `SITE_DOMAIN`
  (default `localhost:8000`) — dead on every unconfigured install, including the
  headline "non-staff assignees decide via the emailed link" story. The approvals
  monitor now reports it. Skipped under `DEBUG` and when the email channel is off.
  (F-33)
- **Global search finds a non-staff assignee's own approvals.** Search was the one
  read surface the eligibility scoper never reached (`search_access` defaults to
  STAFF), so a user who could open and decide a request could not find it.
  (F-43)
- **A non-staff approver has a nav entry to the console.** The console is
  LoginRequired + eligibility-scoped, but its only nav registration sat in the
  staff-only ADMIN section. New `nav.register(visible=<predicate>)` for rules the
  `auth_required`/`staff_required` flags cannot express. (F-46)
- **Stale "Approval needed" bells created before the `subject_key` migration can
  be retired.** New data migration backfills `subject_key` from the row's URL and
  marks read any bell whose request is already terminal. Without it the
  retirement feature reached only rows filed after the upgrade — 105 of 105 unread
  rows on the reference install were unaddressable. Idempotent. (F-42)
- The decision-email recipient rule is documented correctly at last: the set is
  **the approvers — including the decider** — plus the requester. The bell differs
  from the email by exactly one person (it skips the actor), and that asymmetry is
  now stated in `emails.py` and both `.md` files. (F-04)

## [0.20.1] - 2026-08-29

### Changed
- **`make lint` now runs ruff *and* mypy** — one command, the full static gate.
  `make typecheck` existed as a deliberately separate target wired only into
  the pre-commit hook, so *commits* were type-checked but a by-hand
  `make test && make lint` gave no type check and no signal one existed. A
  hand-run lint now enforces exactly what the hook enforces; the hook drops
  its duplicate mypy step, and `make typecheck` remains for running mypy alone.
- **CLAUDE.md gains a Types convention**: prefer strongly typed code where
  practical, annotate signatures on new and edited code — under this mypy
  config (`check_untyped_defs = false`) annotating a function is what opts its
  body into checking — and keep `make lint` green before reporting work done.
  CLI reference docs synced (`cli-reference.md`, `cli-tools.md`).

## [0.20.0] - 2026-08-16

### Added
- **`/api/logger/` — the telemetry surface a machine can drive.** The staff
  viewer answered "an operator needs to read the logs without shell access";
  this answers the same question for a CI job, a frontend dev panel, or an AI
  agent. Staff-only, Bearer or session auth, advertised in the OpenAPI schema:

  | Endpoint | |
  |---|---|
  | `GET /api/logger/` | Capability document — filters, limits, capture state |
  | `GET /api/logger/records/` | Search, with the viewer's filters |
  | `GET /api/logger/records/<id>/` | One record, full untruncated traceback |
  | `GET|POST|DELETE /api/logger/capture/` | Read, open, or close a capture window |
  | `GET /api/logger/config/` | Effective settings + live handler stats (read-only) |
  | `GET /api/logger/loggers/` | Logger names with counts, for discovery |

  Shaped for its consumer rather than copying the UI. **Unknown query parameters
  are a 400**, not silently ignored: a human eventually notices a result set
  looks wrong, but `?sevrity=ERROR` returning the *unfiltered* table reads to a
  script as a successful query, and everything concluded afterwards is built on
  it. **`?after_id=` is a cursor, not a page number** — new rows arrive at the
  top, so page 2 of a live tail re-reads what page 1 already returned.
  **`applied_filters` is echoed back**, so a caller can check the server
  understood the query it thinks it sent. List responses truncate tracebacks and
  flag `exc_truncated`; the detail endpoint serves the full text.

  `POST /api/logger/capture/` requires a `note` (the CLI leaves it optional — a
  human running a command is present and accountable in the moment, an
  unattended caller is neither). Duration is clamped with `clamped: true`
  reported rather than silently running for a different period than asked for.
  `DELETE` is idempotent, so a cleanup step in a `finally` is safe. Both are
  audited. A **read-only token can read everything here but cannot open a
  window** — the right credential for CI.

  `GET /api/logger/config/` is deliberately read-only. Persistent configuration
  belongs in settings/env where a deploy reproduces it; an API that rewrote
  baseline logging config would be a drift generator. The capture window is the
  one runtime knob, and it expires.

- **Five MCP tools** — `logs_search`, `logs_get`, `logs_status`,
  `logs_capture_start`, `logs_capture_stop` — so an agent can run a whole
  debugging session: turn capture up, reproduce, correlate an `X-Request-ID` to
  the lines that explain it, turn capture back down. Five rather than eight
  because every tool costs room in an agent's tool list, and "what's the state
  of logging here" is one question: `logs_status` answers capture state,
  effective config, and the busiest loggers together.

- **`manage.py logs`** — search captured records from the shell, which
  previously required a browser. `--level`, `--logger`, `--request-id`,
  `--trace-id`, `--search`, `--since`/`--until`, `--after-id`, plus `--id` for
  one record with its full traceback and `--follow` for a cursor-based tail. An
  empty result says whether capture was simply at its baseline, which is the
  usual cause.

- **`--json` on `log_capture` and `prune_logs`.** The human output of
  `log_capture status` printed a *Python dict repr* — single quotes, `False` not
  `false` — so anything consuming it was screen-scraping something that was
  never JSON.

- **`apps/telemetry/queries.py`** — one implementation of the filters,
  validation, serialization, and capture verbs, with the REST API, the MCP
  tools, and the CLI as thin adapters over it. Two bugs fixed in this same
  release line were one rule written twice and drifting apart; three transports
  made that risk structural, so the shared core removes it. Tests assert the
  three surfaces return identical results for identical queries.

### Fixed
- **Read-only API tokens could write through any hand-rolled `@api_view`
  endpoint** (security). CRUDView-generated endpoints have always enforced the
  read-only rule via `_check_api_permissions`, but that is only reached from the
  generated views — the `api_view` decorator every *custom* endpoint uses never
  called it. `apps/runbook/api.py` was unaffected only because it independently
  re-implemented the same rule in a private helper; anything else was exempt,
  and a new endpoint had no way to know it needed the check. Verified with a
  synthetic endpoint: a read-only token returned 200 **and ran its side
  effect**. Now enforced in `api_view` itself, so the rule is structural rather
  than remembered. Login tokens (`access_level=""`) are unaffected; only tokens
  explicitly minted read-only change behaviour, which is the point of minting
  them.

- **Django's own 4xx access-log lines carried no `request_id`.** `get_response()`
  calls `log_response(..., request=request)` *after* the middleware chain
  returns — i.e. after `RequestIDMiddleware`'s `finally` reset — so the
  `Unauthorized:`/`Not Found:` line documenting a failure was invisible to a
  search by the very ID the client was told to quote. 500s were fine, which made
  it easy to miss. `RequestContextFilter` now falls back to `record.request.id`,
  defensively enough that a missing or broken `request` can never take the line
  down.

- **`X-Request-ID` was not exposed to cross-origin JavaScript.** The header was
  on the wire but absent from `Access-Control-Expose-Headers`, so `fetch()` read
  `null` — the correlation story was unreachable from exactly the browser
  clients it was written for. `CORS_EXPOSE_HEADERS` now lists it.

- **A freshly-started process ignored an already-open capture window** until it
  happened to log at or above the baseline level. `Logger.callHandlers` compares
  `record.levelno` against the handler's level *before* invoking the handler, so
  nothing inside `emit()` can run for a below-baseline record — meaning the
  writer/poller thread that picks up capture windows never started. A worker
  whose early lines are all INFO could sit outside an open DEBUG window
  indefinitely. `TelemetryConfig.ready()` now starts the poller eagerly.
  (`_ensure_worker()` also gated on `django_apps.ready`, which `Apps.populate()`
  only sets *after* every `ready()` returns — always false at that call site.)

- **The log viewer's `?logger=` filter matched sibling names.** It was a raw
  `startswith`, so `apps.telemetry` also matched `apps.telemetry_report` — the
  bug class the capture handler's own exclusion check had already been fixed
  for. Both now share `logger_match.prefix_q`.

- **A non-serializable `extra` value rendered with `str()` while the docs
  promised `repr()`** — which loses exactly the type information you want when
  reading a log. Now `repr()`, bounded to 2000 characters. An `extra` value whose
  `__repr__()` *raises* no longer drops the whole line either: the DB handler's
  fallback used to re-touch the poisoned value and fail again, losing the
  message and every healthy field with it.

- **`log_capture start` always claimed the duration was clamped**, because it
  compared two independently-generated `timezone.now()` values.

- **CRUDView bulk delete/update left no trace.** A 500-row bulk delete was
  invisible in both the log viewer and the audit trail. Now one summary log line
  per call (not one per row — that is the unbounded-growth failure mode the
  handler's own docstring warns about) plus per-row `LogEntry` audit entries
  written in a single `bulk_create`, because "who deleted row X" has to stay
  answerable per row.

- **`bind_trace_id()` was documented but unused**, and unreachable in the
  viewer. Background tasks and scheduler jobs now bind a trace ID
  automatically, and the viewer gained a `trace_id` filter. The task hook
  subscribes to **both** identically-named signal pairs — `django_tasks.signals`
  (sent by `django_tasks_db`'s worker) and `django.tasks.signals` (sent by
  Django's own backends, including the `ImmediateBackend` the test settings
  use). Subscribing to one meant trace binding silently stopped the moment
  `TASKS["default"]["BACKEND"]` changed; it also meant the real
  `enqueue()`-to-execution path had no test coverage, since the suite runs on
  the namespace the hook wasn't listening to.

- **`django.server` is no longer captured to the database.** The dev server's
  per-request access log wrote one INFO record per request, so anything polling
  the log table filled it with its own poll traffic — the viewer's five-second
  live mode included. Measured: ten polls of the logger API produced eleven new
  records; zero after the fix. It does not exist in production (gunicorn writes
  its own access log), and `RequestLog` already stores the same information
  properly, with a user and a request ID attached.

The telemetry subsystem itself — the staff log viewer, database-backed capture,
and real JSON logging — landed after v0.19.0 and ships here too. Its notes
follow.

### Added — telemetry subsystem
- **`/smallstack/logs/` — a staff log viewer, so the whole loop works without
  shell access.** Newest-first, one line per record, with a colour rail down the
  left edge carrying severity: level is the attribute you scan for, and a rail
  finds it without reading while costing no row height (a badge would have made
  every row taller for information the rail already carries). Filters for level
  (each showing the count you'd get), logger, time range, and a search that
  covers tracebacks as well as messages — the exception class is what you
  remember, and it lives in the traceback.

  Rows expand in place for the full message, traceback, `extra` fields and
  source location; tracebacks load on demand, since one can be 20 KB and fifty
  inlined would dominate the page. A live mode polls every five seconds.

  **The capture control sits in the page header**, because "nothing here, turn
  it up" is the first move when the baseline level missed your bug. Opening a
  window from the UI is audited via `log_action`.

  **Request correlation is now round-trip**: expanding a record links to every
  line its request produced, and `/smallstack/activity/requests/` gained a
  `logs` link per request going the other way.

  Verified across the django / orange / dark-blue / high-contrast palettes, in
  light and dark, and down to a 420px viewport (the logger column drops, the
  rails hold).

- **`apps/telemetry` — log records are written to the database, so a deployment
  is debuggable from inside the app.** Console and file logging both assume you
  can reach the output; a container platform with no shell means the log is
  written perfectly and you can't see a line of it. Records now also land in
  `telemetry_logrecord`, browsable at `/admin/telemetry/logrecord/` and through
  Explorer, each carrying the `request_id` that produced it — so an
  `X-Request-ID` from a bug report pulls every line that request emitted.

- **Time-boxed capture windows.** Baseline capture is WARNING so the table
  stays small. `manage.py log_capture start --level DEBUG --minutes 15` turns it
  up and it closes itself — nothing is left switched on because someone got
  distracted. The window lives in the database, not one process's memory, so
  every worker and container picks it up within a poll interval (5s), and each
  row records who opened it and why.

  Both the handler *and* the logger levels move. A record has to be created
  before any handler is consulted, so lowering the handler alone would capture
  nothing new — this is the usual reason "I turned on DEBUG and saw nothing".
  `TELEMETRY_CAPTURE_LOGGERS` controls which loggers are lowered;
  `django.db.backends` is pinned at WARNING regardless, because at DEBUG it
  emits one line per SQL query.

- **`DatabaseLogHandler`, built so logging can never break a request.** Four
  guards, each for a specific failure mode of writing logs to the database you
  are serving from:
  - *recursion* — writing a row runs a query, the query logs, the record comes
    back to the handler. A thread-local guard plus logger-hierarchy exclusion
    breaks the cycle.
  - *raising* — every path swallows; a failed write costs log lines, not a 500.
  - *latency* — nothing is written on the request path; records go to a bounded
    queue and a background thread batches them out.
  - *load* — an incident floods ERROR lines exactly when the database can least
    absorb them, so the queue drops on overflow and counts the drops instead of
    blocking the caller. `log_capture status` reports them.

- **`manage.py prune_logs`** — retention by age (`TELEMETRY_LOG_RETENTION_DAYS`,
  default 7) *and* a hard row cap (`TELEMETRY_LOG_MAX_ROWS`, default 20000),
  whichever binds first; wired into the container cron every 15 minutes. Age
  alone wouldn't survive an incident logging a million lines in ten minutes; a
  cap alone would keep stale rows forever on a quiet site.

- **`manage.py log_capture start|stop|status`** — control surface for the
  window, plus queue health (written / dropped / errors / worker liveness).

- 51 tests in `apps/telemetry/tests/`. Two bugs they caught during development:
  logger exclusion used a raw string prefix, which also swallowed unrelated apps
  like `apps.telemetry_report`; and the row-cap prune cut on `pk`, copied from
  `prune_activity` where pk order tracks timestamp order — it doesn't here,
  because records are queued and batched, so concurrent workers interleave.
  It now cuts on `ts`.

- `TELEMETRY_LOG_CAPTURE_ENABLED=false` switches the whole subsystem off: no
  handler, no queue, no thread, no rows.

### Fixed — telemetry subsystem
- **Production log output is now actually JSON.** The `json` formatter was a
  `%`-style string template (`'{"message": "%(message)s"}'`) that only looked
  like JSON. It emitted malformed lines in three routine cases, all of which
  silently corrupted anything downstream that tried to parse them:

  - **Any quote, backslash, or newline in a message** broke the line — nothing
    escaped `%(message)s`. A single `logger.info('Ticket "42" closed')` was
    enough.
  - **`logger.exception()` was unparseable by construction.** Python appends the
    traceback *after* the formatted string, so the JSON object was followed by
    20-odd raw `Traceback` lines. The most important events were the ones a
    collector could never read.
  - **`extra={...}` was silently discarded.** The format string had no
    placeholder for it, so existing structured call sites in `apps/api/threats.py`
    and `apps/help/search.py` were logging fields that went nowhere.

  Formatting now runs through `json.dumps` (`apps.smallstack.logging.JSONFormatter`):
  messages are escaped, tracebacks land in an `exc` field (with `exc_type`
  alongside) *inside* the object, `stack_info` lands in `stack`, and `extra`
  fields are preserved under an `extra` key. Non-serializable values fall back to
  `repr()` instead of taking the line down, and the formatter cannot raise — a
  serialization failure degrades to a minimal object carrying the message.

### Added — telemetry subsystem (correlation)
- **Log lines carry the request ID that produced them.** `RequestIDMiddleware`
  binds the request ID to a `contextvar`; a new `RequestContextFilter` on each
  handler copies it onto every record as `request_id`. The docs already promised
  you could correlate a user-reported `X-Request-ID` to log entries — now you
  actually can, across both the log stream and the `RequestLog` table, with no
  changes at any call site.
- **`bind_trace_id()` / `reset_trace_id()`** in `apps.smallstack.logging`, for
  stitching together work that isn't a single HTTP request — scheduled jobs,
  webhook delivery chains, multi-step agent runs. Every log line emitted inside
  the binding carries a shared `trace_id`.
- **`apps/smallstack/test_logging.py`** — 33 tests pinning JSON validity
  (quotes, backslashes, newlines, unicode, nested JSON), traceback containment,
  `extra` preservation, context binding and reset-on-exception, and a check that
  the `development.py` / `production.py` `LOGGING` dicts configure cleanly. The
  test settings override `LOGGING`, so nothing else in the suite exercised them.

### Changed — telemetry subsystem
- **Production log timestamps are ISO-8601 UTC** (`2026-03-04T14:23:01.123Z`)
  instead of local-time `%(asctime)s`, so lines from different hosts sort
  correctly. JSON output is ASCII-escaped by default so it can never raise
  `UnicodeEncodeError` on a stream with a non-UTF-8 encoding; parsers decode the
  escapes back to the original text. Pass `ensure_ascii=False` to `JSONFormatter`
  if you read raw container logs by eye.
- **Development console lines show `request_id=…`** when emitted during a
  request, appended at the end of the line so the left edge stays scannable.

## [0.19.0] - 2026-08-16

### Changed
- **The "Connect a SmallStack" pairing panel picks events instead of asking for
  raw JSON.** The "Events (JSON)" text field is replaced by the same
  `EventFilterWidget` picker the endpoint form uses — checkboxes built from
  `available_events()`, with `*` pre-checked reproducing the old `["*"]`
  default. Both surfaces now share one picker, upgraded together:

  - **Plain-English annotations** on every option (`*.created — any record is
    created`; model patterns resolve verbose names: *"a Ticket is created"*).
  - **A help popup** on the custom-pattern box explaining the
    `app.model.action` grammar with examples — built on a new reusable
    `.help-pop` component (`<details>`-based, no JS, keyboard-operable,
    palette-correct), documented in `admin-page-styling.md`.
  - **Progressive disclosure**: the custom-pattern box collapses to a quiet
    "advanced" line when empty and auto-expands with a count badge whenever
    patterns exist — expansion is round-trip safety, since patterns usually
    arrive via REST/MCP/CLI and a UI save with the textarea absent would
    silently strip them.

  The scripted contract is unchanged: raw `events` JSON is still accepted by
  the pairing action, and REST/MCP/CLI post `event_filter` exactly as before.

### Fixed
- **Malformed event patterns are now rejected instead of silently matching
  nothing.** A typo is still valid JSON, so `"support ticket created"` or a
  pasted `["*"]` sailed through every surface and produced an endpoint that
  simply never fires, with no error anywhere. `validate_event_patterns()`
  shape-checks patterns on the endpoint form — HTML, REST, MCP, and CLI all
  validate through it — and in the pairing view. Well-formed patterns that
  match nothing this instance currently emits are still accepted (they may
  target future events); the pairing flow warns about them, staying silent on
  instances with no concrete events where the warning would be noise. Pairing
  with an empty selection is rejected rather than creating a link that
  forwards nothing.
- **The event picker's border used the undefined `--border-color` variable**,
  falling back to a hard-coded `#333` on light themes (the v0.15.2 bug class).
  Now `var(--card-border)`.

## [0.18.0] - 2026-08-15

### Changed
- **The scheduler job edit page is redesigned as a control console.** It was a
  1,830px single-column form with **Run now** buried at the bottom as a
  tertiary outline button; it is now 1,040px with Run now leading the page.

  An **identity strip** replaces both the generic "Edit Scheduled job" card
  header and the read-only "What it runs" section: status dot, job name as the
  title, task path / queue / args in the monospace ops voice, a status line,
  and Run now as a solid-accent button top right. The body becomes two rails —
  cadence editor left, behavior toggles + the Next-5-runs preview right — so
  the fire-time feedback is visible *while* the cadence is edited. Collapses
  to one column under 940px; on mobile Run now stays above the fold.

  The strip also surfaces a state the old page hid: a `next_run_at` in the
  past (stalled worker) used to display as a future-looking "next fire" — it
  now reads **"fire overdue since <date> — is the worker running?"** in
  warning color.

  Delivered as `scheduler/crud/scheduledjob_edit.html` via the CRUDView
  template chain — no framework changes, all cadence-builder JS and htmx
  endpoints untouched. Theme-variable-only, verified across palettes.

### Fixed
- **"Run now" returns to the job page.** `scheduler_run_now` honors a
  same-origin-validated `next` param (the control page posts its own path);
  offsite values fall back to the dashboard, so it cannot become an open
  redirect. Callers that don't pass `next` see the old behavior.

## [0.17.0] - 2026-08-15

### Changed
- **The admin sidebar section is listed A–Z instead of by hand-assigned
  `order`.** It reads: Activity, API Health, API Tokens, Backups, Dashboard,
  Explorer, MCP, Scheduler, Search, Status, Users, Webhooks.

  That section is a tool drawer — a dozen unrelated utilities contributed by
  whichever apps are installed, with no workflow sequence to preserve. It was
  hand-numbered across twelve `apps.py` files, so every new app had to pick a
  number, the numbers collided (`Status` and `Explorer` both sat at `20`, making
  their relative position a function of `INSTALLED_APPS` ordering rather than
  intent), and the list drifted out of alphabetical whenever anything was added
  or relabelled. Sorting in the registry keeps it A–Z permanently, including for
  apps a downstream project adds — which renumbering upstream could never fix.

  Sorting is case-insensitive, so "API Health" files next to "Activity" rather
  than ahead of every lowercase label.

  **`order` is now inert for the admin section** (documented on `register()`).
  A downstream project that deliberately ordered its own admin nav items will
  see them alphabetised instead. Existing `order=` values are harmless and were
  left in place. Every other section still honours `order` exactly as before.

  **"Admin Panel" is unaffected** — it isn't a registry item, but a hardcoded
  link at the end of `sidebar.html` out to Django's own admin, so it stays
  pinned last rather than filing under A.

## [0.16.2] - 2026-08-15

### Fixed
- **Empty states rendered raw template source into the page.** Django's
  tokenizer matches tags with `{%.*?%}` and **no `DOTALL`**, so a `{% %}` tag
  split across lines is never parsed — it is emitted as literal text. Four
  empty-state includes were wrapped for readability and shipped that way, so a
  visitor saw:

  ```
  {% include "smallstack/includes/empty_state.html" with
     no_card=True
     title="No matches"
     body="No "|add:object_verbose_name_plural|add:" matched your search…" %}
  ```

  This hit **every CRUDView on the default templates whenever its list was
  empty** — a no-match search or a fresh install with nothing added yet — on
  both the plain page load and the HTMX toolbar swap, plus the dashboard
  "no widgets available" state and the MCP tools admin.

  The pattern spread because `empty_state.html`'s own usage example was written
  wrapped and every caller copied it; that example is now a single line carrying
  an explicit warning. A whole-tree sweep test now fails the build on any
  multi-line tag — the defect is invisible in review, since the template reads
  perfectly well.
- **A missing `object_verbose_name_plural` raised instead of degrading.** With
  the tag parsing again, `body="No "|add:object_verbose_name_plural` makes that
  variable a filter *argument*, and an unresolved filter argument raises
  `VariableDoesNotExist` rather than rendering empty the way `{{ missing }}`
  does. `_CRUDContextMixin` always supplies it, but this partial is also
  included by hand-written list templates (`usermanager` does, and downstream
  projects do) — it now resolves through `{% with %}` with a default noun.

### Added
- **The related-tab partial is overridable like every other CRUD surface.**
  `_CRUDRelatedTabBase` hardcoded its template while every sibling — including
  `_CRUDFieldPreviewBase` directly above it — resolves through
  `_get_template_names(suffix)`, so it was the one CRUD surface a project could
  not override per model or per app. It now offers the same instance → app →
  default chain. The shipped partial lives at
  `crud/includes/related_tab_content.html`, which doesn't fit the
  `crud/object_{suffix}` default convention, so that path is appended as the
  final fallback — the loader takes the first template that exists, so behavior
  is unchanged when no override is present.

## [0.16.1] - 2026-08-14

### Fixed
- **`CalendarDisplay` compared `DateTimeField`s against naive month boundaries.**
  Filtering used plain `date` bounds, so under `USE_TZ` Django built a naive
  midnight, emitted "received a naive datetime while time zone support is
  active", then coerced it with the **default** timezone — while the bucketing
  side used `localtime()`, the **current** one. Two halves of the same display
  deciding "is this in the month?" through different clocks. Boundaries are now
  coerced to the type each field expects (aware midnight for datetimes, the
  plain date for `DateField`s), resolved independently for the start and end
  fields.

  **No events move.** Verified against rows straddling both month edges,
  including exact midnights: old and new code select identically. The two
  timezones coincide because nothing activates a per-request timezone (the
  profile timezone is applied by a template filter), so the drift this prevents
  is latent — it would only appear if timezone-activating middleware were added.
  Removes 24 warnings from the test suite.
- **`api_doctor` detected opt-ins by regex while `mcp_doctor` used AST.** The
  line-anchored regex matched `enable_api = True` on any line with only
  whitespace before it — i.e. exactly how a code example is indented inside a
  docstring, which is how this codebase documents its own flags (8 in-scope
  modules already mention `enable_api` in prose). Nothing was misreported: of
  two regex/AST disagreements repo-wide, both sat outside the scan's scope. That
  was the problem — the check was correct only because a directory exclusion
  happened to cover the one offending file.

  Both doctors now share `has_enable_classvar(source, marker)` in
  `apps/smallstack/autodiscover.py`, so they agree on what an opt-in is. With
  AST the `management/` exclusion is unnecessary, so `api_doctor` scans that
  directory again — closing the opposite gap, where a genuine opt-in defined in
  a management command was invisible to it but visible to `mcp_doctor`.

## [0.16.0] - 2026-08-14

### Changed
- **`CalendarDisplay` caps events rendered per day (`max_per_day`, default 5).**
  The calendar rendered one chip — plus a hover-tooltip subtree — for every
  record in the visible month, so a high-volume site produced tens of thousands
  of DOM nodes and a calendar that took seconds to paint, or never usefully did.
  Cells now render at most 5 events followed by a **"+N more"** link that
  expands that single day in full (`?day=YYYY-MM-DD`). Overflow events are
  counted, not materialised.

  The point isn't the constant factor — it's that rendered chips are now bounded
  by `max_per_day × days_in_month` **regardless of record count**. Measured on
  200 seeded records: 201 chips / 171 KB before, 26 chips / 73 KB after.

  Capping is a *rendering* limit only: the header total and every "+N more"
  badge still report exact counts. **This changes what existing calendars
  display** — pass `max_per_day=None` to restore the previous behavior.

### Fixed
- **Related tabs 500'd when the related view had no DETAIL action.**
  `_CRUDRelatedTabBase` hardcoded `crud_actions = [Action.DETAIL]`, so
  `{% crud_table %}` reversed `<url_base>-detail` for a view that never
  generates that route (`get_urls` only registers it when `actions` include
  DETAIL). Because related tabs load lazily over HTMX, the NoReverseMatch
  surfaced as a tab with a count badge and an empty body rather than a visible
  error. The tab now forwards what the related view actually routes — DETAIL,
  else UPDATE, else unlinked — matching `crud_table`'s documented fallback.
  DELETE is never forwarded, and exactly one action is passed so a tab whose
  target routes both doesn't grow an Edit column it never had.
- **Related tabs rendered child rows through the parent's hooks.**
  `crud_config` stayed the parent CRUDView's, and `{% crud_table %}` reads
  `row_link_url()`, `row_actions()` and `column_widths` off it — so a parent
  that redirects its row links silently pointed a child row at an unrelated
  record that happened to share its pk. Fails silently, so worth re-checking any
  related tab under a CRUDView that overrides those hooks.
- **`api_doctor` / `mcp_doctor` reported test fixtures as unregistered opt-ins.**
  Both excluded test code by directory (`tests/`), missing the flat `test_*.py`
  convention `apps/smallstack` uses — so `smallstack/test_bulk_ops.py` was
  flagged as an orphan on every run and on the `/smallstack/api/` and
  `/smallstack/mcp/` pages. A CRUDView declared in a test is meant to stay out
  of the registry; the advertised fix (importing it from `AppConfig.ready()`)
  would have published a test view as a live REST endpoint and MCP tool. The
  shared `is_test_module()` helper now lives in
  `apps/smallstack/autodiscover.py` and covers both layouts.

## [0.15.2] - 2026-08-12

### Fixed
- **Invisible "Copy" button on the token-reveal page (gold + high contrast).**
  The button set a background but no `color`, so it inherited `--button-fg` —
  the foreground meant to pair with a *solid* `--primary` fill. On the only two
  palettes with a dark `--button-fg` (gold `#1a1a1a`, high-contrast `#000000`)
  that painted dark text on a dark card and the label disappeared. It now uses
  the existing `.btn-outline` class.
- **Unreadable MCP consent page (`/mcp/oauth/authorize`) on dark themes.** The
  template referenced `--border`, `--muted-fg` and `--code-bg`, none of which
  were defined anywhere, so each always resolved to its hard-coded *light*
  fallback: gray borders on dark cards, and `#f4f4f4` chips whose inherited text
  was also light. That made the client id and the **redirect host** — the one
  field a user must read before granting access — invisible. Its Allow button
  also hard-coded `color: #fff` over `var(--primary)`, i.e. white-on-white on
  the high-contrast palette.
- **Links ignored the selected palette in light mode.** Every dark palette block
  set `--link-fg`, but the gold / orange / purple / dark-blue *light* blocks set
  only `--link-color`. SmallStack's own CSS reads `--link-color`, while Django
  admin's `a:link, a:visited` rule reads `--link-fg` — so every plain anchor
  stayed on admin's `#417893` teal. All light blocks now set both.
- **The default `django` palette had no light block at all**, so light mode fell
  through to Django admin's colors (`--primary: #79aec8`) instead of
  SmallStack's. `admin/css/base.css` declares its variables under
  `html[data-theme="light"], :root`; that first branch scores (0,1,1) and the
  theme JS always writes an explicit `data-theme`, so it outranks theme.css's
  plain `:root` (0,1,0) no matter which file loads last. Adds a django light
  block built on emerald-700 `#047857` (5.5:1 on white — the dark palette's
  `#10b981` is only 2.5:1 and unusable for accent text).

### Added
- **`--border`, `--muted-fg` and `--code-bg`** are now defined in `theme.css`.
  They were referenced by templates but declared nowhere, which is what let the
  bugs above degrade silently. Defined as derived aliases (`var(--card-border)`,
  `var(--text-muted)`, and a `color-mix` recipe) so they track the active theme
  and palette with no per-palette overrides. Prefer the specific token in new
  code.
- **`apps/smallstack/test_palette_css.py`** — parses `palettes.css` against
  `UserProfile.COLOR_PALETTE_CHOICES` and fails if any palette is missing a
  light or dark block, or omits `--link-fg` / `--link-color`.

## [0.15.1] - 2026-08-09

### Internal
- **Test coverage backfill (codebase-review F4).** No behavior change — new
  tests only. `postgres_fts.py` 0% → 83% (a Postgres-gated suite that runs under
  `TEST_DB=postgres` and skips on SQLite); `api.py` 75% → 88% (the auth endpoints
  — register / password change / admin reset — and the REST bulk-update
  endpoint); `mcp/factory.py` 76% → 92% (the update/delete MCP tool handlers);
  `crud.py` 78% → 84% (the HTML bulk-action + bulk-update-form views);
  `audit.py` 57% → 80% (the `log_write` never-raises discipline).

## [0.15.0] - 2026-08-09

### Changed
- **BREAKING — CRUDViews require login by default.** `CRUDView.mixins` now
  defaults to `None`, which the framework resolves to `[LoginRequiredMixin]`;
  previously the default was `[]` (anonymous). A CRUDView that *omitted* `mixins`
  silently shipped public HTML **and** REST endpoints — now it requires login.
  Opt into anonymous access with the new **`public = True`** flag (or an explicit
  `mixins = []`); an explicit `mixins` list always wins. A public view that
  exposes write actions with `enable_api=True` now emits a warning. All bundled
  framework views set `mixins` explicitly and are unaffected. See
  [`UPGRADING.md`](UPGRADING.md). (Codebase-review F6.)

### Added
- **`make typecheck`** — mypy + django-stubs, configured leniently and scoped to
  the type-clean apps (starts at `apps/feeds`; widen app-by-app as each reaches
  green). A local / pre-commit guard, no CI lane. (Codebase-review F3.)

### Removed
- **django-debug-toolbar** — removed from the project entirely (dependency, the
  dev-settings toggle, the `__debug__/` URL, and the bundled help page). It was
  off-by-default dev tooling; dropping it slims the dependency surface.

## [0.14.3] - 2026-08-09

Fixes from a full codebase review (two security fixes + a Django 6.1 deploy-check
regression). All backward-compatible.

### Fixed
- **Security — stored XSS on public search snippets.** Dropped `|safe` on the
  website search result snippet (`templates/website/search.html`); the value is
  raw model text and the view is anonymous, so it's now auto-escaped.
- **Security — PKCE code-challenge compared in constant time.** `verify_pkce`
  (`apps/mcp/oauth.py`) now uses `hmac.compare_digest` instead of `==`.
- **Fresh-clone `manage.py check --deploy` passes again.** Django 6.1's
  `mail.E001` deploy check errored on dev's console email backend; it's now
  silenced in development settings (dev isn't a deploy target — production/SMTP
  is unaffected and still validated). Regression from the v0.14.2 / Django 6.1
  MAILERS migration.

### Removed
- **Dead search abstraction layer** — `apps/search/{api,orchestration,cache,serializers}.py`
  (813 lines with no runtime importers; runtime search goes through
  `get_backend()` directly). Removing it also eliminates a latent
  `SearchAPI.search()` access-gate bypass.

### Internal
- Test integrity + coverage: replaced hollow `api_doctor` tests with a real
  fail-case assertion, restored the SearchBuilder-example + search-admin tests,
  and added audit-logging failure-path tests (`audit.py` 57% → 80%). Documented
  the help-renderer trust boundary.

## [0.14.2] - 2026-08-09

### Fixed
- **Absolute URLs are `https://` behind kamal-proxy.** The base `production.py`
  shipped without `SECURE_PROXY_SSL_HEADER`, so behind the TLS-terminating proxy
  (which forwards over HTTP) `request.is_secure()` was False and Django built
  `http://` absolute URLs — feed self-links, sitemaps, and the links in
  password-reset / invite emails all went out as http. Now sets
  `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`, **gated on the
  existing `TRUST_PROXY_HEADERS` flag** (default-on in production). Safe by
  default for non-proxy deployments: a directly-exposed instance
  (`TRUST_PROXY_HEADERS=false`) never trusts a client-supplied `X-Forwarded-Proto`.

## [0.14.1] - 2026-08-09

Two upstream bug fixes surfaced by a downstream deploy.

### Fixed
- **Docker builds install from the frozen `uv.lock`.** The `Dockerfile` copied
  `uv.lock` but installed with `uv pip install -e .`, which re-resolves the
  `pyproject.toml` ranges (`django>=6.1`, …) against the index at build time and
  ignores the lock — so images could silently drift onto newer, untested
  dependency releases (a routine deploy pulling a future Django and breaking on
  an incompatible transitive dep, with nothing changed in the repo). Now exports
  the frozen lock and installs that exact set, then the project with `--no-deps`.
  Builds are reproducible (prod == local == CI) and fail loudly if `uv.lock`
  drifts from `pyproject.toml`. Verified via an image build.
- **`mcp_doctor` no longer false-positives on `enable_mcp = True` in strings.**
  The unregistered-opt-in scan was a naive substring match that fired on the
  marker inside docstrings/seed content (the runbook seed command embeds a
  teaching example), turning `mcp_doctor` and the dashboard MCP card yellow over
  a non-issue. It now uses AST detection — the marker counts only as a real
  `ClassDef`-body assignment. `mcp_doctor` goes 6✓/1⚠ → 7✓/0⚠.

## [0.14.0] - 2026-08-08

Django 6.1 + the email `MAILERS` migration. Minor bump because the email change
is **breaking for downstream projects that set `EMAIL_BACKEND`** in their own
settings (see UPGRADING). Also the first published release to carry the
accessibility foundation and the RSS/Atom feeds surface from v0.13.13.

### Changed
- **Django 6.0 → 6.1** (latest stable). `manage.py check` clean and the full
  suite passes; every third-party dependency (axes, csp, filter, htmx,
  tasks-db, cors-headers, debug-toolbar, extensions, whitenoise, mcp) is
  compatible unchanged.
- **Email migrated to Django 6.1's `MAILERS`.** The framework now ships a
  `MAILERS` dict (assembled from the same `EMAIL_*` **environment variables**
  via `config/settings/_email.py`) instead of the deprecated flat `EMAIL_*`
  *settings*, and drops the deprecated `fail_silently` argument across all mail
  calls. This clears every `RemovedInDjango70Warning`. `DEFAULT_FROM_EMAIL` /
  `SERVER_EMAIL` and `send_mail` / `EmailMultiAlternatives` / `mail_admins` are
  unchanged. **Breaking:** Django 6.1 raises `ImproperlyConfigured` if a
  deprecated `EMAIL_*` setting coexists with `MAILERS` — downstream projects
  that define `EMAIL_BACKEND` must migrate (UPGRADING.md).

### Fixed
- Accessibility WCAG 2.1 AA follow-ups across the theme, CRUD tables, and the
  feeds surfaces (sortable headers became real `<button>`s with `aria-sort`,
  focus and labelling polish).
- Feeds: enforce the `SMALLSTACK_FEEDS_ENABLED` master switch on the request
  surface, Django-6 enclosure handling, and consume-side auth headers.
- Test suite: silenced pre-existing naive-datetime and unclosed-file
  `ResourceWarning` noise (no behavior change).

## [0.13.13] - 2026-08-08

Two new surfaces — first-party RSS/Atom feeds and an accessibility foundation —
both built as reusable, documented primitives with the "fix once in the
framework, every project benefits" model.

### Added
- **RSS/Atom feeds (`apps.feeds`)** — a symmetric publish + consume surface,
  mirroring the webhooks philosophy. **Publish**: ``enable_rss = True`` on a
  CRUDView exposes it at ``/feed/<slug>.rss`` (+ ``.atom``), deriving items from
  the existing ``search_display``/``search_subtitle``/timestamp/detail-route
  declarations; curated feeds subclass ``Feed`` + ``register_feed``. Access is
  gated by ``SearchAccess`` (anonymous/authenticated/staff; token via Bearer or
  ``?token=``). The ``rss_item_extra(obj)`` seam attaches enclosures/iTunes tags
  so media/podcast feeds are a downstream add-on, not core. **Consume**:
  ``register_feed_source(name, url, model=, map=, dedupe=)`` + a dependency-free
  RSS 2.0/Atom parser + a collector that runs as ``manage.py collect_feeds`` and
  a ``@scheduled`` poll job (idempotent, deduped), landing in a bundled
  ``CollectedItem`` model or your own. The public status page publishes an
  incidents-plus-maintenance feed at ``/feed/status.rss`` as the reference.
  Skill: ``docs/skills/rss.md``.
- **Accessibility primitives** — reusable building blocks: ``.sr-only``,
  ``.skip-link``, a global ``:focus-visible`` ring, and
  ``window.SmallStack.trapFocus(el)`` (used by the stat modal + omnibar). Skill:
  ``docs/skills/accessibility.md`` (primitives, rules, pre-"done" checklist),
  wired into the read-first guides so agents build accessibly by default.

### Fixed
- **Accessibility (WCAG 2.1 AA) gaps across the theme** — keyboard focus rings
  on form inputs (previously ``outline: none`` with no ``:focus-visible``
  replacement, a 2.4.7 blocker); a skip-to-content link; form errors announced
  via ``role="alert"``; ``<th scope>`` + ``aria-sort`` on CRUD tables; modal
  ``role="dialog"``/``aria-modal``/labelled close + focus trap; and
  ``aria-hidden`` on the decorative SVGs in the shared topbar/sidebar/user-menu.

## [0.13.12] - 2026-08-08

Postgres out-of-the-box hardening for search, upstreamed from a downstream
post-mortem (search worked in dev SQLite, then broke and crawled on prod
Postgres). SQLite masks each of these, so the fix is making the Postgres path
good by default. All backward-compatible; verified on SQLite and a real
Postgres 16.

### Added
- **`reindex_instances(model, objects=None)`** (`apps.search`) — reindex rows
  written by `bulk_create` / `bulk_update` / `QuerySet.update()`, which fire no
  signals and were otherwise left **silently un-indexed** (the most common
  importer/data-migration footgun).
- **Search diagnostics** — `manage.py search_diagnose [query]` and a staff page
  at `/smallstack/search/diagnostics/` share one core: per-table health (est.
  rows, GIN present, un-indexed backlog), app-level timing, and a live
  `EXPLAIN` verdict (Seq Scan vs GIN Bitmap Index Scan, size-aware so it doesn't
  cry wolf on small tables). Answers "is search fast, and if not, where's the
  time" when you can't reach `psql`.
- **`analyze_search_index` management command** — refreshes Postgres planner
  stats for every searchable table (cheap, fast, safe on every deploy; wired
  into the container entrypoint). No-op on SQLite.
- **Help full-text search on Postgres** — both the article index (omnibar /
  `search_help`) and the passage-level RAG index behind the `search_help_docs`
  MCP tool now build a `tsvector`+GIN index on Postgres instead of falling back
  to a Python scan (which returned **empty** for the RAG tool on prod).
- **`digits_search()`** (`apps.search`) — recipe/helper for indexing opaque
  identifiers (phone numbers, SKUs) that the `english` FTS tokenizer won't
  match on partial/formatted input.

### Changed
- **Postgres `rebuild_search_index` is now set-based** — one
  `UPDATE … setweight(to_tsvector(…)) || …` for views whose `search_fields` are
  all local columns (seconds instead of O(rows) per-row UPDATEs); per-row
  fallback retained for property/`__`-related fields. Runs `ANALYZE` afterward.
- **GIN indexes are created `CONCURRENTLY`** on Postgres (autocommit-guarded) so
  provisioning never locks a live table; provisioning failures are surfaced
  rather than only logged.
- **Search-hub row counts use the planner's `reltuples` estimate** on Postgres
  instead of `COUNT(*)` per model (instant catalog lookup vs full scan).

### Fixed
- **Help docs were re-parsed from disk on every request.** `build_search_index()`
  is now memoized (`@lru_cache`); on Postgres, where help search fell back to a
  scan, this took the hot path from ~4.5 s to ~15 ms (~300×).
- **Search results are clickable without `get_absolute_url`.** Hits fall back to
  the registering CRUDView's `{url_base}-detail` route.
- **Changing `search_fields` no longer breaks SQLite search.** FTS5 bakes one
  column per field at create time; the table is now detected as drifted and
  recreated (previously `rebuild_search_index` failed with "table … has no
  column named …").
- **`api_view` no longer force-parses multipart/form bodies as JSON.** File
  uploads to custom API endpoints returned 400 "Invalid JSON" because the
  decorator read `request.body` and demanded JSON for every write method.
  Multipart and form-encoded content types now skip JSON parsing
  (`request.json` is `None`; use `request.POST`/`request.FILES` as usual).
- **Bare-button hover styling no longer outranks custom button classes.** The
  base `button` / `input[type=submit|button]` rules put only the wrapper inside
  `:where()`, so `button:hover` still carried (0,1,1) specificity — enough to
  beat a downstream single-class button (0,1,0) on hover and slide the
  `--primary-hover` background under its custom text color (low-contrast
  accent-on-accent hovers). The entire selector now sits inside `:where()`
  (true zero specificity, all states), matching the rule's stated intent.
  Downstream apps that added defensive per-state `background` declarations can
  keep or drop them; they are now redundant.

## [0.13.11] - 2026-07-29

### Added
- **Datasets — bucketed grouping + drilldown** (R8, the final datasets-feedback
  item). `series()` now accepts a **dict** dimension for bucketed grouping:
  numeric bands (`{lo, hi}`, half-open), categorical (`{value}` / `{values}`),
  an honest `{other: true}` complement, and **auto** top-N value buckets keyed
  `v:<value>` (+ `other`) derived from the unnarrowed scope so keys stay stable
  under filters. Count-only (`[{key, label, value, lo, hi}]`). A `rows(dimension=,
  bucket=)` **drilldown** re-applies the same bucket condition, so the rows behind
  a bucket reconcile with its count by construction. Exposed over REST (JSON
  `buckets` / `auto` params, `bucket=` drilldown) and MCP (`buckets` array, `auto`,
  `bucket`). The bucket grammar (`apps/datasets/buckets.py`) is lifted verbatim
  from the downstream reporter so call_stats can swap to it.

## [0.13.10] - 2026-07-29

### Added
- **Datasets hardening** (from downstream feedback):
  - `@dataset(filterable=…)` replaces `filters=` for the *declaration* of which
    columns may be filtered; the old `filters=` decorator kwarg is a deprecated
    alias (warns). Runtime `rows()/series()/scalar()(filters=…)` is unchanged.
  - Public **`ds.queryset(request, filters)`** seam so a higher layer (a BI/report
    layer) can compose on a dataset's filtered queryset without touching internals.
  - **Pagination**: `rows(limit, offset)` (+ `limit=None` for the whole set) and
    `ds.count()`; the REST rows route returns an envelope `{count, total, offset,
    results}` and CSV exports the whole filtered set.
  - **Declared ratio measures**: `@dataset(measures=[(name, num, denom, fmt)])`
    computes `sum(num)/sum(denom)` in-DB per group (`×100` for percent), returning
    `None` for an empty denominator — never the average of per-row ratios. Surfaced
    in `schema()` (`computed: true`) and the MCP tool.
  - **Explicit date ranges**: `<col>__gte` / `<col>__lt` half-open bounds on any
    date/datetime column, everywhere filters are accepted (explicit wins over a
    preset); `schema()` advertises `"range": true`.
- Datasets app **label namespaced** to `smallstack_datasets` (avoids an
  `INSTALLED_APPS` clash with a downstream app named `datasets`).
- Docs: naming guidance + the flat-filter invariant documented in `datasets.md`.

## [0.13.9] - 2026-07-29

### Added
- **Datasets (`apps/datasets/`)** — the `@dataset` primitive: register a filtered
  queryset as a named, typed source of rows/columns for dashboard/report/chart
  UIs. `schema()` introspects it into dimensions/measures + filter widgets;
  `rows()` returns tabular data (FK columns are a bare pk by default, `id`+`name`
  on expand), `series()` aggregates a measure over a dimension (resolving FK
  dimension labels to name), and a **scalar** mode returns a single aggregate
  (count / sum) when no dimension is given. Opt-in REST + MCP: a `query_dataset`
  tool (series + scalar, honoring filters) and JSON endpoints (anonymous → 401).
  Unknown dimension/measure raise a clear `ValueError`. See `docs/skills/datasets.md`.
- **Help RAG** — a lexical passage index over the bundled help docs plus a
  `search_help_docs` MCP tool, so AI clients can retrieve relevant doc passages.

## [0.13.8] - 2026-07-26

### Added
- **Webhooks (`apps/webhooks/`)** — outbound event delivery and inbound receivers,
  built on the CRUDView pipeline. A model opts into **outbound** with
  `enable_webhooks = True` (like `enable_search`); a global `post_save`/`post_delete`
  observer fans every change — across HTML, REST, MCP, `sc`, and raw ORM — out to
  matching `WebhookEndpoint`s as an HMAC-SHA256-signed POST, delivered through the
  `django.tasks` queue with exponential backoff, **`Retry-After`** support,
  auto-disable, a dead-letter state, and **bulk replay**. **Inbound**: a
  `WebhookReceiver` + a `@webhook_handler` verify the signature (constant-time) and
  dispatch. Ships an SSRF guard, staff-only secret reveal/rotate, a
  `/smallstack/webhooks/` dashboard, a status monitor, `webhook_doctor`, `sc webhook`
  ops, and MCP tools.
- **Webhook extension seams** — four named-registry hooks (`@webhook_transform`,
  `@webhook_auth`, `@webhook_verifier`, `@webhook_challenge`), autodiscovered from an
  app's `webhook_*.py` and each defaulting to the built-in behavior, so a specific
  integration (Slack payloads, Stripe/GitHub/SNS signatures, SAS/OIDC auth, Event Grid
  validation) is a small plug-in rather than a core change. A complete **Azure Event
  Grid** reference adapter (`apps/webhooks/contrib/eventgrid.py`) is built purely on
  the seams with zero core edits.
- **SmallStack↔SmallStack pairing** — `sc webhook pair` stands up a loop-safe two-way
  link in one command (paired endpoint + receiver with per-direction secrets, a
  `suppress_webhooks()` loop guard, and an `X-SmallStack-Origin` header so write-backs
  can't run away). A stable `X-SmallStack-Event-Id` lets consumers dedupe across
  retries and operator replay.

## [0.13.7] - 2026-07-25

### Fixed
- **CRUD list "N Records" count** — the record count lives in the toolbar, outside
  the `#crud-list-content` htmx swap target, so a search/filter left it showing the
  stale pre-filter total. The list-content response now emits an out-of-band copy
  of the count span (`hx-swap-oob`) so it refreshes alongside the list — no extra
  request, no JS. Guarded by `request.htmx` so a full-page load (which includes the
  partial in-page) doesn't render a duplicate. The `tokenmgr` app, which overrides
  the generic list-content partial, gets the same out-of-band refresh.

## [0.13.6] - 2026-07-21

### Added
- **Scheduler (`apps/scheduler/`)** — recurring background jobs over `django.tasks`
  (no Celery/Redis). Ships the `@scheduled` decorator (cron / interval / once,
  with calendar-aware intervals and anchors), DB-backed `ScheduledJob` schedules
  with idempotent code-sync, and a `run_due_jobs` tick with an **atomic claim**
  so concurrent triggers can't double-fire. Overlap guard (with a stale-run
  timeout so a dead worker can't wedge a schedule), catch-up policy, and run
  history linked to the task engine's `DBTaskResult`.
- **Scheduler surfaces** — themed `/smallstack/scheduler/` dashboard (stat cards,
  24h run timeline, upcoming + recent runs, per-job Run-now), a `ScheduledJob`
  CRUDView with REST (`enable_api`) + MCP (`list_schedules` … `delete_schedule`)
  + search, a dashboard widget, a `/status/` core monitor, and Explorer browsing.
- **Scheduler control UI** — the jobs list gains a table⇄calendar toggle (upcoming
  runs by next fire) plus a read-only **run-history** view with its own
  table⇄calendar coloured by outcome. Code-owned jobs render as a **read-only
  control page**: the definition is locked to code; operators override only the
  schedule + enable/pause + Run-now. UI schedule overrides survive code-sync
  (`schedule_overridden`), with a "reset to code default".
- **Triggers** — `POST /smallstack/scheduler/tick/` (localhost-only, runs inside
  gunicorn), `manage.py run_due_tasks`, `manage.py scheduler_beat`; plus
  `manage.py prune_job_runs` history retention. Cron lines added to
  `scripts/smallstack-cron`.
- **Focus mode** on Help & Docs and Runbook now also collapses the SmallStack side
  menu for an immersive read (non-persistent; restored on Expand). `theme.js`
  exposes `window.smallstackSidebar` (get/set state with a persist opt-out).
- Settings: `SMALLSTACK_SCHEDULER_ENABLED`, `_STALE_RUN_SECONDS`,
  `_OVERDUE_GRACE_SECONDS`, `_FAILURE_EMAILS`. New dependency: `croniter`.
- Docs: `docs/skills/scheduler.md`; `@scheduled` flipped from "coming soon" to
  shipped in `CLAUDE.md`, `README.md`, `background-tasks.md`, `skills/README.md`.

### Changed
- **Runbook markdown** now renders with the same recipe as Help & Docs (roomier
  18px/1.8 prose, heading rules, neutral non-accent-tinted code inset into the
  card) — fixes the long-standing readability gap between the two surfaces.
- **Orange palette** retuned to a warm-ground "quiet luxury" look (vivid accent,
  warm-biased surfaces); the elegance levers are documented in `modify-palettes.md`.
- User-menu **"Admin"** now opens the SmallStack dashboard (`/smallstack/`) rather
  than raw Django admin (still reachable from the sidebar "Admin Panel").

### Fixed
- Scheduler hardening: timezone dev/prod parity (Linux/Docker), recompute + monitor
  sample-floor tuning, and agent-hostile input hardening.

## [0.13.5] - 2026-07-19

### Fixed
- **SQLiteFTSBackend.rebuild() deadlock** — Fixed "database is locked" error on models with >500 rows. 
  Root cause: iterator(chunk_size=500) kept read cursor open during writes. Solution: materialize pk list, 
  batch with explicit transactions. Approximately 50x faster; tested with 25,713+ rows.
- **SearchBuilder.transform_hit() call convention** — Fixed silent failure where custom variants returned 
  empty extra payload. Root cause: instance method called unbound on class (TypeError swallowed). 
  Solution: instantiate view before calling, matching pattern elsewhere. Enhanced error logging to 
  document contract.
- **PostgresFTSBackend.rebuild()** — Applied same deadlock fix as SQLite (consistent batching pattern).

### Documentation
- Added fixes/DOWNSTREAM-ISSUES.md documenting both bugs, root causes, and fixes.
- Clarified that filter_searchable_queryset and get_ranking_weights are dead code in v0.13.4; 
  use search_weight and post-filtering instead.

### Backward Compatible
- No API changes
- All fixes are transparent to downstream apps
- Required for any model with >500 rows + enable_search, or custom SearchBuilder.transform_hit()


## [0.13.4] - 2026-07-18

### Added
- **SearchBuilder — programmable search customization** (Phases 1-2, ~3,500 LOC): Optional SearchBuilder protocol 
  enables models to define custom search variants (admin, public, api, mcp, etc.) with computed fields, custom 
  display logic, cross-model orchestration, and automatic MCP tool generation per variant. Native dict serialization 
  (no DRF dependency). Full type hints and comprehensive testing.
- **Native search serialization** — 4 pure-Python dict functions (`serialize_search_hit`, `serialize_search_results`, 
  `serialize_search_config`, `serialize_all_search_configs`) for JSON-safe output. Supports variant-specific extra fields 
  with transparent flattening.
- **Search introspection API** — `SearchAPI` class with 5 methods (get_config, list_variants, search, search_and_filter, 
  get_output_schema) for high-level orchestration; `SearchOrchestrator` for multi-stage workflows and cross-model search.
- **Search variant caching** — In-memory config cache with 1-hour TTL and cache invalidation on view registration.
- **Per-variant MCP tools** — Auto-generated MCP tools for each search variant (search_model, search_model_summary, 
  search_model_admin, etc.) for agent orchestration.

### Fixed
- **F1 (BLOCKER)** — Instance method call on class; fixed by instantiating view_cls before calling get_search_variants().
- **F2 (MAJOR)** — Removed djangorestframework dependency; replaced with 4 native dict serialization functions.
- **F4 (MAJOR)** — Guarded 3 unguarded date_joined references in search examples; added missing email field to admin variant.
- **F5 (MAJOR)** — Fixed 252 ruff lint errors (226 W293 whitespace, 16 F401 unused imports, 9 I001 unsorted, 1 E501 line length).
- **F6 (MAJOR)** — Replaced broken DRF serializer tests with real native serializer tests; removed false pytest.skip guards.
- **F7 (OBSERVATION)** — Documented extra field flattening behavior and collision risk in serialize_search_hit() docstring.

### Technical Details
- All new code is fully typed (Python 3.10+ syntax: dict[str, Any], QuerySet, return types)
- 119 integration tests covering all variants, orchestration, caching, and admin integration
- Comprehensive documentation: RUNBOOK.md, TUTORIAL.md, ORCHESTRATION-GUIDE.md, and 2 AI skills
- Backward compatible: all SearchBuilder methods optional; existing search works unchanged
- No breaking changes to SearchBackend protocol or query() signature


## [0.13.3] - 2026-07-16

### Fixed
- **Runbook dark-mode CSS** — enhanced styling now correctly scoped to app theme (`html[data-theme="dark"]`) 
  instead of OS setting (`@media prefers-color-scheme`), ensuring enhancements apply on default dark mode 
  regardless of OS theme setting.
- **Seeder idempotency** — `seed_platform_runbook` command now properly assigns section before guard check, 
  preventing `IntegrityError` crashes on re-run; added comprehensive idempotency test.

## [0.13.2] - 2026-07-12

### Added
- **`sc` — a framework CLI** (`manage.py sc` / the `sc` console script): a fifth thin skin over the
  CRUDView registry, the same operations as web/REST/MCP. Resource verbs — `ls` (registered models +
  rows, with `-q`/`--filter`/`--order`/`--limit`), `get`, `describe`, `search`, and writes `new`/`set`/
  `rm` through the model's `form_class` validation + `log_write` audit (staff-gated like the MCP tools).
  Operational verbs — `doctor`/`backup`/`token`/`status`/`index` (thin fronts over the framework's
  management commands) plus `sc commands` discovery. `--json` on every read. Explorer-synthesized views
  mean it reaches every admin-registered model, not just hand-written CRUDViews. See
  `docs/skills/sc-cli.md`.

### Fixed
- **Bundled JS client** (`clients/js` v0.3.1): SSR-safe `localStorage` access — the client guards
  `localStorage` so it's safe to import in a server-side-rendering context.

## [0.13.1] - 2026-07-12

### Added
- **Bundled API clients** under `clients/`: a TypeScript/JavaScript SDK (`clients/js`, with built
  `dist/`) and a single-file Python client (`clients/python/smallstack_client.py`) for talking to the
  REST API from external apps. See `clients/README.md`.

## [0.13.0] - 2026-07-12

### Added
- **Runbook — a first-class dynamic-documents app** (`apps/runbook/`): versioned markdown documents
  with images, sections, keyword + full-text search, retention, subscriptions, and portable ZIP
  bundles — readable and writable from the web UI, a transport-agnostic service layer, REST, MCP,
  and a unix-style CLI. (Previously the standalone `smallstack-runbook` package; now permanent core.
  The `smallstack_runbook` DB label is preserved, so existing tables/migrations reuse as-is.)
- **Runbook CLI** (`manage.py runbook` / the `rb` console script): `ls`, `toc`, `find` (BM25-ranked
  search), `cat` (`<ref>@N` reads an earlier version), `write` (stdin), `cp`, `rm`, `restore`, `mv`,
  `revert`, `log`, `stat`, `mkdir`, `sections`, `publish`/`unpublish`. Every verb takes `--json`.
- **Runbook REST API**: full document lifecycle (`api/documents/…`, incl. `append`/`move`/`archive`/
  `unarchive`/`revert`/`copy`) plus an `api/runbooks/…` container resource (list/create, detail +
  table of contents, sections, publish/unpublish). All registered in the OpenAPI schema (Swagger/
  ReDoc) and ownership-scoped. `GET api/documents/?q=` is BM25-ranked (substring fallback).
- **Runbook MCP tools** + search-engine registration (`search_runbook_documents`, global omnibar).
- **Runbook dashboard widget** on the central `/smallstack/` dashboard (runbook + document counts).
- `api_doctor` now lists hand-registered (`register_api_path`) custom endpoints, so its inventory
  matches the OpenAPI schema (and warns on any `url_name` that no longer reverses).

### Changed
- Client-IP resolution is now proxy-aware and shared by the activity log and the django-axes login
  lockout. Behind a trusted reverse proxy (`TRUST_PROXY_HEADERS`, defaulted on in production for
  kamal-proxy) the real client is read from the rightmost, proxy-appended `X-Forwarded-For` entry
  (spoof-resistant); otherwise the unspoofable `REMOTE_ADDR` is used. One helper
  (`apps/smallstack/client_ip.py`) is the single source of truth.
- The markdown hardening from the CRUD field-preview is extracted into a reusable
  `harden_markdown_renderer()` and shared with the runbook renderer.

### Fixed
- **Stored XSS in runbook document rendering** — user- and AI-authored document bodies could inject
  `<script>` / `<img onerror>` / `javascript:` links that executed in a viewer's session. The
  renderer now escapes raw HTML and blanks dangerous URL schemes, and drops the unsafe `md_in_html`
  and `attr_list` extensions. Regression-tested.
- Runbook ZIP export silently omitted section-less ("loose") documents attached straight to a
  runbook — they are now included (loose docs at the archive root).
- Runbook CLI N+1 queries in `ls`, `toc`, and `sections`.
- MCP activity page: the filter `Apply`/`Reset` buttons now align with the control row.
- Silenced the django-axes INFO startup banner in development (it polluted piped CLI output).

### Security
- django-axes now resolves the real client IP behind kamal-proxy, so per-IP brute-force lockout is
  effective in production (previously every request keyed to the proxy's address, neutering it).

## [0.12.4] - 2026-07-11

### Security
- **Dependencies:** bumped Django (→6.0.7), Pillow (→12.3.0), starlette, pydantic-settings, pygments,
  and pytest to their fix releases — `pip-audit` goes from 13 known vulnerabilities to 0.
- Fixed stored-XSS in the CRUD field-preview markdown renderer — arbitrary field content can no
  longer inject script. Raw HTML is neutralized (rendered as escaped text), dangerous link/image
  URL schemes (`javascript:`, `data:`, …) are blanked via a URL allowlist, and the extension set
  is restricted to `fenced_code`/`tables` (no `md_in_html` / `attr_list`). Regression-tested.
- Fixed stored-XSS in search-result snippets — the plain-text snippet is no longer rendered `|safe`.
- CSP: added `base-uri 'self'` and `object-src 'none'` directives (no inline-script trade-off).

### Added
- `register_api_path` — let custom `@api_view` endpoints join the OpenAPI schema.
- Maintenance-window tooling for heartbeat/status: `manage.py maintenance` command and
  `apps/heartbeat/maintenance.py` (open a maintenance window / SLA-exclude a deploy).
- Per-app `README.md` files, plus `SECURITY.md` and this `CHANGELOG.md`.

### Fixed
- Ordering by a computed/non-DB column no longer 500s — a misconfigured `ordering_fields` (or a
  hand-crafted `?ordering=`) degrades to no-sort instead of raising `FieldError`.
- Search: a model registered *after* the search app's `ready()` (from a later app in
  `INSTALLED_APPS`) now gets its per-model `search_<plural>` MCP tool — registration is now
  independent of app order.
- OpenAPI `info.version` and `MCP_SERVER_VERSION` derive from the package version (new
  `SMALLSTACK_VERSION` setting) instead of a hardcoded `1.0.0`.
- Dev `SECRET_KEY` is persisted to a gitignored `.secret_key` so all local processes share one key —
  `screenshot_auth` sessions are no longer silently rejected on a fresh clone.

### Changed
- API-layer dedup: `json.loads` bodies via `_load_json_body`; the three HTML-pagination sites via
  `attach_display_helpers`; `_api_list` and the OpenAPI path builders slimmed via extracted helpers.
- Heartbeat: six function-based views moved to a shared `staff_required` decorator.
- Type hints completed on `apps/activity`, `apps/tasks`, `apps/profile`, and `apps/smallstack/displays.py`;
  narrowed/logged several broad `except` handlers.
- Standardized test layout (`accounts`/`heartbeat` → `tests/` packages); `apps/tasks` coverage 0% → 99%.
- Docs: unified "Coming soon" framing for `@scheduled` + vector search; completed the CLI reference.

## [0.12.3] - 2026

### Fixed
- Invisible status calendar/timeline cells on standalone status pages.

## [0.12.2] - 2026

### Changed
- Maintenance-aware status: uptime/SLA calculations exclude scheduled maintenance windows.

### Fixed
- Test-suite robustness improvements.

## [0.12.1] - 2026

### Added
- `merge-0.12.0` upgrade skill documenting the v0.12.0 migration path.

## [0.12.0] - 2026

### Added
- **Pluggable status monitoring system** — register a Service + Monitor to track a
  subsystem's uptime/health on `/smallstack/status/`; add status visualizations.
  See `docs/skills/status-monitors.md`.

### Changed
- MCP and Search are decoupled from the status system (independent enable flags).
- Daily-timeline "today" coloring and doctor-command flag-awareness fixes.

### Removed
- **django-tables2** and the public `apps.smallstack.tables` / `table_class` surface.
  Downstream projects importing these must migrate — see `UPGRADING.md`.

## [0.11.x] - 2026

Condensed highlights of the v0.11 series (see git history for per-patch detail):

### Added
- Account invites by email + passwordless code login with branded emails (`apps/accounts`).
- Username-or-email login (`EmailOrUsernameBackend`).
- `usermanager`: password-on-create, edit actions, and guardrails.
- Consolidated dashboard stat cards into one `{% stat_card %}` standard with drill-down modals.
- API endpoints admin page; clickable list rows; table pagination.
- Editorial "Getting Started" redesign; apps-dropdown redesign; Search section on Home.

### Fixed
- **v0.11.14** — pinned test settings to `config.settings.test` (`--ds` in `addopts`) so the
  suite no longer silently ran under dev settings; hermetic dev-superuser test; v0.12 upgrade note.
- **v0.11.13** — platform re-audit hardening: security fixes (OAuth scope→role capping, token
  scope, backups, allowed hosts), Postgres fixes, **GitHub Actions CI** (SQLite + Postgres matrix
  + ruff), and the django-tables2 removal groundwork.
- Django-6 `log_action` breakage that broke programmatic API/MCP write audit logging.
- Explorer detail grid rendering every boolean as ✓ regardless of value.

## Earlier releases (0.8.x – 0.10.x)

See the git tag history (`git tag`) and `ai_cowork/audit_history/` for the full record of the
v0.8–v0.10 API-server, modern-dark-theme, search, MCP, and Postgres eras.

[Unreleased]: https://github.com/emichaud/django-smallstack/compare/v0.32.2...HEAD
[0.32.2]: https://github.com/emichaud/django-smallstack/compare/v0.32.1...v0.32.2
[0.32.1]: https://github.com/emichaud/django-smallstack/compare/v0.32.0...v0.32.1
[0.32.0]: https://github.com/emichaud/django-smallstack/compare/v0.31.0...v0.32.0
[0.31.0]: https://github.com/emichaud/django-smallstack/compare/v0.30.3...v0.31.0
[0.30.3]: https://github.com/emichaud/django-smallstack/compare/v0.30.2...v0.30.3
[0.30.2]: https://github.com/emichaud/django-smallstack/compare/v0.30.1...v0.30.2
[0.30.1]: https://github.com/emichaud/django-smallstack/compare/v0.30.0...v0.30.1
[0.30.0]: https://github.com/emichaud/django-smallstack/compare/v0.29.0...v0.30.0
[0.29.0]: https://github.com/emichaud/django-smallstack/compare/v0.28.0...v0.29.0
[0.28.0]: https://github.com/emichaud/django-smallstack/compare/v0.27.1...v0.28.0
[0.27.1]: https://github.com/emichaud/django-smallstack/compare/v0.27.0...v0.27.1
[0.27.0]: https://github.com/emichaud/django-smallstack/compare/v0.26.0...v0.27.0
[0.26.0]: https://github.com/emichaud/django-smallstack/compare/v0.25.2...v0.26.0
[0.25.2]: https://github.com/emichaud/django-smallstack/compare/v0.25.1...v0.25.2
[0.25.1]: https://github.com/emichaud/django-smallstack/compare/v0.25.0...v0.25.1
[0.25.0]: https://github.com/emichaud/django-smallstack/compare/v0.24.0...v0.25.0
[0.24.0]: https://github.com/emichaud/django-smallstack/compare/v0.23.1...v0.24.0
[0.23.1]: https://github.com/emichaud/django-smallstack/compare/v0.23.0...v0.23.1
[0.23.0]: https://github.com/emichaud/django-smallstack/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/emichaud/django-smallstack/compare/v0.21.11...v0.22.0
[0.21.11]: https://github.com/emichaud/django-smallstack/compare/v0.21.10...v0.21.11
[0.21.10]: https://github.com/emichaud/django-smallstack/compare/v0.21.9...v0.21.10
[0.21.9]: https://github.com/emichaud/django-smallstack/compare/v0.21.8...v0.21.9
[0.21.8]: https://github.com/emichaud/django-smallstack/compare/v0.21.7...v0.21.8
[0.21.7]: https://github.com/emichaud/django-smallstack/compare/v0.21.6...v0.21.7
[0.21.6]: https://github.com/emichaud/django-smallstack/compare/v0.21.5...v0.21.6
[0.21.5]: https://github.com/emichaud/django-smallstack/compare/v0.21.4...v0.21.5
[0.21.4]: https://github.com/emichaud/django-smallstack/compare/v0.21.3...v0.21.4
[0.21.3]: https://github.com/emichaud/django-smallstack/compare/v0.21.2...v0.21.3
[0.21.2]: https://github.com/emichaud/django-smallstack/compare/v0.21.1...v0.21.2
[0.21.1]: https://github.com/emichaud/django-smallstack/compare/v0.21.0...v0.21.1
[0.21.0]: https://github.com/emichaud/django-smallstack/compare/v0.20.1...v0.21.0
[0.20.1]: https://github.com/emichaud/django-smallstack/compare/v0.20.0...v0.20.1
[0.20.0]: https://github.com/emichaud/django-smallstack/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/emichaud/django-smallstack/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/emichaud/django-smallstack/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/emichaud/django-smallstack/compare/v0.16.2...v0.17.0
[0.16.2]: https://github.com/emichaud/django-smallstack/compare/v0.16.1...v0.16.2
[0.16.1]: https://github.com/emichaud/django-smallstack/compare/v0.16.0...v0.16.1
[0.16.0]: https://github.com/emichaud/django-smallstack/compare/v0.15.2...v0.16.0
[0.15.2]: https://github.com/emichaud/django-smallstack/compare/v0.15.1...v0.15.2
[0.15.1]: https://github.com/emichaud/django-smallstack/compare/v0.15.0...v0.15.1
[0.15.0]: https://github.com/emichaud/django-smallstack/compare/v0.14.3...v0.15.0
[0.14.3]: https://github.com/emichaud/django-smallstack/compare/v0.14.2...v0.14.3
[0.14.2]: https://github.com/emichaud/django-smallstack/compare/v0.14.1...v0.14.2
[0.14.1]: https://github.com/emichaud/django-smallstack/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/emichaud/django-smallstack/compare/v0.13.13...v0.14.0
[0.13.13]: https://github.com/emichaud/django-smallstack/compare/v0.13.12...v0.13.13
[0.13.12]: https://github.com/emichaud/django-smallstack/compare/v0.13.11...v0.13.12
[0.13.8]: https://github.com/emichaud/django-smallstack/compare/v0.13.7...v0.13.8
[0.13.7]: https://github.com/emichaud/django-smallstack/compare/v0.13.6...v0.13.7
[0.13.6]: https://github.com/emichaud/django-smallstack/compare/v0.13.5...v0.13.6
[0.13.5]: https://github.com/emichaud/django-smallstack/compare/v0.13.4...v0.13.5
[0.13.4]: https://github.com/emichaud/django-smallstack/compare/v0.13.3...v0.13.4
[0.13.3]: https://github.com/emichaud/django-smallstack/compare/v0.13.2...v0.13.3
[0.13.2]: https://github.com/emichaud/django-smallstack/compare/v0.13.1...v0.13.2
[0.13.1]: https://github.com/emichaud/django-smallstack/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/emichaud/django-smallstack/compare/v0.12.4...v0.13.0
[0.12.4]: https://github.com/emichaud/django-smallstack/compare/v0.12.3...v0.12.4
[0.12.3]: https://github.com/emichaud/django-smallstack/compare/v0.12.2...v0.12.3
[0.12.2]: https://github.com/emichaud/django-smallstack/compare/v0.12.1...v0.12.2
[0.12.1]: https://github.com/emichaud/django-smallstack/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/emichaud/django-smallstack/compare/v0.11.19...v0.12.0
