# TODO: Background Tasks Improvements

Date: 2026-03-19
Source: ai_cowork/background-email-tasks-bab-construction.md

## Completed

- [x] Add `QUEUES` to test settings template (prevents `InvalidTask` in downstream projects)
- [x] Document batch recipients in `send_email_task` (skill doc updated)
- [x] Register TaskResult in Explorer for staff visibility (readonly, System group)

## Remaining

### HTML Email Task

Add a `send_html_email_task` or template-based variant to `apps/tasks/tasks.py`. The current `send_email_task` only supports plain text. Every project that sends user-facing notifications ends up building an HTML email from scratch.

**Approach:**
```python
@task(queue_name="email")
def send_template_email_task(recipient, subject, template_name, context=None, from_email=None):
    """Send an HTML email rendered from a Django template."""
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    ctx = context or {}
    html = render_to_string(f"{template_name}.html", ctx)
    text = render_to_string(f"{template_name}.txt", ctx)

    email = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=recipient if isinstance(recipient, list) else [recipient],
    )
    email.attach_alternative(html, "text/html")
    return email.send(fail_silently=False)
```

Also ship a base email template pair (`templates/email/base.html` + `base.txt`) with SmallStack branding that downstream projects can extend.

**Effort:** ~1 hour (task + base templates + skill doc update)

### Retry Support

The django-tasks framework does not yet support automatic retry with backoff. When it does:

- Configure email tasks with 3 retries and exponential backoff
- Log retry attempts
- Update skill doc with retry configuration examples

**Status:** Blocked on upstream django-tasks framework. Monitor for retry API additions.

### Task Dashboard Widget

The Explorer registration gives staff a table view of task history. A more useful addition would be a dashboard widget on the SmallStack dashboard showing:

- Tasks in last 24h: successful / failed / pending counts
- Most recent failure with error snippet
- Link to full Explorer task list

**Effort:** ~2 hours (widget template + dashboard context update)
