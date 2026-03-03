"""
Background tasks for the admin starter project.

This module demonstrates Django 6's built-in Tasks framework.
Tasks defined here can be executed in the background by the db_worker.

Usage:
    from apps.tasks.tasks import send_email_task, process_data_task

    # Enqueue a task to run in background
    result = send_email_task.enqueue(
        recipient="user@example.com",
        subject="Hello",
        message="This is a test email."
    )

    # Check task status later
    result.refresh()
    print(result.status)  # SUCCESSFUL, RUNNING, or FAILED
"""

import logging
import time

from django.conf import settings
from django.core.mail import send_mail
from django.tasks import task

logger = logging.getLogger(__name__)


@task(queue_name="email")
def send_email_task(recipient, subject, message, from_email=None):
    """
    Send an email in the background.

    This task is useful for sending emails without blocking the HTTP response.
    The email is queued and processed by the background worker.

    Args:
        recipient: Email address to send to (string or list of strings)
        subject: Email subject line
        message: Plain text email body
        from_email: Optional sender address (defaults to DEFAULT_FROM_EMAIL)

    Returns:
        int: Number of emails sent (1 if successful, 0 if failed)

    Example:
        result = send_email_task.enqueue(
            recipient="user@example.com",
            subject="Welcome!",
            message="Thanks for signing up."
        )
    """
    if isinstance(recipient, str):
        recipient_list = [recipient]
    else:
        recipient_list = list(recipient)

    logger.info(f"Sending email to {recipient_list}: {subject}")

    return send_mail(
        subject=subject,
        message=message,
        from_email=from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=recipient_list,
        fail_silently=False,
    )


@task(queue_name="email")
def send_welcome_email(user_id):
    """
    Send a welcome email to a newly registered user.

    This is a convenience task that fetches user data and sends a welcome message.
    Useful for triggering from signals after user creation.

    Args:
        user_id: The ID of the user to email

    Returns:
        int: Number of emails sent

    Example:
        # In a signal or view after user creation:
        send_welcome_email.enqueue(user_id=user.id)
    """
    from django.contrib.auth import get_user_model
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    User = get_user_model()

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for welcome email")
        return 0

    if not user.email:
        logger.warning(f"User {user_id} has no email address")
        return 0

    site_name = getattr(settings, "SITE_NAME", "Admin Starter")
    domain = getattr(settings, "SITE_DOMAIN", "localhost:8000")
    protocol = "https" if getattr(settings, "USE_HTTPS", False) else "http"

    context = {
        "user": user,
        "site_name": site_name,
        "domain": domain,
        "protocol": protocol,
    }

    subject = f"Welcome to {site_name}!"
    text_content = render_to_string("email/welcome.txt", context)
    html_content = render_to_string("email/welcome.html", context)

    logger.info(f"Sending welcome email to {user.email}")

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[user.email],
    )
    email.attach_alternative(html_content, "text/html")
    return email.send(fail_silently=False)


@task(priority=5)
def process_data_task(data, operation="transform"):
    """
    A simple example task for processing data in the background.

    This demonstrates how to run CPU-intensive or time-consuming operations
    without blocking web requests.

    Args:
        data: Dictionary of data to process (must be JSON-serializable)
        operation: Type of operation to perform

    Returns:
        dict: Processed result

    Example:
        result = process_data_task.enqueue(
            data={"items": [1, 2, 3, 4, 5]},
            operation="transform"
        )
    """
    logger.info(f"Processing data with operation: {operation}")

    # Simulate some processing time
    time.sleep(1)

    if operation == "transform":
        # Example: double all numeric values
        if "items" in data:
            data["items"] = [x * 2 for x in data["items"]]
        data["processed"] = True
        data["operation"] = operation

    elif operation == "summarize":
        # Example: calculate statistics
        if "items" in data:
            items = data["items"]
            data["summary"] = {
                "count": len(items),
                "sum": sum(items),
                "average": sum(items) / len(items) if items else 0,
            }

    logger.info(f"Data processing complete: {data}")
    return data


@task(takes_context=True)
def example_task_with_context(context, message):
    """
    Example task that demonstrates accessing task context.

    The context provides metadata about the current task execution,
    including attempt number and the task result object.

    Args:
        context: TaskContext automatically injected by the framework
        message: A message to log

    Returns:
        dict: Task execution info

    Example:
        result = example_task_with_context.enqueue(message="Hello from task!")
    """
    logger.info(f"Task {context.task_result.id} executing (attempt {context.attempt}): {message}")

    return {
        "task_id": str(context.task_result.id),
        "attempt": context.attempt,
        "message": message,
        "status": "completed",
    }
