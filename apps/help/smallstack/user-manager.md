---
title: User Manager
description: Built-in user management with search, profiles, activity stats, and timezone dashboard
---

# User Manager

{{ project_name }} includes a staff-only user management interface at `/manage/users/`. It's designed to be "just enough" — a clean, usable interface for managing user accounts without locking you into a rigid admin pattern. Downstream projects get a solid foundation to build on however they need.

## What You Get

- **User list** at `/manage/users/` — searchable, sortable table with stat card drilldowns
- **User edit** at `/manage/users/<pk>/edit/` — tabbed form with Account, Profile, and Activity sections
- **Timezone dashboard** at `/manage/users/timezones/` — live clocks, local times, and working status for distributed teams
- **Stat card drilldowns** — click any stat card to see the detail breakdown in a modal
- **HTMX search** — progressive filtering without page reload

## User List

![User Manager list page](/static/smallstack/docs/images/usermanager-list.png)

The list page follows the standard management page pattern:

**Title bar** — "Users" heading with inline breadcrumbs (Home / Users) on the left, stat cards on the right showing Total users, Staff count, New signups (30 days), and Timezones configured.

**Stat card drilldowns** — click any stat card to open a modal with the detail breakdown. The "Total" card lists all active users with emails. The "Staff" card shows only staff accounts. The "Timezones" card shows configured timezones with user counts.

**Search** — type in the search bar to filter users by username, email, first name, or last name. Results update instantly via HTMX without a page reload.

**Sortable table** — django-tables2 table with columns for Username, Email, Name, Timezone, Staff status, and Active status. Click column headers to sort. The username links to the edit page.

**Self-protection** — the delete button is hidden for your own row. You can't accidentally delete your own account.

## User Edit

![User edit form](/static/smallstack/docs/images/usermanager-edit.png)

The edit page uses a tabbed layout with three sections:

### Account Tab

Standard Django user fields: username, email, first name, last name, staff status, and active status. These come from the built-in User model.

### Profile Tab

Extended fields from the UserProfile model: profile photo, timezone, and any additional fields your project adds. The profile is auto-created via signals when a user is created — no manual setup needed.

The timezone field is a searchable dropdown with all IANA timezones. When set, dates and times throughout the interface display in that user's local timezone with a tooltip showing the server time and UTC.

### Activity Tab

A snapshot of the user's activity pulled from the request log:

- **Total requests** — all-time request count
- **Last 30 days** — recent activity volume
- **Avg response** — average response time in ms
- **Last seen** — when they last made a request
- **Top paths** — their most-visited pages (last 30 days)
- **Status breakdown** — HTTP status code distribution
- **Daily sparkline** — visual activity trend for the last 7 days

This gives you a quick read on whether a user is active and how they're using the site — without switching to the Activity dashboard.

## Timezone Dashboard

![Timezone dashboard](/static/smallstack/docs/images/usermanager-timezones.png)

The timezone dashboard at `/manage/users/timezones/` is an opinionated addition. Distributed teams are so common now that timezone awareness should be a first-class feature, not an afterthought.

### Why Timezones Matter

When users set their timezone in their profile, {{ project_name }} uses it everywhere:

- **Date display** — all dates render in the user's local timezone via the `localtime_tooltip` template tag
- **Hover tooltips** — when your timezone differs from the server's, dates show a dotted underline with server time and UTC on hover
- **Dashboard context** — the timezone dashboard shows who's working, who's off, and what time it is for each team member

By building timezone handling into the base, downstream projects inherit correct date display automatically. The timezone dashboard serves as the reference implementation — it demonstrates how to use the timezone data in your own views.

### What It Shows

**Live clocks** — analog clocks showing current time in each unique timezone across your team, with city name and UTC offset.

**Sortable table** — each user with a configured timezone, showing:

| Column | Description |
|--------|-------------|
| User | Avatar, name, staff badge, link to edit page |
| Timezone | IANA timezone (e.g., America/New_York) |
| Local Time | Current time in 12-hour format with timezone abbreviation |
| UTC Offset | Hours ahead/behind UTC |
| Status | Working (green), Off Hours, or Night — based on local business hours |
| Region | Geographic region extracted from the timezone |

**Search** — filter by username, timezone, or region.

### The "Working" Indicator

The status column uses a simple heuristic: if it's a weekday and between 8 AM and 6 PM in the user's timezone, they're marked as "Working" with a green dot. Night hours (10 PM – 6 AM) show a yellow dot. Everything else shows a gray "Off Hours" indicator.

This isn't meant to be a presence system — it's a quick visual reference for "is it a reasonable time to message this person?"

## Architecture

### Files

| File | Purpose |
|------|---------|
| `apps/usermanager/views.py` | CRUDView config, dashboard stats, stat detail endpoint |
| `apps/usermanager/tables.py` | UserTable, TimezoneTable with custom columns |
| `apps/usermanager/forms.py` | UserAccountForm, UserProfileForm |
| `apps/usermanager/timezone_views.py` | Timezone dashboard view |
| `apps/usermanager/urls.py` | URL configuration |
| `templates/usermanager/user_list.html` | List page with title bar, search, stat cards |
| `templates/usermanager/_user_table.html` | Table partial for HTMX search |
| `templates/accounts/user_form.html` | Tabbed edit form |
| `templates/usermanager/timezone_dashboard.html` | Timezone dashboard |

### How CRUDView Works

The User Manager uses `CRUDView` — a declarative class that generates list, create, update, and delete views from a single configuration:

```python
class UserCRUDView(CRUDView):
    model = User
    url_base = "manage/users"
    paginate_by = 10
    mixins = [StaffRequiredMixin]
    table_class = UserTable
    form_class = UserAccountForm
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
```

This generates four URL patterns, four views, and wires up the table, form, pagination, and access control. The `_make_view` method is overridden to inject search filtering, profile form handling, and self-delete protection.

See the [Extending with AI](/help/smallstack/extending-with-ai/) page for the full CRUDView pattern documentation.

## Access Control

All user manager views require staff status:

- **List, Create, Update, Delete** — `StaffRequiredMixin` via CRUDView
- **Stat detail endpoint** — `@staff_member_required` decorator
- **Timezone dashboard** — `StaffRequiredMixin`

The sidebar shows the Users link only inside the `{% if user.is_staff %}` block.

## Extending Downstream

The User Manager is intentionally minimal. Here's what downstream projects typically add:

- **Role-based access** — add roles or permission groups to the user model
- **Custom profile fields** — extend `UserProfile` with project-specific fields (department, phone, preferences)
- **Invitation flow** — add an invite-by-email workflow on top of the create view
- **Bulk operations** — add select-all + bulk actions to the table
- **User activity detail** — link from the Activity tab to filtered request logs

The User Manager provides the scaffolding. The `UserTable` class can be subclassed to add columns. The `UserAccountForm` can be extended with additional fields. The CRUDView's `_make_view` override pattern lets you inject custom logic at any point in the view lifecycle.

## What's Not Included

Keeping with the {{ project_name }} philosophy of "just enough":

- **Password management** — handled by Django's built-in auth views (password reset, change)
- **User registration** — controlled by the `SIGNUP_ENABLED` feature flag, separate from user manager
- **Permissions UI** — use Django admin for granular permission management
- **Org/team structure** — left for downstream projects to implement per their needs
- **Profile page (public)** — the edit form is staff-only; public profiles are project-specific

These are deliberate omissions, not gaps. Each downstream project has different needs — a ticketing system needs roles, a SaaS needs teams, a blog needs author profiles. The User Manager gives you the foundation without making those choices for you.
