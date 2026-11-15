"""Redact one-time tokens already captured in LogRecord rows (G3-1).

``django.request`` and ``django.security.csrf`` log the request path, so a
failed POST to an invite link or a 404 near a reset link could leave the token
in ``message``, ``exc_text`` or the request repr in ``extra``. The handler now
redacts before writing; this rewrites what an upgraded deployment captured.
Irreversible on purpose: the reverse is a no-op.
"""

from django.db import migrations
from django.db.models import Q

MARKERS = (
    "/accounts/reset/",
    "/accounts/invite/",
    "/blog/subscribe/confirm/",
    "/blog/unsubscribe/",
    "token=",
    "code=",
    "secret=",
    "password=",
    "api_key=",
    "apikey=",
    "sig=",
    "signature=",
    "code_verifier=",
)


def _redact_extra(value, redact_text):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: _redact_extra(v, redact_text) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_extra(v, redact_text) for v in value]
    return value


def redact_rows(apps, schema_editor):
    from apps.smallstack.redaction import redact_text

    LogRecord = apps.get_model("telemetry", "LogRecord")
    candidates = Q()
    for marker in MARKERS:
        candidates |= Q(message__icontains=marker) | Q(exc_text__icontains=marker)
    for row in LogRecord.objects.filter(candidates).order_by().iterator():
        message = redact_text(row.message)
        exc_text = redact_text(row.exc_text)
        extra = _redact_extra(row.extra, redact_text)
        if (message, exc_text, extra) != (row.message, row.exc_text, row.extra):
            LogRecord.objects.filter(pk=row.pk).update(message=message, exc_text=exc_text, extra=extra)


class Migration(migrations.Migration):
    dependencies = [
        ("telemetry", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(redact_rows, migrations.RunPython.noop),
    ]
