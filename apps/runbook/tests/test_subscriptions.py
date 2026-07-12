"""Tests for the subscription demo: consumer of document_written + async fan-out."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.runbook import service, subscriptions
from apps.runbook.models import Document, Runbook, Section, Subscription

from ._factory import make_document

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def rb(db):
    return Runbook.objects.create(name="Ops", slug="ops")


@pytest.fixture
def section(rb):
    return Section.objects.create(name="Gen", slug="gen", runbook=rb)


@pytest.fixture
def doc(section):
    return make_document(title="Doc", section=section)


@pytest.fixture
def subscriber(db):
    return User.objects.create_user("sub", email="sub@example.com", password="p", is_staff=True)


@pytest.mark.django_db
class TestSubscriptions:
    def test_subscribe_toggle(self, doc, subscriber):
        assert not subscriptions.is_subscribed(subscriber, doc)
        subscriptions.subscribe(subscriber, doc)
        assert subscriptions.is_subscribed(subscriber, doc)
        assert list(subscriptions.subscribers_of(doc)) == [subscriber]
        subscriptions.unsubscribe(subscriber, doc)
        assert not subscriptions.is_subscribed(subscriber, doc)

    def test_subscribe_idempotent(self, doc, subscriber):
        subscriptions.subscribe(subscriber, doc)
        subscriptions.subscribe(subscriber, doc)
        assert Subscription.objects.filter(document=doc).count() == 1

    def test_notifications_sent(self, doc, subscriber, mailoutbox):
        subscriptions.subscribe(subscriber, doc)
        assert subscriptions.send_update_notifications(doc.pk, "new_version") == 1
        assert len(mailoutbox) == 1
        assert "sub@example.com" in mailoutbox[0].to
        assert doc.title in mailoutbox[0].subject

    def test_no_subscribers_no_email(self, doc, mailoutbox):
        assert subscriptions.send_update_notifications(doc.pk, "new_version") == 0
        assert mailoutbox == []

    def test_subscriber_without_email_skipped(self, doc, db, mailoutbox):
        user = User.objects.create_user("noemail", password="p")
        User.objects.filter(pk=user.pk).update(email="")  # ensure blank email
        subscriptions.subscribe(user, doc)
        assert subscriptions.send_update_notifications(doc.pk, "new_version") == 0
        assert mailoutbox == []


@pytest.mark.django_db
class TestFanOut:
    def test_write_emails_subscribers(self, rb, subscriber, mailoutbox, django_capture_on_commit_callbacks):
        result = service.put_document("ops", "d", body="v1", title="D")
        subscriptions.subscribe(subscriber, Document.objects.get(pk=result.id))
        with django_capture_on_commit_callbacks(execute=True):
            service.put_document("ops", "d", body="v2", on_exists="new_version")
        assert len(mailoutbox) == 1
        assert "sub@example.com" in mailoutbox[0].to

    def test_no_email_without_subscribers(self, rb, mailoutbox, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            service.put_document("ops", "d", body="v1", title="D")
            service.put_document("ops", "d", body="v2", on_exists="new_version")
        assert mailoutbox == []


@pytest.mark.django_db
class TestSubscribeView:
    def test_toggle_via_web(self, doc, subscriber):
        client = Client()
        client.force_login(subscriber)
        url = reverse("runbook:document_subscribe", kwargs={"pk": doc.pk})
        client.post(url)
        assert subscriptions.is_subscribed(subscriber, doc)
        client.post(url)
        assert not subscriptions.is_subscribed(subscriber, doc)
