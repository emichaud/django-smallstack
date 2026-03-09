# Database Backups

SmallStack includes built-in SQLite backup tooling — a management command for automation, optional cron scheduling in Docker, and a staff-only web dashboard for manual backups, history, and status.

## Quick Start

```bash
# Create a backup
make backup

# Or with options (override retention count)
python manage.py backup_db --keep 5
```

That's all you need. Backups are saved to your `BACKUP_DIR` and tracked in the database automatically. By default, the 10 most recent backups are kept — configurable via the `BACKUP_RETENTION` setting or the `--keep` flag.

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

## Web Interface

Staff users can access the backup dashboard at `/backups/`. The Backups link appears in the sidebar under the Admin section.

### Backup Activity Tab

- **Stat cards** — quick counts for recent (24h), successful, failed, and pruned backups, plus average duration and total size on disk
- **Backup history** — paginated table with clickable IDs that link to each backup's detail page

All dates in the backup dashboard display in your timezone (set on the Profile Edit page, or the server default). When your timezone differs from the server's, dates show a dotted underline — hover to see the server time and UTC. See [Working with Timezones](/help/smallstack/timezones/) for details.

### Backup Detail Page

Click any backup ID (e.g. `#12`) to see its full detail page at `/backups/12/`. This shows:

- **Details card** — filename, size, duration, trigger source, status, and file availability
- **Activity timeline** — visual history of the backup lifecycle: when it was created, and if/when it was pruned or went missing
- **Download button** — if the file is still on disk and downloads are enabled

### Pruning

When backups are pruned (automatically via retention policy or manually via `--keep`), SmallStack marks the original backup record with a `pruned_at` timestamp instead of creating a separate record. This means:

- Pruned backups show a muted "pruned" badge and a gray trash icon in the history table
- The detail page shows exactly when the file was removed
- The red warning icon is reserved for files that are *unexpectedly* missing — not routine pruning
- Stat cards correctly separate "successful" (file available) from "pruned" (file removed by policy)

### Files Tab

Lists all backup files currently on disk with their sizes and modification dates.

### Configuration Tab

Shows your current backup settings, database info, email configuration status, and admin recipients.

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

The cron schedule is **pinned to UTC** via `CRON_TZ=UTC` in `scripts/smallstack-cron`. This means backups always fire at a predictable absolute time regardless of:

- The Django `TIME_ZONE` setting (which only affects how dates are *displayed*)
- The container's system timezone (`TZ` environment variable)

This is intentional — changing your display timezone should never accidentally shift when backups run. If you need backups at 2 AM in a specific timezone, convert to UTC and update the cron expression.

### Customize the Schedule

Edit `scripts/smallstack-cron` to change the cron expression:

```cron
# Every 6 hours, keep 28 backups
CRON_TZ=UTC
0 */6 * * * . /app/.env.cron && cd /app && python manage.py backup_db --keep 28 >> /proc/1/fd/1 2>&1
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

## Setup Checklist

If you're enabling backups in a project built from SmallStack, verify these are in place:

- [ ] `apps.smallstack` is in `INSTALLED_APPS` (`config/settings/base.py`)
- [ ] `/backups/` URL is included in `config/urls.py`
- [ ] `BACKUP_*` settings are defined in `config/settings/base.py`
- [ ] Migrations are up to date (`make migrate`)
- [ ] `make backup` target exists in your `Makefile`
- [ ] For Docker/Kamal: `BACKUP_CRON_ENABLED` is set in `docker-compose.yml` or `config/deploy.yml`
- [ ] For email notifications: `ADMINS`, `SERVER_EMAIL`, and SMTP env vars are configured (see below)

## Failure Notifications

If a backup fails, SmallStack will email the `ADMINS` list using `mail_admins()`. This requires three things to be configured:

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

## Off-Server Copies

Backups stored on the same disk as your database don't protect against disk failure. For additional safety, periodically copy backups to another location:

```bash
# Copy latest backup from your server
scp root@your-server:/root/myapp_data/db/backups/db-*.sqlite3 ./local-backups/

# Or use rsync for incremental copies
rsync -avz root@your-server:/root/myapp_data/db/backups/ ./local-backups/
```

## What's Not Included

True to the SmallStack philosophy, we only add what's essential. These are on our radar but won't be added unless there's clear demand:

- PostgreSQL backup
- S3/remote storage
- API endpoints for integrations
- Automated restore
- Media file backup

Let us know what's important to you — your feedback shapes what we build next.
