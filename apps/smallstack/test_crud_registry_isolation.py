"""A CRUDView a test defines must not outlive the test.

A CRUDView subclass registers itself for its model when it is defined
(``CRUDView.__init_subclass__``, first wins). ``BackupRecord`` has no real
CRUDView, so a throwaway one used to stay registered for the rest of the run;
the backups dataset then linked every row through routes that don't exist, and
the calendar's point-events test failed depending on which files ran first.
The root conftest's ``_restore_crud_registry`` undoes it after each test.

These two run in file order: the first leaves a registration behind, the
second checks it was undone.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_a_test_may_register_a_throwaway_crudview():
    from apps.smallstack.crud import CRUDView
    from apps.smallstack.models import BackupRecord

    class ThrowawayBackupCRUD(CRUDView):
        model = BackupRecord
        url_base = "throwaway/backups"

    assert CRUDView._registry.get(BackupRecord) is ThrowawayBackupCRUD


def test_and_it_is_gone_for_the_next_test():
    from apps.datasets.core import get_dataset
    from apps.smallstack.crud import CRUDView
    from apps.smallstack.models import BackupRecord

    assert CRUDView._registry.get(BackupRecord) is None
    backup = BackupRecord.objects.create(filename="x.sqlite3", status="success")
    ds = get_dataset("smallstack_backups")
    assert ds is not None and ds.link_for(backup) == backup.get_absolute_url()


def test_real_crudviews_survive_the_restore():
    """The restore must never drop the app's own registrations."""
    from apps.smallstack.crud import CRUDView
    from apps.smallstack.models import APIToken

    assert CRUDView._registry.get(APIToken) is not None
