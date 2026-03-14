---
title: Backup Tool
description: Visual backup management dashboard for scheduling, running, and downloading SQLite backups
---

# Backup Tool

{{ project_name }} includes a staff-only backup dashboard at `/backups/` that gives you full visibility and control over your SQLite database backups. Create backups on demand, download copies to your local machine, monitor scheduled backup status, and review your complete backup history — all from a single page.

The dashboard is designed for quick daily use. At a glance you can see whether scheduled backups are running, how many backups succeeded or failed recently, and how much disk space they consume. For detailed configuration, scheduling, retention policies, and backup strategy guidance, see the full [Database Backups guide](/smallstack/help/smallstack/database-backups/).

## Main Dashboard

The backup dashboard (`/backups/`) is organized into a page header and three tabs.

### Page Header

The top of the page displays the title and up to three action cards:

- **Scheduled status** — a green "Scheduled" indicator when cron backups are enabled, or a red "Not Scheduled" warning with a link to the setup docs
- **Backup Now** — creates a backup and saves it to server storage instantly
- **Download** — creates a fresh backup and streams it to your browser as a `.sqlite3` file

### Backup Activity Tab

The default tab shows six **stat cards** across the top — recent backups (24h), successful, failed, pruned, average duration, and total size on disk. Clicking a stat card opens a modal with the matching backup records.

Below the stats is the **Backup History** table: a paginated list of every backup with clickable IDs, timestamps, file sizes, status badges (success/failed/pruned), and trigger source (manual, download, or cron).

### Files Tab

Lists all backup files currently on disk with their sizes and modification dates. This reflects what is actually in your backup directory, regardless of what the database records show.

### Configuration Tab

Shows your current backup settings at a glance in two sections:

- **Status cards** — whether SMTP email is configured for failure alerts, and how many admin recipients are set up. Red warnings link to the relevant setup docs when something is missing.
- **Settings tables** — database engine, file path, current database size, backup directory, retention count, scheduled status, and download status.

## Backup Detail Page

Click any backup ID (e.g., `#12`) to open its detail page at `/backups/12/`. This shows:

- **Details card** — filename, size, duration, trigger source, status, and whether the file is still on disk
- **Activity timeline** — visual history of the backup lifecycle: when it was created, and if/when it was pruned or went missing
- **Download button** — available if the file is still on disk and downloads are enabled

## See Also

- [Database Backups](/smallstack/help/smallstack/database-backups/) — full guide covering configuration, scheduling, retention, backup strategy, failure notifications, and the management command
- [SQLite Database](/smallstack/help/smallstack/database-sqlite/) — how {{ project_name }} configures and persists SQLite
