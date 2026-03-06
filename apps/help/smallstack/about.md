---
title: About & Inspiration
description: The philosophy behind Django SmallStack and what's included
---

# About Django SmallStack

{{ project_name }} is a minimal Django stack for building and deploying admin-style apps. Everything below is included out of the box — production-ready with sensible defaults.

> **See it in action:** [Activity Tracking slide deck](/help/slides/activity-tracking/) — a quick walkthrough built with the slide viewer.

---

## Profile App

A complete user profile system with auto-creation on signup.

- **Photo & cover image** uploads with Pillow
- **Bio, location, website** and display name fields
- **Color palette** preference per user — persisted and applied on login
- Extend with your own fields — it's a standard Django model

> [Full documentation →](/help/smallstack/getting-started/)

---

## Activity Tracking

Zero-config request logging with a staff-only dashboard.

- **Middleware-based** — captures every request automatically
- **Staff dashboard** at `/activity/` with stat cards and filterable log table
- **Live refresh** via htmx polling (no WebSockets)
- **Auto-pruning** — configurable retention with background task cleanup

> [Full documentation →](/help/smallstack/activity-tracking/)

---

## Theming

Light and dark modes with selectable color palettes, all built on CSS custom properties.

- **Dark mode** toggle with `data-theme` attribute — user preference saved
- **5 built-in palettes** (Django, Nord, Dracula, Solarized, High Contrast)
- **CSS variables** for colors, spacing, shadows — change the look from one file
- Inherits Django admin's responsive foundation

> [Full documentation →](/help/smallstack/theming/)

---

## Authentication

Built on Django's battle-tested `contrib.auth` — no third-party auth packages.

- **Custom User model** ready for email login
- **Signup control** — enable/disable registration with a setting
- **Password reset** flows using Django's built-in views and email
- **Feature flags** — toggle app sections on and off

> [Full documentation →](/help/smallstack/authentication/)

---

## Help System

The documentation viewer you're reading right now — file-based, markdown-powered.

- **YAML-driven** navigation with sections, icons, and ordering
- **Template variables** for version numbers, project names, etc.
- **Full-text search** with client-side indexing
- **FAQ mode** with collapsible sections
- **Slide viewer** for focused presentations ([see below](#slide-viewer))

> [Full documentation →](/help/smallstack/help-system/)

---

## Background Tasks

Django 6's Tasks framework, pre-configured with a database backend.

- **No Redis or Celery** — uses `django-tasks-db` with SQLite/PostgreSQL
- **Background worker** via `manage.py db_worker`
- Handles email sending, data processing, scheduled cleanup
- **Kamal deployment** runs the worker as a separate service

> [Full documentation →](/help/smallstack/background-tasks/)

---

## Docker & Deployment

Production-ready container setup with zero-downtime deployment.

- **Multi-stage Dockerfile** — small, secure images
- **Docker Compose** with web, worker, and health checks
- **Kamal deployment** — push to any VPS with `kamal deploy`
- **SQLite in production** — works great for small-to-medium apps

> [Full documentation →](/help/smallstack/docker-deployment/)

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

## Slide Viewer

SmallStack includes a **slide presentation mode** for the help system. Create focused, one-slide-at-a-time walkthroughs using the same YAML + markdown approach.

[Try the Activity Tracking slide deck →](/help/slides/activity-tracking/)

> **Learn how to create your own:** [Using the Help System → Slide Viewer](/help/smallstack/help-system/#slide-viewer)
