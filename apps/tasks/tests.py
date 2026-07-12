"""Tests for the background tasks in ``apps/tasks/tasks.py``.

These run under ``config.settings.test``, which uses the django-tasks
``ImmediateBackend`` (so ``.enqueue()`` executes the task inline and
``result.return_value`` is available immediately) and the locmem email backend
(so sends land in ``mail.outbox``). No worker or broker needed.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from apps.tasks.tasks import (
    example_task_with_context,
    process_data_task,
    send_email_task,
    send_html_email_task,
    send_welcome_email,
)

pytestmark = pytest.mark.django_db
User = get_user_model()


class TestSendEmailTask:
    def test_sends_plain_email(self):
        result = send_email_task.enqueue(recipient="user@example.com", subject="Hello", message="Body text")
        assert result.status.name == "SUCCESSFUL"
        assert result.return_value == 1
        assert len(mail.outbox) == 1
        sent = mail.outbox[0]
        assert sent.subject == "Hello"
        assert sent.body == "Body text"
        assert sent.to == ["user@example.com"]

    def test_accepts_a_list_of_recipients(self):
        send_email_task.enqueue(recipient=["a@example.com", "b@example.com"], subject="Hi", message="x")
        assert mail.outbox[0].to == ["a@example.com", "b@example.com"]


class TestSendHtmlEmailTask:
    def test_sends_html_with_text_alternative(self):
        # welcome.html has a welcome.txt sibling → exercises the full path incl. the .txt fallback lookup.
        # Task args must be JSON-serializable (the backend validates this), so `user` is a plain dict —
        # the template's `{{ user.get_full_name|default:user.username }}` resolves against it fine.
        ctx = {"user": {"username": "alice"}, "site_name": "SmallStack", "domain": "example.com", "protocol": "https"}
        result = send_html_email_task.enqueue(
            recipient="alice@example.com", subject="Report", template="email/welcome.html", context=ctx,
        )
        assert result.return_value == 1
        assert len(mail.outbox) == 1
        sent = mail.outbox[0]
        assert sent.subject == "Report"
        assert sent.alternatives[0][1] == "text/html"  # HTML alternative attached

    def test_text_body_falls_back_to_subject_without_txt_template(self):
        # base_email.html has no .txt sibling → the plain-text body falls back to the subject.
        # (Guards the D4 change that narrowed this except to TemplateDoesNotExist.)
        result = send_html_email_task.enqueue(
            recipient="x@example.com", subject="No-Txt-Subject", template="email/base_email.html", context={},
        )
        assert result.return_value == 1
        assert mail.outbox[0].body == "No-Txt-Subject"


class TestSendWelcomeEmail:
    def test_sends_to_user_with_email(self):
        user = User.objects.create_user(username="bob", email="bob@example.com", password="pw")
        result = send_welcome_email.enqueue(user_id=user.id)
        assert result.return_value == 1
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["bob@example.com"]

    def test_returns_zero_for_missing_user(self):
        result = send_welcome_email.enqueue(user_id=999_999)
        assert result.return_value == 0
        assert mail.outbox == []

    def test_returns_zero_when_user_has_no_email(self):
        user = User.objects.create_user(username="noemail", password="pw")
        result = send_welcome_email.enqueue(user_id=user.id)
        assert result.return_value == 0
        assert mail.outbox == []


class TestProcessDataTask:
    def test_transform_doubles_numeric_items(self, monkeypatch):
        monkeypatch.setattr("apps.tasks.tasks.time.sleep", lambda *a: None)
        result = process_data_task.enqueue(data={"items": [1, 2, 3]}, operation="transform")
        assert result.return_value["items"] == [2, 4, 6]
        assert result.return_value["processed"] is True

    def test_summarize_computes_stats(self, monkeypatch):
        monkeypatch.setattr("apps.tasks.tasks.time.sleep", lambda *a: None)
        result = process_data_task.enqueue(data={"items": [2, 4, 6]}, operation="summarize")
        assert result.return_value["summary"] == {"count": 3, "sum": 12, "average": 4}


class TestContextTask:
    def test_returns_context_info(self):
        result = example_task_with_context.enqueue(message="ping")
        rv = result.return_value
        assert rv["message"] == "ping"
        assert rv["status"] == "completed"
        assert rv["attempt"] >= 1
        assert rv["task_id"]
