"""The search signals must not index from inside migrations.

Downstream-reported (Postgres, from-scratch migrate): ``@receiver(post_save)``
has no sender filter, and ``get_view()`` resolves by LABEL STRING — so the
historical model ``apps.get_model()`` hands a RunPython migration (same
``app_label.Name``, different class) matches the registry entry for the real
model. The search column is provisioned by ``post_migrate`` — after every
migration — so on a fresh Postgres DB the index write hits a missing
``search_vector`` column *inside the migration's transaction*, poisoning it:
the visible error is Django's next statement (``INSERT INTO
django_migrations``), and ``migrate`` is unbuildable from scratch. On SQLite
the failed write is a log line: the FTS index is a separate table (fails off
to the side) and SQLite doesn't poison transactions — the bug's category is
invisible on the default backend.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save

from apps.search import registry

pytestmark = pytest.mark.django_db

User = get_user_model()


def _historical_twin(model):
    """EXACTLY what ``apps.get_model()`` yields inside a RunPython migration:
    the model re-rendered from migration state into a separate Apps registry —
    same ``app_label`` + ``__name__`` (so the label-keyed search registry
    matches), but a DIFFERENT class object than the registered model."""
    from django.apps import apps as global_apps
    from django.db.migrations.state import ProjectState

    state_apps = ProjectState.from_apps(global_apps).apps
    return state_apps.get_model(model._meta.app_label, model.__name__)


class _RecordingBackend:
    def __init__(self):
        self.indexed: list = []
        self.removed: list = []

    def index_object(self, view, instance):
        self.indexed.append(instance)

    def remove_object(self, view, pk):
        self.removed.append(pk)


@pytest.fixture
def recording_backend(monkeypatch):
    backend = _RecordingBackend()
    import apps.search.backends as backends_pkg
    from apps.search import signals as search_signals  # noqa: F401 — handlers connected

    monkeypatch.setattr(backends_pkg, "get_backend", lambda: backend)
    return backend


def test_registry_label_matches_historical_twin(db):
    """The precondition the bug depends on: the label lookup DOES match a
    historical twin — which is exactly why the identity check must exist."""
    twin = _historical_twin(User)
    view = registry.get_view(twin)
    assert view is not None
    assert view.model is User
    assert view.model is not twin


def test_historical_model_save_does_not_index(recording_backend, db):
    """Firing post_save with a historical sender must be a no-op."""
    user = User.objects.create_user("mig-victim", password="p")
    recording_backend.indexed.clear()

    twin = _historical_twin(User)
    post_save.send(sender=twin, instance=user, created=True)
    assert recording_backend.indexed == []  # pre-fix: indexed via label match


def test_real_model_save_still_indexes(recording_backend, db):
    user = User.objects.create_user("real-deal", password="p")
    assert user in recording_backend.indexed  # the identity check narrows, not disables


def test_failed_index_write_does_not_poison_the_transaction(db, monkeypatch):
    """The docstring's promise — "a search index write should never break a
    model save" — must hold INSIDE a transaction. The handler wraps the
    write in atomic() (a savepoint), so after the failure the outer
    transaction still accepts statements. On Postgres, without the
    savepoint, the next query raises "current transaction is aborted";
    SQLite passes either way — run under TEST_DB=postgres for the real
    assertion."""
    import apps.search.backends as backends_pkg

    class _Boom:
        def index_object(self, view, instance):
            raise RuntimeError("index write blows up")

        def remove_object(self, view, pk):
            raise RuntimeError("index delete blows up")

    monkeypatch.setattr(backends_pkg, "get_backend", lambda: _Boom())

    user = User.objects.create_user("poison-probe", password="p")  # write fails, save survives
    # The decisive part: the SAME transaction keeps working afterwards.
    assert User.objects.filter(pk=user.pk).exists()
    user.delete()
    assert not User.objects.filter(pk=user.pk).exists()
