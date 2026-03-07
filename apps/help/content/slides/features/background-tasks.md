# Background Tasks

<div class="two-col" markdown="1">
<div class="col" markdown="1">

Django 6's Tasks framework, pre-configured with a database backend.

- **No Redis or Celery** — uses `django-tasks-db`
- **Background worker** via `manage.py db_worker`
- Handles email, data processing, scheduled cleanup
- **Kamal deployment** runs the worker as a separate service

</div>
<div class="col" markdown="1">

```python
@task
def send_notification_email(user_email, message):
    return send_mail(
        subject="Notification",
        message=message,
        from_email=None,
        recipient_list=[user_email],
    )

# In your view — returns instantly
send_notification_email.enqueue(
    user_email="user@example.com",
    message="Hello!",
)
```

</div>
</div>
