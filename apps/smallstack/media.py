"""The public ``/media/`` route, minus the subtrees that are access-controlled.

``MEDIA_ROOT`` holds both public uploads (profile photos) and private ones
(runbook document bodies and images, served only through views that check
``can_view``). Serving the whole root unauthenticated made those checks
bypassable: ``/media/runbook/<key>.md`` returned a private runbook to anyone.
(Audit 2026-09-13, C2.)

Prefixes in ``SMALLSTACK_PRIVATE_MEDIA_PREFIXES`` 404 here. Add your own when a
model stores files that a view is supposed to gate.

The gate compares the **resolved filesystem path** the file server would open
against the resolved private directories — never URL strings. A string-prefix
check normalized the path differently from ``django.views.static.serve``, so
``/media/../media/runbook/x.md`` looked public to the gate while ``serve``
resolved it straight back into ``MEDIA_ROOT/runbook/``. (Test round
2026-09-24, G1.)
"""

from __future__ import annotations

import os
import posixpath
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import Http404, HttpRequest, HttpResponseBase
from django.utils._os import safe_join
from django.views.static import serve

DEFAULT_PRIVATE_PREFIXES = ("runbook/",)


def private_prefixes() -> tuple[str, ...]:
    configured = getattr(settings, "SMALLSTACK_PRIVATE_MEDIA_PREFIXES", DEFAULT_PRIVATE_PREFIXES)
    return tuple(p.strip("/") for p in configured if p.strip("/"))


def _key(p: Path) -> str:
    # casefold: a case-insensitive filesystem (macOS dev, some volumes) serves
    # "RUNBOOK/x.md" from runbook/, so the comparison must ignore case too.
    return os.path.normcase(str(p)).casefold()


def is_private_media_path(path: str, document_root: Any = None) -> bool:
    """True if ``serve(path, document_root)`` would read inside a private subtree.

    Resolves ``path`` exactly the way ``django.views.static.serve`` does, then
    follows symlinks, and checks containment against each resolved private
    directory. Anything ``safe_join`` refuses is treated as private (it would
    404 in ``serve`` anyway).
    """
    root = Path(document_root or settings.MEDIA_ROOT)
    try:
        target = Path(safe_join(root, posixpath.normpath(path).lstrip("/"))).resolve()
    except (SuspiciousFileOperation, ValueError):
        return True
    target_key = _key(target)
    for prefix in private_prefixes():
        private_key = _key((root / prefix).resolve())
        if target_key == private_key or target_key.startswith(private_key + os.sep):
            return True
    return False


def public_media_serve(request: HttpRequest, path: str, document_root: Any = None, **kwargs: Any) -> HttpResponseBase:
    root = document_root or settings.MEDIA_ROOT
    if is_private_media_path(path, root):
        raise Http404("Not found")
    return serve(request, path, document_root=root, **kwargs)
