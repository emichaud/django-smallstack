# Docker Deployment Guide

This guide walks you through deploying Django SmallStack using Docker. Don't worry if you're new to Docker—we'll take it step by step.

## Prerequisites

Before starting, make sure you have:

1. **Docker Desktop** installed and running
   - [Download for Mac](https://docs.docker.com/desktop/install/mac-install/)
   - [Download for Windows](https://docs.docker.com/desktop/install/windows-install/)
   - [Download for Linux](https://docs.docker.com/desktop/install/linux-install/)

2. **The project files** on your computer

To verify Docker is working, open your terminal and run:

```bash
docker --version
docker-compose --version
```

You should see version numbers for both commands.

---

## Quick Start (5 Minutes)

### Step 1: Create Your Environment File

The project needs some configuration. Copy the example environment file:

```bash
cp .env.example .env
```

Or create a new `.env` file with these settings:

```bash
# Required settings
SECRET_KEY=your-secret-key-change-this-to-something-random
DJANGO_SETTINGS_MODULE=config.settings.production
ALLOWED_HOSTS=localhost,127.0.0.1

# Optional: Create an admin user automatically
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=your-secure-password
DJANGO_SUPERUSER_EMAIL=admin@example.com
```

**Important:** Change `SECRET_KEY` to a random string. You can generate one at [djecrety.ir](https://djecrety.ir/).

### Step 2: Build the Docker Image

This downloads everything needed and creates your application image:

```bash
docker-compose build
```

This may take a few minutes the first time. You'll see lots of output—that's normal!

### Step 3: Start the Application

```bash
docker-compose up -d
```

The `-d` flag runs it in the background so you get your terminal back.

### Step 4: Open the Application

Visit **http://localhost:8010** in your browser. You should see the home page!

If you set the superuser environment variables, you can log in at **http://localhost:8010/admin** with those credentials.

---

## Detailed Explanation

### What's Happening Behind the Scenes?

When you run `docker-compose up`, Docker:

1. **Builds** an image with Python, Django, and all dependencies
2. **Runs migrations** to set up the database
3. **Creates a superuser** (if configured)
4. **Starts the web server** (Gunicorn) on port 8010

### Project Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Instructions for building the application image |
| `docker-compose.yml` | Defines services, ports, and volumes |
| `docker-entrypoint.sh` | Runs on container startup (migrations, etc.) |
| `.dockerignore` | Files to exclude from the Docker image |

---

## Common Commands

### Starting and Stopping

```bash
# Start the application (background)
docker-compose up -d

# Stop the application
docker-compose down

# Stop and remove all data (database, uploads)
docker-compose down -v
```

### Viewing Logs

```bash
# See all logs
docker-compose logs

# Follow logs in real-time
docker-compose logs -f

# See last 50 lines
docker-compose logs --tail=50
```

### Checking Status

```bash
# See running containers
docker-compose ps

# Check if the app is healthy
curl http://localhost:8010/health/
```

### Running Commands Inside the Container

```bash
# Open a shell in the container
docker-compose exec web bash

# Run a Django management command
docker-compose exec web python manage.py createsuperuser

# Run migrations manually
docker-compose exec web python manage.py migrate
```

---

## Creating an Admin User

### Option 1: Environment Variables (Automatic)

Add these to your `.env` file before starting:

```bash
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=your-secure-password
DJANGO_SUPERUSER_EMAIL=admin@example.com
```

Then restart the container:

```bash
docker-compose down
docker-compose up -d
```

### Option 2: Command Line (Manual)

```bash
docker-compose exec web python manage.py createsuperuser
```

Follow the prompts to enter username, email, and password.

---

## Data Persistence

Your data is stored in Docker volumes, which persist even when containers stop:

- **db_data**: SQLite database file
- **media_data**: Uploaded files (profile photos, etc.)

To see your volumes:

```bash
docker volume ls
```

**Warning:** Running `docker-compose down -v` deletes these volumes and all your data!

---

## Changing the Port

By default, the app runs on port **8010**. To change it:

1. Edit `docker-compose.yml`:
   ```yaml
   ports:
     - "8080:8010"  # Change 8080 to your preferred port
   ```

2. Restart:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

3. Visit `http://localhost:8080` (your new port)

---

## Troubleshooting

### "Port already in use"

Another application is using port 8010. Either:
- Stop the other application, or
- Change the port (see above)

### "Permission denied"

On Linux, you may need to run Docker commands with `sudo`, or add your user to the docker group:

```bash
sudo usermod -aG docker $USER
# Then log out and back in
```

### Container keeps restarting

Check the logs for errors:

```bash
docker-compose logs web
```

Common issues:
- Missing `.env` file
- Invalid `SECRET_KEY`
- Database connection problems

### Static files not loading (CSS looks broken)

Make sure `DEBUG=False` in production and static files were collected:

```bash
docker-compose exec web python manage.py collectstatic --noinput
```

Then restart:

```bash
docker-compose restart
```

### Need to reset everything

```bash
# Stop containers and remove volumes
docker-compose down -v

# Remove the built image
docker-compose down --rmi local

# Start fresh
docker-compose up -d --build
```

---

## Production Considerations

This Docker setup is great for local development and small deployments. For larger production deployments, consider:

1. **Use a real database** (PostgreSQL) instead of SQLite
2. **Use a reverse proxy** (nginx, Traefik) for SSL/HTTPS
3. **Use cloud storage** (S3) for media files
4. **Set up backups** for your database
5. **Use Docker Swarm or Kubernetes** for scaling

### Example: Adding PostgreSQL

Update `docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=smallstack
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=your-db-password

  web:
    build: .
    depends_on:
      - db
    environment:
      - DATABASE_URL=postgres://postgres:your-db-password@db:5432/smallstack
    # ... rest of config

volumes:
  postgres_data:
```

---

## Getting Help

- Check the [Django documentation](https://docs.djangoproject.com/)
- Check the [Docker documentation](https://docs.docker.com/)
- Open an issue in the project repository

---

## Quick Reference Card

```bash
# Build
docker-compose build

# Start
docker-compose up -d

# Stop
docker-compose down

# Logs
docker-compose logs -f

# Shell access
docker-compose exec web bash

# Create admin user
docker-compose exec web python manage.py createsuperuser

# Full reset
docker-compose down -v && docker-compose up -d --build
```

**Application URL:** http://localhost:8010
**Admin URL:** http://localhost:8010/admin
**Health Check:** http://localhost:8010/health/
