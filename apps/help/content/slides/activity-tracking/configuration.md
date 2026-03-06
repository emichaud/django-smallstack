# Configuration & Pruning

Key settings in `settings.py`:

- `ACTIVITY_TRACKING_ENABLED` — on/off toggle
- `ACTIVITY_EXCLUDE_PATHS` — prefixes to skip (`/static/`, `/media/`, etc.)
- `ACTIVITY_RETENTION_DAYS` — auto-prune after N days (default 30)

Pruning runs daily via `django-tasks` background worker. ~60 MB storage for 10k requests/day over 30 days.
