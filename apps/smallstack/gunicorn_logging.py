"""Gunicorn's access log, with one-time credentials redacted.

The shipped ``gunicorn.conf`` names this class as ``logger_class``. Gunicorn's
access line logs the path (``%(U)s``) and the referer (``%(f)s``), and a
password-reset or invite link carries its token in the path
(``/accounts/reset/<uidb64>/<token>/``). Anyone who can read the container's
stdout (``kamal app logs``, a log shipper) could otherwise replay a link that
someone opened but didn't finish. Every string atom goes through
:mod:`apps.smallstack.redaction`, the same rules the activity log and the
captured logs use: the token segment becomes ``***`` and the route shape is
kept (``/accounts/reset/MQ/***/``); credential query parameters (``token=``,
``code=`` ...) are redacted wherever a query string appears (``%(q)s``,
``%(r)s``, the referer, a header or environ atom).

Imported by gunicorn's master before Django is set up, so it imports nothing
from Django; ``redaction`` is pure Python.
"""

from __future__ import annotations

from typing import Any

from gunicorn.glogging import Logger

from .redaction import redact_path, redact_text

#: Atoms that hold a bare query string, without its leading ``?``.
_QUERY_ATOMS = frozenset({"q", "{query_string}e"})
#: Atoms that hold a bare path.
_PATH_ATOMS = frozenset({"U", "{path_info}e"})


def redact_atom(key: str, value: Any) -> Any:
    """One access-log atom with any credential in it redacted."""
    if not isinstance(value, str) or not value:
        return value
    if key in _QUERY_ATOMS:
        return redact_text("?" + value)[1:]
    if key in _PATH_ATOMS:
        return redact_path(value)
    return redact_text(value)


class RedactingLogger(Logger):
    """Gunicorn's default logger, with every access-log atom redacted."""

    def atoms(self, resp: Any, req: Any, environ: Any, request_time: Any) -> dict[str, Any]:
        atoms = super().atoms(resp, req, environ, request_time)
        return {key: redact_atom(key, value) for key, value in atoms.items()}
