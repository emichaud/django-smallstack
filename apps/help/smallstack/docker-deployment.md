---
title: Docker Deployment
description: Local development and generic container hosting
---

# Docker Deployment

This guide walks you through deploying {{ project_name }} using Docker Compose. This approach works for local development and is compatible with virtually any container hosting service.

> **See also:** [Deployment Overview](/help/smallstack/deployment/) for a comparison of deployment options, or [Kamal Deployment](/help/smallstack/kamal-deployment/) for zero-downtime VPS deployments.

## Prerequisites

1. **Docker Desktop** installed and running
   - [Mac](https://docs.docker.com/desktop/install/mac-install/) | [Windows](https://docs.docker.com/desktop/install/windows-install/) | [Linux](https://docs.docker.com/desktop/install/linux-install/)

2. Verify installation:
   ```bash
   docker --version
   docker-compose --version
   ```

## Quick Start

### Step 1: Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Required
DJANGO_SETTINGS_MODULE=config.settings.production
ALLOWED_HOSTS=localhost,127.0.0.1

# Optional: Auto-create admin user
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=your-secure-password
DJANGO_SUPERUSER_EMAIL=admin@example.com
```

> **SECRET_KEY** is auto-generated and persisted to `/app/data/.secret_key` on first deploy. You don't need to set it manually unless you want a specific key.

### Step 2: Build the Image

```bash
docker-compose build
```

This takes a few minutes the first time.

### Step 3: Start the Application

```bash
docker-compose up -d
```

### Step 4: Open in Browser

- **Homepage:** http://localhost:8010
- **Admin:** http://localhost:8010/admin

## Common Commands

### Starting and Stopping

```bash
# Start (background)
docker-compose up -d

# Stop
docker-compose down

# Stop and remove all data
docker-compose down -v
```

### Viewing Logs

```bash
# All logs
docker-compose logs

# Follow logs in real-time
docker-compose logs -f

# Last 50 lines
docker-compose logs --tail=50
```

### Checking Status

```bash
# See running containers
docker-compose ps

# Health check
curl http://localhost:8010/health/
```

### Running Django Commands

```bash
# Open a shell
docker-compose exec web bash

# Run management commands
docker-compose exec web python manage.py createsuperuser
docker-compose exec web python manage.py migrate
```

## Creating an Admin User

### Option 1: Environment Variables (Automatic)

Add to `.env` before starting:

```bash
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=your-secure-password
DJANGO_SUPERUSER_EMAIL=admin@example.com
```

Then restart:

```bash
docker-compose down
docker-compose up -d
```

### Option 2: Command Line (Manual)

```bash
docker-compose exec web python manage.py createsuperuser
```

## Data Persistence

{{ project_name }} uses **SQLite by default**—a production-ready database that requires no additional services. Your data is stored in Docker volumes that persist across container rebuilds:

- **db_data**: SQLite database file (`/data/db.sqlite3`)
- **media_data**: Uploaded files (`/app/media`)

This separation means containers are disposable but data is not. Deploy new versions freely—your database survives.

View volumes:

```bash
docker volume ls
```

> **Warning:** `docker-compose down -v` deletes all data!

> **Need PostgreSQL?** See [PostgreSQL Database](/help/smallstack/database-postgresql/) for Docker Compose configuration with PostgreSQL.

## Changing the Port

Default port is **8010**. To change:

1. Edit `docker-compose.yml`:
   ```yaml
   ports:
     - "8080:8010"  # Change 8080 to your port
   ```

2. Restart:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

## Troubleshooting

### "Port already in use"

Another app is using port 8010. Either stop it or change the port (see above).

### "Permission denied" (Linux)

Add your user to the docker group:

```bash
sudo usermod -aG docker $USER
# Log out and back in
```

### Container keeps restarting

Check logs for errors:

```bash
docker-compose logs web
```

Common issues:
- Missing `.env` file
- Invalid `SECRET_KEY`
- Database connection problems

### Static files not loading

Collect static files and restart:

```bash
docker-compose exec web python manage.py collectstatic --noinput
docker-compose restart
```

### Full Reset

```bash
# Stop and remove everything
docker-compose down -v

# Remove the image
docker-compose down --rmi local

# Rebuild fresh
docker-compose up -d --build
```

## Quick Reference

| Command | Description |
|---------|-------------|
| `docker-compose build` | Build the image |
| `docker-compose up -d` | Start containers |
| `docker-compose down` | Stop containers |
| `docker-compose logs -f` | View logs |
| `docker-compose exec web bash` | Shell access |
| `docker-compose down -v` | Stop and remove data |

**URLs:**
- App: http://localhost:8010
- Admin: http://localhost:8010/admin
- Health: http://localhost:8010/health/
