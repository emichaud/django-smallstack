---
title: Database Backups
description: Protect your data from day one with built-in SQLite backup tooling
---

# Database Backups

Your database is the most important thing in your application. {{ project_name }} ships with a complete backup system so you can protect your data from day one — scheduled backups, a staff dashboard for manual control, and one-click downloads to get a copy on your local machine.

> **See also:** [SQLite Database](/help/smallstack/database-sqlite/) for how {{ project_name }} configures and persists SQLite, and [PostgreSQL Database](/help/smallstack/database-postgresql/) for when you need to scale beyond SQLite.

## Why SQLite Backups Are Simple

SQLite is just a file. That single fact makes backups remarkably straightforward compared to traditional database servers. There is no dump process, no export format, no client-server protocol — you copy the file and you have a complete, working database.

{{ project_name }} uses Python's `sqlite3.Connection.backup()` API to create safe, non-blocking copies of your live database. The backup runs while your application continues serving requests. No downtime, no locking, no complexity.

For small sites, departmental tools, hobby projects, or club websites, SQLite is surprisingly fast and capable. And because it is just a file, backing it up is as natural as copying a document.

## How Backups Work

{{ project_name }} provides three ways to create backups:

**Scheduled backups** run automatically via cron inside your Docker container. Disabled by default — enable with one environment variable. The default schedule creates a daily backup at 2 AM UTC and retains two weeks of history.

**Manual backups** are triggered from the staff dashboard or the command line. Click "Backup Now" on the backups page to create an on-server copy instantly.

**Download backups** create a fresh backup and stream it straight to your browser. This is the fastest way to get a copy of your database onto your local machine for safekeeping or analysis.

All three methods use the same safe backup process and are tracked in the backup history with timestamps, file sizes, duration, and status.

## Quick Start

```bash
# Create a backup from the command line
make backup

# Or with options (override retention count)
python manage.py backup_db --keep 5
```

That's all you need. Backups are saved to your `BACKUP_DIR` and tracked in the database automatically. By default, the 10 most recent backups are kept — configurable via the `BACKUP_RETENTION` setting or the `--keep` flag.

## The Backup Dashboard

Staff users can access the backup management page at `/backups/`. The Backups link appears in the sidebar under the Admin section.

### Page Header

The top of the page shows your current backup status at a glance:

- **Scheduled status** — green checkmark if cron backups are enabled, red warning if not (with a link to the setup docs)
- **Backup Now** — creates a backup and saves it to server storage
- **Download** — creates a backup and downloads it to your browser

### Backup Activity Tab

The default view shows:

- **Stat cards** — six cards showing recent backups (24h), successful, failed, pruned, average duration, and total size on disk. Click a stat card to see the matching backup records in a detail modal.
- **Backup history table** — paginated list of all backups with clickable IDs, timestamps, file sizes, status badges, and trigger source. Pruned backups show a muted badge; missing files show a red warning icon.

All dates display in your timezone (set on the Profile Edit page, or the server default). When your timezone differs from the server's, dates show a dotted underline — hover to see the server time and UTC. See [Working with Timezones](/help/smallstack/timezones/) for details.

### Backup Detail Page

Click any backup ID (e.g., `#12`) to see its full detail page at `/backups/12/`. This shows:

- **Details card** — filename, size, duration, trigger source, status, and file availability
- **Activity timeline** — visual history of the backup lifecycle: when it was created, and if/when it was pruned or went missing
- **Download button** — if the file is still on disk and downloads are enabled

### Files Tab

Lists all backup files currently on disk with their sizes and modification dates. This shows what is actually in your backup directory, regardless of what the database records say.

### Configuration Tab

Shows your current backup settings at a glance:

- **Database info** — engine, file path, and current database size
- **Backup settings** — directory, retention count, scheduled status, and download status
- **Email status** — whether SMTP is configured for failure alerts
- **Admin recipients** — who receives failure notifications (click to see the list)

Status indicators turn red when email or admin configuration is missing, linking directly to the relevant setup docs.

## Pruning

When backups are pruned (automatically via retention policy or manually via `--keep`), {{ project_name }} marks the original backup record with a `pruned_at` timestamp instead of creating a separate record. This means:

- Pruned backups show a muted "pruned" badge and a gray trash icon in the history table
- The detail page shows exactly when the file was removed
- The red warning icon is reserved for files that are *unexpectedly* missing — not routine pruning
- Stat cards correctly separate "successful" (file available) from "pruned" (file removed by policy)

