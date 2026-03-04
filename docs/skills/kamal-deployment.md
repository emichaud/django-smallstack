# Skill: Kamal Deployment

This skill describes how to configure and deploy SmallStack applications using Kamal, an optional zero-downtime deployment tool.

## Overview

Kamal is an optional deployment utility included with SmallStack. It deploys Docker containers to VPS servers with zero-downtime updates via SSH. It is **not required** — SmallStack works with any deployment method.

### Requirements

- **VPS with SSH access** — Any provider (Digital Ocean, Linode, Hetzner, etc.) running Ubuntu 22.04+ or Debian 12+
- **SSH key authentication** — Root or sudo access to the VPS
- **Docker Desktop** — Must be running locally during deployments (builds images and transfers via SSH)
- **Kamal installed locally** — `brew install kamal` or `gem install kamal`
- **Domain name** (optional but recommended) — Required for HTTPS. When configured, Kamal provides free, automatic SSL certificates via Let's Encrypt with seamless renewal.

Without a domain name, the app is accessible via the VPS IP address over HTTP only.

## Key Files

```
smallstack/
├── config/
│   └── deploy.yml           # Main Kamal deployment configuration
├── .kamal/
│   ├── secrets              # Environment secrets (gitignored)
│   └── secrets.example      # Template for secrets file
├── Dockerfile               # Production container build
├── docker-entrypoint.sh     # Container startup script
├── gunicorn.conf            # Gunicorn production settings
└── Makefile                 # make deploy, make logs shortcuts
```

## Configuration

### config/deploy.yml

The main deployment configuration. Key sections to update for a new project:

```yaml
service: myapp              # App name (lowercase, no spaces)
image: myapp                # Docker image name (usually same as service)

servers:
  web:
    - 123.45.67.89          # VPS IP address

volumes:
  - /root/myapp_data/media:/app/media   # Persistent media uploads
  - /root/myapp_data/db:/app/data       # Persistent SQLite database

proxy:
  ssl: true                 # Enable Let's Encrypt HTTPS (requires domain)
  hosts:
    - myapp.com             # Domain name
    - www.myapp.com         # www subdomain

# Local registry - no Docker Hub account needed
registry:
  server: localhost:5555

builder:
  arch: amd64               # VPS architecture (usually amd64)
```

### .kamal/secrets

Environment secrets — never committed to version control:

```bash
SECRET_KEY=your-unique-secret-key-here
ALLOWED_HOSTS=myapp.com,www.myapp.com,123.45.67.89,localhost,127.0.0.1,*
CSRF_TRUSTED_ORIGINS=https://myapp.com,https://www.myapp.com
```

The `*` in ALLOWED_HOSTS is required for kamal-proxy internal health checks.

## Common Commands

### Make Shortcuts

```bash
make deploy       # Deploy to production (runs kamal deploy)
make logs         # View production logs (runs kamal app logs)
```

### Full Kamal Commands

```bash
# First-time server setup (installs Docker, creates network)
kamal setup

# Deploy latest changes
kamal deploy

# Rollback to previous version
kamal rollback

# View logs
kamal app logs
kamal app logs -n 200

# Check status
kamal app details
kamal proxy status

# Shell into production container
kamal app exec -i bash

# Run Django management commands in production
kamal app exec "python manage.py migrate"
kamal app exec "python manage.py createsuperuser"
kamal app exec "python manage.py shell"

# Release a stuck deploy lock
kamal lock release
```

## Deployment Flow

When `make deploy` (or `kamal deploy`) runs:

1. Docker image is built locally using Docker Desktop
2. Image transfers to VPS via SSH tunnel (no external registry needed)
3. New container starts alongside the old one
4. Kamal waits for `/health/` endpoint to return 200
5. kamal-proxy routes traffic to new container
6. Old container is stopped and removed

The old container **continues serving traffic** until the new one passes health checks. If the new container fails, deployment aborts and the old container keeps running.

## SSL / HTTPS

When `ssl: true` is set in deploy.yml and a domain name is configured:

- Kamal automatically obtains Let's Encrypt certificates
- HTTPS is configured for all listed domains
- HTTP requests redirect to HTTPS
- Certificates auto-renew before expiration
- **No manual certificate management required**

Requirements for SSL:
- Domain DNS must point to VPS IP address
- Ports 80 and 443 must be open on the VPS
- At least one domain listed in `proxy.hosts`

Without a domain (IP-only access), set `ssl: false`.

## Data Persistence

SmallStack uses SQLite by default, stored in a mounted volume:

```yaml
volumes:
  - /root/myapp_data/media:/app/media   # Uploaded files
  - /root/myapp_data/db:/app/data       # SQLite database
```

The container is ephemeral but data persists on the VPS filesystem across deployments. VPS provider backups automatically include the database.

## Creating a Production Superuser

### Option 1: Environment Variables (automatic)

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

## Troubleshooting

### Common Issues

| Problem | Solution |
|---------|----------|
| Deploy lock stuck | `kamal lock release` |
| Container unhealthy | Check `kamal app logs -n 200` for errors |
| SSH connection failed | Verify `ssh root@your-vps-ip` works, run `ssh-add` |
| Docker errors during deploy | Ensure Docker Desktop is running (`docker info`) |
| SSL not working | Verify domain DNS points to VPS IP, ports 80/443 open |
| Health check failing | Ensure `/health/` endpoint exists and ALLOWED_HOSTS includes `*` |
| Missing env vars | Check `.kamal/secrets` has all required variables |

### Modifying deploy.yml

When making changes to deploy.yml:

- **service/image name:** Must be lowercase, no spaces. Changing this on an existing deployment requires cleanup on the VPS.
- **servers:** Add/remove VPS IPs. Kamal deploys to all listed servers.
- **volumes:** Ensure VPS directories exist or Kamal will create them.
- **proxy.hosts:** Update domain names. SSL certs are provisioned per-domain.
- **env.secret:** Any variable listed here must exist in `.kamal/secrets`.

### Health Check Endpoint

SmallStack includes a health check at `/health/` in `config/urls.py`:

```python
path("health/", health_check, name="health_check"),
```

This returns a simple 200 response. Kamal uses this to verify the container is ready before routing traffic to it. Do not remove or break this endpoint.

## Multi-App VPS

Kamal supports multiple apps on a single VPS. Each app gets its own container and domain routing via kamal-proxy:

```
VPS ($10/month)
├── kamal-proxy (:80/:443)
│   ├── myapp.com      → Django app container
│   ├── api.myapp.com  → API container
│   └── other.com      → Another app entirely
```

Each app has its own `config/deploy.yml` pointing to the same VPS IP but with different service names and domains.

## Further Reading

- SmallStack docs: `/help/smallstack/kamal-deployment/`
- SmallStack docs: `/help/smallstack/make-commands/`
- Kamal official docs: https://kamal-deploy.org
- Kamal GitHub: https://github.com/basecamp/kamal
