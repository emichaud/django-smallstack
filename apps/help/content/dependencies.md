---
title: Dependencies
description: Why we chose each package in SmallStack
---

# Dependencies

SmallStack is intentionally minimal. Every dependency earns its place by solving a real problem without adding unnecessary complexity. Here's why each package is included.

## Core Framework

### Django 6.0+

We build on Django 6.0 because it includes the new **django-tasks** framework—a lightweight background task runner built into Django itself. For small to medium applications, this eliminates the need for Celery, Redis, and the operational complexity they bring.

```python
"django>=6.0"
```

**When to consider alternatives:** If your application requires complex task routing, scheduled jobs at scale, or distributed task processing across multiple workers, consider [Celery](https://docs.celeryq.dev/) or [Dramatiq](https://dramatiq.io/).

### django-tasks-db

The database backend for Django's task framework. Tasks are stored in your existing database (SQLite or PostgreSQL), so there's no additional infrastructure to manage.

```python
"django-tasks-db>=0.2"
```

This is perfect for:
- Sending emails in the background
- Processing uploads
- Running periodic cleanup jobs
- Any task that doesn't need sub-second execution

## Configuration

### python-decouple

Separates secrets and environment-specific settings from your code. Configuration comes from environment variables or `.env` files, never hardcoded.

```python
"python-decouple>=3.8"
```

**Why not django-environ?** Both are excellent. We chose decouple for its simplicity and minimal API. It does one thing well: read configuration from the environment.

## Web Server & Static Files

### Gunicorn

A production-grade WSGI server that's simple to configure and performs well out of the box.

```python
"gunicorn>=21.0"
```

SmallStack uses Gunicorn with gevent workers for handling concurrent connections efficiently. The configuration lives in `gunicorn.conf` and works well for most deployments.

### Whitenoise

Serves static files directly from your application, eliminating the need for a separate static file server or CDN for small applications.

```python
"whitenoise>=6.6"
```

**The controversy:** Some argue that Python shouldn't serve static files—that's what Nginx or a CDN is for. They're not wrong for high-traffic sites. But for small applications, the convenience of Whitenoise far outweighs the minor performance difference.

**What Whitenoise gives you:**
- Zero additional infrastructure
- Automatic compression (gzip/brotli)
- Cache headers and fingerprinting
- Works identically in development and production

**When to add a reverse proxy:** As your site grows, consider adding Nginx, Caddy, or Traefik in front of your application. Signs you might need this:
- Serving large media files (videos, large images)
- High traffic requiring aggressive caching
- Need for advanced load balancing
- SSL termination at the edge

For most small to medium applications, Whitenoise handles static files just fine.

## Development Tools

### django-extensions

A collection of useful management commands and utilities that make development faster.

```python
"django-extensions>=3.2"
```

**Highlights:**
- `shell_plus` - Enhanced Django shell with auto-imports
- `show_urls` - List all URL patterns
- `graph_models` - Generate model diagrams
- `runserver_plus` - Enhanced development server

These are **opinionated inclusions**—we believe they're valuable enough that every Django project benefits from having them available.

### django-debug-toolbar

An in-browser debugging panel that shows SQL queries, template rendering, cache usage, and more.

```python
"django-debug-toolbar>=4.2"
```

**Important:** The debug toolbar is automatically hidden in production. It only appears when `DEBUG=True`, so there's no security risk in having it installed.

The toolbar helps you:
- Identify slow or duplicate database queries
- Debug template context and inheritance
- Profile request/response cycles
- Inspect headers and settings

## Content & Media

### Pillow

The standard Python imaging library, required for Django's `ImageField` and user profile photos.

```python
"pillow>=10.0"
```

Used by the profile app for handling avatar and cover photo uploads.

### Markdown

Renders the help system documentation from Markdown files to HTML.

```python
"markdown>=3.5"
```

We use the `fenced_code` and `tables` extensions for code blocks and tables in documentation.

### PyYAML

Parses the help system configuration file (`_config.yaml`) that defines navigation order, page metadata, and template variables.

```python
"pyyaml>=6.0"
```

## Summary

| Package | Purpose | When to Replace |
|---------|---------|-----------------|
| Django 6.0+ | Web framework with built-in tasks | Never |
| django-tasks-db | Task storage in database | Celery for complex workflows |
| python-decouple | Environment configuration | Personal preference |
| Gunicorn | WSGI server | uWSGI if you prefer |
| Whitenoise | Static file serving | Nginx/Caddy at scale |
| django-extensions | Dev utilities | Never (dev only) |
| django-debug-toolbar | Debugging | Never (dev only) |
| Pillow | Image processing | Never (if using images) |
| Markdown | Help system rendering | Never (if using help) |
| PyYAML | Config parsing | Never (if using help) |

## Adding Dependencies

When adding new packages, ask yourself:

1. **Does Django already do this?** Check the built-in features first.
2. **Is this worth the maintenance burden?** Every dependency is code you don't control.
3. **Is it actively maintained?** Check the GitHub activity and release history.
4. **Does it have good Django integration?** Native Django support is better than generic Python packages.

Use UV to add dependencies:

```bash
uv add package-name
```

This updates both `pyproject.toml` and `uv.lock` for reproducible builds.
