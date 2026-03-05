---
title: Kamal Deployment
description: Zero-downtime VPS deployment for small teams
---

# Kamal Deployment

Kamal is a deployment tool that makes it easy to deploy containerized applications to VPS servers with zero-downtime updates. Created by **David Heinemeier Hansson (DHH)**, the founder of Ruby on Rails, Kamal works with any Docker container—including Django applications.

For more information, visit the official documentation at **[kamal-deploy.org](https://kamal-deploy.org)**.

> **See also:** [Deployment Overview](/help/deployment/) for a comparison of deployment options.

## Why Kamal?

Kamal fills a gap between simple manual deployments and complex orchestration systems like Kubernetes:

- **Zero-downtime deployments** in under 60 seconds
- **No Kubernetes required** — just SSH access to your servers
- **No external registry required** — images transfer directly via SSH
- **Multiple apps per server** — cost-effective for small teams
- **Built-in SSL** via Let's Encrypt (free, automatic renewal)
- **Simple rollbacks** to previous versions

## The VPS Stack Model

Self-hosted VPS with Docker is an **emerging trend** that reduces costs by consolidating applications and sharing resources. A single VPS can host multiple containers, each serving a different purpose or even different domains.

### Single VPS Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    VPS ($5-10/month)                        │
│                   1 CPU / 1GB RAM / 25GB                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────────────────────────────┐ │
│  │ kamal-proxy │───▶│  Routes traffic by domain name      │ │
│  │   :80/:443  │    │  Handles SSL certificates           │ │
│  └─────────────┘    └─────────────────────────────────────┘ │
│         │                                                   │
│         ├──── www.myapp.com ────▶ ┌─────────────────┐       │
│         │                         │  Django App     │       │
│         │                         │  (web container)│       │
│         │                         └─────────────────┘       │
│         │                                                   │
│         │                         ┌─────────────────┐       │
│         │                         │  Background     │       │
│         │                         │  Worker         │       │
│         │                         │  (db_worker)    │       │
│         │                         └─────────────────┘       │
│         │                                                   │
│         ├──── api.myapp.com ────▶ ┌─────────────────┐       │
│         │                         │  Django API     │       │
│         │                         │  (api container)│       │
│         │                         └─────────────────┘       │
│         │                                                   │
│         └──── other.domain.com ──▶ ┌─────────────────┐      │
│                                    │  Another App    │      │
│                                    │  (any container)│      │
│                                    └─────────────────┘      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Key insight:** Different domain names can all point to the same VPS IP address. Kamal-proxy routes requests to the correct container based on the domain.

### Growing the Stack

As your needs grow, simply add more containers to the same VPS:

```
┌─────────────────────────────────────────────────────────────┐
│               Production VPS ($10-20/month)                 │
│                   2 CPU / 2GB RAM / 50GB                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                    kamal-proxy                      │    │
│  │            (routes all incoming traffic)            │    │
│  └─────────────────────────────────────────────────────┘    │
│         │              │              │           │         │
│         ▼              ▼              ▼           ▼         │
│  ┌───────────┐  ┌───────────┐  ┌──────────┐  ┌─────────┐   │
│  │  www app  │  │  api app  │  │ postgres │  │  redis  │   │
│  │  :3000    │  │  :3001    │  │  :5432   │  │  :6379  │   │
│  └───────────┘  └───────────┘  └──────────┘  └─────────┘   │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌──────────────────────┐    │
│  │  umami    │  │prometheus │  │       grafana        │    │
│  │ analytics │  │ metrics   │  │     dashboards       │    │
│  │  :3002    │  │  :9090    │  │       :3003          │    │
│  └───────────┘  └───────────┘  └──────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Scaling Options

When you outgrow a single VPS, you have options:

1. **Vertical scaling** — Upgrade to more CPU, RAM, and disk (usually a few clicks in your VPS provider's dashboard)

2. **Horizontal scaling** — Add more VPS servers to your Kamal configuration:

```yaml
servers:
  web:
    - 123.45.67.89   # VPS 1
    - 123.45.67.90   # VPS 2
    - 123.45.67.91   # VPS 3
```

Kamal deploys to all servers simultaneously. However, for multi-server setups you'll need an **external load balancer** (like Digital Ocean Load Balancer, AWS ALB, or Cloudflare) in front of your servers to distribute traffic. Each server runs its own kamal-proxy instance which handles local container routing and zero-downtime deploys.

> **Note:** For most solo developers and small teams, vertical scaling on a single VPS is sufficient and avoids the complexity of external load balancers.

### Cost Comparison

Consider a typical small team stack:

| Component | Purpose |
|-----------|---------|
| www app | Main website |
| api app | Backend API |
| PostgreSQL | Database |
| Umami | Privacy-focused analytics |
| Prometheus | Metrics collection |
| Grafana | Monitoring dashboards |

**Traditional PaaS Hosting (e.g., Digital Ocean App Platform):**

| Item | Monthly Cost |
|------|-------------|
| 6 app containers @ $5 each | $30 |
| Managed PostgreSQL (basic) | $15 |
| ~20% backup fees | $9 |
| **Total** | **~$54/month** |

**Self-Hosted VPS with Kamal:**

| Item | Monthly Cost |
|------|-------------|
| VPS (2 CPU / 2GB RAM / 50GB) | $10-12 |
| Backups (~20%) | $2 |
| **Total** | **~$12-14/month** |

**Estimated savings: ~$40/month ($480/year)**

> *Pricing based on Digital Ocean rates as of March 2026. Costs vary between providers.*

The trade-off is that you manage the server yourself—but Kamal makes that management remarkably simple with zero-downtime deploys and straightforward container orchestration.

## Quick Setup Checklist

Before your first deploy, update these files with your project info:

### 1. config/deploy.yml

```yaml
service: myapp              # Your app name (lowercase, no spaces)
image: myapp                # Usually same as service

servers:
  web:
    - 123.45.67.89          # Your VPS IP address
  worker:
    hosts:
      - 123.45.67.89        # Same VPS as web
    cmd: python manage.py db_worker --queue-name "*"

volumes:
  - /root/myapp_data/media:/app/media   # Update 'myapp' to your app name
  - /root/myapp_data/db:/app/data

proxy:
  hosts:
    - myapp.com             # Your domain
    - www.myapp.com         # Your www subdomain
```

### 2. .kamal/secrets

Copy from the example and fill in your values:

```bash
cp .kamal/secrets.example .kamal/secrets
```

Then edit `.kamal/secrets`:

```bash
# Generate a new secret key at https://djecrety.ir/
SECRET_KEY=your-unique-secret-key-here

# Include your domain, www, VPS IP, and * for health checks
ALLOWED_HOSTS=myapp.com,www.myapp.com,123.45.67.89,localhost,127.0.0.1,*

# HTTPS origins (required for CSRF protection)
CSRF_TRUSTED_ORIGINS=https://myapp.com,https://www.myapp.com
```

> **Important:** The `.kamal/secrets` file is gitignored. Never commit real secrets to version control.

## Prerequisites

Before deploying with Kamal, you need:

1. **A VPS** (Digital Ocean, Linode, Hetzner, etc.) with:
   - **Minimum 1GB RAM and 1 CPU** recommended for reliable deployments
   - Ubuntu 22.04+ or Debian 12+
   - SSH access as root (or sudo user)
   - Ports 80 and 443 open

> **Performance note:** Deployments involve building Docker images and transferring them to your VPS via SSH. Slow VPS hardware or poor network connectivity can cause deployments to time out or fail intermittently. A VPS with at least 1GB RAM and 1 CPU provides enough headroom for reliable builds, health checks, and day-to-day application performance. Budget VPS plans with 512MB RAM may work but can be unreliable under load.

2. **A domain name** pointed to your VPS IP address

3. **Docker Desktop** running on your local machine
   - [Mac](https://docs.docker.com/desktop/install/mac-install/) | [Windows](https://docs.docker.com/desktop/install/windows-install/) | [Linux](https://docs.docker.com/desktop/install/linux-install/)
   - Must be running during deployments (Kamal uses it to build images and transfer them via SSH)

4. **Kamal installed** on your local machine:
   ```bash
   # macOS
   brew install kamal

   # Or via Ruby gem
   gem install kamal
   ```

## Configuration Files

Kamal uses two main configuration files:

### config/deploy.yml

The main deployment configuration:

```yaml
service: my-app

image: my-app

servers:
  web:
    - 123.45.67.89  # Your VPS IP
  worker:
    hosts:
      - 123.45.67.89  # Same VPS as web
    cmd: python manage.py db_worker --queue-name "*"

ssh:
  user: root

volumes:
  - /root/my_app_data/media:/app/media
  - /root/my_app_data/db:/app/data

env:
  clear:
    DJANGO_SETTINGS_MODULE: config.settings.production
    DJANGO_DEBUG: "False"
  secret:
    - SECRET_KEY
    - ALLOWED_HOSTS

proxy:
  ssl: true
  hosts:
    - myapp.com
    - www.myapp.com
  healthcheck:
    path: /health/
    interval: 10
    timeout: 60

# Local registry - no external service needed
# Kamal handles SSH port forwarding automatically
registry:
  server: localhost:5555

builder:
  arch: amd64
```

### .kamal/secrets

Environment secrets (gitignored):

```bash
SECRET_KEY=your-secret-key-here
# Important: Include * at the end for kamal-proxy health checks
ALLOWED_HOSTS=myapp.com,www.myapp.com,123.45.67.89,localhost,127.0.0.1,*
CSRF_TRUSTED_ORIGINS=https://myapp.com,https://www.myapp.com
```

## Data Persistence

{{ project_name }} uses **SQLite by default**, stored in a mounted volume on your VPS. This means:

- **Database survives deployments** — The `/app/data` directory is mounted from `/root/my_app_data/db` on the VPS
- **Simple backups** — VPS snapshots include your database automatically
- **No database service costs** — Everything runs on your single VPS

```yaml
# In deploy.yml
volumes:
  - /root/my_app_data/media:/app/media   # Uploaded files
  - /root/my_app_data/db:/app/data       # SQLite database
```

The container is ephemeral, but your data is not. When you deploy a new version, the old container is replaced, but the database file on the VPS filesystem remains untouched.

> **Need PostgreSQL?** See [PostgreSQL Database](/help/database-postgresql/) for migration instructions and Kamal accessory configuration.

## Common Commands

### Deployment

```bash
# First-time setup (installs Docker, creates network)
kamal setup

# Deploy latest changes
make deploy        # or: kamal deploy

# Rollback to previous version
kamal rollback
```

### Logs and Status

```bash
# View application logs
make logs          # or: kamal app logs

# View last 100 lines
kamal app logs -n 100

# Check container status
kamal app details

# Check proxy status
kamal proxy status
```

### Container Access

```bash
# Interactive shell
kamal app exec -i bash

# Run Django commands
kamal app exec "python manage.py createsuperuser"
kamal app exec "python manage.py migrate"
kamal app exec "python manage.py shell"
```

### Container Management

```bash
# Restart the app
kamal app boot

# Stop the app
kamal app stop

# Start the app
kamal app start
```

### Lock Management

```bash
# Release a stuck deploy lock
kamal lock release

# Check lock status
kamal lock status
```

## How Zero-Downtime Works

When you run `kamal deploy`:

1. **Build** — Docker image is built locally using Docker Desktop
2. **Transfer** — Image is pushed to VPS via SSH tunnel (no external registry)
3. **Boot** — New container starts alongside the old one
4. **Health Check** — Kamal waits for `/health/` to return 200
5. **Switch** — Proxy routes traffic to new container
6. **Cleanup** — Old container is stopped and removed

The old container **keeps serving traffic** until the new one passes health checks. If the new container fails to become healthy, the deployment aborts and the old container continues running.

## Background Worker

{{ project_name }} includes a **background worker** role in the Kamal deployment configuration. This runs the `db_worker` management command to process background tasks (emails, data processing, etc.) in production.

### How It Works

The `worker` role in `deploy.yml` uses the **same Docker image** as the web role but with a different startup command:

```yaml
servers:
  web:
    - 123.45.67.89
  worker:
    hosts:
      - 123.45.67.89
    cmd: python manage.py db_worker --queue-name "*"
```

- **Same image** — No separate Dockerfile or build step
- **Same entrypoint** — Migrations and collectstatic run (idempotent, safe from both containers)
- **No proxy needed** — The worker has no HTTP traffic, so Kamal skips proxy configuration for it
- **Shared volumes** — Worker reads/writes the same database as the web container

### Worker Commands

```bash
# View worker logs
kamal app logs --role worker

# View last 100 lines of worker logs
kamal app logs --role worker -n 100

# Check worker container status
kamal app details

# Run a command in the worker container
kamal app exec --role worker "python manage.py shell"
```

The worker deploys automatically alongside the web container when you run `kamal deploy`. No extra steps required.

> **See also:** [Background Tasks](/help/smallstack/background-tasks/) for details on defining and enqueueing tasks.

## Registry: Local by Default

One of Kamal's best features for simple deployments is **local registry support**. Unlike traditional container deployments that require pushing images to Docker Hub or a private registry, Kamal can transfer images directly to your VPS via SSH.

### How It Works

```yaml
registry:
  server: localhost:5555
```

With this configuration:

1. Kamal builds your Docker image locally using Docker Desktop
2. Kamal sets up SSH port forwarding to a temporary registry on your VPS
3. The image transfers securely through your existing SSH connection
4. No external registry account, credentials, or costs required

> **Important:** Docker Desktop must be running on your local machine during deployments. Kamal uses the Docker daemon to build images and manage the SSH tunnel.

### When to Use External Registries

For most solo developers and small teams, the local registry is ideal. Consider an external registry only if you need:

- **Team deployments** — Multiple developers deploying from different machines
- **CI/CD pipelines** — Automated deployments from GitHub Actions, etc.
- **Image history** — Long-term storage of previous image versions

### External Registry Options

If needed, Kamal supports external registries:

```yaml
# Docker Hub
registry:
  username: yourusername
  password:
    - KAMAL_REGISTRY_PASSWORD

# Private/Self-hosted Registry
registry:
  server: registry.yourdomain.com
  username: registryuser
  password:
    - KAMAL_REGISTRY_PASSWORD
```

Add `KAMAL_REGISTRY_PASSWORD` to your `.kamal/secrets` file when using external registries.

## Creating a Superuser

### Option 1: Environment Variables (Automatic)

Add to `.kamal/secrets`:

```bash
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=secure-password
DJANGO_SUPERUSER_EMAIL=admin@example.com
```

The entrypoint script creates the user on container start.

### Option 2: Manual

```bash
kamal app exec "python manage.py createsuperuser"
```

## SSL Certificates

With `ssl: true` in your proxy config, Kamal automatically:

1. Obtains certificates from Let's Encrypt
2. Configures HTTPS for your domains
3. Redirects HTTP to HTTPS
4. Renews certificates before expiration

**Requirements:**
- Domain must point to your VPS IP
- Ports 80 and 443 must be accessible
- Valid email configured (for Let's Encrypt notifications)

## Troubleshooting

### Deploy Lock Stuck

```bash
kamal lock release
```

### Container Unhealthy

Check logs for errors:

```bash
kamal app logs -n 200
```

Common causes:
- Missing environment variables
- Database migration needed
- Invalid ALLOWED_HOSTS

### SSH Connection Issues

Test SSH access:

```bash
ssh root@your-vps-ip
```

Ensure your SSH key is added:

```bash
ssh-add ~/.ssh/id_rsa
```

### Docker Desktop Not Running

If deployments fail with connection errors, ensure Docker Desktop is running:

```bash
docker info
```

Kamal requires Docker Desktop to build images and manage the SSH tunnel for image transfer.

### Registry Authentication Failed (External Registries Only)

If using an external registry, verify credentials:

```bash
docker login your-registry.com
```

Check `.kamal/secrets` has correct `KAMAL_REGISTRY_PASSWORD`.

### Health Check Failing

Ensure your app has a `/health/` endpoint that returns 200:

```python
# urls.py
path("health/", lambda r: HttpResponse("OK"))
```

Check ALLOWED_HOSTS includes the container hostname pattern or use `*` for internal health checks.

## Quick Reference

| Task | Make shortcut | Kamal command |
|------|--------------|---------------|
| Deploy | `make deploy` | `kamal deploy` |
| View logs | `make logs` | `kamal app logs` |
| View worker logs | — | `kamal app logs --role worker` |
| First-time setup | — | `kamal setup` |
| Rollback | — | `kamal rollback` |
| Shell access | — | `kamal app exec -i bash` |
| Run Django command | — | `kamal app exec "python manage.py ..."` |
| Release stuck lock | — | `kamal lock release` |
| Check status | — | `kamal app details` |

> **Tip:** `make deploy` and `make logs` are convenience shortcuts included in the Makefile. See [Make Commands](/help/smallstack/make-commands/) for the full list of available shortcuts.

## Further Reading

- [Kamal Documentation](https://kamal-deploy.org/docs/installation/)
- [Kamal GitHub Repository](https://github.com/basecamp/kamal)
- [Make Commands](/help/smallstack/make-commands/) — All available Makefile shortcuts
- [Docker Deployment Guide](/help/docker-deployment/) — Alternative deployment approach
