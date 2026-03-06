# Skill: Docker Deployment

This skill describes how to build and run SmallStack with Docker and Docker Compose.

## Overview

SmallStack includes a `Dockerfile` and `docker-compose.yml` for containerized deployment. The setup runs two services: a web server (Gunicorn) and a background worker (db_worker). SQLite is the default database, stored in a named volume for persistence.

## File Locations

```
Dockerfile              # Multi-stage build with UV
docker-compose.yml      # Web + worker services
docker-entrypoint.sh    # Startup script (migrate, collectstatic, superuser)
gunicorn.conf           # Gunicorn configuration
.env                    # Environment variables (not committed)
```

## Quick Start

```bash
# Build and start all services
make docker-up

# Stop all services
make docker-down
```

Or directly:

```bash
docker compose up --build -d
docker compose down
```

## Services

### web

The main Django application served by Gunicorn on port 80 inside the container, mapped to port 8010 on the host.

```yaml
web:
  build: .
  ports:
    - "8010:80"
  environment:
    - DJANGO_SETTINGS_MODULE=config.settings.production
    - SECRET_KEY=${SECRET_KEY:-change-me-in-production}
    - ALLOWED_HOSTS=localhost,127.0.0.1
    - DATABASE_PATH=/data/db.sqlite3
    - MEDIA_ROOT=/app/media
  volumes:
    - db_data:/data
    - media_data:/app/media
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost/health/"]
    interval: 30s
```

### worker

Background task processor using `django-tasks-db`:

```yaml
worker:
  build: .
  command: python manage.py db_worker --queue-name "*"
  volumes:
    - db_data:/data       # Shares SQLite with web service
  depends_on:
    web:
      condition: service_healthy
```

The worker shares the same `db_data` volume as the web service so both can access the SQLite database.

## Dockerfile

The Dockerfile uses Python 3.12 slim with UV for dependency management:

1. Installs system dependencies (curl for health checks)
2. Installs UV and Python dependencies from `pyproject.toml`/`uv.lock`
3. Copies application code
4. Runs `docker-entrypoint.sh` which handles migrations, collectstatic, and optional superuser creation
5. Starts Gunicorn on port 80

## Environment Variables

Set in `.env` file (create from `.env.example` if available):

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (required) | Django secret key |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed hosts |
| `DATABASE_PATH` | `/data/db.sqlite3` | SQLite database path |
| `MEDIA_ROOT` | `/app/media` | Media file storage path |
| `DJANGO_SUPERUSER_USERNAME` | (optional) | Auto-create superuser on startup |
| `DJANGO_SUPERUSER_PASSWORD` | (optional) | Superuser password |
| `DJANGO_SUPERUSER_EMAIL` | (optional) | Superuser email |

## Volumes

| Volume | Mount | Purpose |
|--------|-------|---------|
| `db_data` | `/data` | SQLite database persistence |
| `media_data` | `/app/media` | User-uploaded media files |

## PostgreSQL (Optional)

The `docker-compose.yml` includes a commented-out PostgreSQL service. To switch:

1. Uncomment the `db` service block
2. Add `DATABASE_URL` to web and worker environment
3. Add `depends_on` for `db` to the web service
4. Comment out `DATABASE_PATH` lines
5. Uncomment `postgres_data` in volumes

```yaml
# Add to web/worker environment:
- DATABASE_URL=postgres://postgres:${POSTGRES_PASSWORD:-postgres}@db:5432/smallstack
```

## Health Check

The web service includes a health check at `/health/` that Docker uses to verify the container is ready before starting the worker.

## Best Practices

1. **Never commit `.env`** — Use `.env.example` as a template
2. **Set a real SECRET_KEY** — The default is insecure
3. **Use named volumes** — Ensures data persists across container restarts
4. **Worker depends on web** — The `service_healthy` condition ensures migrations run first
5. **Port mapping** — Default is `8010:80`; change the host port as needed
