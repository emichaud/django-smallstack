# Tech stack

| Component | Choice |
|-----------|--------|
| **Framework** | Django 6 |
| **Frontend** | Themed admin shell, htmx interactions, six palettes × light/dark |
| **Database** | SQLite for dev and production; Postgres supported, same test suite on both |
| **Search** | SQLite FTS5 or Postgres `tsvector` + GIN, ranked |
| **Tasks** | Django Tasks + `django-tasks-db` worker with a `@scheduled` recurring scheduler — no Redis or Celery |
| **Typing** | mypy + django-stubs over every app, gated in `make lint` |
| **Package manager** | UV |
| **Deployment** | Docker Compose or Kamal with Let's Encrypt. Your choice. |