## Management Command

The `backup_db` command creates a safe, non-blocking backup using Python's `sqlite3.Connection.backup()` API.

```bash
# Basic backup (saved to BACKUP_DIR)
python manage.py backup_db

# Override retention for this run (keeps only the 5 most recent)
python manage.py backup_db --keep 5

# Save to a specific path
python manage.py backup_db --output /tmp/my-backup.sqlite3
```

**Options:**

| Flag | Description |
|------|-------------|
| `--keep N` | Prune oldest backups beyond N. Defaults to `BACKUP_RETENTION` setting (10) if not specified. |
| `--output PATH` | Override the destination file path |

Backup files are named `db-YYYYMMDD-HHMMSS.sqlite3` (timestamp in UTC) and stored in `BACKUP_DIR`. The UTC naming is intentional — filenames stay consistent regardless of display timezone settings, and sort correctly on disk.

## Scheduled Backups (Docker)

Backups can run automatically on a schedule inside your Docker container. This is disabled by default.

### Enable Scheduled Backups

The setting is already in your configuration files, just disabled by default. Uncomment and enable it:

**docker-compose.yml** — find the commented line in the `web` service `environment` section and uncomment it:
```yaml
- BACKUP_CRON_ENABLED=true  # Enable scheduled database backups
```

**Kamal (config/deploy.yml)** — find the commented line in `env.clear` and uncomment it:
```yaml
BACKUP_CRON_ENABLED: "true"  # Enable scheduled database backups
```

The default schedule is **daily at 2 AM UTC**. The cron script uses `--keep 14` to retain two weeks of daily backups (overriding the default `BACKUP_RETENTION` of 10).

### Cron and Timezones

Cron jobs run in the **container's system timezone**, which is set via the `TZ` environment variable. By default this is UTC, so `0 2 * * *` means 2 AM UTC.

The Django `TIME_ZONE` setting only affects how dates are *displayed* in templates — it has no effect on when cron jobs fire.

**To run backups at 2 AM in your local timezone**, set `TZ` in your deployment config:

**docker-compose.yml:**
```yaml
services:
  web:
    environment:
      - TZ=America/New_York
```

**Kamal (config/deploy.yml):**
```yaml
env:
  clear:
    TZ: "America/New_York"
```

With `TZ=America/New_York`, the `0 2 * * *` cron expression fires at 2 AM Eastern. This is usually what you want — backups run during your off-hours regardless of daylight saving shifts.

> **Note:** Scheduled tasks run via supercronic, which uses the `TZ` environment variable to determine timezone. `CRON_TZ` is not supported — use `TZ` instead.

### Customize the Schedule

Edit `scripts/smallstack-cron` to change the cron expression:

```cron
# Every 6 hours, keep 28 backups
0 */6 * * * cd /app && python3 manage.py backup_db --keep 28
```

After changing, rebuild and redeploy your container.

## Configuration

These settings are already defined in `config/settings/base.py` with sensible defaults. Override them via environment variables or your `.env` file:

| Setting | Default | Description |
|---------|---------|-------------|
| `BACKUP_DIR` | `<project>/backups/` | Directory to store backup files |
| `BACKUP_RETENTION` | `10` | Default number of backups to keep (used when `--keep` is not specified) |
| `BACKUP_CRON_ENABLED` | `false` | Enable cron-based scheduled backups in Docker |
| `BACKUP_DOWNLOAD_ENABLED` | `true` | Allow backup file downloads from the web UI |

## Backup Strategy: Protecting Against Real Risks

The built-in backup system keeps copies of your database on your server's disk. This protects you from application errors, accidental data changes, and bad deployments. But there is one scenario it does not cover: **if your VPS itself fails or is destroyed, your backups go with it.**

This is the biggest risk with on-server backups. Here is how to mitigate it:

### 1. Download Your Database Periodically

The simplest protection is to download a copy of your database to your local machine on a regular basis. Use the "Download" button on the backup dashboard, or pull files from the server:

```bash
# Copy the latest backup from your server
scp root@your-server:/root/myapp_data/db/backups/db-*.sqlite3 ./local-backups/

# Or use rsync for incremental copies
rsync -avz root@your-server:/root/myapp_data/db/backups/ ./local-backups/
```

Because SQLite is just a file, the downloaded copy is a fully working database. You can open it locally with `sqlite3`, attach it to a local Django instance, or simply keep it as an archive.

### 2. Enable VPS-Level Backups

Most hosting providers offer automated server snapshots:

