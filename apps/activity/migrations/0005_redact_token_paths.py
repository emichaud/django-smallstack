"""Redact one-time tokens already stored in RequestLog.path (G3-1).

Before this release the middleware stored ``request.path`` verbatim, so a
password-reset or invite link that was opened (``/accounts/reset/<uidb64>/<token>/``)
sat in the request log, and the Activity pages showed it to every staff
account. The middleware now redacts at record time; this rewrites the rows an
upgraded deployment already holds, keeping the route shape
(``/accounts/reset/MQ/***/``). Irreversible on purpose: the reverse is a no-op.
"""

from django.db import migrations
from django.db.models import Q

#: Substrings that select the candidate rows; redact_path() decides.
MARKERS = ("/accounts/reset/", "/accounts/invite/", "/blog/subscribe/confirm/", "/blog/unsubscribe/")


def redact_paths(apps, schema_editor):
    from apps.smallstack.redaction import redact_path

    RequestLog = apps.get_model("activity", "RequestLog")
    candidates = Q(route__contains="token>")
    for marker in MARKERS:
        candidates |= Q(path__contains=marker)
    pairs = RequestLog.objects.filter(candidates).order_by().values_list("path", "route").distinct()
    for path, route in list(pairs):
        redacted = redact_path(path, route)[:2048]
        if redacted != path:
            RequestLog.objects.filter(path=path, route=route).update(path=redacted)


class Migration(migrations.Migration):
    dependencies = [
        ("activity", "0004_requestlog_route"),
    ]

    operations = [
        migrations.RunPython(redact_paths, migrations.RunPython.noop),
    ]
