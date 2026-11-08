"""Background senders for account emails (invites, sign-in codes).

Queued on ``email`` so a slow SMTP server holds a worker rather than the web
request a user is waiting on. Arguments are IDs and a site URL only: each task
mints its own secret when it runs (see ``emails.send_invite_now`` /
``emails.send_login_code_now``), so no credential sits in the task table.
"""

from __future__ import annotations

from django.tasks import task

from apps.tasks.reliability import retry_policy

from . import emails

# Same policy as apps.tasks' email tasks: retry transient transport failures
# (OSError covers smtplib errors and timeouts), fail template errors at once.
_email_retry = retry_policy(max_attempts=3, backoff=30, backoff_max=600, retry_on=(OSError,))


@_email_retry
@task(queue_name="email")
def send_invite_email_task(user_id: int, inviter: str, site_url: str) -> int:
    return emails.send_invite_now(user_id, inviter, site_url)


@_email_retry
@task(queue_name="email")
def send_login_code_task(login_code_id: int, site_url: str) -> int:
    return emails.send_login_code_now(login_code_id, site_url)
