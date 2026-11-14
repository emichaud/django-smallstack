"""Public maintenance helpers for the search index.

The search index is kept current by ``post_save`` / ``post_delete`` signals
(:mod:`apps.search.signals`). **Bulk operations fire no per-row signals** —
``QuerySet.bulk_create``, ``bulk_update``, and ``QuerySet.update`` all bypass
them — so rows written that way land in the table **un-indexed and invisible
to search**. This is the single most common silent failure for any project
with an importer or a data migration.

Call :func:`reindex_instances` right after a bulk write to close that gap::

    from apps.search import reindex_instances

    objs = Company.objects.bulk_create([...])
    reindex_instances(Company, objs)          # index the new rows

    Ticket.objects.filter(stale=True).update(status="closed")
    reindex_instances(Ticket, Ticket.objects.filter(stale=True))

Passing no ``objects`` reindexes the whole model (same effect as
``manage.py rebuild_search_index <label>``, minus the drop):

    reindex_instances(Company)

:func:`digits_search` is the companion recipe for the "identifiers don't
tokenize" problem (phone numbers, account codes) — see its docstring.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from django.db.models import Model

logger = logging.getLogger(__name__)


def reindex_instances(
    model: Any,
    objects: Iterable[Any] | None = None,
    *,
    chunk_size: int = 500,
) -> int:
    """Re-index rows the signals didn't see (bulk_create / bulk_update / update).

    Args:
        model: a model class, instance, or ``"app_label.ModelName"`` label
            for a CRUDView registered with ``enable_search = True``.
        objects: what to reindex. One of:
            * ``None`` — every row of the model.
            * a ``QuerySet``.
            * an iterable of model instances (e.g. the return of ``bulk_create``).
            * an iterable of primary-key values.
            Rows are always re-loaded from the database by pk, so the freshly
            written state is what gets indexed.
        chunk_size: rows per transaction (matches ``rebuild``).

    Returns:
        The number of rows re-indexed. ``0`` (with a warning) if ``model`` is
        not a searchable view — makes accidental calls loud, not silent.
    """
    from django.db import transaction

    from .backends import get_backend
    from .registry import get_view, get_view_by_label

    view = get_view_by_label(model) if isinstance(model, str) else get_view(model)
    if view is None:
        logger.warning(
            "reindex_instances: %r is not a registered searchable view "
            "(no enable_search=True). Nothing indexed.",
            model,
        )
        return 0

    pks = _resolve_pks(view.model, objects)
    backend = get_backend()
    count = 0
    for start in range(0, len(pks), chunk_size):
        batch = list(view.model._default_manager.filter(pk__in=pks[start : start + chunk_size]))
        with transaction.atomic():
            for obj in batch:
                backend.index_object(view, obj)
        count += len(batch)
    return count


def _resolve_pks(model: type[Model], objects: Iterable[Any] | None) -> list:
    """Normalize the ``objects`` argument to a concrete list of primary keys."""
    if objects is None:
        return list(model._default_manager.values_list("pk", flat=True))
    # A QuerySet — pull its pks without materializing instances.
    if hasattr(objects, "values_list") and hasattr(objects, "filter"):
        return list(objects.values_list("pk", flat=True))
    # An iterable of instances or of raw pk values.
    pks = []
    for item in objects:
        pks.append(item.pk if hasattr(item, "pk") else item)
    return pks


# ---------------------------------------------------------------------------
# Identifier search recipe (phone numbers, account codes, SKUs).
#
# ``to_tsvector('english', '+13128482994')`` (Postgres) and the FTS5 porter
# tokenizer both treat a run of digits as ONE opaque token, so a phone stored
# as ``+13128482994`` only matches that exact 11-digit string — the natural
# lookups (10 digits, formatted, partial) all miss. FTS is the wrong tool for
# substring identifier matching (``pg_trgm`` is the right one if that's a
# first-class need); but for "find this phone/code" the cheap, portable fix is
# to feed the index the normalized digit forms as an extra search field.
# ---------------------------------------------------------------------------


def digits_search(*values: Any) -> str:
    """Emit normalized digit variants of identifiers for a computed search field.

    Add a property to your model that returns this over the raw identifier(s),
    then list that property in ``search_fields`` — ``_resolve_field`` is
    ``getattr``-based, so a property resolves at index time with no DB column::

        class CallRecord(models.Model):
            phone = models.CharField(max_length=32)

            @property
            def phone_search(self):
                return digits_search(self.phone)

        class CallRecordView(CRUDView):
            enable_search = True
            search_fields = ["phone_search", ...]

    For a US-style ``+13128482994`` this yields ``"13128482994 3128482994"``
    so both the 11- and 10-digit queries hit. Query-side input that is
    formatted or partial still needs its own digit-normalization before it's
    passed to search.
    """
    out: list[str] = []
    for value in values:
        digits = re.sub(r"\D", "", str(value or ""))
        if not digits:
            continue
        out.append(digits)
        # US convenience: also index the 10-digit form of an 11-digit "1+" number.
        if len(digits) == 11 and digits.startswith("1"):
            out.append(digits[1:])
    return " ".join(dict.fromkeys(out))  # dedupe, preserve order
