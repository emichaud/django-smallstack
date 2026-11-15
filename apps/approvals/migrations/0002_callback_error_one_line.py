"""Shorten stored callback errors to one line (G1-3).

``callback_error`` used to hold the last 2000 characters of a Python
traceback, frames and server paths included, and REST, MCP ``get_approval``
and the request page returned it to the requester. New rows store one line
(``ExcType: message``); this keeps each existing row's last line, which for a
traceback is that same line. The full tracebacks were logged when they
happened.
"""

from django.db import migrations


def shorten(apps, schema_editor):
    from apps.approvals.models import summarize_error

    ApprovalRequest = apps.get_model("smallstack_approvals", "ApprovalRequest")
    for req in ApprovalRequest.objects.exclude(callback_error="").only("pk", "callback_error").iterator():
        short = summarize_error(req.callback_error)
        if short != req.callback_error:
            ApprovalRequest.objects.filter(pk=req.pk).update(callback_error=short)


class Migration(migrations.Migration):
    dependencies = [("smallstack_approvals", "0001_initial")]

    operations = [migrations.RunPython(shorten, migrations.RunPython.noop)]
