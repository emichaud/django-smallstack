# tasks — background-task helpers

Example `@task` functions (email send, data processing) for the pre-wired `django-tasks-db`
queue. Run the worker with `manage.py db_worker`.

**Status:** Framework-provided, but `tasks.py` is **example code you can edit/replace** with your
own tasks. Recurring/`@scheduled` jobs are roadmap — until then, use management commands + system
cron.

**Key files:** `tasks.py`.

**See:** [`../../docs/skills/background-tasks.md`](../../docs/skills/background-tasks.md).