- **DigitalOcean** — Enable weekly backups for 20% of your droplet cost (~$1/month on a $5 droplet). You can also create on-demand snapshots before risky changes.
- **Hetzner** — Automated snapshots available on all cloud servers.
- **AWS Lightsail** — Automatic snapshots with configurable retention.

These snapshots capture your entire server — database, backups, configuration, everything. If your VPS is destroyed, you can restore from a snapshot and be back online in minutes.

### 3. The Result: Multiple Copies

With this approach, you have three layers of protection:

| Layer | What It Covers | What It Doesn't Cover |
|-------|---------------|----------------------|
| **On-server backups** | Bad deploys, data errors, accidental changes | VPS failure, disk corruption |
| **Downloaded copies** | VPS failure, provider outage, account issues | Only as fresh as your last download |
| **VPS snapshots** | Disk failure, VPS destruction, full server recovery | Provider-level outage (rare) |

Any single layer has gaps. Together, they cover each other's weaknesses. For the early days, this gives you solid data protection without the cost or complexity of a managed database service.

## Failure Notifications

If a backup fails, {{ project_name }} will email the `ADMINS` list using `mail_admins()`. This requires three things to be configured:

**1. Set ADMINS** — uncomment and edit the example in `config/settings/production.py`:
```python
ADMINS = [("Your Name", "you@example.com")]
```

**2. Set SERVER_EMAIL** — this is the from-address Django uses for `mail_admins()` emails. Set it via environment variable or in `production.py`:
```bash
SERVER_EMAIL=server@yourdomain.com
```

**3. Configure SMTP email** — the default email backend prints to console, which won't reach anyone in production. Set these environment variables to use a real mail server:
```bash
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-app-password
```

> **Note:** Your SMTP provider must authorize the `SERVER_EMAIL` and `DEFAULT_FROM_EMAIL` addresses as sending identities. For example, Fastmail requires you to add each from-address as an alias or sending identity before it will accept outbound mail from that address.

**Verify email delivery** — use Django's built-in test command to confirm your SMTP config works before waiting for a backup failure:
```bash
python manage.py sendtestemail you@example.com
```

In development, `EMAIL_BACKEND` defaults to the console backend, so emails print to your terminal instead of sending. To test real delivery locally, set `EMAIL_BACKEND` in your `.env` file:
```bash
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
```

See the [Email & Password Reset](/help/smallstack/email-auth/) docs for full SMTP setup instructions.

If `ADMINS` is empty or email is not configured, backup failures are still recorded in the backup history — they just won't trigger a notification.

## Security Considerations

**Backup files contain all application data.** Treat them with the same care as your database file itself.

- Backup files are excluded from git via `.gitignore`
- The `/backups/` page requires staff access
- File downloads require staff authentication
- The download endpoint includes path traversal protection

## Setup Checklist

If you're enabling backups in a project built from {{ project_name }}, verify these are in place:

- [ ] `apps.smallstack` is in `INSTALLED_APPS` (`config/settings/base.py`)
- [ ] `/backups/` URL is included in `config/urls.py`
- [ ] `BACKUP_*` settings are defined in `config/settings/base.py`
- [ ] Migrations are up to date (`make migrate`)
- [ ] `make backup` target exists in your `Makefile`
- [ ] For Docker/Kamal: `BACKUP_CRON_ENABLED` is set in `docker-compose.yml` or `config/deploy.yml`
- [ ] For email notifications: `ADMINS`, `SERVER_EMAIL`, and SMTP env vars are configured

## When to Consider PostgreSQL

The built-in backup system is designed for SQLite. If your project grows to the point where you need PostgreSQL — high concurrent writes, millions of requests, heavy write pressure — you will also outgrow this backup tool.

At that point, consider a **managed database service** from DigitalOcean, AWS, Google Cloud, Supabase, or Neon. Managed services handle automated backups, point-in-time recovery, and replication for you. That is the right tool for that stage of growth.

But for where most projects start — a small site, an internal tool, a side project, a club website — SQLite with {{ project_name }}'s backup system has you covered.

**[Read the PostgreSQL Migration Guide](/help/smallstack/database-postgresql/)**

## What's Not Included

True to the {{ project_name }} philosophy, we only add what's essential. These are on our radar but won't be added unless there's clear demand:

- PostgreSQL backup
- S3/remote storage
- API endpoints for integrations
- Automated restore
- Media file backup

Let us know what's important to you — your feedback shapes what we build next.
