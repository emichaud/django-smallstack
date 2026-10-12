# Background tasks & scheduler

<div class="two-col" markdown="1">
<div class="col" markdown="1">

Django 6's Tasks framework with a database backend, plus a recurring scheduler.

- **No Redis or Celery** — `django-tasks-db`; the worker is `manage.py db_worker`
- **`@scheduled`** — cron, interval or once, with a themed `/smallstack/scheduler/` UI, REST + MCP controls and a per-minute tick
- **Lost-task reaper + heartbeat** — stuck jobs are detected and the status page says so
- **Docker & Kamal** run the worker automatically; only local dev needs to start it

</div>
<div class="col" markdown="1">

```python
from apps.scheduler import scheduled
from django.tasks import task

@scheduled(every="5m", name="Publish due posts")
@task()
def publish_scheduled_posts():
    return service.publish_due_posts()

# One-shot, from a view — returns instantly
send_welcome_email.enqueue(user_id=user.pk)
```

</div>
</div>
