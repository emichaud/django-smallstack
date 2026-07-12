"""Domain events for documents.

Emitted by the service layer (``service.py``) on ``transaction.on_commit`` — one
event per business operation, so a rolled-back write never fires consumers.
These are the supported extension seam for downstream innovation (subscribers,
emailers, formatters, converters). Raw ``post_save`` still works for simple
cases, but these carry domain intent and a rich payload.

Signal kwargs (all senders are the ``Document`` class):

``document_written``       document, version, change_type, previous_version, actor, source, via
``document_archived``      document, actor
``document_expired``       document, policy
``document_image_attached``document, image, actor
``document_moved``         document, from_runbook, to_runbook, actor
"""

from django.dispatch import Signal

document_written = Signal()
document_archived = Signal()
document_expired = Signal()
document_image_attached = Signal()
document_moved = Signal()
