# Database Backups

SmallStack includes built-in SQLite backup tooling — a management command for automation, optional cron scheduling in Docker, and a staff-only web page for manual downloads and status.

## Quick Start

```bash
# Create a backup
make backup

# Or with options
python manage.py backup_db --keep 14
```

## Management Command

The `backup_db` command creates a safe, non-blocking backup using Python's `sqlite3.Connection.backup()` API.

```bash
# Basic backup (saved to BACKUP_DIR)
python manage.py backup_db

# Keep only the 14 most recent backups
python manage.py backup_db --keep 14

# Save to a specific path
python manage.py backup_db --output /tmp/my-backup.sqlite3
```

**Options:**

| Flag | Description |
|------|-------------|
| `--keep N` | Prune oldest backups beyond N. Uses `BACKUP_RETENTION` setting if not specified. |
| `--output PATH` | Override the destination file path |

Backup files are named `db-YYYYMMDD-HHMMSS.sqlite3` and stored in `BACKUP_DIR`.

## Web Interface

Staff users can access the backup page at `/backups/`. It shows:

- **Database info** — engine, file path, file size
- **Download button** — creates and downloads a backup immediately
- **Backup history** — table of all backup records with download links
- **Cron status** — whether scheduled backups are enabled

The Backups link appears in the sidebar under the Admin section for staff users.

## Scheduled Backups (Docker)

Backups can run automatically on a schedule inside your Docker container. This is disabled by default.

### Enable Scheduled Backups

Add `BACKUP_CRON_ENABLED=true` to your environment:

**docker-compose.yml:**
```yaml
environment:
  - BACKUP_CRON_ENABLED=true
```

**Kamal (config/deploy.yml):**
```yaml
env:
  clear:
    BACKUP_CRON_ENABLED: "true"
```

The default schedule is **daily at 2 AM**, keeping the last 14 backups.

### Customize the Schedule

Edit `scripts/smallstack-cron` to change the cron expression:

```cron
# Every 6 hours, keep 28 backups
0 */6 * * * . /app/.env.cron && cd /app && python manage.py backup_db --keep 28 >> /proc/1/fd/1 2>&1
```

After changing, rebuild and redeploy your container.

## Configuration

Add these to your `.env` file or environment variables:

| Setting | Default | Description |
|---------|---------|-------------|
| `BACKUP_DIR` | `<project>/backups/` | Directory to store backup files |
| `BACKUP_RETENTION` | `10` | Default number of backups to keep (used when `--keep` is not specified) |
| `BACKUP_CRON_ENABLED` | `false` | Enable cron-based scheduled backups in Docker |

## Failure Notifications

If a backup fails and you have `ADMINS` configured in your Django settings, SmallStack will call `mail_admins()` to notify you. This uses your existing Django email configuration.

```python
# config/settings/production.py
ADMINS = [("Your Name", "you@example.com")]
```

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

## What's Not Included (Yet)

- PostgreSQL backup (coming in a future release)
- S3/remote upload
- Automated restore
- Media file backup
