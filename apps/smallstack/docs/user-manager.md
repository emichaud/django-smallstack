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

**Title bar** — "User Manager" heading with subtitle and inline breadcrumbs (Home / Users) on the left. On the right, a "Timezones" button links to the timezone dashboard and an "+ Add User" button opens the create form.

**Stat cards** — four clickable cards below the title bar showing Recent (30d), Total Users, Staff, and Timezones. Click any card to open a modal with the detail breakdown. The "Total" card lists all active users with emails. The "Staff" card shows only staff accounts. The "Recent" card shows users who joined in the last 30 days. The "Timezones" card shows configured timezones with user counts.

**Search** — type in the search bar to filter users by username, email, first name, or last name. Results update instantly via HTMX without a page reload.

**Sortable table** — themed table with columns for Username, Email, Name, Timezone, Staff status, and Active status. Click column headers to sort. The username links to the edit page.

**Self-protection** — the delete button is hidden for your own row. You can't accidentally delete your own account.

## User Edit

![User edit form](/static/smallstack/docs/images/usermanager-edit.png)

The edit page uses a title bar showing the username, breadcrumbs (Home / Users / username), and summary cards for Status (green "Active" or red "Inactive"), Member Since (month and year), and Role ("Staff" badge, shown only for staff users). Below the title bar is a tabbed layout with three sections:

### Account Tab

Standard Django user fields: username, email, first name, last name, staff status, and active status. These come from the built-in User model.

### Profile Tab

Extended fields from the UserProfile model. The profile is auto-created via signals when a user is created — no manual setup needed.

The tab opens with a two-column photo upload area — profile photo (circular crop) and background photo (wide crop) — with drag-and-drop preview. Below that:

- **Display name** — shown publicly, falls back to username
- **Bio** — free-text description
- **Location** and **Website** — side by side
- **Date of birth** and **Timezone** — side by side

The timezone field is a searchable dropdown with all IANA timezones. When set, dates and times throughout the interface display in that user's local timezone with a tooltip showing the server time and UTC.

### Activity Tab

A snapshot of the user's activity pulled from the request log:

- **Total requests** — all-time request count
- **Last 30 days** — recent activity volume
- **Avg response** — average response time in ms
- **Last 7 days** — recent weekly activity
- **Daily sparkline** — visual bar chart of request volume for the last 7 days
- **Top pages** — their most-visited paths (last 30 days)
- **Status codes** — HTTP status code distribution with color-coded badges (2xx green, 3xx blue, 4xx yellow, 5xx red)
- **Last seen** — relative timestamp of their most recent request

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

**Title bar** — "Timezones" heading with breadcrumbs (Home / Users / Timezones) and summary cards showing total users, unique timezones, and regions.

**Live clocks** — three digital clocks updating every second: UTC, Server Time (with timezone label), and Your Local Time (detected from the browser). Each shows 24-hour time, 12-hour time with AM/PM, and the full date.

**Filter buttons** — quick-filter the table by status or region: All, Working Hours, Off Hours, Staff Only, and one button per geographic region (Americas, Europe, Asia & Pacific, etc.). Filters work client-side for instant results.

**Sortable table** — each user with their timezone data, showing:

| Column | Description |
|--------|-------------|
| User | Avatar (photo or initial), name, staff badge, link to edit page |
| Timezone | Friendly display name from IANA timezone |
| Local Time | Live-updating current time in 12-hour format with timezone abbreviation |
| UTC Offset | Hours ahead/behind UTC (e.g., UTC+5:30) |
| Status | Working (green dot), Off Hours (gray dot), or Night (yellow dot) |
| Region | Geographic region: Americas, Europe, Asia & Pacific, Africa & Middle East |

**Search** — filter by username, email, timezone, display name, or region. Results update via HTMX without page reload.

### The "Working" Indicator

The status column uses a simple heuristic: if it's a weekday and between 8 AM and 6 PM in the user's timezone, they're marked as "Working" with a green dot. Night hours (10 PM – 6 AM) show a yellow dot. Everything else shows a gray "Off Hours" indicator.

This isn't meant to be a presence system — it's a quick visual reference for "is it a reasonable time to message this person?"

### Configuring Work Hours

The working indicator reads from three Django settings, all optional:

| Setting | Default | Description |
|---------|---------|-------------|
| `WORK_HOURS_START` | `8` | Hour (0-23) when work begins |
| `WORK_HOURS_END` | `18` | Hour (0-23) when work ends |
| `WORK_DAYS` | `(0, 1, 2, 3, 4)` | Weekday integers (0=Monday through 6=Sunday) |

For example, to set a 9-to-5 schedule that includes Saturday:

```python
# config/settings/base.py
WORK_HOURS_START = 9
WORK_HOURS_END = 17
WORK_DAYS = (0, 1, 2, 3, 4, 5)  # Mon–Sat
```

## Architecture

### Files

| File | Purpose |
|------|---------|
| `apps/usermanager/views.py` | CRUDView config, dashboard stats, stat detail endpoint |
| `apps/usermanager/tables.py` | UserTable, TimezoneTable (legacy django-tables2, being migrated to TableDisplay) |
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
    form_class = UserAccountForm
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
```

This generates four URL patterns, four views, and wires up the form, pagination, and access control. The built-in `TableDisplay` handles sortable column headers, pagination, and themed styling automatically. The `_make_view` method is overridden to inject search filtering, profile form handling, and self-delete protection.

See the [Building CRUD Pages](/help/smallstack/building-crud-pages/) guide for the full CRUDView pattern documentation.

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
