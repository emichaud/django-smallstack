---
title: About & Inspiration
description: The philosophy behind Django SmallStack and what's included
---

# About Django SmallStack

{{ project_name }} is a minimal Django stack for building and deploying admin-style apps. Everything below is included out of the box — production-ready with sensible defaults.

---

## The Philosophy

1. **Use what Django gives you** — before adding a package, check if Django already has it
2. **Keep it simple** — add complexity only when needed
3. **Stay close to Django** — follow conventions so the ecosystem works for you
4. **Production-ready defaults** — secure settings, proper static files, Docker support

## Who Is This For?

- Developers who want a clean starting point without reinventing the wheel
- Teams tired of setting up auth, profiles, and theming from scratch
- Projects that need a professional look without a heavy frontend framework

## Beyond Business Logic

Building your app's core features is the exciting part. But once the logic is working, there's a wall of operational concerns — deployment, security headers, database backups, user onboarding, monitoring — that can stall a project for weeks. SmallStack helps you bust through that wall.

SmallStack provides a strong foundation for your app to thrive, whether it's an internal tool for your team or the next big thing on the internet:

- **Auth and signup** are ready to go — start onboarding users immediately
- **User management** gives staff a clean interface for accounts, profiles, and timezones
- **CRUDView** lets you spin up model management pages in minutes, not hours
- **Activity tracking** gives you lightweight analytics from day one
- **Uptime monitoring** proves your site is alive with a public status page
- **Database backups** protect your precious data with scheduled and on-demand backups
- **Deployment tooling** gets you from localhost to production with a single command

You focus on what makes your app unique. SmallStack handles the rest.

---

## What's Included

### Profile App

A complete user profile system with auto-creation on signup.

![Profile edit page](/static/smallstack/docs/images/about-profile.png)

- **Photo & cover image** uploads with Pillow
- **Bio, location, website** and display name fields
- **Color palette** preference per user — persisted and applied on login
- Extend with your own fields — it's a standard Django model

> [Full documentation →](/help/smallstack/getting-started/)

---

### Activity Tracking

Zero-config request logging with a staff-only dashboard.

![Activity dashboard](/static/smallstack/docs/images/about-activity.png)

> **See it in action:** [Activity Tracking slide deck](/help/slides/activity-tracking/) — a quick walkthrough built with the slide viewer.

- **Middleware-based** — captures every request automatically
- **Staff dashboard** at `/activity/` with stat cards and filterable log table
- **Live refresh** via htmx polling (no WebSockets)
- **Auto-pruning** — configurable retention with background task cleanup

> [Full documentation →](/help/smallstack/activity-tracking/)

---

### Database Backups

Built-in SQLite backup system with a staff dashboard.

![Backup dashboard](/static/smallstack/docs/images/about-backups.png)

- **On-demand backups** — one click from the admin dashboard
- **Scheduled backups** — automatic via background tasks and cron
- **Backup history** with status, file size, and duration tracking
- **File browser** — view, download, or delete backup files from the UI
- **Email alerts** — get notified when backups fail (configure ADMINS + SMTP)
- **Configurable retention** — auto-prune old backups to save disk space

> [Full documentation →](/help/smallstack/database-backups/)

---

### Uptime Monitoring

A built-in heartbeat system with a public status page — no external services needed.

![Public status page](/static/smallstack/docs/images/about-status.png)

- **Automatic heartbeat** — cron checks database connectivity every minute
- **Public status page** at `/status/` with uptime %, visual timelines, response times
- **Staff dashboard** with heartbeat log, timeline views, and JSON output
- **SLA tracking** — configurable goal and commitment thresholds with color-coded compliance
- **JSON API** at `/status/json/` — point external monitors here for alerting
- **Daily summaries** preserve long-term uptime data after individual records are pruned

For small and internal sites, this is all the monitoring you need. As you grow, use the JSON endpoint with external tools like UptimeRobot or Healthchecks.io for outside-in verification and alerting.

> [Full documentation →](/help/smallstack/uptime-monitoring/)

