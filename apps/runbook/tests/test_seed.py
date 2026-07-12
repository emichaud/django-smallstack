"""Verify the seed command builds the sample runbook under Model B."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.runbook.models import Document

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.mark.django_db
def test_seed_creates_sample_runbook():
    User.objects.create_superuser(username="admin", email="a@b.co", password="x")
    call_command("seed_runbook")

    assert Document.objects.filter(title="System Architecture", is_archived=False).exists()
    # the multi-version sample doc has two versions with head = v2
    dc = Document.objects.get(title="Deploy Checklist")
    assert dc.version == 2
    assert dc.versions.count() == 2
    assert dc.current_version.version == 2