---

### Theming

Light and dark modes with selectable color palettes, all built on CSS custom properties.

![Dark mode](/static/smallstack/docs/images/about-theming-dark.png)

![Light mode](/static/smallstack/docs/images/about-theming-light.png)

- **Dark mode** toggle with `data-theme` attribute — user preference saved
- **5 built-in palettes** (Django, Contrast, Blue, Orange, Purple)
- **CSS variables** for colors, spacing, shadows — change the look from one file
- Inherits Django admin's responsive foundation

> [Full documentation →](/help/smallstack/theming/)

---

### Authentication

Built on Django's battle-tested `contrib.auth` — no third-party auth packages.

- **Custom User model** ready for email login
- **Signup control** — enable/disable registration with a setting
- **Password reset** flows using Django's built-in views and email
- **Feature flags** — toggle app sections on and off

> [Full documentation →](/help/smallstack/authentication/)

---

### User Manager

Staff-only interface for managing user accounts, profiles, and timezones.

![User Manager](/static/smallstack/docs/images/about-usermanager.png)

- **Searchable user list** with sortable django-tables2 table and stat card drilldowns
- **Tabbed edit form** — Account, Profile, and Activity tabs on a single page
- **Timezone dashboard** at `/manage/users/timezones/` — live clocks, working status, and local times for distributed teams
- **Self-protection** — you can't accidentally delete your own account
- **Built to extend** — a "just enough" foundation that downstream projects can customize without fighting the framework

> [Full documentation →](/help/smallstack/user-manager/)

---

### CRUDView & django-tables2

A declarative pattern for building model management pages — define one class, get a complete interface.

- **CRUDView** generates list, create, update, and delete views from a single config class
- **django-tables2** integration for sortable, paginated tables with themed styling
- **Reusable columns** — `DetailLinkColumn`, `BooleanColumn`, `ActionsColumn` handle common patterns
- **Generic templates** work out of the box — customize only when you need the full title bar pattern
- **HTMX search** with a reusable search bar partial and progressive filtering
- **Stat card drilldowns** — clickable dashboard cards that open detail modals
- Inspired by [Neapolitan](https://github.com/carltongibson/neapolitan) by [Carlton Gibson](https://github.com/carltongibson)

> [Full documentation →](/help/smallstack/building-crud-pages/)

---

### Help System

The documentation viewer you're reading right now — file-based, markdown-powered.

![Help system](/static/smallstack/docs/images/about-help.png)

- **YAML-driven** navigation with sections, icons, and ordering
- **Template variables** for version numbers, project names, etc.
- **Full-text search** with client-side indexing
- **FAQ mode** with collapsible sections
- **Slide viewer** for focused presentations ([see below](#slide-viewer))

> [Full documentation →](/help/smallstack/help-system/)

---

### Background Tasks

Django 6's Tasks framework, pre-configured with a database backend.

- **No Redis or Celery** — uses `django-tasks-db` with SQLite/PostgreSQL
- **Background worker** via `manage.py db_worker`
- Handles email sending, data processing, scheduled cleanup
- **Kamal deployment** runs the worker as a separate service

> [Full documentation →](/help/smallstack/background-tasks/)

---

### Docker & Deployment

Production-ready container setup with zero-downtime deployment.

- **Multi-stage Dockerfile** — small, secure images
- **Docker Compose** with web, worker, and health checks
- **Kamal deployment** — push to any VPS with `kamal deploy`
- **SQLite in production** — works great for small-to-medium apps

> [Full documentation →](/help/smallstack/docker-deployment/)

---

## Slide Viewer

SmallStack includes a **slide presentation mode** for the help system. Create focused, one-slide-at-a-time walkthroughs using the same YAML + markdown approach.

![Slide viewer](/static/smallstack/docs/images/about-slides.png)

[Try the Activity Tracking slide deck →](/help/slides/activity-tracking/)

> **Learn how to create your own:** [Using the Help System → Slide Viewer](/help/smallstack/help-system/#slide-viewer)
